# CC PROMPT — v2.28.8 — Fix version badge: Platform Core + collapsed container card

## What this does
Two targeted bug fixes:

**Bug 1 — Platform Core agent row never shows version delta**
`PlatformCoreCards` uses `fullStatus?.latest_version` but `fullStatus` comes from `fetchStatus()` 
(`/api/status`) which has no `latest_version` field. Fix: add a separate fetch of
`/api/dashboard/update-status` and use its result for the agent row version delta.

**Bug 2 — Collapsed container card never shows version status badge**
`ConnectedContainerCard` passes `state={{ tags: [] }}` to `ContainerCardCollapsed` with no
`updateStatus`. The `version_status` renderer needs either `tags[0]` or `updateStatus` to
produce a badge. Fix: fetch update-status once at the `ServiceCards` level, pass both
`tags: knownLatest[c.id] ? [knownLatest[c.id]] : []` and `updateStatus` into the collapsed state.
Version bump: 2.28.7 → 2.28.8

---

## Change 1 — gui/src/App.jsx: fix Platform Core version delta

### 1a — Add agentUpdateStatus state to PlatformCoreCards

FIND (exact):
```jsx
function PlatformCoreCards({ onTab }) {
  const [memHealth, setMemHealth] = useState(null)
  const { health, collectorsData, containersData } = useDashboardData()
  const containers = containersData?.containers || []

  // Keep fetching status (kafka/es health) + memHealth separately — not in summary
  const [fullStatus, setFullStatus] = useState(null)
```

REPLACE WITH:
```jsx
function PlatformCoreCards({ onTab }) {
  const [memHealth, setMemHealth] = useState(null)
  const { health, collectorsData, containersData } = useDashboardData()
  const containers = containersData?.containers || []

  // Keep fetching status (kafka/es health) + memHealth separately — not in summary
  const [fullStatus, setFullStatus] = useState(null)
  const [agentUpdateStatus, setAgentUpdateStatus] = useState(null)
```

### 1b — Also fetch update-status in the same useEffect

FIND (exact):
```jsx
  useEffect(() => {
    const load = () => {
      fetchStatus().then(setFullStatus).catch(() => {})
      fetchMemoryHealth().then(setMemHealth).catch(() => {})
    }
    load()
    const id = setInterval(load, 90_000)  // 90s — these change slowly
    return () => clearInterval(id)
  }, [])
```

REPLACE WITH:
```jsx
  useEffect(() => {
    const BASE = import.meta.env.VITE_API_BASE ?? ''
    const load = () => {
      fetchStatus().then(setFullStatus).catch(() => {})
      fetchMemoryHealth().then(setMemHealth).catch(() => {})
      fetch(`${BASE}/api/dashboard/update-status`, { headers: { ...authHeaders() } })
        .then(r => r.ok ? r.json() : null)
        .then(d => { if (d) setAgentUpdateStatus(d) })
        .catch(() => {})
    }
    load()
    const id = setInterval(load, 90_000)  // 90s — these change slowly
    return () => clearInterval(id)
  }, [])
```

### 1c — Use agentUpdateStatus in the agent row version delta

FIND (exact):
```jsx
  // Version delta display
  const runningVer = agentContainer?.running_version || health?.version
  const latestVer  = agentContainer ? fullStatus?.latest_version : null
  const hasUpdate  = latestVer && runningVer && latestVer !== runningVer
  const versionStr = hasUpdate
    ? `${runningVer} → ${latestVer}`
    : runningVer ? `v${runningVer}` : '—'
```

REPLACE WITH:
```jsx
  // Version delta display — use update-status endpoint, not /api/status (which has no version info)
  const runningVer = agentContainer?.running_version || health?.version
  const latestVer  = agentUpdateStatus?.latest_version || null
  const hasUpdate  = agentUpdateStatus?.update_available === true
                  || (latestVer && runningVer && latestVer !== runningVer)
  const versionStr = hasUpdate && latestVer && runningVer
    ? `${runningVer} → ${latestVer}`
    : hasUpdate
    ? 'update available'
    : runningVer ? `v${runningVer}` : '—'
```

---

## Change 2 — gui/src/components/ServiceCards.jsx: fix collapsed card version state

### 2a — Add containerUpdateStatus state at ServiceCards level

