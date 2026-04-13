# CC PROMPT — v2.17.0 — Entity timeline view

## What this does

Clicking an entity card opens EntityDrawer. Currently it shows status, metadata,
and an AI ask widget. The entity_changes and entity_events tables (written by
collectors since v2.9.0) are never surfaced to the user. This adds a TIMELINE
section at the bottom of EntityDrawer that shows recent field changes and discrete
events (restarts, version changes, threshold crossings) for the selected entity,
grouped by day and sorted newest-first. Also adds a backend endpoint to serve
this data.

Version bump: 2.16.1 → 2.17.0

---

## Change 1 — api/routers/entities.py

Add a new endpoint at the bottom of the file, before the final blank line:

```python
@router.get("/{entity_id:path}/history")
async def entity_history(
    entity_id: str,
    hours: int = 48,
    _: str = Depends(get_current_user),
):
    """Return recent field changes and discrete events for one entity.

    entity_id is path-encoded (may contain colons, e.g. proxmox:hp1:100).
    hours: look-back window, default 48h, max 168h (7 days).
    """
    hours = min(max(1, hours), 168)
    from api.db.entity_history import get_changes, get_events
    changes = get_changes(entity_id, hours=hours, limit=50)
    events  = get_events(entity_id,  hours=hours, limit=50)
    return {
        "entity_id": entity_id,
        "hours":     hours,
        "changes":   changes,
        "events":    events,
    }
```

---

## Change 2 — gui/src/api.js

Add one new function at the end of the Dashboard section (after `fetchContainerTags`):

```js
export async function fetchEntityHistory(entityId, hours = 48) {
  const r = await fetch(
    `${BASE}/api/entities/${encodeURIComponent(entityId)}/history?hours=${hours}`,
    { headers: { ...authHeaders() } }
  )
  if (!r.ok) return { changes: [], events: [] }
  return r.json()
}
```

---

## Change 3 — gui/src/components/EntityDrawer.jsx

### 3a — Add import

At the top of the file, add to the existing import from `../api`:

```js
import { authHeaders, askAgent, fetchAskSuggestions, fetchEntityHistory } from '../api'
```

### 3b — Add timeline state

Inside the `EntityDrawer` component, after the existing state declarations
(`const [suggestions, setSuggestions] = useState([])`), add:

```js
const [timeline, setTimeline]       = useState(null)   // { changes, events } | null
const [tlLoading, setTlLoading]     = useState(false)
const [tlHours, setTlHours]         = useState(48)
const [tlOpen, setTlOpen]           = useState(false)
```

### 3c — Add timeline fetch effect

After the existing `useEffect` that calls `fetchAskSuggestions`, add:

```js
  // Load timeline when drawer opens or hours changes (lazy — only when tlOpen)
  useEffect(() => {
    if (!entityId || !tlOpen) return
    setTlLoading(true)
    fetchEntityHistory(entityId, tlHours)
      .then(d => setTimeline(d))
      .catch(() => setTimeline({ changes: [], events: [] }))
      .finally(() => setTlLoading(false))
  }, [entityId, tlOpen, tlHours])
```

### 3d — Add the TIMELINE section to the drawer body

Find the closing `</div>` of the drawer's scrollable content area. It is the div
that contains the entity status, metadata rows, and the ask widget. Inside that
scrollable div, after the AI ask section and before its closing `</div>`, add:

