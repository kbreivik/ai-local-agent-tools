# CC PROMPT — v2.22.0 — Dashboard summary endpoint + DashboardDataContext

## What this does

Currently ~12 API calls fire simultaneously on every dashboard load because 5 separate
components each fetch their own data independently at 30s intervals. SubBar alone makes
6 calls per cycle (health + stats + containers + swarm + VMs + external). DashboardView
and PlatformCoreCards make several of the same calls in parallel.

This introduces two changes:

1. **`GET /api/dashboard/summary`** — single backend endpoint that returns all dashboard
   data in one response (containers, swarm, VMs, external, collectors, health). The backend
   assembles this from DB snapshots — all cheap PG reads, no SSH/API calls. Replaces 5–6
   individual calls with one.

2. **`DashboardDataContext`** — shared React context that owns all dashboard fetches.
   Components subscribe to it instead of fetching independently. Tiered refresh intervals
   based on data volatility: external/health = 30s, swarm/containers = 60s, VMs = 120s,
   connections = one-time + invalidate-on-edit. Skeleton states let cards render immediately
   while data loads.

Version bump: 2.21.2 → 2.22.0

---

## Change 1 — api/routers/dashboard.py

Add this endpoint near the top of the file, after the existing helpers:

```python
@router.get("/summary")
async def get_dashboard_summary(user: str = Depends(get_current_user)):
    """Single call returning all dashboard data needed for the main dashboard view.

    Assembles from DB snapshots (all fast PG reads — no SSH/API calls).
    Replaces 5–6 individual dashboard endpoint calls on the frontend.
    Response shape is stable — additive changes only.
    """
    from api.collectors import manager as coll_mgr

    async with get_engine().connect() as conn:
        # All fetched in parallel via gather
        import asyncio as _asyncio
        (
            containers_snap,
            swarm_snap,
            vms_snap,
            external_snap,
            vm_hosts_snap,
        ) = await _asyncio.gather(
            q.get_latest_snapshot(conn, "docker_agent01"),
            q.get_latest_snapshot(conn, "swarm"),
            q.get_latest_snapshot(conn, "proxmox_vms"),
            q.get_latest_snapshot(conn, "external_services"),
            q.get_latest_snapshot(conn, "vm_hosts"),
        )

    containers_state = _parse_state(containers_snap)
    swarm_state      = _parse_state(swarm_snap)
    vms_state        = _parse_state(vms_snap)
    external_state   = _parse_state(external_snap)
    vm_hosts_state   = _parse_state(vm_hosts_snap)

    # Enrich swarm services with dot/problem
    services = []
    for svc in swarm_state.get("services", []):
        enriched = dict(svc)
        enriched["dot"]     = _swarm_dot(svc)
        enriched["problem"] = _swarm_problem(svc)
        enriched["replicas_running"] = enriched.get("running_replicas")
        enriched["replicas_desired"] = enriched.get("desired_replicas")
        services.append(enriched)

    collectors = coll_mgr.status()

    return {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "containers": {
            "containers":        containers_state.get("containers", []),
            "agent01_ip":        containers_state.get("agent01_ip", ""),
            "health":            containers_state.get("health", "unknown"),
            "connection_label":  containers_state.get("connection_label", "agent-01"),
            "last_updated":      containers_snap.get("timestamp") if containers_snap else None,
        },
        "swarm": {
            "services":       services,
            "nodes":          swarm_state.get("nodes", []),
            "swarm_managers": sum(1 for n in swarm_state.get("nodes", []) if n.get("role") == "manager"),
            "swarm_workers":  sum(1 for n in swarm_state.get("nodes", []) if n.get("role") == "worker"),
            "health":         swarm_state.get("health", "unknown"),
            "last_updated":   swarm_snap.get("timestamp") if swarm_snap else None,
        },
        "vms": {
            "clusters":          vms_state.get("clusters", []),
            "vms":               vms_state.get("vms", []),
            "lxc":               vms_state.get("lxc", []),
            "health":            vms_state.get("health", "unknown"),
            "connection_label":  vms_state.get("connection_label", ""),
            "connection_host":   vms_state.get("connection_host", ""),
            "last_updated":      vms_snap.get("timestamp") if vms_snap else None,
        },
        "external": {
            "services":    external_state.get("services", []),
            "health":      external_state.get("health", "unknown"),
            "last_updated": external_snap.get("timestamp") if external_snap else None,
        },
        "vm_hosts": {
            "vms":        vm_hosts_state.get("vms", []),
            "health":     vm_hosts_state.get("health", "unknown"),
            "last_updated": vm_hosts_snap.get("timestamp") if vm_hosts_snap else None,
        },
        "collectors": collectors,
    }
```

