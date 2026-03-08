import { useCallback, useEffect, useState } from 'react'
import { fetchLogs, fetchOperations, fetchOperationDetail, fetchEscalations, resolveEscalation, fetchStats } from '../api'

const FEEDBACK_ICON = { thumbs_up: '👍', thumbs_down: '👎' }

const BASE = import.meta.env.VITE_API_BASE ?? ''

const fmtTs = (ts) => {
  if (!ts) return 'N/A'
  const d = new Date(ts)
  return isNaN(d.getTime()) ? 'N/A' : d.toLocaleTimeString()
}

async function fetchCorrelation(opId) {
  const r = await fetch(`${BASE}/api/elastic/correlate/${opId}`)
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
          <td colSpan={6} className="px-3 py-2">
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
        <div className="text-xs space-y-1">
          <div className="flex gap-4 text-slate-500">
            <span>Logs: {corr.total_log_count}</span>
            <span className={corr.error_count > 0 ? 'text-red-400' : ''}>
              Errors: {corr.error_count}
            </span>
          </div>
          {corr.anomalies?.length > 0 && (
            <div className="bg-red-950 rounded px-2 py-1">
              {corr.anomalies.map((a, i) => (
                <p key={i} className="text-red-300">{a}</p>
              ))}
            </div>
          )}
          {corr.error_summary && (
            <p className="text-red-400 italic">{corr.error_summary}</p>
          )}
          <div className="max-h-40 overflow-y-auto space-y-0.5 mt-1 font-mono">
            {corr.all_logs?.slice(0, 30).map((lg, i) => (
              <div key={i} className="flex gap-2">
                <span className="text-slate-600 shrink-0">
                  {fmtTs(lg.timestamp)}
                </span>
                <span className={`shrink-0 uppercase w-10 ${
                  lg.level?.toLowerCase() === 'error' ? 'text-red-400' :
                  lg.level?.toLowerCase() === 'warn' ? 'text-yellow-400' : 'text-slate-500'
                }`}>{lg.level?.slice(0, 4)}</span>
                <span className="text-slate-300 break-all">{lg.message?.slice(0, 120)}</span>
              </div>
            ))}
          </div>
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
              <tr>{['Time','Tool','Params','Status','Duration','Model'].map(h => (
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

// ── Operations view ───────────────────────────────────────────────────────────

export function OpsView({ refreshTick }) {
  const [ops, setOps]         = useState([])
  const [loading, setLoading] = useState(false)
  const [detail, setDetail]   = useState(null)  // {op, tool_calls}
  const [ratedOnly, setRatedOnly] = useState(false)

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
        <button onClick={load} className="ml-auto text-xs text-slate-500 hover:text-slate-300">↺</button>
      </div>
      <div className="flex-1 overflow-auto">
        {loading && <p className="text-xs text-slate-500 p-3 animate-pulse">Loading…</p>}
        {!loading && visible.length === 0 && <p className="text-xs text-slate-600 p-3">No operations yet.</p>}
        {visible.length > 0 && (
          <table className="w-full border-collapse text-xs">
            <thead className="sticky top-0 bg-slate-900 border-b border-slate-700">
              <tr>{['Started','Label','Status','Duration','Model','Calls','Feedback'].map(h => (
                <th key={h} className="px-2 py-1.5 text-left text-slate-500 font-semibold uppercase text-xs whitespace-nowrap">{h}</th>
              ))}</tr>
            </thead>
            <tbody>
              {visible.map(op => (
                <>
                  <tr key={op.id} className="border-b border-slate-800 hover:bg-slate-800 cursor-pointer"
                      onClick={() => openDetail(op)}>
                    <td className="px-2 py-1.5 text-slate-400 whitespace-nowrap">
                      {fmtTs(op.started_at)}
                    </td>
                    <td className="px-2 py-1.5 text-slate-300 truncate max-w-[160px]">{op.label ?? '—'}</td>
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
                      <td colSpan={7} className="px-3 py-2">
                        <div className="text-xs text-slate-400 mb-1 font-semibold">Tool calls ({detail.tool_calls?.length ?? 0})</div>
                        {detail.tool_calls?.map(tc => (
                          <div key={tc.id} className="flex gap-3 py-0.5 border-b border-slate-800">
                            <span className="text-slate-500 w-20 shrink-0">{fmtTs(tc.timestamp)}</span>
                            <span className="text-blue-300 font-mono w-36 shrink-0 truncate">{tc.tool_name}</span>
                            <Badge status={tc.status} />
                            <span className="text-slate-500">{tc.duration_ms}ms</span>
                          </div>
                        ))}
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
              <tr>{['Time','Reason','Status',''].map(h => (
                <th key={h} className="px-2 py-1.5 text-left text-slate-500 font-semibold uppercase text-xs">{h}</th>
              ))}</tr>
            </thead>
            <tbody>
              {escs.map(e => (
                <tr key={e.id} className="border-b border-slate-800 hover:bg-slate-800">
                  <td className="px-2 py-1.5 text-slate-400 whitespace-nowrap">
                    {fmtTs(e.timestamp)}
                  </td>
                  <td className="px-2 py-1.5 text-slate-300 truncate max-w-[200px]">{e.reason}</td>
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

  return (
    <div className="flex flex-col h-full">
      {/* View switcher */}
      <div className="flex items-center gap-0 px-3 border-b border-slate-700 shrink-0 pt-1">
        {VIEWS.map(v => (
          <button key={v} onClick={() => setView(v)}
            className={`text-xs px-3 py-1.5 border-b-2 transition-colors ${
              view === v
                ? 'border-blue-500 text-blue-400'
                : 'border-transparent text-slate-500 hover:text-slate-300'
            }`}>
            {v}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-hidden min-h-0">
        {view === 'Tool Calls'  && <ToolCallsView refreshTick={refreshTick} />}
        {view === 'Operations'  && <OpsView refreshTick={refreshTick} />}
        {view === 'Escalations' && <EscView refreshTick={refreshTick} />}
        {view === 'Stats'       && <StatsView />}
      </div>
    </div>
  )
}
