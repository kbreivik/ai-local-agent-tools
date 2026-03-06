import { useCallback, useEffect, useState } from 'react'
import { fetchLogs } from '../api'

const FILTERS = ['all', 'ok', 'degraded', 'failed', 'escalated', 'error']

const STATUS_STYLE = {
  ok:        'bg-green-900 text-green-300',
  degraded:  'bg-yellow-900 text-yellow-300',
  failed:    'bg-red-900 text-red-300',
  escalated: 'bg-orange-900 text-orange-300',
  error:     'bg-red-900 text-red-400',
  running:   'bg-blue-900 text-blue-300',
}

function Badge({ status }) {
  return (
    <span className={`px-1.5 py-0.5 rounded text-xs font-mono ${STATUS_STYLE[status] ?? 'bg-slate-700 text-slate-300'}`}>
      {status}
    </span>
  )
}

function Row({ log, onClick, expanded }) {
  const ts = new Date(log.timestamp).toLocaleTimeString()
  let params = {}
  let result = {}
  try { params = JSON.parse(log.params || '{}') } catch {}
  try { result = JSON.parse(log.result || '{}') } catch {}

  return (
    <>
      <tr
        className="border-b border-slate-800 hover:bg-slate-800 cursor-pointer text-xs"
        onClick={onClick}
      >
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

export default function LogTable({ refreshTick }) {
  const [filter, setFilter]   = useState('all')
  const [logs, setLogs]       = useState([])
  const [total, setTotal]     = useState(0)
  const [expanded, setExpanded] = useState(null)
  const [loading, setLoading] = useState(false)

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
      {/* Filter bar */}
      <div className="flex items-center gap-1 px-3 py-2 border-b border-slate-700 flex-wrap">
        <span className="text-xs text-slate-500 mr-1 uppercase font-bold">Logs</span>
        {FILTERS.map(f => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`text-xs px-2 py-0.5 rounded transition-colors ${
              filter === f
                ? 'bg-blue-600 text-white'
                : 'bg-slate-700 text-slate-400 hover:bg-slate-600'
            }`}
          >
            {f}
          </button>
        ))}
        <span className="ml-auto text-xs text-slate-600">{total} records</span>
        <button onClick={load} className="text-xs text-slate-500 hover:text-slate-300">↺</button>
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto">
        {loading && <p className="text-xs text-slate-500 p-3 animate-pulse">Loading…</p>}
        {!loading && logs.length === 0 && (
          <p className="text-xs text-slate-600 p-3">No logs yet. Run a tool or agent task.</p>
        )}
        {logs.length > 0 && (
          <table className="w-full border-collapse text-xs">
            <thead className="sticky top-0 bg-slate-900 border-b border-slate-700">
              <tr>
                {['Time', 'Tool', 'Params', 'Status', 'Duration', 'Model'].map(h => (
                  <th key={h} className="px-2 py-1.5 text-left text-slate-500 font-semibold uppercase text-xs whitespace-nowrap">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {logs.map(log => (
                <Row
                  key={log.id}
                  log={log}
                  expanded={expanded === log.id}
                  onClick={() => setExpanded(expanded === log.id ? null : log.id)}
                />
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