```jsx
        {/* ── TIMELINE ────────────────────────────────────────────── */}
        <div style={{ marginTop: 16, borderTop: '1px solid var(--border)' }}>
          <button
            onClick={() => setTlOpen(o => !o)}
            style={{
              width: '100%', display: 'flex', alignItems: 'center',
              justifyContent: 'space-between', padding: '8px 0',
              background: 'none', border: 'none', cursor: 'pointer',
              fontFamily: 'var(--font-mono)', fontSize: 9,
              letterSpacing: '0.08em', color: 'var(--text-3)',
            }}
          >
            <span>TIMELINE</span>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              {tlOpen && (
                <select
                  value={tlHours}
                  onChange={e => { e.stopPropagation(); setTlHours(Number(e.target.value)) }}
                  onClick={e => e.stopPropagation()}
                  style={{
                    fontSize: 8, fontFamily: 'var(--font-mono)', background: 'var(--bg-2)',
                    border: '1px solid var(--border)', borderRadius: 2,
                    color: 'var(--text-2)', padding: '1px 4px', cursor: 'pointer',
                  }}
                >
                  <option value={24}>24h</option>
                  <option value={48}>48h</option>
                  <option value={168}>7d</option>
                </select>
              )}
              <span style={{ fontSize: 8 }}>{tlOpen ? '▲' : '▼'}</span>
            </div>
          </button>

          {tlOpen && (
            <div style={{ paddingBottom: 12 }}>
              {tlLoading && (
                <div style={{ fontSize: 9, color: 'var(--text-3)', fontFamily: 'var(--font-mono)', padding: '4px 0' }}>
                  Loading timeline…
                </div>
              )}

              {!tlLoading && timeline && (() => {
                const items = [
                  ...(timeline.changes || []).map(c => ({
                    kind: 'change',
                    ts: c.detected_at,
                    label: c.field_name,
                    detail: `${c.old_value ?? '—'} → ${c.new_value}`,
                    color: 'var(--cyan)',
                  })),
                  ...(timeline.events || []).map(e => ({
                    kind: 'event',
                    ts: e.occurred_at,
                    label: e.event_type,
                    detail: e.description,
                    color: e.severity === 'critical' ? 'var(--red)'
                         : e.severity === 'error'    ? 'var(--red)'
                         : e.severity === 'warning'  ? 'var(--amber)'
                         : 'var(--green)',
                  })),
                ].sort((a, b) => new Date(b.ts) - new Date(a.ts))

                if (items.length === 0) {
                  return (
                    <div style={{ fontSize: 9, color: 'var(--text-3)', fontFamily: 'var(--font-mono)', padding: '4px 0' }}>
                      No changes or events in the last {tlHours}h
                    </div>
                  )
                }

                // Group by calendar day
                const byDay = {}
                for (const item of items) {
                  const day = item.ts ? new Date(item.ts).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' }) : 'Unknown'
                  if (!byDay[day]) byDay[day] = []
                  byDay[day].push(item)
                }

                return Object.entries(byDay).map(([day, dayItems]) => (
                  <div key={day} style={{ marginBottom: 10 }}>
                    <div style={{
                      fontSize: 8, fontFamily: 'var(--font-mono)', color: 'var(--text-3)',
                      letterSpacing: '0.08em', marginBottom: 4, textTransform: 'uppercase',
                    }}>{day}</div>
                    {dayItems.map((item, i) => (
                      <div key={i} style={{
                        display: 'flex', gap: 8, marginBottom: 4, alignItems: 'flex-start',
                      }}>
                        <div style={{
                          width: 6, height: 6, borderRadius: '50%',
                          background: item.color, flexShrink: 0, marginTop: 3,
                        }} />
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ display: 'flex', gap: 6, alignItems: 'baseline' }}>
                            <span style={{
                              fontSize: 9, fontFamily: 'var(--font-mono)',
                              color: item.color, letterSpacing: '0.04em',
                            }}>{item.label}</span>
                            <span style={{ fontSize: 8, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>
                              {item.ts ? new Date(item.ts).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }) : ''}
                            </span>
                          </div>
                          <div style={{
                            fontSize: 9, color: 'var(--text-2)', fontFamily: 'var(--font-mono)',
                            wordBreak: 'break-word',
                          }}>{item.detail}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                ))
              })()}

              {!tlLoading && !timeline && (
                <div style={{ fontSize: 9, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>
                  Timeline unavailable
                </div>
              )}
            </div>
          )}
        </div>
```

---

## Do NOT touch

- `entity_history.py` — no changes, endpoint calls it directly
- `api/main.py` — entities router already mounted
- Any collector files
- Any other component

---

## Version bump

Update `VERSION`: `2.16.1` → `2.17.0`

---

## Commit

```bash
git add -A
git commit -m "feat(ui): v2.17.0 entity timeline view — field changes + events in EntityDrawer

- GET /api/entities/{entity_id}/history?hours=N — new endpoint serving entity_changes + entity_events
- fetchEntityHistory() added to api.js
- EntityDrawer: collapsible TIMELINE section at bottom showing changes (cyan) and events (severity-colored)
- Items sorted newest-first, grouped by calendar day
- Time window selector: 24h / 48h / 7d — lazy-loaded only when expanded
- Colour coding: cyan=field change, green=info event, amber=warning, red=error/critical
- entity_changes and entity_events tables have been written by collectors since v2.9.0"
git push origin main
```
