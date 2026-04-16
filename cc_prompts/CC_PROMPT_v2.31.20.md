# CC PROMPT — v2.31.20 — fix(windows): WindowsSection reads from DashboardDataContext

## What this does
v2.31.16 shipped `WindowsSection.jsx` which fetches from
`/api/collectors/windows/data`. That endpoint was never implemented on the
backend — it returns 404, so `data` state never populates and the WINDOWS
tile is stuck on "Loading Windows hosts…" forever, even though the
collector IS polling successfully (per `/api/entities` — MS-S1 shows up
with real data).

The rest of the dashboard uses `useDashboardData()` which reads from
`/api/dashboard/summary` (already implemented, hot-path endpoint). That's
the right pattern. This prompt wires Windows in the same way.

Two small changes:

1. **Backend** (`api/routers/dashboard.py`): the `/summary` endpoint
   currently gathers snapshots for `docker_agent01, swarm, proxmox_vms,
   external_services, vm_hosts` — add `windows` to the gather, parse it,
   and emit a `summary.windows = {hosts, health, last_updated}` block
   parallel to `summary.vm_hosts`.
2. **Frontend**:
   - `gui/src/context/DashboardDataContext.jsx`: add
     `windowsData = summary?.windows ?? null` to the derived values and
     expose it via the provider value object.
   - `gui/src/components/WindowsSection.jsx`: rewrite to consume
     `useDashboardData().windowsData` instead of doing its own fetch.
     Remove the dead `/api/collectors/windows/data` call entirely.

No new endpoints. No new state. Just wiring the existing collector output
into the existing dashboard data pipeline.

---

## Change 1 — `api/routers/dashboard.py` — include `windows` in `/summary`

Open `api/routers/dashboard.py`. Find `get_dashboard_summary()`
(the `/summary` endpoint handler). It currently looks like:

```python
    async with get_engine().connect() as conn:
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
```

Extend to include `windows`:

```python
    async with get_engine().connect() as conn:
        import asyncio as _asyncio
        (
            containers_snap,
            swarm_snap,
            vms_snap,
            external_snap,
            vm_hosts_snap,
            windows_snap,
        ) = await _asyncio.gather(
            q.get_latest_snapshot(conn, "docker_agent01"),
            q.get_latest_snapshot(conn, "swarm"),
            q.get_latest_snapshot(conn, "proxmox_vms"),
            q.get_latest_snapshot(conn, "external_services"),
            q.get_latest_snapshot(conn, "vm_hosts"),
            q.get_latest_snapshot(conn, "windows"),
        )
```

Below the existing `vm_hosts_state = _parse_state(vm_hosts_snap)` line, add:

```python
    windows_state    = _parse_state(windows_snap)
```

And in the returned dict, after the `"vm_hosts": {...}` block, insert:

```python
        "windows": {
            "hosts":        windows_state.get("hosts", []),
            "health":       windows_state.get("health", "unknown"),
            "last_updated": windows_snap.get("timestamp") if windows_snap else None,
        },
```

Keep the `"collectors": collectors,` line where it is. Shape stays
strictly additive — no existing keys renamed or removed.

---

## Change 2 — `gui/src/context/DashboardDataContext.jsx` — expose `windowsData`

Open `gui/src/context/DashboardDataContext.jsx`. Find the derived-helpers
block:

```jsx
  // ── Derived helpers ─────────────────────────────────────────────────────────
  // Provide the same shape as individual fetchDashboard* results for compatibility
  const containersData = summary?.containers ?? null
  const swarmData      = summary?.swarm      ?? null
  const vmsData        = summary?.vms        ?? null
  const vmHostsData    = summary?.vm_hosts   ?? null
  const collectorsData = summary?.collectors ?? {}
  const externalData   = external            ?? summary?.external ?? null
```

Add one line after `vmHostsData`:

```jsx
  const windowsData    = summary?.windows    ?? null
```

Then in the `DashboardDataContext.Provider` value object, find the
`vmHostsData,` line and add below it:

```jsx
      windowsData,
```

(Keep alphabetical or positional consistency with how the other keys are
listed — if they're grouped with "derived data" comment block, insert in
that block right after `vmHostsData`.)

---

## Change 3 — `gui/src/components/WindowsSection.jsx` — consume from context

Open `gui/src/components/WindowsSection.jsx`. Find the exported component:

