# CC PROMPT — v2.22.1 — Skeleton loading + WebSocket-driven live updates

## What this does

After v2.22.0 the data fetching is consolidated. This prompt adds the visual layer:

1. **Skeleton cards** — sections render immediately with placeholder shimmer rows
   while data loads. The dashboard shows structure (section headers, empty card
   outlines) from the first render instead of "Loading..." or blank space.

2. **WebSocket push for collector health changes** — when a collector transitions
   from healthy → degraded, the backend already broadcasts a `check_transition`
   alert. Wire this to immediately refresh the summary in DashboardDataContext so
   the dashboard updates within seconds of a health change — not waiting up to 60s
   for the next poll.

3. **Stale indicator** — when `summaryTs` is >90s old, show a small "⟳ stale"
   badge next to the section header. Clicking it triggers a manual refresh.

Version bump: 2.22.0 → 2.22.1

---

## Change 1 — gui/src/context/DashboardDataContext.jsx

### 1a — Listen to WebSocket for collector health events and refresh summary

In the DashboardDataProvider component, inside the mount `useEffect`, add a WebSocket
listener after the interval setup:

Find the return statement of the mount useEffect:
```jsx
    return () => {
      clearInterval(externalId)
      clearInterval(summaryId)
      clearInterval(statsId)
      clearInterval(healthId)
      window.removeEventListener('agent-done', agentDoneHandler)
    }
```

Before that return, add:
```jsx
    // WS: immediately refresh summary when health changes are broadcast
    const wsHealthHandler = (e) => {
      try {
        const msg = JSON.parse(e.data || '{}')
        // Refresh summary on: health transitions, vm_action completions,
        // escalation_recorded, swarm replica changes
        if (['alert', 'vm_action', 'escalation_recorded', 'health_change'].includes(msg.type)) {
          fetchSummary()
          if (msg.type === 'vm_action') fetchSummary()  // double refresh for action feedback
        }
      } catch (_) {}
    }
    window.addEventListener('ws:message', wsHealthHandler)
    return () => {
      clearInterval(externalId)
      clearInterval(summaryId)
      clearInterval(statsId)
      clearInterval(healthId)
      window.removeEventListener('agent-done', agentDoneHandler)
      window.removeEventListener('ws:message', wsHealthHandler)
    }
```

### 1b — Expose staleness info

In the context value object, add:
```jsx
      summaryStale: summaryTs ? (Date.now() - summaryTs) > 90_000 : false,
```

---

## Change 2 — gui/src/components/SkeletonCard.jsx (NEW FILE)

Create this small reusable skeleton component:

```jsx
/**
 * SkeletonCard — shimmer placeholder for cards while data loads.
 * Matches the visual weight of real cards to prevent layout shift.
 */
export function SkeletonRow({ width = '70%', height = 8 }) {
  return (
    <div style={{
      height, borderRadius: 2,
      background: 'linear-gradient(90deg, var(--bg-3) 25%, var(--bg-2) 50%, var(--bg-3) 75%)',
      backgroundSize: '200% 100%',
      animation: 'ds-shimmer 1.4s infinite',
      width,
    }} />
  )
}

export function SkeletonCard({ rows = 3 }) {
  return (
    <div style={{
      background: 'var(--bg-2)', border: '1px solid var(--border)',
      borderLeft: '3px solid var(--bg-3)', borderRadius: 2,
      padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 8,
    }}>
      {Array.from({ length: rows }).map((_, i) => (
        <SkeletonRow key={i} width={i === 0 ? '45%' : i % 2 === 0 ? '65%' : '80%'} />
      ))}
    </div>
  )
}

export function SkeletonGrid({ count = 4 }) {
  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
      gap: 8,
    }}>
      {Array.from({ length: count }).map((_, i) => (
        <SkeletonCard key={i} rows={3 + (i % 2)} />
      ))}
    </div>
  )
}
```

---

## Change 3 — gui/src/index.css

Add the shimmer keyframe animation. Find any existing `@keyframes` block, or add after
the existing animation declarations:

```css
@keyframes ds-shimmer {
  0%   { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}
```

---

## Change 4 — gui/src/App.jsx — use skeletons in DashboardView sections

### 4a — Import SkeletonGrid

Add import:
```jsx
import { SkeletonGrid } from './components/SkeletonCard'
```

### 4b — Use skeletons in sectionContent

In `DashboardView`, the `sectionContent` map renders ServiceCards and
ConnectionSectionCards. Wrap each with a skeleton fallback.

For the COMPUTE section, add a null-check guard. Find:

```jsx
    COMPUTE: showSection('COMPUTE') ? (
      <ServiceCardsErrorBoundary>
        <ServiceCards activeFilters={['vms']} ...
```

Wrap to show skeleton until data arrives. Add a `summaryLoading` check from context:

