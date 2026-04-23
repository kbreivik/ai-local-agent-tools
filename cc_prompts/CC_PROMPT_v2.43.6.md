# CC PROMPT — v2.43.6 — feat(ui): Collectors monitor view + Session Output sidebar items

## What this does

Two missing sidebar views:

1. **Collectors** (under MONITOR) — shows each collector: name, health dot,
   last poll time, poll interval, entity count from snapshot, error if any,
   and a trigger-poll button. Data already exists in `collectorsData` from
   the dashboard summary (`coll_mgr.status()`) plus per-collector snapshots.

2. **Session Output** (under OPERATE) — shows all session output log entries
   from `operation_log` table, filterable by session/type/keyword. The API
   endpoint `/api/logs/session/{session_id}/output` already exists. This view
   lists recent sessions and lets the user drill into the raw output of any run.

Version bump: 2.43.5 → 2.43.6.

---

## Change 1 — `gui/src/components/Sidebar.jsx`

Add two items to the nav structure:

Under MONITOR, add after `ExternalAICalls`:
```js
{ key: 'Collectors', icon: '⟳', label: 'Collectors' },
```

Under OPERATE, add after `Output`:
```js
{ key: 'SessionOutput', icon: '▤', label: 'Session Output' },
```

---

## Change 2 — `gui/src/components/CollectorsTab.jsx` (NEW FILE)

```jsx
/**
 * CollectorsTab — Monitor → Collectors
 * Shows each active collector: health, last poll, interval, error, trigger button.
 * Data source: /api/dashboard/summary → collectors (coll_mgr.status())
 *              /api/logs/snapshots/{component} for entity counts
 */
import { useState, useEffect, useCallback } from 'react'
import { authHeaders } from '../api'

const BASE = import.meta.env.VITE_API_BASE ?? ''

const DOT_COLOR = {
  healthy: 'var(--green)',
  ok:      'var(--green)',
  degraded:'var(--amber)',
  error:   'var(--red)',
  unknown: 'var(--text-3)',
  unconfigured: 'var(--text-3)',
}

function healthDot(h) {
  return (
    <span style={{
      display: 'inline-block', width: 7, height: 7, borderRadius: '50%',
      background: DOT_COLOR[h] || 'var(--text-3)', marginRight: 6, flexShrink: 0,
    }} />
  )
}

function ago(iso) {
  if (!iso) return 'never'
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 5) return 'just now'
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.round(s / 60)}m ago`
  return `${Math.round(s / 3600)}h ago`
}

export default function CollectorsTab() {
  const [collectors, setCollectors] = useState({})
  const [triggering, setTriggering] = useState({})
  const [triggerMsg, setTriggerMsg] = useState({})
  const [loading, setLoading] = useState(true)
  const [lastRefresh, setLastRefresh] = useState(null)

  const load = useCallback(async () => {
    try {
      const r = await fetch(`${BASE}/api/dashboard/summary`, { headers: authHeaders() })
      if (!r.ok) return
      const d = await r.json()
      setCollectors(d.collectors || {})
      setLastRefresh(new Date())
    } catch (_) {}
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load(); const t = setInterval(load, 15_000); return () => clearInterval(t) }, [load])

  const trigger = async (name) => {
    setTriggering(p => ({ ...p, [name]: true }))
    setTriggerMsg(p => ({ ...p, [name]: '' }))
    try {
      const r = await fetch(`${BASE}/api/dashboard/trigger-poll`, {
        method: 'POST', headers: { ...authHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ component: name }),
      })
      const d = await r.json().catch(() => ({}))
      setTriggerMsg(p => ({ ...p, [name]: r.ok ? 'triggered' : (d.detail || 'error') }))
      setTimeout(() => {
        setTriggerMsg(p => ({ ...p, [name]: '' }))
        load()
      }, 2500)
    } catch (e) {
      setTriggerMsg(p => ({ ...p, [name]: 'error' }))
    } finally {
      setTriggering(p => ({ ...p, [name]: false }))
    }
  }

  const sorted = Object.entries(collectors).sort(([a], [b]) => a.localeCompare(b))

  return (
    <div style={{ padding: '20px 24px', maxWidth: 900 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-3)', letterSpacing: '0.15em', textTransform: 'uppercase' }}>
          COLLECTORS
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {lastRefresh && (
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-3)' }}>
              refreshed {ago(lastRefresh.toISOString())}
            </span>
          )}
          <button onClick={load} style={{
            fontFamily: 'var(--font-mono)', fontSize: 9, padding: '3px 8px',
            background: 'transparent', border: '1px solid var(--border)', color: 'var(--text-2)',
            borderRadius: 2, cursor: 'pointer',
          }}>↻ refresh</button>
        </div>
      </div>

      {loading && (
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-3)' }}>Loading...</div>
      )}

      {!loading && sorted.length === 0 && (
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-3)' }}>No collectors running.</div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {sorted.map(([name, c]) => (
          <div key={name} style={{
            border: '1px solid var(--border)',
            background: c.last_error ? 'rgba(204,40,40,0.05)' : 'var(--bg-2)',
            borderColor: c.last_error ? 'rgba(204,40,40,0.25)' : 'var(--border)',
            borderRadius: 2, padding: '9px 12px',
            display: 'grid', gridTemplateColumns: '180px 80px 100px 80px 1fr auto',
            alignItems: 'center', gap: 12,
          }}>
            {/* Name + health dot */}
            <div style={{ display: 'flex', alignItems: 'center', minWidth: 0 }}>
              {healthDot(c.last_health)}
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-1)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {name}
              </span>
            </div>
            {/* Health label */}
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: DOT_COLOR[c.last_health] || 'var(--text-3)' }}>
              {c.last_health || 'unknown'}
            </span>
            {/* Last poll */}
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-2)' }}>
              {c.last_poll ? ago(c.last_poll) : '—'}
            </span>
            {/* Interval */}
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-3)' }}>
              every {c.interval_s}s
            </span>
            {/* Error */}
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--red)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {c.last_error || ''}
            </span>
            {/* Trigger button */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              {triggerMsg[name] && (
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: triggerMsg[name] === 'triggered' ? 'var(--green)' : 'var(--red)' }}>
                  {triggerMsg[name]}
                </span>
              )}
              <button
                onClick={() => trigger(name)}
                disabled={!!triggering[name]}
                style={{
                  fontFamily: 'var(--font-mono)', fontSize: 9, padding: '2px 7px',
                  background: 'transparent', border: '1px solid var(--border)',
                  color: triggering[name] ? 'var(--text-3)' : 'var(--text-2)',
                  borderRadius: 2, cursor: triggering[name] ? 'not-allowed' : 'pointer',
                  whiteSpace: 'nowrap',
                }}
              >
                {triggering[name] ? '...' : '⟳ poll'}
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
```

---

## Change 3 — `gui/src/components/SessionOutputTab.jsx` (NEW FILE)

```jsx
/**
 * SessionOutputTab — Operate → Session Output
 * Lists recent operations and shows raw session output for each.
 */
