# CC PROMPT — v2.27.8 — Docker entity metadata + EntityDrawer exposed-at display

## What this does
Two coordinated changes:
1. `docker_agent01.py`: add `ports`, `networks`, `ip_addresses` to `to_entities()` metadata
   so these fields are available in EntityDrawer (previously only on card dict, not entity)
2. `EntityDrawer.jsx`: for docker-platform entities, show "Container accessible at {ip}:{port}"
   auto-derived from `window.location.hostname` (the IP the user is already connected via);
   render array metadata fields (ports, networks, ip_addresses) as readable joined strings;
   also annotate if container is exposed externally vs loopback-only
Version bump: 2.27.7 → 2.27.8

---

## Change 1 — api/collectors/docker_agent01.py: add ports/networks/ips to to_entities()

NOTE for CC: Read api/collectors/docker_agent01.py first and find the `to_entities()` method.
The current method stamps metadata with image, state, ip_port, started_at, restart_count.
Add the following additional metadata fields from the container dict:

FIND the metadata dict inside `to_entities()` (exact context will vary — find the
`metadata={` block in the Entity() constructor call inside the list comprehension):

Add these fields to the metadata dict, extracting from the container card dict (`c`):
```python
"ports":        c.get("ports", []),         # list of port mapping strings e.g. ["8000→8000/tcp"]
"networks":     c.get("networks", []),       # list of docker network names
"ip_addresses": c.get("ip_addresses", []),  # list of internal container IPs
"ip_port":      c.get("ip_port", ""),       # host-bound ip:port (may be loopback)
```

These fields are already populated on the card dict from the collector — they just weren't
included in the entity metadata passed to EntityDrawer.

---

## Change 2 — gui/src/components/EntityDrawer.jsx

NOTE for CC: Read EntityDrawer.jsx first to understand how metadata is currently rendered.
The drawer renders a METADATA section with key/value rows. Make the following additions:

### 2a — Array field rendering

Find where metadata rows are rendered in EntityDrawer. Currently it probably renders each
metadata key/value pair as a simple string. For array fields, join them with ' · ':

The render logic should look like:
```jsx
// When rendering a metadata value:
const renderValue = (val) => {
  if (Array.isArray(val)) {
    return val.length > 0 ? val.join(' · ') : '—'
  }
  if (val === null || val === undefined || val === '') return '—'
  return String(val)
}
```

### 2b — "Accessible at" annotation for docker entities

After the main metadata table, for entities with `platform === 'docker'` or
`component === 'docker_agent01'`, add a section showing the container's external accessibility.

The logic to add (as a new JSX block inside the drawer, after METADATA section):

```jsx
{/* Container accessibility — for docker entities only */}
{(entity?.platform === 'docker' || entity?.component === 'docker_agent01') && (() => {
  const meta = entity?.metadata || {}
  const ports = meta.ports || []
  const ipPort = meta.ip_port || ''

  // Derive the host's LAN IP from how the browser is connected.
  // window.location.hostname gives 192.168.199.10 if connected directly by IP,
  // or a hostname if via DNS. Fall back to agentHostIp setting if loopback.
  const browserHost = typeof window !== 'undefined' ? window.location.hostname : ''
  const isLoopback = !browserHost || browserHost === 'localhost' || browserHost === '127.0.0.1'

  // Try to get agentHostIp from settings if browser host is loopback
  // (settings is available from OptionsContext or can be fetched)
  const hostIp = isLoopback ? (window.__agentHostIp || browserHost) : browserHost

  // Extract host-bound ports from port mappings (e.g. "8000→8000/tcp" → "8000")
  const externalPorts = ports.map(p => {
    const hostPart = p.split('→')[0]?.trim()
    // Only include if it's a real port (not loopback-prefixed like "127.0.0.1:8000")
    if (!hostPart) return null
    if (hostPart.startsWith('127.') || hostPart.startsWith('0.0.0')) {
      // Loopback — extract just the port number for display
      const portNum = hostPart.split(':').pop()
      return portNum ? { port: portNum, loopback: true } : null
    }
    // Real binding
    const portNum = hostPart.includes(':') ? hostPart.split(':').pop() : hostPart
    return portNum ? { port: portNum, loopback: false } : null
  }).filter(Boolean)

  if (externalPorts.length === 0 && !ipPort) return null

  return (
    <div style={{ marginTop: 12, paddingTop: 12, borderTop: '1px solid var(--bg-3)' }}>
      <div style={{ fontSize: 8, fontFamily: 'var(--font-mono)', color: 'var(--text-3)',
        letterSpacing: 1, marginBottom: 6 }}>ACCESSIBILITY</div>
      {externalPorts.map(({ port, loopback }, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '3px 0', fontSize: 10, fontFamily: 'var(--font-mono)' }}>
          <span style={{ color: 'var(--text-3)' }}>
            {loopback ? 'loopback only' : 'exposed on LAN'}
          </span>
          {loopback ? (
            <span style={{ color: 'var(--text-3)' }}>localhost:{port}</span>
          ) : (
            <a
              href={`http://${hostIp}:${port}`}
              target="_blank"
              rel="noopener noreferrer"
              style={{ color: 'var(--cyan)', textDecoration: 'none' }}
              onClick={e => e.stopPropagation()}
            >
              {hostIp}:{port} ↗
            </a>
          )}
        </div>
      ))}
    </div>
  )
})()}
```

### 2c — Inject agentHostIp into window for the above logic

NOTE for CC: Find where the app initialises or where settings are loaded. Add a one-liner
that writes `window.__agentHostIp` from the agentHostIp setting value when settings load.
This could be in OptionsContext.jsx or wherever settings are applied to the app:

```js
// When settings load/update — write agentHostIp to window for EntityDrawer
if (settings.agentHostIp) {
  window.__agentHostIp = settings.agentHostIp
}
```

Find the appropriate location in OptionsContext.jsx where settings are loaded from the server
and applied, and add this line there.

---

## Version bump
Update VERSION: 2.27.7 → 2.27.8

## Commit
```bash
git add -A
git commit -m "feat(entities): v2.27.8 docker ports/networks in entity metadata, exposed-at display"
git push origin main
```
