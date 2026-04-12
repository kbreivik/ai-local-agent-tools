# CC PROMPT — v2.15.7 — Container cards redesign

## What this does

Four container card issues:
1. Container name is missing or showing image URL — `c.name` must be the primary label
2. Containers section should use per-docker-host Section headers (like Proxmox clusters)
3. Compact card: show container name + real host IP:port (not 127.0.0.1/loopback)
4. Expanded card: show Docker networks the container is attached to

Version bump: 2.15.6 → 2.15.7 (UI fix, x.x.1)

---

## Fix 1 — ServiceCards.jsx: Container name is primary label

In `InfraCard` usage for containers, `name` prop currently gets `c.name`:
```jsx
<InfraCard
  ...
  dot={c.dot} name={c.name} sub={_computeContainerSub(c, knownLatest)} ...
/>
```

`c.name` from the swarm API returns `kafka_broker-1`, `logstash_logstash` etc.
For local containers it returns the container name. This IS correct — the bug is
likely that `c.name` is sometimes undefined and InfraCard falls through to show
the image instead. Add a fallback:

```jsx
name={c.name || c.id?.slice(0, 12) || '(unknown)'}
```

Also verify `_computeContainerSub` — it returns the image string as the `sub` field.
The image string `ghcr.io/kbreivik/hp1-ai-agent:latest` is too long. Shorten it:

```js
function _computeContainerSub(c, knownLatest) {
  const latestTag = knownLatest[c.id]
  // Shorten image to just the repo:tag part (strip registry host)
  const imageParts = (c.image || '').split('/')
  const shortImage = imageParts[imageParts.length - 1] || c.image || ''

  if (!latestTag || !c.running_version) return shortImage
  const severity = compareBuildTag(c.running_version, latestTag)
  if (severity === 'major') return { text: `${shortImage} — update avail`, cls: 'text-[#b04020]' }
  if (severity === 'minor' || severity === 'patch') return { text: `${shortImage} — update avail`, cls: 'text-[#92601a]' }
  return shortImage
}
```

---

## Fix 2 — ServiceCards.jsx: Container compact net — real IP, not loopback

`_containerNet(c)` already filters loopback, but the host IP isn't in `c.ip_port`
when Docker binds to all interfaces. The collector should provide the docker host's
actual IP, not `127.0.0.1`.

In the compact card display, if `_containerNet(c)` returns empty (loopback filtered),
fall back to showing just the port with a note:

```js
function _containerNet(c) {
  // Try ip_port first (from collector) — _displayIp strips loopback
  const filtered = _displayIp(c.ip_port)
  if (filtered) return filtered
  // Try ports array — strip loopback prefix, keep port
  if (c.ports?.length) {
    for (const p of c.ports) {
      const host = p.split('→')[0]?.trim()
      if (host && !host.startsWith('127.') && !host.startsWith('0.0.0')) return host
      // If loopback, show just the port number prefixed with :
      const portOnly = p.split(':').pop()?.split('/')[0]?.split('→')[0]?.trim()
      if (portOnly && /^\d+$/.test(portOnly)) return `:${portOnly}`
    }
  }
  return ''
}
```

---

## Fix 3 — ServiceCards.jsx: Container expanded — show Docker networks

The `ContainerCardExpanded` component doesn't show Docker network info.
The collector data for containers includes `c.networks` (or similar). Check what
the backend provides — the container card data shape from `fetchDashboardContainers()`
likely has a `networks` field.

In `ContainerCardExpanded`, after the ports line, add networks:

```jsx
{/* Docker networks */}
{c.networks?.length > 0 && (
  <div className="text-[10px] text-[#4a6a9a] font-mono mb-1.5">
    <span className="text-[9px] text-gray-700">networks </span>
    {c.networks.join(' · ')}
  </div>
)}
{/* All IP addresses */}
{c.ip_addresses?.length > 0 && (
  <div className="text-[10px] text-[#4a6a9a] font-mono mb-1.5">
    <span className="text-[9px] text-gray-700">ips </span>
    {c.ip_addresses.join(' · ')}
  </div>
)}
```

If the backend doesn't currently include `networks` in the container data,
update `api/collectors/swarm.py` (or whichever collector builds the container list)
to include network names:

```python
# In the container data collection, add:
"networks": list(container.attrs.get("NetworkSettings", {}).get("Networks", {}).keys()),
"ip_addresses": [
    net_data.get("IPAddress")
    for net_data in container.attrs.get("NetworkSettings", {}).get("Networks", {}).values()
    if net_data.get("IPAddress")
],
```