At the top of `DashboardView`, add:
```jsx
  const { summaryLoading, summaryStale, refreshSummary } = useDashboardData()
```

Then update each section that depends on summary data to show a skeleton:

```jsx
    COMPUTE: showSection('COMPUTE') ? (
      summaryLoading ? <SkeletonGrid count={4} /> :
      <ServiceCardsErrorBoundary>
        <ServiceCards activeFilters={['vms']} onTab={onTab} onEntityDetail={onEntityClick} compareMode={compareMode} compareSet={compareSet} onCompareAdd={onCompareAdd} showFilter={showFilter} search={search} />
      </ServiceCardsErrorBoundary>
    ) : null,

    CONTAINERS: showSection('COMPUTE') ? (
      summaryLoading ? <SkeletonGrid count={6} /> :
      <ServiceCardsErrorBoundary>
        <ServiceCards activeFilters={['containers_local', 'containers_swarm']} onTab={onTab} onEntityDetail={onEntityClick} compareMode={compareMode} compareSet={compareSet} onCompareAdd={onCompareAdd} showFilter={showFilter} search={search} />
      </ServiceCardsErrorBoundary>
    ) : null,

    VM_HOSTS: showSection('COMPUTE') ? (
      summaryLoading ? <SkeletonGrid count={5} /> :
      <VMHostsSection showFilter={showFilter} />
    ) : null,
```

### 4c — Stale badge in DrillDownBar

In the DrillDownBar component, find the `SAVE LAYOUT` button section and add a stale
refresh button after it. Add `summaryStale` and `refreshSummary` as new props to
DrillDownBar:

Add to the DrillDownBar function signature:
```jsx
function DrillDownBar({ ..., summaryStale, onRefreshSummary }) {
```

And in the DrillDownBar JSX, after the SAVE LAYOUT button:

```jsx
      {summaryStale && (
        <button
          onClick={onRefreshSummary}
          title="Dashboard data is stale — click to refresh"
          style={{
            padding: '2px 8px', fontSize: 9, fontFamily: 'var(--font-mono)', flexShrink: 0,
            background: 'var(--amber-dim)',
            color: 'var(--amber)',
            border: '1px solid var(--amber)',
            borderRadius: 2, cursor: 'pointer',
            display: 'flex', alignItems: 'center', gap: 4,
          }}
        >
          ⟳ stale
        </button>
      )}
```

Pass `summaryStale={summaryStale}` and `onRefreshSummary={refreshSummary}` in the
`<DrillDownBar ...>` invocation in DashboardView.

---

## Change 5 — api/routers/dashboard.py — broadcast health changes via WebSocket

When the summary endpoint is fetched, the backend is passive. But when a collector
detects a health degradation it calls `check_transition` which logs an alert. Wire
that to also broadcast a `health_change` WS event so the frontend can immediately refresh.

In `api/alerts.py`, find the `check_transition` function. After the existing
`fire_alert` / audit write, add a WebSocket broadcast:

Find the section inside `check_transition` that fires the alert:
```python
    _alerts.appendleft(alert)
    log.warning("ALERT [%s] %s", severity.upper(), message)
```

After that block, add:
```python
    # Broadcast health change to all connected WebSocket clients
    try:
        from api.websocket import manager as _ws_mgr
        import asyncio as _asyncio
        _loop = None
        try:
            _loop = _asyncio.get_event_loop()
        except RuntimeError:
            pass
        if _loop and _loop.is_running():
            _asyncio.ensure_future(_ws_mgr.broadcast({
                "type":      "health_change",
                "component": component,
                "severity":  severity,
                "prev":      prev,
                "current":   current_health,
                "message":   message,
                "timestamp": now.isoformat(),
            }))
    except Exception as _e:
        log.debug("health_change broadcast failed: %s", _e)
```

---

## Do NOT touch

- `api/agents/router.py`
- Any collector files
- `mcp_server/`
- `api/db/`

---

## Version bump

Update `VERSION`: `2.22.0` → `2.22.1`

---

## Commit

```bash
git add -A
git commit -m "feat(ux): v2.22.1 skeleton loading + WebSocket-driven dashboard refresh

- SkeletonCard.jsx: shimmer placeholder grid shown immediately on load
- index.css: ds-shimmer keyframe animation for skeleton effect
- DashboardView: COMPUTE/CONTAINERS/VM_HOSTS sections show skeletons while
  summaryLoading=true — layout visible instantly, data fills in
- DashboardDataContext: WS listener for health_change/vm_action/alert events
  triggers immediate refreshSummary() rather than waiting up to 60s
- DrillDownBar: 'stale' badge + click-to-refresh when summary is >90s old
- api/alerts.py: check_transition() broadcasts health_change WS event on
  any collector health transition — frontend sees changes within seconds"
git push origin main
```