Also add the `datetime` import if not already at the top:
```python
import datetime
```

---

## Change 2 — NEW FILE: gui/src/context/DashboardDataContext.jsx

```jsx
/**
 * DashboardDataContext — single source of truth for all dashboard data.
 *
 * Replaces independent polling in SubBar, DashboardView, PlatformCoreCards,
 * ConnectionSectionCards, and VMHostsSection. Components subscribe to this
 * context instead of fetching their own data.
 *
 * Tiered refresh intervals:
 *   summary (containers+swarm+vms+external+vm_hosts): 60s
 *   external only (health dots, latency): 30s — most volatile, own fast fetch
 *   connections list: one-time + WS-invalidated (changes only on user edit)
 *   stats: 60s
 *   health: 90s
 *
 * On mount: fetch everything immediately, then stagger subsequent polls
 * so they don't all fire at once. External fires at t+0, summary at t+200ms,
 * stats at t+400ms, health at t+600ms.
 */
import { createContext, useContext, useState, useEffect, useRef, useCallback } from 'react'
import { authHeaders, fetchDashboardExternal, fetchStats, fetchHealth } from '../api'

const BASE = import.meta.env.VITE_API_BASE ?? ''

const DashboardDataContext = createContext(null)

export function DashboardDataProvider({ children }) {
  // Summary data (containers + swarm + VMs + vm_hosts + collectors)
  const [summary, setSummary]     = useState(null)
  const [summaryTs, setSummaryTs] = useState(null)

  // External (health dots — refreshes faster)
  const [external, setExternal]   = useState(null)

  // Connections (almost never changes — fetch once)
  const [connections, setConnections]   = useState(null)
  const [connVersion, setConnVersion]   = useState(0)  // bump to force refetch

  // Agent stats + platform health
  const [stats, setStats]   = useState(null)
  const [health, setHealth] = useState(null)

  // Loading flags — true until first fetch completes
  const [summaryLoading, setSummaryLoading]       = useState(true)
  const [externalLoading, setExternalLoading]     = useState(true)
  const [connectionsLoading, setConnectionsLoading] = useState(true)

  const mountedRef = useRef(true)
  useEffect(() => () => { mountedRef.current = false }, [])

  // ── Summary fetch (60s) ─────────────────────────────────────────────────────
  const fetchSummary = useCallback(async () => {
    try {
      const r = await fetch(`${BASE}/api/dashboard/summary`, { headers: authHeaders() })
      if (!r.ok || !mountedRef.current) return
      const d = await r.json()
      setSummary(d)
      setSummaryTs(Date.now())
      setSummaryLoading(false)
    } catch (_) {}
  }, [])

  // ── External fetch (30s) ────────────────────────────────────────────────────
  const fetchExternal = useCallback(async () => {
    try {
      const d = await fetchDashboardExternal()
      if (!mountedRef.current) return
      setExternal(d)
      setExternalLoading(false)
    } catch (_) {}
  }, [])

  // ── Connections fetch (once + on connVersion bump) ──────────────────────────
  const fetchConnections = useCallback(async () => {
    try {
      const r = await fetch(`${BASE}/api/connections`, { headers: authHeaders() })
      if (!r.ok || !mountedRef.current) return
      const d = await r.json()
      setConnections(d.data || [])
      setConnectionsLoading(false)
    } catch (_) {}
  }, [])

  // ── Stats fetch (60s) ───────────────────────────────────────────────────────
  const refreshStats = useCallback(async () => {
    try {
      const d = await fetchStats()
      if (!mountedRef.current) return
      setStats(d)
    } catch (_) {}
  }, [])

  // ── Health fetch (90s) ──────────────────────────────────────────────────────
  const refreshHealth = useCallback(async () => {
    try {
      const d = await fetchHealth()
      if (!mountedRef.current) return
      setHealth(d)
    } catch (_) {}
  }, [])

  // ── Mount: staggered initial loads ─────────────────────────────────────────
  useEffect(() => {
    fetchExternal()                                      // t+0ms
    setTimeout(fetchSummary, 200)                        // t+200ms
    setTimeout(refreshStats, 400)                        // t+400ms
    setTimeout(refreshHealth, 600)                       // t+600ms
    setTimeout(fetchConnections, 800)                    // t+800ms

    // Polling intervals
    const externalId    = setInterval(fetchExternal, 30_000)   // 30s
    const summaryId     = setInterval(fetchSummary, 60_000)    // 60s
    const statsId       = setInterval(refreshStats, 60_000)    // 60s
    const healthId      = setInterval(refreshHealth, 90_000)   // 90s
    // Connections: no interval — only refetch when connVersion changes

    // WebSocket: re-fetch stats after agent run completes
    const agentDoneHandler = () => refreshStats()
    window.addEventListener('agent-done', agentDoneHandler)

    return () => {
      clearInterval(externalId)
      clearInterval(summaryId)
      clearInterval(statsId)
      clearInterval(healthId)
      window.removeEventListener('agent-done', agentDoneHandler)
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Connections: refetch when connVersion bumps ──────────────────────────────
  useEffect(() => {
    if (connVersion > 0) fetchConnections()
  }, [connVersion]) // eslint-disable-line react-hooks/exhaustive-deps

  const invalidateConnections = useCallback(() => {
    setConnVersion(v => v + 1)
  }, [])

  // ── Derived helpers ─────────────────────────────────────────────────────────
  // Provide the same shape as individual fetchDashboard* results for compatibility
  const containersData = summary?.containers ?? null
  const swarmData      = summary?.swarm      ?? null
  const vmsData        = summary?.vms        ?? null
  const vmHostsData    = summary?.vm_hosts   ?? null
  const collectorsData = summary?.collectors ?? {}
  const externalData   = external            ?? summary?.external ?? null

  return (
    <DashboardDataContext.Provider value={{
      // Raw summary
      summary,
      summaryTs,
      summaryLoading,

      // Derived data (same shape as old individual endpoints)
      containersData,
      swarmData,
      vmsData,
      vmHostsData,
      externalData,
      collectorsData,

      // Individual
      connections,
      connectionsLoading,
      stats,
      health,
      externalLoading,

      // Actions
      invalidateConnections,
      refreshSummary: fetchSummary,
      refreshExternal: fetchExternal,
    }}>
      {children}
    </DashboardDataContext.Provider>
  )
}

export function useDashboardData() {
  const ctx = useContext(DashboardDataContext)
  if (!ctx) throw new Error('useDashboardData must be used inside DashboardDataProvider')
  return ctx
}
```

