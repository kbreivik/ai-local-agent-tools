/**
 * LogsPanel — live Elasticsearch log stream + error summary.
 * Polls /api/elastic/logs every 5s for recent entries (tail -f style).
 * Filter bar: service | level | keyword.
 * Color-coded by level.
 */
import { useEffect, useState, useCallback, useRef } from 'react'

const BASE = import.meta.env.VITE_API_BASE ?? ''
const POLL_MS = 5_000

const LEVEL_STYLE = {
  debug:    'text-slate-600',
  info:     'text-slate-300',
  warn:     'text-yellow-400',
  warning:  'text-yellow-400',
  error:    'text-red-400',
  critical: 'text-red-300 font-bold',
  fatal:    'text-red-300 font-bold',
}
const LEVEL_BG = {
  error:    'bg-red-950',
  critical: 'bg-red-950',
  fatal:    'bg-red-950',
  warn:     'bg-yellow-950',
  warning:  'bg-yellow-950',
}

function levelStyle(lvl = '') {
  const l = lvl.toLowerCase()
  return LEVEL_STYLE[l] ?? 'text-slate-400'
}
function levelBg(lvl = '') {
  const l = lvl.toLowerCase()
  return LEVEL_BG[l] ?? ''
}

function LogLine({ entry }) {
  const ts = entry.timestamp
    ? new Date(entry.timestamp).toLocaleTimeString()
    : '??:??:??'
  const lvl = (entry.level || 'info').toLowerCase()
  const svc = entry.service || entry.container || entry.hostname || ''

  return (
    <div className={`flex gap-2 px-2 py-0.5 font-mono text-xs ${levelBg(lvl)} hover:bg-slate-800`}>
      <span className="text-slate-600 shrink-0 w-20">{ts}</span>
      <span className={`shrink-0 w-10 uppercase ${levelStyle(lvl)}`}>{lvl}</span>
      {svc && (
        <span className="text-blue-500 shrink-0 truncate max-w-[120px]" title={svc}>
          {svc.replace(/^.*_stack_/, '')}
        </span>
      )}
      <span className={`flex-1 break-all ${levelStyle(lvl)}`}>{entry.message}</span>
    </div>
  )
}

function ErrorSummary({ errors }) {
  if (!errors || Object.keys(errors).length === 0) return null
  return (
    <div className="px-3 py-2 border-b border-slate-800 shrink-0">
      <p className="text-xs text-slate-500 uppercase font-semibold mb-1">Errors (last 30min)</p>
      <div className="flex flex-wrap gap-1.5">
        {Object.entries(errors).map(([svc, count]) => (
          <span key={svc} className="bg-red-900 text-red-300 px-2 py-0.5 rounded text-xs font-mono">
            {svc.replace(/^.*_stack_/, '') || 'unknown'}: {count}
          </span>
        ))}
      </div>
    </div>
  )
}