For Swarm services, add:
```python
"networks": [
    net.get("Target") or net.get("NetworkID", "")[:12]
    for net in service_spec.get("TaskTemplate", {}).get("Networks", [])
],
```

---

## Fix 4 — App.jsx + ServiceCards.jsx: Containers section uses docker_host connections

Currently the CONTAINERS section in `DashboardView` passes `activeFilters=['containers_local', 'containers_swarm']`
which renders flat sections. The request is to show one Section cluster header per
docker_host connection, similar to how COMPUTE shows one Section per Proxmox connection.

The current data comes from `fetchDashboardContainers()` and `fetchDashboardSwarm()`
which return flat data for a single host. For the new approach:

### 4a — Backend: expose which docker_host connection containers belong to

In `api/collectors/swarm.py` (or the container collector), add `connection_id` and
`connection_label` to the top-level response so the frontend knows which docker host
each container set belongs to.

The current response shape from `fetchDashboardContainers()` is:
```json
{ "containers": [...], "agent01_ip": "127.0.0.1" }
```

Add connection metadata:
```json
{
  "containers": [...],
  "connection_id": "uuid",
  "connection_label": "DS-agent-01",
  "connection_host": "192.168.199.10",
  "agent01_ip": "127.0.0.1"
}
```

In `api/collectors/swarm.py`, at the top of the data build:
```python
from api.connections import get_connection_for_platform
docker_conn = get_connection_for_platform("docker_host")
connection_id = str(docker_conn.get("id", "")) if docker_conn else ""
connection_label = docker_conn.get("label", "agent-01") if docker_conn else "agent-01"
connection_host = docker_conn.get("host", "") if docker_conn else ""
```

And include in the returned dict:
```python
return {
    ...existing fields...,
    "connection_id": connection_id,
    "connection_label": connection_label,
    "connection_host": connection_host,
}
```

### 4b — ServiceCards.jsx: render containers in a Section cluster header

For the `containers_local` section, wrap in the cluster-style `Section` component:

```jsx
{show('containers_local') && (
  <Section
    label={containers?.connection_label || 'agent-01'}
    dot={containers?.containers?.some(c => c.dot === 'red') ? 'red'
       : containers?.containers?.some(c => c.dot === 'amber') ? 'amber' : 'green'}
    auth="DOCKER"
    host={containers?.connection_host || containers?.agent01_ip || ''}
    runningCount={containers?.containers?.filter(c => c.status === 'running').length ?? 0}
    totalCount={containers?.containers?.length ?? 0}
    issueCount={errorCount(containers?.containers)}
  >
    {[...(containers?.containers || [])]
      .sort((a, b) => (a.name || '').localeCompare(b.name || ''))
      .filter(c => (matchesShowFilter(c.dot) || isPinned(`docker:${c.name || c.id}`))
              && matchesSearch(c.name, c.image, c.id))
      .map(c => (
        <InfraCard ... />  // same as before
      ))}
  </Section>
)}
```

For swarm services similarly:
```jsx
{show('containers_swarm') && (
  <Section
    label={swarm?.cluster_label || 'Docker Swarm'}
    dot={...}
    auth="SWARM"
    host={`${swarm?.swarm_managers ?? '?'} mgr · ${swarm?.swarm_workers ?? '?'} wkr`}
    runningCount={swarm?.services?.filter(s => s.running_replicas === s.desired_replicas).length ?? 0}
    totalCount={swarm?.services?.length ?? 0}
    issueCount={errorCount(swarm?.services)}
  >
    {[...(swarm?.services || [])]
      .sort((a, b) => (a.name || '').localeCompare(b.name || ''))
      ...
  </Section>
)}
```

---

## Version bump

Update VERSION: `2.15.6` → `2.15.7`

---

## Commit

```bash
git add -A
git commit -m "fix(ui): v2.15.7 container cards redesign

- Container name is primary label (fallback to id slice if name missing)
- Image string shortened to repo:tag (strip registry host prefix)
- Compact card: real IP:port shown, loopback filtered, port-only fallback
- Expanded card: Docker networks + all IP addresses shown
- Containers section: cluster Section header (like Proxmox) per docker_host
- Backend: connection_id/label/host added to container collector response
- All container lists sorted alphabetically by name"
git push origin main
```