---

## Change 3 — gui/src/App.jsx

### 3a — Import DashboardDataProvider

Add import near the top:
```jsx
import { DashboardDataProvider, useDashboardData } from './context/DashboardDataContext'
```

### 3b — Wrap the app content in DashboardDataProvider

In `AppWithPanelProvider`, wrap the `<AgentProvider>` tree:

Find:
```jsx
  return (
    <CommandPanelProvider defaultOpen={commandsPanelDefault === 'visible'}>
      <AgentProvider>
        <AppShell />
      </AgentProvider>
    </CommandPanelProvider>
  )
```

Replace with:
```jsx
  return (
    <CommandPanelProvider defaultOpen={commandsPanelDefault === 'visible'}>
      <DashboardDataProvider>
        <AgentProvider>
          <AppShell />
        </AgentProvider>
      </DashboardDataProvider>
    </CommandPanelProvider>
  )
```

### 3c — Update SubBar to use DashboardDataContext

The SubBar currently calls fetchDashboardContainers, fetchDashboardSwarm, fetchDashboardVMs,
fetchDashboardExternal, fetchStats, and fetchHealth every 30s. Replace all of that.

In `SubBar`, replace the entire `useEffect` data-fetching block with context consumption.

Find the SubBar function signature and all its useState declarations:
```jsx
function SubBar({ onTab, onAlertNavigate }) {
  const { panelOpen, togglePanel } = useCommandPanel()
  const { wsState, agentType, lastAgentType } = useAgentOutput()
  const [stats,  setStats]  = useState(null)
  const [health, setHealth] = useState(null)
  const [alerts, setAlerts] = useState([])
  const [rawContainers, setRawContainers] = useState(null)
  const [rawSwarm,      setRawSwarm]      = useState(null)
  const [rawVms,        setRawVms]        = useState(null)
  const [rawExternal,   setRawExternal]   = useState(null)
  const [alertTrayOpen, setAlertTrayOpen] = useState(false)
  const trayRef = useRef(null)
```

