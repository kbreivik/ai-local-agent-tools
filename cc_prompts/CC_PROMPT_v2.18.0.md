# CC PROMPT — v2.18.0 — Result store viewer in Logs tab

## What this does

When an agent run stores large tool results (lists of VMs, containers, clients, etc.),
they're saved as `rs-*` references with a 2-hour TTL in the `result_store` table.
Currently there's no way to browse these from the UI — users can't see what refs
are active or what's in them. This adds a "Result Refs" sub-tab to the Logs panel
showing all active (non-expired) result refs with their metadata and a preview of
the stored rows.

Version bump: 2.17.1 → 2.18.0

---

## Change 1 — api/routers/logs.py

Add a new endpoint at the end of the file that lists active result store entries.
Find the existing file (read it first) and append before the final blank line:

```python
@router.get("/result-store")
async def list_result_refs(
    limit: int = 50,
    session_id: str = "",
    _: str = Depends(get_current_user),
):
    """List active (non-expired) result store references."""
    try:
        from api.db.result_store import _is_pg
        if not _is_pg():
            return {"refs": [], "count": 0}
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        sql = """
            SELECT id, tool_name, session_id, operation_id,
                   row_count, columns, created_at, expires_at, accessed_at
            FROM result_store
            WHERE expires_at > NOW()
        """
        params = []
        if session_id:
            sql += " AND session_id = %s"
            params.append(session_id)
        sql += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.close(); conn.close()
        for r in rows:
            for k in ('created_at', 'expires_at', 'accessed_at'):
                if r.get(k):
                    try: r[k] = r[k].isoformat()
                    except: pass
            if isinstance(r.get('columns'), list):
                r['columns'] = r['columns']
        return {"refs": rows, "count": len(rows)}
    except Exception as e:
        return {"refs": [], "count": 0, "error": str(e)}


@router.get("/result-store/{ref}")
async def get_result_ref(
    ref: str,
    offset: int = 0,
    limit: int = 20,
    _: str = Depends(get_current_user),
):
    """Retrieve rows from a specific result ref."""
    from api.db.result_store import fetch_result
    result = fetch_result(ref, offset=offset, limit=limit)
    if result is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Ref not found or expired")
    return result
```

---

## Change 2 — gui/src/api.js

Add two new functions in the Dashboard section, after `fetchEntityHistory`:

```js
export async function fetchResultRefs(sessionId = '') {
  const qs = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : ''
  const r = await fetch(`${BASE}/api/logs/result-store${qs}`, { headers: { ...authHeaders() } })
  if (!r.ok) return { refs: [], count: 0 }
  return r.json()
}

export async function fetchResultRef(ref, offset = 0, limit = 20) {
  const r = await fetch(
    `${BASE}/api/logs/result-store/${encodeURIComponent(ref)}?offset=${offset}&limit=${limit}`,
    { headers: { ...authHeaders() } }
  )
  if (!r.ok) return null
  return r.json()
}
```

---

## Change 3 — gui/src/components/LogsPanel.jsx

### 3a — Add import

Add `fetchResultRefs` and `fetchResultRef` to the existing api import:

```js
import { createUnifiedLogStream, authHeaders, fetchResultRefs, fetchResultRef } from '../api'
```

### 3b — Add ResultRefsView component

Before the `// ── Root ──` comment, add this new component:

```jsx
function ResultRefsView() {
  const [refs, setRefs] = useState([])
  const [loading, setLoading] = useState(true)
  const [openRef, setOpenRef] = useState(null)
  const [refData, setRefData] = useState(null)
  const [refLoading, setRefLoading] = useState(false)

  const load = () => {
    setLoading(true)
    fetchResultRefs()
      .then(d => setRefs(d.refs || []))
      .catch(() => setRefs([]))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
    const id = setInterval(load, 30000)
    return () => clearInterval(id)
  }, [])

  const openRows = (ref) => {
    if (openRef === ref) { setOpenRef(null); setRefData(null); return }
    setOpenRef(ref)
    setRefData(null)
    setRefLoading(true)
    fetchResultRef(ref, 0, 20)
      .then(d => setRefData(d))
      .catch(() => setRefData(null))
      .finally(() => setRefLoading(false))
  }

  const timeAgo = (iso) => {
    if (!iso) return '—'
    const age = Date.now() - new Date(iso).getTime()
    const mins = Math.round(age / 60000)
    if (mins < 60) return `${mins}m ago`
    return `${Math.round(age / 3600000)}h ago`
  }

  const expiresIn = (iso) => {
    if (!iso) return '—'
    const remaining = new Date(iso).getTime() - Date.now()
    if (remaining < 0) return 'expired'
    const mins = Math.round(remaining / 60000)
    if (mins < 60) return `${mins}m`
    return `${Math.round(remaining / 3600000)}h`
  }

  if (loading) {
    return (
      <div className="p-4 text-xs text-slate-500 font-mono">Loading result refs…</div>
    )
  }

  if (refs.length === 0) {
    return (
      <div className="p-4 text-xs text-slate-600 font-mono">
        No active result refs — refs are stored when agent tool results exceed 3KB and expire after 2h.
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full overflow-auto p-3 gap-2">
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs text-slate-500 font-mono">{refs.length} active ref{refs.length !== 1 ? 's' : ''}</span>
        <button onClick={load} className="text-xs text-slate-600 hover:text-slate-400 font-mono">↻ refresh</button>
      </div>

      {refs.map(r => (
        <div key={r.id} className="border border-slate-800 rounded overflow-hidden">
          {/* Header row */}
          <div
            className="flex items-center gap-2 px-3 py-2 bg-slate-900 cursor-pointer hover:bg-slate-800 transition-colors"
            onClick={() => openRows(r.id)}
          >
            <span className="font-mono text-xs text-violet-400 shrink-0">{r.id}</span>
            <span className="text-xs text-slate-500 shrink-0">{r.tool_name}</span>
            <span className="text-xs text-slate-600 shrink-0">{r.row_count} rows</span>
            <span className="flex-1" />
            <span className="text-xs text-slate-600 font-mono shrink-0">{timeAgo(r.created_at)}</span>
            <span
              className={`text-xs font-mono shrink-0 ${
                expiresIn(r.expires_at) === 'expired' ? 'text-red-500' : 'text-slate-600'
              }`}
            >
              exp {expiresIn(r.expires_at)}
            </span>
            <span className="text-xs text-slate-700 shrink-0">{openRef === r.id ? '▲' : '▼'}</span>
          </div>

          {/* Columns row */}
          {r.columns?.length > 0 && (
            <div className="px-3 py-1 bg-slate-950 border-t border-slate-800">
              <span className="text-xs text-slate-700 font-mono">
                cols: {r.columns.join(', ')}
              </span>
            </div>
          )}

          {/* Session link */}
          {r.session_id && (
            <div className="px-3 py-1 bg-slate-950 border-t border-slate-800">
              <span className="text-xs text-slate-700 font-mono">session: {r.session_id.slice(0, 16)}…</span>
            </div>
          )}

          {/* Expanded rows */}
          {openRef === r.id && (
            <div className="border-t border-slate-800 bg-slate-950 overflow-x-auto">
              {refLoading && (
                <div className="p-3 text-xs text-slate-600 font-mono">Loading rows…</div>
              )}
              {!refLoading && refData && (
                <>
                  <div className="px-3 py-1 text-xs text-slate-600 font-mono border-b border-slate-800">
                    {refData.total} total rows — showing {refData.items?.length ?? 0}
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs font-mono">
                      <thead>
                        <tr className="border-b border-slate-800">
                          {refData.items?.[0] && Object.keys(refData.items[0]).slice(0, 8).map(col => (
                            <th key={col} className="text-left px-3 py-1 text-slate-600 whitespace-nowrap">{col}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {(refData.items || []).map((item, i) => (
                          <tr key={i} className="border-b border-slate-900 hover:bg-slate-900">
                            {Object.values(item).slice(0, 8).map((val, j) => (
                              <td key={j} className="px-3 py-1 text-slate-400 whitespace-nowrap max-w-xs truncate">
                                {val == null ? '—' : typeof val === 'object' ? JSON.stringify(val).slice(0, 60) : String(val).slice(0, 80)}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
              {!refLoading && !refData && (
                <div className="p-3 text-xs text-red-500 font-mono">Failed to load ref data</div>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
```

### 3c — Add tab to TABS array

Find:
```js
const TABS = ['Live Logs', 'Tool Calls', 'Operations', 'Escalations', 'Stats']
```

Replace with:
```js
const TABS = ['Live Logs', 'Tool Calls', 'Operations', 'Escalations', 'Stats', 'Result Refs']
```

### 3d — Add tab render in LogsPanel

Find inside the `<div className="flex-1 overflow-hidden min-h-0">` block:
```jsx
        {tab === 'Stats'       && <StatsView />}
```

After that line, add:
```jsx
        {tab === 'Result Refs' && <ResultRefsView />}
```

---

## Do NOT touch

- `LiveLogsView`, `ToolCallsView`, `OpsView`, `EscView`, `StatsView` — no changes
- `result_store.py` — no changes (endpoint reads from it directly via `_get_conn`)
- Any other component or router

---

## Version bump

Update `VERSION`: `2.17.1` → `2.18.0`

---

## Commit

```bash
git add -A
git commit -m "feat(ui): v2.18.0 result store viewer in Logs tab

- GET /api/logs/result-store: list active (non-expired) result refs with metadata
- GET /api/logs/result-store/{ref}: retrieve paginated rows from a ref
- fetchResultRefs() + fetchResultRef() added to api.js
- ResultRefsView component: shows ref ID, tool name, row count, age, expiry
- Click any ref to expand and see first 20 rows in a table (columns auto-detected)
- Session ID shown for traceability back to the agent run
- Auto-refreshes every 30s, manual refresh button
- New 'Result Refs' sub-tab in LogsPanel tab bar"
git push origin main
```