NOTE for CC: Read ServiceCards.jsx to find the state declarations at the top of the
`ServiceCards` export function. Find the block starting with:
```jsx
  const [containers, setContainers] = useState(null)
  const [swarm, setSwarm]           = useState(null)
```

Add `containerUpdateStatus` state alongside the other useState declarations:

FIND (exact):
```jsx
  const [containers, setContainers] = useState(null)
  const [swarm, setSwarm]           = useState(null)
  const [vms, setVMs]               = useState(null)
  const [external, setExternal]     = useState(null)
```

REPLACE WITH:
```jsx
  const [containers, setContainers] = useState(null)
  const [swarm, setSwarm]           = useState(null)
  const [vms, setVMs]               = useState(null)
  const [external, setExternal]     = useState(null)
  const [containerUpdateStatus, setContainerUpdateStatus] = useState(null)
```

### 2b — Fetch update-status on mount in ServiceCards

Find the useEffect that sets up the poll and calls `load()`:

FIND (exact):
```jsx
  useEffect(() => {
    load()
    const id = setInterval(load, POLL_MS)
    return () => clearInterval(id)
  }, [load])
```

REPLACE WITH:
```jsx
  useEffect(() => {
    load()
    const id = setInterval(load, POLL_MS)
    return () => clearInterval(id)
  }, [load])

  // Fetch update-status once on mount — used for collapsed version badge
  useEffect(() => {
    fetch(`${BASE}/api/dashboard/update-status`, { headers: { ...authHeaders() } })
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setContainerUpdateStatus(d) })
      .catch(() => {})
    // Refresh every 5 min
    const id = setInterval(() => {
      fetch(`${BASE}/api/dashboard/update-status`, { headers: { ...authHeaders() } })
        .then(r => r.ok ? r.json() : null)
        .then(d => { if (d) setContainerUpdateStatus(d) })
        .catch(() => {})
    }, 300_000)
    return () => clearInterval(id)
  }, [])
```

### 2c — Pass knownLatest + updateStatus into ConnectedContainerCard collapsed state

FIND (exact):
```jsx
      collapsed={<ContainerCardCollapsed c={c} template={template} state={{ tags: [] }} />}
```

REPLACE WITH:
```jsx
      collapsed={<ContainerCardCollapsed c={c} template={template} state={{
        tags: knownLatest[c.id] ? [knownLatest[c.id]] : [],
        updateStatus: containerUpdateStatus,
      }} />}
```

NOTE for CC: The `ConnectedContainerCard` component currently doesn't receive `containerUpdateStatus`
from the ServiceCards parent. Two options:
  a) Pass it as a prop to `ConnectedContainerCard` and thread it through
  b) Move `ContainerCardCollapsed` rendering back into ServiceCards inline

Option (a) is cleaner. Add `containerUpdateStatus` as a prop to `ConnectedContainerCard` and
pass it from the ServiceCards containers map.

The updated `ConnectedContainerCard` signature:
```jsx
function ConnectedContainerCard({ c, isSwarm, onAction, confirm, showToast, onTagsLoaded, onTab, openKeys, setOpenKeys, lastOpenedKey, setLastOpenedKey, expandAllFlag, entityId, onEntityDetail, compareMode, compareSet, onCompareAdd, entityForCompare, knownLatest, containerUpdateStatus }) {
```

And the `ConnectedContainerCard` call in the containers_local map — add the two new props:
```jsx
<ConnectedContainerCard
  key={c.id} c={c} isSwarm={false} onAction={load} confirm={confirm} showToast={showToast}
  onTagsLoaded={onTagsLoaded} onTab={onTab}
  openKeys={openKeys} setOpenKeys={setOpenKeys} lastOpenedKey={lastOpenedKey} setLastOpenedKey={setLastOpenedKey}
  expandAllFlag={expandAllFlag} entityId={c.entity_id} onEntityDetail={onEntityDetail}
  compareMode={compareMode} compareSet={compareSet} onCompareAdd={onCompareAdd}
  knownLatest={knownLatest}
  containerUpdateStatus={containerUpdateStatus}
  entityForCompare={{ ... }}  {/* keep existing entityForCompare unchanged */}
/>
```

---

## Version bump
Update VERSION: 2.28.7 → 2.28.8

## Commit
```bash
git add -A
git commit -m "fix(ui): v2.28.8 version badge in Platform Core and collapsed container card"
git push origin main
```