Replace with:
```jsx
function SubBar({ onTab, onAlertNavigate }) {
  const { panelOpen, togglePanel } = useCommandPanel()
  const { wsState, agentType, lastAgentType } = useAgentOutput()
  const {
    stats,
    health,
    containersData,
    swarmData,
    vmsData,
    externalData,
  } = useDashboardData()

  const rawContainers = containersData
  const rawSwarm      = swarmData
  const rawVms        = vmsData
  const rawExternal   = externalData

  const [alerts, setAlerts] = useState([])
  const [alertTrayOpen, setAlertTrayOpen] = useState(false)
  const trayRef = useRef(null)
```

Now find and DELETE the entire `useEffect(() => { const refreshStats = ...}, [])` block in SubBar — the one that calls fetchStats, fetchHealth, fetchDashboardContainers/Swarm/VMs/External every 30s. Replace it with an effect that just builds the alerts array from the context data:

Find:
```jsx
  useEffect(() => {
    const refreshStats = () => fetchStats().then(setStats).catch(() => setStats(null))

    const refreshAlerts = () => {
      Promise.allSettled([
        fetchDashboardContainers(),
        fetchDashboardSwarm(),
        fetchDashboardVMs(),
        fetchDashboardExternal(),
      ]).then(([c, s, v, e]) => {
```

Replace the entire `useEffect` block (from `useEffect(() => {` through the matching closing `}, [])`) with:

```jsx
  // Rebuild alert list whenever dashboard data updates
  useEffect(() => {
    const issues = []
    let idx = 0
    for (const x of rawContainers?.containers || []) if (x.problem) issues.push({ sev: x.dot, text: `${x.name} ${x.problem}`, idx: idx++ })
    for (const x of rawSwarm?.services         || []) if (x.problem) issues.push({ sev: x.dot, text: `${x.name} ${x.problem}`, idx: idx++ })
    for (const x of [...(rawVms?.vms || []), ...(rawVms?.lxc || [])]) if (x.problem) issues.push({ sev: x.dot, text: `${x.name} ${x.problem}`, idx: idx++ })
    for (const x of rawExternal?.services      || []) if (x.problem) issues.push({ sev: x.dot, text: `${x.name} ${x.problem}`, idx: idx++ })
    issues.sort((a, b) => (SEV[a.sev] ?? 2) - (SEV[b.sev] ?? 2) || a.idx - b.idx)
    setAlerts(issues)
    if (issues.length === 0) setAlertTrayOpen(false)
  }, [rawContainers, rawSwarm, rawVms, rawExternal])
```

