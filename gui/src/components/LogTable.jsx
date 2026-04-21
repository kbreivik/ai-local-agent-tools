import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchLogs, fetchOperations, fetchOperationDetail, fetchEscalations, resolveEscalation, fetchStats, authHeaders } from '../api'
import { fmtDateTime, fmtTime } from '../utils/fmtTs'
import CopyableId from './CopyableId'

const FEEDBACK_ICON = { thumbs_up: '👍', thumbs_down: '👎' }

const BASE = import.meta.env.VITE_API_BASE ?? ''

// Keep the `fmtTs` name for minimal diff across the file — but now
// returns the v2.38.5 full "YYYY-MM-DD HH:MM:SS" format.
const fmtTs = fmtDateTime

async function fetchCorrelation(opId) {
  const r = await fetch(`${BASE}/api/elastic/correlate/${opId}`, { headers: authHeaders() })
  if (!r.ok) return { error: `HTTP ${r.status}` }
  return r.json()
}

const STATUS_STYLE = {
  ok:        'bg-green-900 text-green-300',
  degraded:  'bg-yellow-900 text-yellow-300',
  failed:    'bg-red-900 text-red-300',
  escalated: 'bg-orange-900 text-orange-300',
  error:     'bg-red-900 text-red-400',
  running:   'bg-blue-900 text-blue-300',
  completed: 'bg-green-900 text-green-300',
}

function Badge({ status }) {
  return (
    <span className={`px-1.5 py-0.5 rounded text-xs font-mono ${STATUS_STYLE[status] ?? 'bg-slate-700 text-slate-300'}`}>
      {status}
    </span>
  )
}

// Safely coerce a value that may be a string (old SQLite) or object (new API) to object
function safeObj(v) {
  if (!v) return {}
  if (typeof v === 'object') return v
  try { return JSON.parse(v) } catch { return {} }
}

// ── Tool Call view ────────────────────────────────────────────────────────────

const TC_FILTERS = ['all', 'ok', 'degraded', 'failed', 'escalated', 'error']

function TcRow({ log, expanded, onClick }) {
  const ts = fmtTs(log.timestamp)
  const params = safeObj(log.params)
  const result = safeObj(log.result)
  return (
    <>
      <tr className="border-b border-slate-800 hover:bg-slate-800 cursor-pointer text-xs" onClick={onClick}>
        <td className="px-2 py-1.5 text-slate-400 whitespace-nowrap">{ts}</td>
        <td className="px-2 py-1.5 whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
          <CopyableId value={log.id} />
        </td>
        <td className="px-2 py-1.5 whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
          <CopyableId value={log.session_id} dim />
        </td>
        <td className="px-2 py-1.5 text-blue-300 font-mono whitespace-nowrap">{log.tool_name}</td>
        <td className="px-2 py-1.5 text-slate-400 truncate max-w-[120px]">
          {Object.keys(params).length
            ? Object.entries(params).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(' ')
            : '—'}
        </td>
        <td className="px-2 py-1.5"><Badge status={log.status} /></td>
        <td className="px-2 py-1.5 text-slate-500 whitespace-nowrap">
          {log.duration_ms != null ? `${log.duration_ms}ms` : '—'}
        </td>
        <td className="px-2 py-1.5 text-slate-600 truncate max-w-[100px]" title={log.model_used}>
          {log.model_used?.split('/').pop() ?? '—'}
        </td>
      </tr>
      {expanded && (
        <tr className="bg-slate-900">
          <td colSpan={8} className="px-3 py-2">
            <pre className="text-xs text-slate-300 whitespace-pre-wrap max-h-40 overflow-y-auto">
              {JSON.stringify(result, null, 2)}
            </pre>
          </td>
        </tr>
      )}
    </>
  )
}

// ── Correlation view (operation detail) ──────────────────────────────────────

