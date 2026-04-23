# CC PROMPT — v2.44.8 — feat(ui): AnalysisView overhaul — grouped dropdown, date quick-selects, search filter

## What this does

Replaces the single flat `<select>` in AnalysisView with:

1. **Grouped dropdown** — templates grouped by category (Operations, Diagnostics,
   Facts, Safety) with `<optgroup>` labels, showing template description on hover.

2. **Quick-select date filters** — for templates with `hours` or `days` params,
   show preset buttons: Last 1h · 6h · 24h · 7d · 30d. Clicking auto-fills the
   param and runs immediately.

3. **Search/filter** — text input above the dropdown that filters template titles
   in real time so you can type "fact" or "escalation" and narrow instantly.

4. **Template info card** — when a template is selected, show its description +
   param list more clearly in a proper card, not just inline text.

5. **Recent runs sidebar** — narrow left column showing last 8 queries run this
   session (template name + row_count + latency). Click to re-apply params.

6. **Results as table** — when result.columns exist, render as a proper sticky-
   header table instead of JSON tree. Keep JSON tree as fallback for complex
   nested results (like operation_full_context). Toggle button to switch views.

Version bump: 2.44.7 → 2.44.8.

---

## Change — replace `gui/src/components/AnalysisView.jsx` entirely

```jsx
/**
 * AnalysisView — v2.44.8
 * Admin-only SQL template runner. sith_lord only.
 * Grouped dropdown + search + date quick-selects + table results + history.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { authHeaders } from '../api'

const BASE = import.meta.env.VITE_API_BASE ?? ''

// ── Template categories ───────────────────────────────────────────────────────
const TEMPLATE_GROUPS = [
  {
    label: 'Operations',
    ids: ['operation_full_context', 'session_all_operations', 'recent_failures'],
  },
  {
    label: 'Diagnostics',
    ids: ['tool_error_frequency', 'escalations_detail', 'entity_recent_attempts'],
  },
  {
    label: 'Facts & Knowledge',
    ids: ['fact_history'],
  },
]

const DATE_PRESETS = [
  { label: '1h',  hours: 1 },
  { label: '6h',  hours: 6 },
  { label: '24h', hours: 24 },
  { label: '7d',  hours: 168 },
  { label: '30d', hours: 720 },
]

// ── Helpers ───────────────────────────────────────────────────────────────────
function monoStyle(extra = {}) {
  return { fontFamily: 'var(--font-mono)', fontSize: 9, ...extra }
}
function Mono({ c, children, style }) {
  return <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: `var(--${c||'text-2'})`, ...style }}>{children}</span>
}
function Btn({ onClick, disabled, accent, red, small, children, style }) {
  const col = accent ? 'var(--accent)' : red ? 'var(--red)' : 'var(--text-2)'
  const bg  = accent ? 'rgba(160,24,40,0.12)' : 'transparent'
  const bdr = accent ? 'rgba(160,24,40,0.35)' : red ? 'rgba(204,40,40,0.35)' : 'var(--border)'
  return (
    <button onClick={onClick} disabled={disabled} style={{
      fontFamily: 'var(--font-mono)', fontSize: small ? 8 : 9,
      padding: small ? '2px 6px' : '3px 9px',
      background: bg, border: `1px solid ${bdr}`, color: disabled ? 'var(--text-3)' : col,
      borderRadius: 2, cursor: disabled ? 'not-allowed' : 'pointer', ...style,
    }}>{children}</button>
  )
}

// ── Table result view ─────────────────────────────────────────────────────────
function ResultTable({ columns, rows }) {
  return (
    <div style={{ overflow: 'auto', maxHeight: '60vh' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-mono)', fontSize: 9 }}>
        <thead style={{ position: 'sticky', top: 0, background: 'var(--bg-1)', zIndex: 1 }}>
          <tr>
            {columns.map(c => (
              <th key={c} style={{ padding: '4px 8px', borderBottom: '1px solid var(--border)', color: 'var(--text-3)', textAlign: 'left', whiteSpace: 'nowrap', letterSpacing: '0.08em', textTransform: 'uppercase', fontSize: 8 }}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} style={{ borderBottom: '1px solid var(--bg-3)' }}
              onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-3)'}
              onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
              {columns.map(c => {
                const val = row[c]
                const s = val === null ? 'null' : typeof val === 'object' ? JSON.stringify(val) : String(val)
                const color = typeof val === 'number' ? 'var(--cyan)' : val === null ? 'var(--text-3)' : typeof val === 'boolean' ? 'var(--amber)' : 'var(--text-2)'
                return (
                  <td key={c} title={s.length > 60 ? s : undefined}
                    style={{ padding: '3px 8px', color, maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {s.length > 80 ? s.slice(0, 80) + '…' : s}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── JSON Tree ─────────────────────────────────────────────────────────────────
function JsonTree({ data, depth = 0 }) {
  const [open, setOpen] = useState(depth < 2)
  if (data === null) return <span style={{ color: 'var(--text-3)' }}>null</span>
  if (typeof data !== 'object') {
    const color = typeof data === 'number' ? 'var(--cyan)' : typeof data === 'boolean' ? 'var(--amber)' : 'var(--text-2)'
    return <span style={{ color }}>{typeof data === 'string' ? `"${data}"` : String(data)}</span>
  }
  const isArr = Array.isArray(data)
  const entries = isArr ? data.map((v, i) => [i, v]) : Object.entries(data)
  if (entries.length === 0) return <span style={{ color: 'var(--text-3)' }}>{isArr ? '[]' : '{}'}</span>
  return (
    <div style={{ marginLeft: depth === 0 ? 0 : 12 }}>
      <button onClick={() => setOpen(o => !o)} style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-3)', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}>
        {open ? '▼' : '▶'} {isArr ? `[${entries.length}]` : `{${entries.length}}`}
      </button>
      {open && (
        <div style={{ borderLeft: '1px dashed var(--border)', paddingLeft: 8, marginTop: 2 }}>
          {entries.map(([k, v]) => (
            <div key={k} style={{ fontFamily: 'var(--font-mono)', fontSize: 10, lineHeight: 1.6 }}>
              <span style={{ color: 'var(--accent)' }}>{k}</span>
              <span style={{ color: 'var(--text-3)' }}>: </span>
              <JsonTree data={v} depth={depth + 1} />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────
export default function AnalysisView() {
  const [templates, setTemplates]     = useState([])
  const [loadErr, setLoadErr]         = useState(null)
  const [selected, setSelected]       = useState('')
  const [paramValues, setParamValues] = useState({})
  const [result, setResult]           = useState(null)
  const [running, setRunning]         = useState(false)
  const [runErr, setRunErr]           = useState(null)
  const [search, setSearch]           = useState('')
  const [viewMode, setViewMode]       = useState('table')  // 'table' | 'json'
  const [history, setHistory]         = useState([])        // [{id, title, row_count, latency_ms, params}]

  useEffect(() => {
    fetch(`${BASE}/api/admin/analysis/templates`, { credentials: 'include', headers: authHeaders() })
      .then(async (r) => {
        if (r.status === 403) throw new Error('Access denied — sith_lord role required.')
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then(d => setTemplates(d.templates || []))
      .catch(e => setLoadErr(e.message))
  }, [])

  // Deep-link support (unchanged from v2.38.1)
  const applyDeepLink = useCallback(() => {
    try {
      const raw = sessionStorage.getItem('deathstar_analysis_deeplink')
      if (!raw) return
      const dl = JSON.parse(raw)
      sessionStorage.removeItem('deathstar_analysis_deeplink')
      if (dl?.template_id) setSelected(dl.template_id)
      if (dl?.params) setParamValues(dl.params)
      setResult(null); setRunErr(null)
    } catch { try { sessionStorage.removeItem('deathstar_analysis_deeplink') } catch {} }
  }, [])
  useEffect(() => {
    applyDeepLink()
    const handler = () => applyDeepLink()
    window.addEventListener('navigate-to-tab', handler)
    return () => window.removeEventListener('navigate-to-tab', handler)
  }, [applyDeepLink])

  const currentTpl = templates.find(t => t.id === selected)

  // Date param helpers
  const dateParams = currentTpl?.params?.filter(p => p.name === 'hours' || p.name === 'days') || []
  const hasDateParams = dateParams.length > 0

  const applyPreset = (preset) => {
    const newVals = { ...paramValues }
    if (currentTpl?.params?.find(p => p.name === 'hours')) newVals.hours = String(preset.hours)
    if (currentTpl?.params?.find(p => p.name === 'days'))  newVals.days = String(Math.round(preset.hours / 24) || 1)
    setParamValues(newVals)
    runWithParams(newVals)
  }

  const onSelect = (tid) => {
    setSelected(tid)
    setParamValues({})
    setResult(null)
    setRunErr(null)
    setSearch('')
  }

  const runWithParams = async (overrideParams = null) => {
    if (!selected) return
    const params = overrideParams || paramValues
    setRunning(true); setRunErr(null); setResult(null)
    try {
      const r = await fetch(`${BASE}/api/admin/analysis/run`, {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ template_id: selected, params }),
      })
      const data = await r.json()
      if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`)
      setResult(data)
      setHistory(h => [{
        id: selected, title: currentTpl?.title || selected,
        row_count: data.row_count, latency_ms: data.latency_ms, params,
        ts: new Date().toLocaleTimeString(),
      }, ...h].slice(0, 8))
    } catch (e) {
      setRunErr(String(e.message || e))
    } finally {
      setRunning(false) 
    }
  }

  const download = (format) => {
    if (!selected) return
    fetch(`${BASE}/api/admin/analysis/dump?format=${format}`, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ template_id: selected, params: paramValues }),
    }).then(async r => {
      if (!r.ok) throw new Error((await r.json().catch(()=>({}))).detail || `HTTP ${r.status}`)
      return r.blob().then(blob => ({ blob, r }))
    }).then(({ blob, r }) => {
      const cd = r.headers.get('Content-Disposition') || ''
      const match = /filename="?([^"]+)"?/i.exec(cd)
      const filename = match ? match[1] : `analysis-${selected}.${format}`
      const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(blob), download: filename })
      document.body.appendChild(a); a.click(); a.remove()
      URL.revokeObjectURL(a.href)
    }).catch(e => setRunErr(String(e.message || e)))
  }

  // Filtered + grouped templates
  const q = search.toLowerCase()
  const filtered = templates.filter(t => !q || t.title.toLowerCase().includes(q) || t.id.includes(q))
  const filteredIds = new Set(filtered.map(t => t.id))

  // Build grouped options
  const assignedIds = new Set(TEMPLATE_GROUPS.flatMap(g => g.ids))
  const ungrouped = filtered.filter(t => !assignedIds.has(t.id))

  if (loadErr) return <div style={{ padding: 16, fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--amber)' }}>{loadErr}</div>

  const isNested = currentTpl?.row_cap === 1 || selected === 'operation_full_context'

  return (
    <div style={{ display: 'flex', height: '100%', overflow: 'hidden', background: 'var(--bg-0)' }}>

      {/* ── Left: history sidebar ── */}
      {history.length > 0 && (
        <div style={{ width: 180, flexShrink: 0, borderRight: '1px solid var(--border)', display: 'flex', flexDirection: 'column', overflow: 'hidden', background: 'var(--bg-1)' }}>
          <div style={{ ...monoStyle({ color: 'var(--text-3)', letterSpacing: '0.15em', textTransform: 'uppercase' }), padding: '10px 10px 6px' }}>RECENT</div>
          <div style={{ flex: 1, overflowY: 'auto' }}>
            {history.map((h, i) => (
              <div key={i} onClick={() => { setSelected(h.id); setParamValues(h.params); setResult(null) }}
                style={{ padding: '5px 10px', cursor: 'pointer', borderBottom: '1px solid var(--bg-3)' }}
                onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-3)'}
                onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
                <div style={{ ...monoStyle({ color: 'var(--text-1)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }) }}>{h.title}</div>
                <div style={{ display: 'flex', gap: 6, marginTop: 2 }}>
                  <Mono c="text-3">{h.ts}</Mono>
                  <Mono c="cyan">{h.row_count}r</Mono>
                  <Mono c="text-3">{h.latency_ms}ms</Mono>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Main ── */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

        {/* Header */}
        <div style={{ padding: '12px 16px 0', flexShrink: 0 }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--accent)', letterSpacing: '0.15em', textTransform: 'uppercase', marginBottom: 2 }}>Analysis — SQL Templates</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-3)', marginBottom: 10 }}>Admin only · results capped per template · downloads available after run</div>
        </div>

        {/* Controls */}
        <div style={{ padding: '0 16px 12px', flexShrink: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>

          {/* Search + dropdown row */}
          <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
            <div style={{ flex: 1 }}>
              <div style={{ ...monoStyle({ color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 3 }) }}>Template</div>
              <div style={{ position: 'relative' }}>
                <input value={search} onChange={e => setSearch(e.target.value)}
                  placeholder="search templates…"
                  style={{ ...monoStyle(), padding: '4px 8px', background: 'var(--bg-1)', border: '1px solid var(--border)', color: 'var(--text-1)', borderRadius: 2, width: '100%', marginBottom: 4 }} />
                <select value={selected} onChange={e => onSelect(e.target.value)}
                  style={{ ...monoStyle({ fontSize: 10 }), padding: '4px 8px', background: 'var(--bg-1)', border: '1px solid var(--border)', color: selected ? 'var(--text-1)' : 'var(--text-3)', borderRadius: 2, width: '100%' }}>
                  <option value="">— pick a template —</option>
                  {TEMPLATE_GROUPS.map(g => {
                    const gFiltered = g.ids.filter(id => filteredIds.has(id))
                    if (gFiltered.length === 0) return null
                    return (
                      <optgroup key={g.label} label={g.label}>
                        {gFiltered.map(id => {
                          const t = templates.find(x => x.id === id)
                          return t ? <option key={id} value={id}>{t.title}</option> : null
                        })}
                      </optgroup>
                    )
                  })}
                  {ungrouped.length > 0 && (
                    <optgroup label="Other">
                      {ungrouped.map(t => <option key={t.id} value={t.id}>{t.title}</option>)}
                    </optgroup>
                  )}
                </select>
              </div>
            </div>
          </div>

          {/* Template description */}
          {currentTpl && (
            <div style={{ background: 'var(--bg-2)', border: '1px solid var(--border)', borderRadius: 2, padding: '7px 10px' }}>
              <div style={{ ...monoStyle({ color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 4 }) }}>{currentTpl.title}</div>
              <div style={{ ...monoStyle({ color: 'var(--text-2)', lineHeight: 1.6 }) }}>{currentTpl.description}</div>
            </div>
          )}

          {/* Date quick-selects */}
          {hasDateParams && (
            <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
              <Mono c="text-3">Quick: </Mono>
              {DATE_PRESETS.map(p => (
                <Btn key={p.label} small onClick={() => applyPreset(p)} disabled={running}>{p.label}</Btn>
              ))}
            </div>
          )}

          {/* Param form */}
          {currentTpl?.params?.length > 0 && (
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'flex-end' }}>
              {currentTpl.params.map(p => (
                <label key={p.name} style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  <span style={{ ...monoStyle({ color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.1em' }) }}>
                    {p.name}{p.required ? ' *' : ''} <span style={{ color: 'var(--text-3)', textTransform: 'none' }}>({p.type})</span>
                  </span>
                  <input
                    type={p.type === 'int' ? 'number' : 'text'}
                    value={paramValues[p.name] ?? ''}
                    onChange={e => setParamValues(v => ({ ...v, [p.name]: e.target.value }))}
                    placeholder={p.default !== undefined ? String(p.default) : ''}
                    style={{ ...monoStyle({ fontSize: 10 }), padding: '3px 8px', background: 'var(--bg-1)', border: '1px solid var(--border)', color: 'var(--text-1)', borderRadius: 2, width: p.type === 'uuid' ? 280 : 120 }}
                  />
                  {p.description && <span style={{ ...monoStyle({ color: 'var(--text-3)', fontSize: 8 }) }}>{p.description}</span>}
                </label>
              ))}
            </div>
          )}

          {/* Action buttons */}
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <Btn accent onClick={() => runWithParams()} disabled={!selected || running}>
              {running ? '⟳ running…' : '▶ run'}
            </Btn>
            {result && !isNested && (
              <div style={{ display: 'flex', gap: 4, background: 'var(--bg-2)', border: '1px solid var(--border)', borderRadius: 2, padding: '1px 2px' }}>
                {['table','json'].map(m => (
                  <button key={m} onClick={() => setViewMode(m)} style={{ ...monoStyle({ fontSize: 8, textTransform: 'uppercase' }), padding: '2px 7px', background: viewMode===m ? 'var(--accent-dim)' : 'transparent', border: 'none', color: viewMode===m ? 'var(--accent)' : 'var(--text-3)', borderRadius: 1, cursor: 'pointer' }}>{m}</button>
                ))}
              </div>
            )}
            {result && ['json','csv','md'].map(f => (
              <Btn key={f} small onClick={() => download(f)}>↓ {f.toUpperCase()}</Btn>
            ))}
          </div>

          {runErr && <div style={{ ...monoStyle({ color: 'var(--red)', fontSize: 10 }), whiteSpace: 'pre-wrap' }}>{runErr}</div>}
        </div>

        {/* Results */}
        {result && (
          <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column', margin: '0 16px 16px', border: '1px solid var(--border)', borderRadius: 2, background: 'var(--bg-1)' }}>
            <div style={{ display: 'flex', gap: 12, padding: '5px 10px', borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
              <Mono c="text-3">rows: <span style={{ color: 'var(--text-1)' }}>{result.row_count}</span></Mono>
              {result.truncated && <Mono c="amber">truncated</Mono>}
              <Mono c="text-3">latency: {result.latency_ms}ms</Mono>
              <Mono c="text-3">{(result.columns||[]).slice(0,6).join(' · ')}{result.columns?.length > 6 ? ` +${result.columns.length - 6}` : ''}</Mono>
            </div>
            <div style={{ flex: 1, overflow: 'auto', padding: viewMode === 'json' ? 8 : 0 }}>
              {(viewMode === 'table' && !isNested)
                ? <ResultTable columns={result.columns || []} rows={result.rows || []} />
                : <JsonTree data={result.rows} />
              }
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
```

---

## Version bump

Update `VERSION`: `2.44.7` → `2.44.8`

---

## Commit

```
git add -A
git commit -m "feat(ui): v2.44.8 AnalysisView — grouped dropdown, search, date quick-selects, table view, history sidebar"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