Also remove `fetchStats, fetchHealth, fetchDashboardContainers, fetchDashboardSwarm, fetchDashboardVMs, fetchDashboardExternal` from the SubBar import at the top of App.jsx (keep fetchStats and fetchHealth in api.js — they're still used elsewhere via the context).

### 3d — Update DashboardView to use context

In `DashboardView`, find:

```jsx
  useEffect(() => {
    fetchStats().then(setStats).catch(() => {})
    const id = setInterval(() => fetchStats().then(setStats).catch(() => {}), 30000)
    return () => clearInterval(id)
  }, [])
  useEffect(() => {
    const load = () => fetchDashboardExternal()
      .then(d => setExternalData(d?.services || []))
      .catch(() => {})
    load()
    const id = setInterval(load, 30000)
    return () => clearInterval(id)
  }, [])
```

Replace with:

```jsx
  const { stats: ctxStats, externalData: ctxExternal } = useDashboardData()
```

And update all references to `stats` → `ctxStats` and `externalData` → `ctxExternal?.services || []` in DashboardView. Remove the `[stats, setStats]` and `[externalData, setExternalData]` useState declarations from DashboardView.

Also remove the `dirtyRef/saveLayoutRef` auto-save effect that references `externalData` if it uses the old state.

### 3e — Update PlatformCoreCards to use context

In `PlatformCoreCards`, replace the entire `useEffect` polling block with context data:

Find:
```jsx
  const [health, setHealth] = useState(null)
  const [statusData, setStatusData] = useState(null)
  const [memHealth, setMemHealth] = useState(null)
  const [containers, setContainers] = useState([])
  useEffect(() => {
    const load = () => {
      fetchHealth().then(setHealth).catch(() => {})
      fetchStatus().then(setStatusData).catch(() => {})
      fetchMemoryHealth().then(setMemHealth).catch(() => {})
      fetchDashboardContainers().then(d => setContainers(d?.containers || [])).catch(() => {})
    }
    load()
    const id = setInterval(load, 30000)
    return () => clearInterval(id)
  }, [])
```

Replace with:

```jsx
  const [memHealth, setMemHealth] = useState(null)
  const { health, collectorsData, containersData, summary } = useDashboardData()
  const statusData = summary ? {
    kafka: summary.swarm ? { health: 'unknown' } : null,  // kafka comes from /api/status directly
    elasticsearch: null,
    collectors: collectorsData,
  } : null
  const containers = containersData?.containers || []

  // Keep fetching status (kafka/es health) + memHealth separately — not in summary
  const [fullStatus, setFullStatus] = useState(null)
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

Then update `statusData` references in PlatformCoreCards to use `fullStatus` for kafka/es health, and `collectorsData` for collectors. Specifically:
- `const kafkaHealth = fullStatus?.kafka?.health || 'unknown'`
- `const esHealth = fullStatus?.elasticsearch?.health || 'unknown'`
- `const sortedCollectors = Object.entries(collectorsData || {}).sort(...)`

### 3f — Update ConnectionSectionCards to use context

In `ConnectionSectionCards`, replace the `useEffect` polling block:

Find:
```jsx
  useEffect(() => {
    const load = () => {
      fetch(`${import.meta.env.VITE_API_BASE ?? ''}/api/connections`, { headers: { ...authHeaders() } })
        .then(r => r.ok ? r.json() : { data: [] })
        .then(d => setConns(...))
        .catch(() => {})
    }
    load()
    const id = setInterval(load, 30000)
    return () => clearInterval(id)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
```

Replace with:
```jsx
  const { connections } = useDashboardData()
  useEffect(() => {
    if (!connections) return
    setConns(
      connections
        .filter(c => platforms.includes(c.platform) && c.host)
        .sort((a, b) => (a.label || a.host || '').localeCompare(b.label || b.host || ''))
    )
  }, [connections, platforms])
```

Remove the `[conns, setConns]` useState since it's now derived from the context.
Actually keep `[conns, setConns]` but remove the fetch loop.

---

## Change 4 — gui/src/components/VMHostsSection.jsx

Replace the independent fetch in VMHostsSection with context data.

Find:
```jsx
  const load = useCallback(() => {
    fetch(`${BASE}/api/dashboard/vm-hosts`, { headers: { ...authHeaders() } })
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setData(d); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  useEffect(() => { load(); const id = setInterval(load, 60000); return () => clearInterval(id) }, [load])
```

Replace with:
```jsx
  const { vmHostsData, summaryLoading } = useDashboardData()
  const data = vmHostsData
  const loading = summaryLoading && !vmHostsData
```

Update the `load` reference (used in `onAction`) to call `refreshSummary` from context:
```jsx
  const { vmHostsData, summaryLoading, refreshSummary } = useDashboardData()
  const data = vmHostsData
  const loading = summaryLoading && !vmHostsData
```

Pass `refreshSummary` as `onAction` instead of the local `load`.

In the VMCard usage: `<VMCard key={...} vm={vm} onAction={refreshSummary} />`

---

## Change 5 — gui/src/api.js — add fetchPipelineHealth

After `fetchResultRef`, add:
```js
export async function fetchPipelineHealth() {
  const r = await fetch(`${BASE}/api/status/pipeline`, { headers: { ...authHeaders() } })
  if (!r.ok) return null
  return r.json()
}
```

---

## Do NOT touch

- Any backend files other than `api/routers/dashboard.py`
- `api/agents/router.py`
- Any collector files

---

## Version bump

Update `VERSION`: `2.21.2` → `2.22.0`

---

## Commit

```bash
git add -A
git commit -m "feat(perf): v2.22.0 dashboard summary endpoint + DashboardDataContext

- GET /api/dashboard/summary: single endpoint returning containers+swarm+vms+
  external+vm_hosts+collectors in one response (5 parallel PG snapshot reads)
- DashboardDataContext: shared React context replacing 5 independent pollers
- Tiered refresh: external=30s, summary=60s, stats=60s, health=90s, connections=once
- Staggered initial load: requests spaced 200ms apart to avoid simultaneous burst
- SubBar: removed 6-call-per-30s polling, now derives alert list from context data
- DashboardView: removed duplicate stats + external fetch (was every 30s)
- PlatformCoreCards: removed 4-call-per-30s polling, kafka/es still fetched at 90s
- ConnectionSectionCards: removed 30s interval, now derives from context connections
- VMHostsSection: removed independent 60s fetch, now reads from context vmHostsData
- Net result: ~12 simultaneous API calls on load → 5 staggered calls; 
  30s duty cycle from ~20 calls → 2 calls (external + summary)"
git push origin main
```
