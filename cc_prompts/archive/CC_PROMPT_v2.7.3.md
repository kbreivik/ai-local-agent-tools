# CC PROMPT — v2.7.3 — Compare per-entity chat suggestions

## What to add

When a slot is empty (no messages yet), show 2-3 pre-populated suggestion chips
derived from the entity's platform, status, and metadata. Clicking a chip sends
that question immediately — same as EntityDrawer suggestions.

---

## Change — gui/src/components/ComparePanel.jsx only

### 1 — Add suggestion derivation function

Add this function near the top of the file, before the component:

```js
/**
 * Derive 2-3 context-aware question suggestions for a compare slot.
 * Based on platform, status, and available metadata fields.
 */
function getEntitySuggestions(entity) {
  const { platform, status, metadata = {} } = entity
  const suggestions = []

  // ── Proxmox VM / LXC ────────────────────────────────────────────────────
  if (platform === 'proxmox') {
    const type = metadata.type === 'lxc' ? 'container' : 'VM'
    if (status === 'error' || metadata.status === 'stopped') {
      suggestions.push(`Why is this ${type} stopped?`)
      suggestions.push(`What are the resource requirements for ${entity.label}?`)
    } else if (status === 'degraded') {
      const pct = metadata.cpu_pct != null ? `CPU at ${metadata.cpu_pct}%` : null
      suggestions.push(pct ? `${pct} — is this normal?` : `Why is this ${type} degraded?`)
      suggestions.push(`Check disk usage on ${entity.label}`)
    } else {
      suggestions.push(`Summarise the health of ${entity.label}`)
      suggestions.push(`What services run on this ${type}?`)
    }
    if (metadata.node) suggestions.push(`Which node is ${entity.label} on and is it healthy?`)
  }

  // ── UniFi device ─────────────────────────────────────────────────────────
  else if (platform === 'unifi') {
    const devType = metadata.type || 'device'
    if (status === 'degraded' || metadata.state === 'disconnected') {
      suggestions.push(`Why is ${entity.label} disconnected?`)
      suggestions.push(`When did ${entity.label} last go offline?`)
    } else {
      if (metadata.clients != null) suggestions.push(`${metadata.clients} clients — is that normal for this ${devType}?`)
      suggestions.push(`What is the uptime and firmware version of ${entity.label}?`)
      if (devType === 'AP') suggestions.push(`Are there any interference issues on ${entity.label}?`)
      if (devType === 'Switch') suggestions.push(`Which ports are most active on ${entity.label}?`)
    }
  }

  // ── PBS datastore ─────────────────────────────────────────────────────────
  else if (platform === 'pbs') {
    const pct = metadata.usage_pct
    if (pct > 85) {
      suggestions.push(`Datastore at ${Math.round(pct)}% — what can be pruned?`)
      suggestions.push(`What is the retention policy for ${entity.label}?`)
    } else {
      suggestions.push(`When was the last backup to ${entity.label}?`)
      suggestions.push(`How much space will ${entity.label} need in 3 months?`)
    }
    if (metadata.gc_status) suggestions.push(`Is the GC status "${metadata.gc_status}" normal?`)
  }

  // ── TrueNAS pool ─────────────────────────────────────────────────────────
  else if (platform === 'truenas') {
    const pct = metadata.usage_pct
    if (status === 'error' || metadata.status !== 'ONLINE') {
      suggestions.push(`Pool ${entity.label} is ${metadata.status} — what does that mean?`)
      suggestions.push(`How do I recover a degraded ZFS pool?`)
    } else if (pct > 80) {
      suggestions.push(`Pool at ${Math.round(pct)}% — what datasets are largest?`)
      suggestions.push(`What are safe ZFS usage thresholds?`)
    } else {
      suggestions.push(`Summarise the health of pool ${entity.label}`)
      suggestions.push(`What is the vdev layout of ${entity.label}?`)
    }
    if (metadata.scan_state) suggestions.push(`Last scrub: ${metadata.scan_state} — should I run another?`)
  }

  // ── FortiGate interface ───────────────────────────────────────────────────
  else if (platform === 'fortigate') {
    if (!metadata.link || status === 'error') {
      suggestions.push(`Interface ${entity.label} is down — what are common causes?`)
      suggestions.push(`How do I diagnose a link-down interface on FortiGate?`)
    } else if (status === 'degraded') {
      suggestions.push(`${entity.label} has errors — how do I troubleshoot interface errors?`)
      suggestions.push(`What do RX/TX errors indicate on a FortiGate interface?`)
    } else {
      const speed = metadata.speed ? `${metadata.speed >= 1000 ? `${metadata.speed/1000}G` : `${metadata.speed}M`}` : ''
      suggestions.push(`What traffic flows through ${entity.label}${speed ? ` (${speed})` : ''}?`)
      suggestions.push(`Is the bandwidth on ${entity.label} within normal range?`)
    }
  }

  // ── Cluster header (Proxmox cluster, UniFi cluster, etc.) ─────────────────
  else if (entity.id?.startsWith('cluster:') || entity.id?.startsWith('unifi:') && !entity.id?.includes(':device:')) {
    suggestions.push(`Summarise the overall health of ${entity.label}`)
    suggestions.push(`Are there any issues I should be aware of?`)
  }

  // ── Generic fallback ──────────────────────────────────────────────────────
  else {
    if (status === 'error' || status === 'degraded') {
      suggestions.push(`What is causing the ${status} status on ${entity.label}?`)
      suggestions.push(`How do I fix this issue?`)
    } else {
      suggestions.push(`Summarise the health of ${entity.label}`)
      suggestions.push(`Are there any optimisations I should consider?`)
    }
  }

  return suggestions.slice(0, 3)
}
```

### 2 — Show suggestions in EntitySlot when chat is empty

In the `EntitySlot` function, find the empty chat state:

```jsx
{chat.length === 0 && (
  <span style={{ fontSize: 9, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>
    Ask about {entity.label}…
  </span>
)}
```

Replace with:

```jsx
{chat.length === 0 && (() => {
  const suggestions = getEntitySuggestions(entity)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <span style={{ fontSize: 9, color: 'var(--text-3)', fontFamily: 'var(--font-mono)', marginBottom: 2 }}>
        Ask about {entity.label}…
      </span>
      {suggestions.map((s, i) => (
        <button
          key={i}
          onClick={() => onSend(s)}
          style={{
            fontSize: 9, padding: '3px 7px', textAlign: 'left',
            border: '1px solid var(--accent-dim)', borderRadius: 2,
            background: 'transparent', color: 'var(--cyan)',
            cursor: 'pointer', fontFamily: 'var(--font-mono)', lineHeight: 1.4,
          }}
        >
          {s}
        </button>
      ))}
    </div>
  )
})()}
```

---

## Notes

- No API changes — suggestions are derived entirely client-side from `entity.metadata`
  which is already passed in when `addToCompare()` is called
- `onSend(s)` sends the suggestion as a user message — same path as typing and pressing Enter
- Suggestions only show on empty slots; once a message is sent they disappear
- 3 suggestions max, platform-aware, status-aware

---

## Commit & deploy

```bash
git add -A
git commit -m "feat(compare): per-entity chat suggestions in compare slots

Derives 2-3 context-aware question chips per entity based on platform,
status, and metadata (cpu_pct, usage_pct, link state, client count, etc.).
Platforms covered: proxmox, unifi, pbs, truenas, fortigate + generic fallback.
Suggestions only show on empty slots; disappear once conversation starts."
git push origin main
# After CI green:
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env \
  up -d hp1_agent
```