import { useState, useEffect, useCallback } from 'react'
import { authHeaders } from '../api'

const BASE = import.meta.env.VITE_API_BASE ?? ''

function ago(iso) {
  if (!iso) return ''
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.round(s / 60)}m ago`
  return `${Math.round(s / 3600)}h ago`
}

const TYPE_COLOR = {
  step:      'var(--text-3)',
  tool:      'var(--cyan)',
  reasoning: 'var(--purple)',
  halt:      'var(--amber)',
  done:      'var(--green)',
  error:     'var(--red)',
  memory:    'var(--text-3)',
}

export default function SessionOutputTab({ initialSessionId }) {
  const [ops, setOps] = useState([])
  const [selectedOp, setSelectedOp] = useState(null)
  const [lines, setLines] = useState([])
  const [loadingOps, setLoadingOps] = useState(true)
  const [loadingLines, setLoadingLines] = useState(false)
  const [keyword, setKeyword] = useState('')
  const [typeFilter, setTypeFilter] = useState('')

  // Load recent operations
  useEffect(() => {
    fetch(`${BASE}/api/logs/operations?limit=30`, { headers: authHeaders() })
      .then(r => r.json())
      .then(d => { setOps(d.operations || []); setLoadingOps(false) })
      .catch(() => setLoadingOps(false))
  }, [])

  // Auto-select if initialSessionId provided
  useEffect(() => {
    if (initialSessionId && ops.length > 0) {
      const op = ops.find(o => o.session_id === initialSessionId || o.id === initialSessionId)
      if (op) selectOp(op)
    }
  }, [initialSessionId, ops])

  const selectOp = useCallback(async (op) => {
    setSelectedOp(op)
    setLines([])
    setLoadingLines(true)
    try {
      const params = new URLSearchParams({ limit: 1000 })
      if (typeFilter) params.set('type_filter', typeFilter)
      if (keyword) params.set('keyword', keyword)
      const r = await fetch(
        `${BASE}/api/logs/session/${op.session_id}/output?${params}`,
        { headers: authHeaders() }
      )
      const d = await r.json()
      setLines(d.lines || d.entries || [])
    } catch (_) {}
    finally { setLoadingLines(false) }
  }, [typeFilter, keyword])

  const reloadLines = () => { if (selectedOp) selectOp(selectedOp) }

  return (
    <div style={{ display: 'flex', height: 'calc(100vh - 90px)', overflow: 'hidden', padding: '16px 24px', gap: 16 }}>

      {/* Left: operations list */}
      <div style={{ width: 280, flexShrink: 0, display: 'flex', flexDirection: 'column', gap: 4, overflowY: 'auto' }}>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-3)', letterSpacing: '0.15em', textTransform: 'uppercase', marginBottom: 8 }}>
          RECENT SESSIONS
        </div>
        {loadingOps && <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-3)' }}>Loading...</div>}
        {ops.map(op => (
          <button
            key={op.id}
            onClick={() => selectOp(op)}
            style={{
              background: selectedOp?.id === op.id ? 'rgba(160,24,40,0.12)' : 'var(--bg-2)',
              border: `1px solid ${selectedOp?.id === op.id ? 'rgba(160,24,40,0.4)' : 'var(--border)'}`,
              borderRadius: 2, padding: '7px 10px', cursor: 'pointer',
              textAlign: 'left', display: 'flex', flexDirection: 'column', gap: 3,
            }}
          >
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-1)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {op.task?.slice(0, 45) || '(no task)'}
            </div>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 8, color: 'var(--text-3)' }}>{ago(op.started_at)}</span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 8, padding: '1px 4px', borderRadius: 1,
                background: op.status === 'completed' ? 'var(--green-dim)' : op.status === 'failed' ? 'rgba(204,40,40,0.12)' : 'var(--bg-1)',
                color: op.status === 'completed' ? 'var(--green)' : op.status === 'failed' ? 'var(--red)' : 'var(--text-3)',
                border: '1px solid transparent',
              }}>{op.status || '?'}</span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 8, color: 'var(--text-3)' }}>{op.agent_type}</span>
            </div>
          </button>
        ))}
      </div>

      {/* Right: output lines */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        {selectedOp ? (
          <>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10, flexShrink: 0 }}>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-3)', letterSpacing: '0.15em', textTransform: 'uppercase' }}>
                OUTPUT
              </div>
              <input
                value={keyword}
                onChange={e => setKeyword(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && reloadLines()}
                placeholder="filter keyword…"
                style={{
                  fontFamily: 'var(--font-mono)', fontSize: 9, padding: '3px 7px',
                  background: 'var(--bg-1)', border: '1px solid var(--border)',
                  color: 'var(--text-1)', borderRadius: 2, width: 150,
                }}
              />
              <select
                value={typeFilter}
                onChange={e => { setTypeFilter(e.target.value); setTimeout(reloadLines, 0) }}
                style={{
                  fontFamily: 'var(--font-mono)', fontSize: 9, padding: '3px 7px',
                  background: 'var(--bg-1)', border: '1px solid var(--border)',
                  color: 'var(--text-2)', borderRadius: 2,
                }}
              >
                <option value="">all types</option>
                {['step','tool','reasoning','halt','done','error','memory'].map(t =>
                  <option key={t} value={t}>{t}</option>
                )}
              </select>
              <button onClick={reloadLines} style={{
                fontFamily: 'var(--font-mono)', fontSize: 9, padding: '3px 7px',
                background: 'transparent', border: '1px solid var(--border)',
                color: 'var(--text-2)', borderRadius: 2, cursor: 'pointer',
              }}>↻</button>
            </div>
            <div style={{ flex: 1, overflowY: 'auto', background: 'var(--bg-1)', border: '1px solid var(--border)', borderRadius: 2, padding: '8px 10px' }}>
              {loadingLines && <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-3)' }}>Loading output...</div>}
              {!loadingLines && lines.length === 0 && (
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-3)' }}>No output lines found.</div>
              )}
              {lines.map((line, i) => (
                <div key={i} style={{ display: 'flex', gap: 8, marginBottom: 3, fontFamily: 'var(--font-mono)', fontSize: 9, lineHeight: 1.6 }}>
                  <span style={{ color: 'var(--text-3)', flexShrink: 0, minWidth: 50 }}>
                    {line.timestamp ? new Date(line.timestamp).toLocaleTimeString() : ''}
                  </span>
                  <span style={{ color: TYPE_COLOR[line.type] || 'var(--text-3)', flexShrink: 0, minWidth: 60 }}>
                    {line.type}
                  </span>
                  <span style={{ color: 'var(--text-2)', wordBreak: 'break-word' }}>
                    {line.content}
                  </span>
                </div>
              ))}
            </div>
          </>
        ) : (
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-3)', marginTop: 40 }}>
            ← select a session to view output
          </div>
        )}
      </div>
    </div>
  )
}
```

---

## Change 4 — `api/routers/dashboard.py` — add trigger-poll endpoint

The Collectors tab needs a trigger button. Add:

```python
@router.post("/trigger-poll")
async def trigger_poll(
    body: dict,
    user: str = Depends(get_current_user),
):
    """Trigger an immediate poll for a named collector."""
    from api.collectors import manager as coll_mgr
    component = (body or {}).get("component", "")
    if not component:
        raise HTTPException(status_code=400, detail="component required")
    try:
        await coll_mgr.trigger_poll(component)
        return {"status": "ok", "component": component}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
```

---

## Change 5 — `gui/src/App.jsx` — wire new tabs

In the `VIEW_MAP` (or equivalent tab routing object), add:

```js
Collectors:    <CollectorsTab />,
SessionOutput: <SessionOutputTab />,
```

Import both components at the top of App.jsx.

CC: search App.jsx for where tabs like `Facts`, `Memory`, `Gates` are defined in the view map and add `Collectors` and `SessionOutput` in the same pattern.

---

## Version bump

Update `VERSION`: `2.43.5` → `2.43.6`

---

## Commit

```
git add -A
git commit -m "feat(ui): v2.43.6 Collectors monitor view + Session Output sidebar items"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