export default function LogsPanel() {
  const [logs, setLogs]           = useState([])
  const [errors, setErrors]       = useState({})
  const [available, setAvailable] = useState(true)
  const [filter, setFilter]       = useState({ service: '', level: '', q: '' })
  const [paused, setPaused]       = useState(false)
  const listRef                   = useRef(null)
  const seenIds                   = useRef(new Set())

  const fetchLogs = useCallback(async () => {
    try {
      const p = new URLSearchParams({
        minutes_ago: 1,
        size: 100,
        ...(filter.service && { service: filter.service }),
        ...(filter.level  && { level:   filter.level }),
        ...(filter.q      && { q:       filter.q }),
      })
      const r = await fetch(`${BASE}/api/elastic/logs?${p}`)
      const d = await r.json()
      if (d.available === false) { setAvailable(false); return }
      setAvailable(true)

      const newEntries = (d.logs || []).filter(e => !seenIds.current.has(e.id))
      newEntries.forEach(e => seenIds.current.add(e.id))
      if (newEntries.length > 0) {
        setLogs(prev => [...newEntries, ...prev].slice(0, 500))
      }
    } catch { /* ES offline */ }
  }, [filter])

  const fetchErrors = useCallback(async () => {
    try {
      const r = await fetch(`${BASE}/api/elastic/errors?minutes_ago=30`)
      const d = await r.json()
      if (d.available !== false) setErrors(d.by_service || {})
    } catch { /* */ }
  }, [])

  useEffect(() => {
    fetchLogs()
    fetchErrors()
    if (paused) return
    const id = setInterval(() => { fetchLogs(); fetchErrors() }, POLL_MS)
    return () => clearInterval(id)
  }, [fetchLogs, fetchErrors, paused])

  const handleFilterChange = (k, v) => {
    setFilter(prev => ({ ...prev, [k]: v }))
    seenIds.current.clear()
    setLogs([])
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-slate-700 shrink-0">
        <span className="text-xs font-bold uppercase tracking-wider text-slate-400">
          Live Logs
        </span>
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${available ? 'bg-green-500' : 'bg-red-600 animate-pulse'}`} />
          <button
            onClick={() => setPaused(p => !p)}
            className={`text-xs px-2 py-0.5 rounded border transition-colors ${
              paused
                ? 'border-yellow-700 text-yellow-400 bg-yellow-950'
                : 'border-slate-700 text-slate-500 hover:text-slate-300'
            }`}
          >
            {paused ? '▶ Resume' : '⏸ Pause'}
          </button>
          <button
            onClick={() => { seenIds.current.clear(); setLogs([]); fetchLogs() }}
            className="text-xs text-slate-500 hover:text-slate-300"
            title="Clear"
          >
            ✕
          </button>
        </div>
      </div>

      {/* Filter bar */}
      <div className="flex gap-2 px-3 py-1.5 border-b border-slate-800 shrink-0">
        <input
          value={filter.service}
          onChange={e => handleFilterChange('service', e.target.value)}
          placeholder="service…"
          className="w-24 bg-slate-800 text-slate-300 text-xs rounded px-2 py-1 border border-slate-700 focus:outline-none focus:border-blue-600 placeholder-slate-600"
        />
        <select
          value={filter.level}
          onChange={e => handleFilterChange('level', e.target.value)}
          className="bg-slate-800 text-slate-300 text-xs rounded px-2 py-1 border border-slate-700 focus:outline-none"
        >
          <option value="">all levels</option>
          <option value="debug">debug</option>
          <option value="info">info</option>
          <option value="warn">warn</option>
          <option value="error">error</option>
          <option value="critical">critical</option>
        </select>
        <input
          value={filter.q}
          onChange={e => handleFilterChange('q', e.target.value)}
          placeholder="keyword…"
          className="flex-1 bg-slate-800 text-slate-300 text-xs rounded px-2 py-1 border border-slate-700 focus:outline-none focus:border-blue-600 placeholder-slate-600"
        />
      </div>

      {/* Error summary bar */}
      <ErrorSummary errors={errors} />

      {/* Log stream */}
      <div
        ref={listRef}
        className="flex-1 overflow-y-auto font-mono"
      >
        {!available && (
          <p className="text-xs text-slate-500 p-4 text-center">
            Elasticsearch unavailable — set ELASTIC_URL to enable log streaming
          </p>
        )}
        {available && logs.length === 0 && (
          <p className="text-xs text-slate-600 p-4 text-center italic">
            Waiting for log events…
          </p>
        )}
        {logs.map((entry, i) => (
          <LogLine key={entry.id || i} entry={entry} />
        ))}
      </div>

      {/* Footer */}
      <div className="px-3 py-1 border-t border-slate-800 shrink-0 flex justify-between">
        <p className="text-xs text-slate-700">{logs.length} entries buffered</p>
        {paused && <p className="text-xs text-yellow-600">⏸ Paused</p>}
      </div>
    </div>
  )
}