```jsx
export default function WindowsSection({ showFilter, onEntityDetail }) {
  const [data, setData] = useState(null)

  useEffect(() => {
    const load = () => {
      fetch(`${BASE}/api/collectors/windows/data`, { headers: authHeaders() })
        .then(r => r.ok ? r.json() : null)
        .then(d => { if (d?.data) setData(d.data) })
        .catch(() => {})
    }
    load()
    const id = setInterval(load, 60000)
    return () => clearInterval(id)
  }, [])

  if (!data || !data.hosts || data.hosts.length === 0) {
    return (
      <div style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--text-3)', padding: 12 }}>
        {data?.health === 'unconfigured'
          ? 'No Windows connections configured — add one in Settings → Connections'
          : 'Loading Windows hosts…'}
      </div>
    )
  }

  // ... rest unchanged
```

Replace with:

```jsx
import { useDashboardData } from '../context/DashboardDataContext'

// ... (keep all the helper components: MemBar, DiskBar, ServiceDots, WinCard)

export default function WindowsSection({ showFilter, onEntityDetail }) {
  const { windowsData, summaryLoading } = useDashboardData()
  const data = windowsData

  if (!data || !data.hosts || data.hosts.length === 0) {
    return (
      <div style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--text-3)', padding: 12 }}>
        {summaryLoading
          ? 'Loading Windows hosts…'
          : data?.health === 'unconfigured'
          ? 'No Windows connections configured — add one in Settings → Connections'
          : 'No Windows hosts yet — collector may still be warming up'}
      </div>
    )
  }

  const hosts = data.hosts.filter(h => {
    if (!showFilter || showFilter === 'ALL') return true
    if (showFilter === 'ERRORS') return h.dot === 'red'
    if (showFilter === 'DEGRADED') return h.dot === 'amber'
    return true
  })

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 8 }}>
      {hosts.map(h => <WinCard key={h.id || h.label} host={h} onEntityDetail={onEntityDetail} />)}
    </div>
  )
}
```

Remove the now-unused imports at the top of the file:
- `useState, useEffect` → still needed by `WinCard` (keep `useState`)
- `authHeaders` → no longer used, drop it
- The `BASE` constant is unused after the change — drop it

Keep everything else (MemBar, DiskBar, ServiceDots, WinCard helper
components) exactly as it is. Only the root export changes.

---

## Commit

```
git add -A
git commit -m "fix(windows): v2.31.20 WindowsSection reads from DashboardDataContext"
git push origin main
```

---

## How to test

After CI builds and you deploy v2.31.20 on agent-01:

1. **Backend payload includes windows**:
   ```bash
   curl -s -b /tmp/hp1.cookies http://192.168.199.10:8000/api/dashboard/summary \
     | python3 -c "import sys,json;d=json.load(sys.stdin);print('windows:', json.dumps(d.get('windows'), indent=2))"
   ```
   Expect the full block:
   ```json
   {
     "hosts": [ {"id":"MS-S1","label":"MS-S1","host":"192.168.199.51","hostname":"MS-S1-SRV-01","cpu_pct":...,"mem_pct":...,...} ],
     "health": "healthy" | "degraded",
     "last_updated": "2026-04-16T..."
   }
   ```

2. **Dashboard renders the card**: refresh UI. The WINDOWS tile should
   show MS-S1 with hostname, uptime, CPU%, memory bar, disk bar. No more
   "Loading Windows hosts…" stuck state.

3. **Clicking the card opens the EntityDrawer** for `windows:MS-S1`
   (already wired via `onEntityDetail`).

4. **No more dead endpoint hits**: DevTools Network tab — filter for
   `windows/data` — should show no requests. If it still shows some,
   either the browser is serving a cached bundle (hard-refresh with
   Ctrl+Shift+R) or Change 3 didn't land correctly.

---

## Notes

- This is the pattern every new collector-driven section should follow:
  add to `/summary`, expose in context, consume in component. Any future
  collector (e.g. `synology`, `pihole`) gets the same three-step wiring
  and renders for free.
- Why not just add the `/api/collectors/windows/data` endpoint instead?
  It would work but creates a second polling path parallel to the
  `/summary` one — more fetches per minute, two snapshot-reads
  per collector instead of one. The current design was intentionally
  consolidated; let's not fragment it.
- The `summaryLoading` flag from context distinguishes "first fetch in
  flight" from "fetched but no Windows hosts configured" — cleaner UX.