function CorrelationView({ operationId }) {
  const [corr, setCorr]     = useState(null)
  const [loading, setLoading] = useState(false)
  const [shown, setShown]   = useState(false)

  const load = () => {
    if (loading || corr) { setShown(s => !s); return }
    setLoading(true)
    setShown(true)
    fetchCorrelation(operationId)
      .then(setCorr)
      .catch(() => setCorr({ error: 'Correlation failed' }))
      .finally(() => setLoading(false))
  }

  if (!shown) {
    return (
      <button
        onClick={load}
        className="text-xs text-blue-500 hover:text-blue-400 underline mt-1"
      >
        + Correlated Logs
      </button>
    )
  }

  return (
    <div className="mt-2 border border-slate-700 rounded p-2">
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs text-slate-400 font-semibold">Correlated Logs</span>
        <button onClick={() => setShown(false)} className="text-slate-600 hover:text-slate-400 text-xs">×</button>
      </div>
      {loading && <p className="text-xs text-slate-500 animate-pulse">Loading…</p>}
      {corr?.error && <p className="text-xs text-red-400">{corr.error}</p>}
      {corr && !corr.error && (
        <div className="text-xs space-y-2">
          {/* Summary counters */}
          <div className="flex gap-4 flex-wrap text-slate-500">
            <span>Total logs: <span className="text-slate-300">{corr.total_log_count ?? 0}</span></span>
            <span className={corr.error_count > 0 ? 'text-red-400' : ''}>
              Errors: <span className="font-semibold">{corr.error_count ?? 0}</span>
            </span>
            {corr.warn_count > 0 && (
              <span className="text-yellow-400">Warnings: <span className="font-semibold">{corr.warn_count}</span></span>
            )}
            {corr.window_seconds && (
              <span className="text-slate-600">Window: {corr.window_seconds}s</span>
            )}
          </div>

          {/* Anomalies */}
          {corr.anomalies?.length > 0 && (
            <div className="bg-red-950 border border-red-800 rounded px-2 py-1.5 space-y-0.5">
              <p className="text-red-400 font-semibold uppercase tracking-wider text-xs mb-1">Anomalies</p>
              {corr.anomalies.map((a, i) => (
                <p key={i} className="text-red-300">⚠ {a}</p>
              ))}
            </div>
          )}

          {/* Error summary */}
          {corr.error_summary && (
            <div className="bg-slate-800 rounded px-2 py-1.5">
              <span className="text-slate-500 font-semibold">Summary: </span>
              <span className="text-red-300">{corr.error_summary}</span>
            </div>
          )}

          {/* Elasticsearch unavailable fallback */}
          {corr.total_log_count === 0 && !corr.anomalies?.length && (
            <p className="text-slate-600 italic">
              No correlated logs found — Elasticsearch may be unavailable or no logs were indexed during this operation.
            </p>
          )}

          {/* Log entries grouped by level */}
          {corr.all_logs?.length > 0 && (
            <div className="max-h-64 overflow-y-auto space-y-0.5 mt-1 font-mono border border-slate-700 rounded p-1">
              {corr.all_logs.slice(0, 50).map((lg, i) => {
                const lvl = lg.level?.toLowerCase() ?? 'info'
                const lvlColor = lvl === 'error' ? 'text-red-400' : lvl === 'warn' ? 'text-yellow-400' : lvl === 'debug' ? 'text-slate-600' : 'text-slate-400'
                const service = lg.container_name || lg.service_name || lg['container.name'] || ''
                return (
                  <div key={i} className="py-0.5 border-b border-slate-800 last:border-0">
                    <div className="flex gap-2 items-start">
                      <span className="text-slate-600 shrink-0 w-16">{fmtTs(lg.timestamp ?? lg['@timestamp'])}</span>
                      <span className={`shrink-0 uppercase w-9 font-bold ${lvlColor}`}>{lg.level?.slice(0, 4) ?? 'INFO'}</span>
                      {service && <span className="text-blue-500 shrink-0 truncate max-w-[80px]" title={service}>{service}</span>}
                      <span className="text-slate-300 break-words leading-relaxed">{(lg.message ?? lg['log.message'] ?? '').slice(0, 320)}</span>
                    </div>
                  </div>
                )
              })}
              {corr.all_logs.length > 50 && (
                <p className="text-slate-600 text-center py-1">… {corr.all_logs.length - 50} more entries</p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export function ToolCallsView({ refreshTick }) {
  const [filter, setFilter] = useState('all')
  const [logs, setLogs]     = useState([])
  const [total, setTotal]   = useState(0)
  const [expanded, setExpanded] = useState(null)
  const [loading, setLoading]   = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    fetchLogs({ status: filter, limit: 100 })
      .then(d => { setLogs(d.logs ?? []); setTotal(d.total ?? 0) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [filter])

  useEffect(load, [load, refreshTick])

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-1 px-3 py-1.5 border-b border-slate-700 flex-wrap shrink-0">
        {TC_FILTERS.map(f => (
          <button key={f} onClick={() => setFilter(f)}
            className={`text-xs px-2 py-0.5 rounded ${filter === f ? 'bg-blue-600 text-white' : 'bg-slate-700 text-slate-400 hover:bg-slate-600'}`}>
            {f}
          </button>
        ))}
        <span className="ml-auto text-xs text-slate-600">{total} records</span>
        <button onClick={load} className="text-xs text-slate-500 hover:text-slate-300">↺</button>
      </div>
      <div className="flex-1 overflow-auto">
        {loading && <p className="text-xs text-slate-500 p-3 animate-pulse">Loading…</p>}
        {!loading && logs.length === 0 && <p className="text-xs text-slate-600 p-3">No logs yet.</p>}
        {logs.length > 0 && (
          <table className="w-full border-collapse text-xs">
            <thead className="sticky top-0 bg-slate-900 border-b border-slate-700">
              <tr>{['Time','ID','Session','Tool','Params','Status','Duration','Model'].map(h => (
                <th key={h} className="px-2 py-1.5 text-left text-slate-500 font-semibold uppercase text-xs whitespace-nowrap">{h}</th>
              ))}</tr>
            </thead>
            <tbody>
              {logs.map(log => (
                <TcRow key={log.id} log={log}
                  expanded={expanded === log.id}
                  onClick={() => setExpanded(expanded === log.id ? null : log.id)} />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

// ── Session raw output view ───────────────────────────────────────────────────

const OUTPUT_TYPES = ['all', 'step', 'tool', 'reasoning', 'memory', 'halt', 'done', 'error']

const OUTPUT_ICON = {
  step:      { icon: '──', color: '#64748b' },
  reasoning: { icon: '\u{1F4AD}', color: '#cbd5e1' },
  tool:      { icon: '\u2699',  color: '#93c5fd' },
  memory:    { icon: '\u25C8',  color: '#64748b' },
  halt:      { icon: '\u26A0',  color: '#fb923c' },
  done:      { icon: '\u2713',  color: '#4ade80' },
  error:     { icon: '\u2717',  color: '#f87171' },
}

export function SessionOutputView({ sessionId, onClose }) {
  const [lines, setLines] = useState([])
  const [loading, setLoading] = useState(true)
  const [typeFilter, setTypeFilter] = useState('all')
  const [keyword, setKeyword] = useState('')
  const [debouncedKw, setDebouncedKw] = useState('')
  const [count, setCount] = useState(0)
  // v2.38.1: scope autoscroll to the lines container only — direct
  // scrollTop writes do not bubble up to the Operations table, so
  // the outer page stays put when filters change or the panel opens.
  const linesContainerRef = useRef(null)

  // Debounce keyword
  useEffect(() => {
    const t = setTimeout(() => setDebouncedKw(keyword), 300)
    return () => clearTimeout(t)
  }, [keyword])

  useEffect(() => {
    if (!sessionId) return
    setLoading(true)
    const params = new URLSearchParams({ limit: '1000' })
    if (typeFilter !== 'all') params.set('type_filter', typeFilter)
    if (debouncedKw) params.set('keyword', debouncedKw)
    fetch(`${BASE}/api/logs/session/${sessionId}/output?${params}`, {
      headers: { ...authHeaders() }
    })
      .then(r => r.ok ? r.json() : { lines: [], count: 0 })
      .then(d => { setLines(d.lines || []); setCount(d.count || 0) })
      .catch(() => setLines([]))
      .finally(() => setLoading(false))
  }, [sessionId, typeFilter, debouncedKw])

  useEffect(() => {
    // v2.38.1: direct scrollTop writes do NOT propagate to scrollable
    // ancestors — the outer Operations table no longer jumps when
    // this effect fires on load / filter change.
    if (!loading && lines.length > 0) {
      const el = linesContainerRef.current
      if (el) el.scrollTop = el.scrollHeight
    }
  }, [loading, lines.length])

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', height: '100%',
      background: '#0f172a', fontFamily: 'var(--font-mono, monospace)',
    }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8,
                    padding: '6px 10px', borderBottom: '1px solid #1e293b',
                    flexShrink: 0 }}>
        <span style={{ fontSize: 10, color: '#64748b', fontFamily: 'var(--font-mono)', letterSpacing: '0.08em' }}>
          RAW OUTPUT
        </span>
        <span style={{ fontSize: 9, fontFamily: 'var(--font-mono)' }}>
          <CopyableId value={sessionId} />
        </span>
        <span style={{ fontSize: 9, color: '#475569', marginLeft: 4 }}>{count} lines</span>
        {/* Type filter chips */}
        <div style={{ display: 'flex', gap: 3, marginLeft: 8, flexWrap: 'wrap' }}>
          {OUTPUT_TYPES.map(t => (
            <button key={t} onClick={() => setTypeFilter(t)}
              style={{
                fontSize: 9, padding: '1px 6px', borderRadius: 2,
                cursor: 'pointer', fontFamily: 'var(--font-mono)',
                background: typeFilter === t ? '#3b82f6' : '#1e293b',
                color: typeFilter === t ? '#fff' : '#64748b',
                border: 'none',
              }}>{t}</button>
          ))}
        </div>
        {/* Keyword search */}
        <input
          value={keyword}
          onChange={e => setKeyword(e.target.value)}
          placeholder="filter content\u2026"
          style={{
            fontSize: 10, padding: '2px 6px', borderRadius: 2, marginLeft: 'auto',
            background: '#1e293b', border: '1px solid #334155',
            color: '#cbd5e1', fontFamily: 'var(--font-mono)', width: 140, outline: 'none',
          }}
        />
        {onClose && (
          <button onClick={onClose} style={{ color: '#475569', background: 'none', border: 'none', cursor: 'pointer', fontSize: 14, lineHeight: 1, marginLeft: 4 }}>\u00D7</button>
        )}
      </div>

      {/* Lines — ref used by v2.38.1 scoped autoscroll */}
      <div ref={linesContainerRef}
           style={{ flex: 1, overflowY: 'auto', padding: '6px 0' }}>
        {loading && (
          <div style={{ padding: '12px 10px', fontSize: 10, color: '#475569', fontFamily: 'var(--font-mono)' }}>
            Loading\u2026
          </div>
        )}
        {!loading && lines.length === 0 && (
          <div style={{ padding: '12px 10px', fontSize: 10, color: '#475569', fontFamily: 'var(--font-mono)' }}>
            No lines found{typeFilter !== 'all' || debouncedKw ? ' \u2014 try adjusting filters' : ' \u2014 session may have been purged or not started yet'}.
          </div>
        )}
        {lines.map((line, i) => {
          const style = OUTPUT_ICON[line.type] ?? { icon: '\u00B7', color: '#475569' }
          // v2.38.5: full "YYYY-MM-DD HH:MM:SS" — the row already has space in
          // the left column because previous width was only for HH:MM:SS. Widen
          // the left-column width so the date fits without wrapping.
          const ts = line.timestamp ? fmtTs(line.timestamp) : ''
          return (
            <div key={line.id || i} style={{
              display: 'flex', gap: 6, alignItems: 'flex-start',
              padding: '1px 10px', borderBottom: '1px solid #0f172a',
              fontSize: 11, lineHeight: 1.5,
            }}>
              <span style={{ color: '#334155', flexShrink: 0, width: 140, fontSize: 9 }}>{ts}</span>
              <span style={{ color: style.color, flexShrink: 0, width: 16 }}>{style.icon}</span>
              <span style={{ color: line.type === 'tool' ? style.color : '#94a3b8',
                             whiteSpace: 'pre-wrap', wordBreak: 'break-all', flex: 1 }}>
                {line.content || ''}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function RawOutputToggle({ sessionId }) {
  const [show, setShow] = useState(false)
  return (
    <div>
      <button
        onClick={() => setShow(s => !s)}
        className="text-xs text-blue-500 hover:text-blue-400 underline"
      >
        {show ? '\u2212 Hide raw output' : '+ Raw output log'}
      </button>
      {show && (
        <div style={{ height: 380, marginTop: 6, borderRadius: 4, overflow: 'hidden',
                      border: '1px solid #1e293b' }}>
          <SessionOutputView sessionId={sessionId} />
        </div>
      )}
    </div>
  )
}

// ── Tree builder for parent/child operations ─────────────────────────────────

function buildOpTree(ops) {
  const bySession = {}
  ops.forEach(op => { bySession[op.session_id] = op })

  const roots = []
  const childMap = {}

  ops.forEach(op => {
    if (op.parent_session_id && bySession[op.parent_session_id]) {
      if (!childMap[op.parent_session_id]) childMap[op.parent_session_id] = []
      childMap[op.parent_session_id].push(op)
    } else {
      roots.push(op)
    }
  })

  // Flatten in depth-first order with depth info
  const result = []
  function visit(op, depth) {
    result.push({ op, depth })
    const children = childMap[op.session_id] || []
    children.forEach(c => visit(c, depth + 1))
  }
  roots.forEach(r => visit(r, 0))
  return result
}

// ── Operations view ───────────────────────────────────────────────────────────

export function OpsView({ refreshTick, highlightSessionId = '' }) {
  const [ops, setOps]         = useState([])
  const [loading, setLoading] = useState(false)
  const [detail, setDetail]   = useState(null)  // {op, tool_calls}
  const [ratedOnly, setRatedOnly] = useState(false)
  const [treeMode, setTreeMode]   = useState(true)
  const [flashSessionId, setFlashSessionId] = useState('')

  // v2.38.1: deep-link into Analysis → operation_full_context for this row.
  const openInAnalysis = useCallback((op, e) => {
    if (e) { e.stopPropagation() }
    if (!op?.id) return
    try {
      sessionStorage.setItem('deathstar_analysis_deeplink', JSON.stringify({
        template_id: 'operation_full_context',
        params: { operation_id: op.id },
      }))
    } catch {}
    window.dispatchEvent(new CustomEvent('navigate-to-tab', {
      detail: { tab: 'Analysis' },
    }))
  }, [])

  // React to highlightSessionId prop changes
  useEffect(() => {
    if (!highlightSessionId) return
    setFlashSessionId(highlightSessionId)
    // Scroll the row into view once data loads
    const t = setTimeout(() => {
      const el = document.querySelector(`[data-session-id="${highlightSessionId}"]`)
      el?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }, 150)
    // Clear flash after 1.5s
    const t2 = setTimeout(() => setFlashSessionId(''), 1500)
    return () => { clearTimeout(t); clearTimeout(t2) }
  }, [highlightSessionId])

  const load = useCallback(() => {
    setLoading(true)
    fetchOperations({ limit: 50 })
      .then(d => setOps(d.operations ?? []))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  useEffect(load, [load, refreshTick])

  const openDetail = (op) => {
    if (detail?.operation?.id === op.id) { setDetail(null); return }
    fetchOperationDetail(op.id).then(setDetail).catch(() => {})
  }

  const visible = ratedOnly ? ops.filter(op => op.feedback) : ops

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-slate-700 shrink-0">
        <span className="text-xs text-slate-500 uppercase font-bold">Operations</span>
        <button
          onClick={() => setRatedOnly(r => !r)}
          className={`text-xs px-2 py-0.5 rounded transition-colors ${
            ratedOnly ? 'bg-blue-600 text-white' : 'bg-slate-700 text-slate-400 hover:bg-slate-600'
          }`}
        >
          Rated only
        </button>
        <button
          onClick={() => setTreeMode(m => !m)}
          className={`text-xs px-2 py-0.5 rounded transition-colors ${
            treeMode ? 'bg-blue-600 text-white' : 'bg-slate-700 text-slate-400 hover:bg-slate-600'
          }`}
        >
          {treeMode ? 'Tree' : 'Flat'}
        </button>
        <button onClick={load} className="ml-auto text-xs text-slate-500 hover:text-slate-300">↺</button>
      </div>
      <div className="flex-1 overflow-auto">
        {loading && <p className="text-xs text-slate-500 p-3 animate-pulse">Loading…</p>}
        {!loading && visible.length === 0 && <p className="text-xs text-slate-600 p-3">No operations yet.</p>}
        {visible.length > 0 && (
          <table className="w-full border-collapse text-xs">
            <thead className="sticky top-0 bg-slate-900 border-b border-slate-700">
              <tr>{['Started','ID','Label','Status','Duration','Model','Calls','Feedback'].map(h => (
                <th key={h} className="px-2 py-1.5 text-left text-slate-500 font-semibold uppercase text-xs whitespace-nowrap">{h}</th>
              ))}</tr>
            </thead>
            <tbody>
              {(treeMode ? buildOpTree(visible) : visible.map(op => ({ op, depth: 0 }))).map(({ op, depth }) => (
                <>
                  <tr key={op.id} data-session-id={op.session_id}
                      className={`border-b border-slate-800 hover:bg-slate-800 cursor-pointer${flashSessionId === op.session_id ? ' ds-flash-amber' : ''}`}
                      onClick={() => openDetail(op)}>
                    <td className="px-2 py-1.5 text-slate-400 whitespace-nowrap">
                      {depth > 0 && (
                        <span style={{ paddingLeft: depth * 12, color: '#334155', marginRight: 4 }}>└</span>
                      )}
                      {fmtTs(op.started_at)}
                    </td>
                    {/* v2.38.5: use shared CopyableId pill */}
                    <td className="px-2 py-1.5 whitespace-nowrap">
                      <span onClick={(e) => e.stopPropagation()}>
                        <CopyableId value={op.id} />
                      </span>
                    </td>
                    <td className="px-2 py-1.5 text-slate-300 max-w-[280px]" title={op.label}>
                      <span className="line-clamp-2 leading-snug">{op.label ?? '—'}</span>
                    </td>
                    <td className="px-2 py-1.5"><Badge status={op.status} /></td>
                    <td className="px-2 py-1.5 text-slate-500">
                      {op.total_duration_ms != null ? `${op.total_duration_ms}ms` : '—'}
                    </td>
                    <td className="px-2 py-1.5 text-slate-600 truncate max-w-[80px]">
                      {op.model_used?.split('/').pop() ?? '—'}
                    </td>
                    <td className="px-2 py-1.5 text-slate-500">{op.tool_call_count ?? 0}</td>
                    <td className="px-2 py-1.5 text-center">
                      {FEEDBACK_ICON[op.feedback] ?? <span className="text-slate-700">—</span>}
                    </td>
                  </tr>
                  {detail?.operation?.id === op.id && (
                    <tr key={`${op.id}-detail`} className="bg-slate-900">
                      <td colSpan={8} className="px-3 py-3 space-y-3">
                        {/* Full task text */}
                        <div>
                          <p className="text-xs text-slate-500 uppercase font-semibold mb-1">Task</p>
                          <p className="text-xs text-slate-200 leading-relaxed whitespace-pre-wrap bg-slate-800 rounded px-2 py-1.5">
                            {detail.operation.label ?? '—'}
                          </p>
                        </div>

                        {/* v2.38.1: copyable Operation ID + Session ID + deep-link to Analysis */}
                        <div>
                          <p className="text-xs text-slate-500 uppercase font-semibold mb-1">Identifiers</p>
                          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs bg-slate-800 rounded px-2 py-1.5">
                            <div className="flex items-center gap-2">
                              <span className="text-slate-500">Operation ID:</span>
                              <CopyableId value={detail.operation.id} prefixLen={36} />
                            </div>
                            {detail.operation.session_id && (
                              <div className="flex items-center gap-2">
                                <span className="text-slate-500">Session ID:</span>
                                <CopyableId value={detail.operation.session_id} prefixLen={36} />
                              </div>
                            )}
                            <button
                              onClick={(e) => openInAnalysis(detail.operation, e)}
                              className="ml-auto px-2 py-0.5 bg-slate-700 hover:bg-slate-600 text-slate-200 font-mono text-xs rounded"
                              style={{ borderRadius: 2 }}
                              title="Pre-fill this operation_id in Analysis → operation_full_context"
                            >
                              Deep-dive in Analysis →
                            </button>
                          </div>
                        </div>

                        {/* Final answer */}
                        {detail.operation.final_answer && (
                          <div>
                            <p className="text-xs text-slate-500 uppercase font-semibold mb-1">Final Answer</p>
                            <p className="text-xs text-green-300 leading-relaxed whitespace-pre-wrap bg-slate-800 rounded px-2 py-1.5 max-h-40 overflow-y-auto">
                              {detail.operation.final_answer}
                            </p>
                          </div>
                        )}

                        {/* Tool calls */}
                        {detail.tool_calls?.length > 0 && (
                          <div>
                            <p className="text-xs text-slate-500 uppercase font-semibold mb-1">
                              Tool calls ({detail.tool_calls.length})
                            </p>
                            {detail.tool_calls.map(tc => (
                              <div key={tc.id} className="flex gap-3 py-0.5 border-b border-slate-800 text-xs">
                                <span className="text-slate-500 w-20 shrink-0">{fmtTs(tc.timestamp)}</span>
                                <span className="text-blue-300 font-mono w-36 shrink-0 truncate">{tc.tool_name}</span>
                                <Badge status={tc.status} />
                                <span className="text-slate-500">{tc.duration_ms != null ? `${tc.duration_ms}ms` : '—'}</span>
                              </div>
                            ))}
                          </div>
                        )}

                        {/* Raw output log */}
                        {detail.operation.session_id && (
                          <RawOutputToggle sessionId={detail.operation.session_id} />
                        )}

                        <CorrelationView operationId={op.id} />
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

// ── Escalations view ──────────────────────────────────────────────────────────

export function EscView({ refreshTick }) {
  const [escs, setEscs]     = useState([])
  const [loading, setLoading] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    fetchEscalations(50).then(d => setEscs(d.escalations ?? [])).catch(() => {}).finally(() => setLoading(false))
  }, [])

  useEffect(load, [load, refreshTick])

  const resolve = async (id) => {
    await resolveEscalation(id).catch(() => {})
    load()
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center px-3 py-1.5 border-b border-slate-700 shrink-0">
        <span className="text-xs text-slate-500 uppercase font-bold">Escalations</span>
        <button onClick={load} className="ml-auto text-xs text-slate-500 hover:text-slate-300">↺</button>
      </div>
      <div className="flex-1 overflow-auto">
        {loading && <p className="text-xs text-slate-500 p-3 animate-pulse">Loading…</p>}
        {!loading && escs.length === 0 && <p className="text-xs text-slate-600 p-3">No escalations.</p>}
        {escs.length > 0 && (
          <table className="w-full border-collapse text-xs">
            <thead className="sticky top-0 bg-slate-900 border-b border-slate-700">
              <tr>{['Time','Severity','Reason','Session','Operation','Escalation ID','Status',''].map(h => (
                <th key={h} className="px-2 py-1.5 text-left text-slate-500 font-semibold uppercase text-xs whitespace-nowrap">{h}</th>
              ))}</tr>
            </thead>
            <tbody>
              {escs.map(e => (
                <tr key={e.id} className="border-b border-slate-800 hover:bg-slate-800">
                  <td className="px-2 py-1.5 text-slate-400 whitespace-nowrap font-mono">
                    {fmtTs(e.timestamp)}
                  </td>
                  <td className="px-2 py-1.5 whitespace-nowrap">
                    <Badge status={
                      e.severity === 'critical' ? 'failed'
                      : e.severity === 'warning' ? 'degraded'
                      : 'ok'
                    } />
                  </td>
                  <td className="px-2 py-1.5 text-slate-300 truncate max-w-[260px]" title={e.reason}>{e.reason}</td>
                  <td className="px-2 py-1.5 whitespace-nowrap">
                    <CopyableId value={e.session_id} dim />
                  </td>
                  <td className="px-2 py-1.5 whitespace-nowrap">
                    <CopyableId value={e.operation_id} dim />
                  </td>
                  <td className="px-2 py-1.5 whitespace-nowrap">
                    <CopyableId value={e.id} />
                  </td>
                  <td className="px-2 py-1.5">
                    <Badge status={e.resolved ? 'ok' : 'escalated'} />
                  </td>
                  <td className="px-2 py-1.5">
                    {!e.resolved && (
                      <button onClick={() => resolve(e.id)}
                        className="text-xs px-2 py-0.5 bg-slate-700 hover:bg-slate-600 rounded text-slate-300">
                        Resolve
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

// ── Stats view ────────────────────────────────────────────────────────────────

export function StatsView() {
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    setLoading(true)
    fetchStats().then(setStats).catch(() => {}).finally(() => setLoading(false))
  }, [])

  if (loading) return <p className="text-xs text-slate-500 p-3 animate-pulse">Loading…</p>
  if (!stats) return <p className="text-xs text-slate-600 p-3">No stats yet.</p>

  const maxCount = stats.most_used_tools?.[0]?.count || 1

  return (
    <div className="flex gap-4 p-3 overflow-auto h-full">
      <div className="flex flex-col gap-3 min-w-[180px]">
        {[
          ['Total Runs', stats.total_operations],
          ['Total Tool Calls', stats.total_tool_calls],
          ['Success Rate', `${stats.success_rate}%`],
          ['Avg Duration', stats.avg_duration_ms ? `${stats.avg_duration_ms}ms` : '—'],
          ['Unresolved Escalations', stats.escalations_unresolved],
        ].map(([label, val]) => (
          <div key={label} className="flex justify-between text-xs">
            <span className="text-slate-500">{label}</span>
            <span className="text-slate-200 font-mono font-bold">{val}</span>
          </div>
        ))}
      </div>
      <div className="flex flex-col gap-1 flex-1 min-w-[160px]">
        <div className="text-xs text-slate-500 uppercase font-semibold mb-1">Top Tools</div>
        {stats.most_used_tools?.map(({ tool, count }) => (
          <div key={tool} className="flex items-center gap-2 text-xs">
            <span className="text-blue-300 font-mono w-36 shrink-0 truncate" title={tool}>{tool}</span>
            <div className="flex-1 h-2 bg-slate-800 rounded overflow-hidden">
              <div className="h-full bg-blue-600 rounded" style={{ width: `${(count / maxCount) * 100}%` }} />
            </div>
            <span className="text-slate-500 w-6 text-right">{count}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Root ──────────────────────────────────────────────────────────────────────

const VIEWS = ['Tool Calls', 'Operations', 'Escalations', 'Stats']

export default function LogTable({ refreshTick }) {
  const [view, setView] = useState('Tool Calls')
  const [sessionOutputId, setSessionOutputId] = useState(null)

  // Listen for open-session-output events from AgentFeed
  useEffect(() => {
    const handler = (e) => {
      const sid = e.detail?.session_id
      if (sid) {
        setSessionOutputId(sid)
        setView('Session Output')
      }
    }
    window.addEventListener('open-session-output', handler)
    return () => window.removeEventListener('open-session-output', handler)
  }, [])

  const allViews = [...VIEWS, ...(sessionOutputId ? ['Session Output'] : [])]

  return (
    <div className="flex flex-col h-full">
      {/* View switcher */}
      <div className="flex items-center gap-0 px-3 border-b border-slate-700 shrink-0 pt-1 overflow-x-auto">
        {allViews.map(v => (
          <button key={v} onClick={() => setView(v)}
            className={`text-xs px-3 py-1.5 border-b-2 transition-colors whitespace-nowrap ${
              view === v
                ? 'border-blue-500 text-blue-400'
                : 'border-transparent text-slate-500 hover:text-slate-300'
            }`}>
            {v}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-hidden min-h-0">
        {view === 'Tool Calls'     && <ToolCallsView refreshTick={refreshTick} />}
        {view === 'Operations'     && <OpsView refreshTick={refreshTick} />}
        {view === 'Escalations'    && <EscView refreshTick={refreshTick} />}
        {view === 'Stats'          && <StatsView />}
        {view === 'Session Output' && sessionOutputId && (
          <SessionOutputView
            sessionId={sessionOutputId}
            onClose={() => { setView('Operations'); setSessionOutputId(null) }}
          />
        )}
      </div>
    </div>
  )
}
