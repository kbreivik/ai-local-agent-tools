# CC PROMPT — v2.10.1 — Small fixes batch

## What this does

Three small deferred fixes bundled together:
1. Alert banner: show health transition (healthy → degraded) in Logs tab alert rows
2. FortiGate ConnectionFilterBar — same pattern as UniFi (already built in v2.7.2)
3. status_snapshots retention — delete rows older than 30 days on a schedule

Version bump: 2.10.0 → 2.10.1 (small fixes, x.x.1)

---

## Change 1 — gui/src/components/AlertsPanel.jsx (or wherever alert rows render)

Find where alert rows are rendered in the Logs tab. Each alert has `health`,
`prev_health`, `severity`, and `connection_label` from the backend.

Add a health transition badge next to the alert title/timestamp:

```jsx
{alert.prev_health && alert.health && alert.prev_health !== alert.health && (
  <span style={{
    fontSize: 8, fontFamily: 'var(--font-mono)', padding: '1px 5px',
    borderRadius: 2, marginLeft: 6,
    background: alert.health === 'critical' ? 'rgba(204,40,40,0.15)' :
                alert.health === 'degraded'  ? 'rgba(204,136,0,0.12)' :
                alert.health === 'healthy'   ? 'rgba(0,170,68,0.12)'  : 'var(--bg-3)',
    color:      alert.health === 'critical' ? 'var(--red)' :
                alert.health === 'degraded'  ? 'var(--amber)' :
                alert.health === 'healthy'   ? 'var(--green)'  : 'var(--text-3)',
  }}>
    {alert.prev_health} → {alert.health}
  </span>
)}
```

Search for where `alert.message` or `alert.component` is rendered in the alert list
and add this span inline. The `prev_health` and `health` fields are already sent by
`api/alerts.py` — no backend change needed.

---

## Change 2 — gui/src/components/ServiceCards.jsx — FortiGate ConnectionFilterBar

Find the UniFi section in ServiceCards.jsx which uses `ConnectionFilterBar`.
Add an identical block for FortiGate using interface type as the filter field.

The FortiGate card data has interface items with a `type` field (physical, vlan, etc.)
and `link` (true/false). Add a filter bar with:

```js
const FG_FILTER_FIELDS = [
  { key: 'type',   label: 'type' },
  { key: 'status', label: 'status' },   // 'up' or 'down'
]
```

The pattern is identical to UniFi — find the UniFi ConnectionFilterBar implementation
in ServiceCards.jsx and replicate it for fortigate, using:
- `fgFilterStates` / `setFgFilterStates` for state
- `fgActiveFilters` / `setFgActiveFilters` for active filters
- Same `applyConnectionFilters()` helper already in the file

---

## Change 3 — api/main.py — status_snapshots retention cleanup

Add a background cleanup task that runs once per day and deletes
status_snapshots rows older than 30 days:

```python
@app.on_event("startup")
async def _schedule_snapshot_cleanup():
    async def _cleanup_loop():
        while True:
            await asyncio.sleep(86400)   # 24 hours
            try:
                from api.db.base import get_engine
                from sqlalchemy import text as _t
                async with get_engine().begin() as conn:
                    result = await conn.execute(_t(
                        "DELETE FROM status_snapshots WHERE timestamp < NOW() - INTERVAL '30 days'"
                    ))
                    deleted = result.rowcount
                    if deleted:
                        log.info("status_snapshots cleanup: deleted %d rows older than 30 days", deleted)
            except Exception as _e:
                log.debug("status_snapshots cleanup error: %s", _e)
    asyncio.create_task(_cleanup_loop())
```

Also add a one-time immediate cleanup on startup (first run may have large backlog):

```python
    # One-time cleanup on startup
    try:
        from api.db.base import get_engine
        from sqlalchemy import text as _t
        async with get_engine().begin() as conn:
            await conn.execute(_t(
                "DELETE FROM status_snapshots WHERE timestamp < NOW() - INTERVAL '30 days'"
            ))
    except Exception:
        pass
```

---

## Version bump

Update VERSION: `2.10.0` → `2.10.1`

---

## Commit

```bash
git add -A
git commit -m "fix: v2.10.1 alert transition badge, FortiGate filter bar, snapshot retention

- Alert rows: show prev_health → health transition badge with severity colour
- FortiGate: add ConnectionFilterBar (type/status) same pattern as UniFi
- status_snapshots: daily cleanup task deletes rows >30 days, one-time on startup"
git push origin main
```
