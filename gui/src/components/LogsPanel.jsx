/**
 * LogsPanel — unified Logs tab.
 * Sub-tabs: Live Logs | Tool Calls | Operations | Escalations | Stats
 * Live Logs: unified SSE stream — all local Docker containers + Elasticsearch.
 * Other tabs: agent tool-call / operation / escalation / stats tables.
 */
import { useEffect, useState, useRef } from 'react'
import { ToolCallsView, OpsView, EscView, StatsView, SessionOutputView } from './LogTable'
import AgentActionsTab from './AgentActionsTab'
import { createUnifiedLogStream, authHeaders, fetchResultRefs, fetchResultRef, fetchPipelineHealth } from '../api'

const _CONN_BASE = import.meta.env.VITE_API_BASE ?? ''

function matchesKeyword(entry, keyword) {
  if (!keyword.trim()) return true
  const text = `${entry.msg ?? ''} ${entry.container ?? ''} ${entry.level ?? ''}`.toLowerCase()
  return keyword.split(/\bOR\b/i).some(group =>
    group.split(/\bAND\b/i).map(t => t.trim()).filter(Boolean).every(term =>
      text.includes(term.toLowerCase())
    )
  )
}

const LEVEL_BADGE = {
  debug:    'bg-slate-800 text-slate-500',
  info:     'bg-slate-800 text-slate-300',
  warn:     'bg-yellow-950 text-yellow-400',
  warning:  'bg-yellow-950 text-yellow-400',
  error:    'bg-red-950 text-red-400',
  critical: 'bg-red-950 text-red-300',
  fatal:    'bg-red-950 text-red-300',
}

function LiveLogsView() {
  const [lines, setLines]                         = useState([])
  const [containers, setContainers]               = useState([])
  const [checkedContainers, setCheckedContainers] = useState(new Set())
  const [levelFilter, setLevelFilter]             = useState('all')
  const [keyword, setKeyword]                     = useState('')
  const [paused, setPaused]                       = useState(false)
  const [esStatus, setEsStatus]                   = useState('unknown')
  const [popoutOpen, setPopoutOpen]               = useState(false)
  const [connSources, setConnSources]             = useState([])
  const [checkedConns, setCheckedConns]            = useState(new Set())

  const pausedRef       = useRef(false)
  const esRef           = useRef(null)
  const scrollRef       = useRef(null)
  const popoutScrollRef = useRef(null)
  const seenContainers  = useRef(new Set())
  const checkedRef      = useRef(new Set())

  // Open stream on mount, close on unmount
  useEffect(() => {
    esRef.current = createUnifiedLogStream(200, (event) => {
      if (event.source === 'status') {
        if (/es.*(offline|lost)/i.test(event.msg ?? '')) setEsStatus('offline')
        return
      }
      if (event.source === 'es') setEsStatus('online')
      // Auto-register new containers
      if (event.container && !seenContainers.current.has(event.container)) {
        seenContainers.current.add(event.container)
        checkedRef.current.add(event.container)
        setContainers(Array.from(seenContainers.current).sort())
        setCheckedContainers(new Set(checkedRef.current))
      }
      if (pausedRef.current) return
      setLines(prev => [...prev, event].slice(-500))
    }, () => {
      esRef.current?.close()
      esRef.current = null
    })
    return () => { esRef.current?.close() }
  }, [])

  // Fetch connection sources for source filter pills
  useEffect(() => {
    const loadConns = () => {
      fetch(`${_CONN_BASE}/api/connections`, { headers: { ...authHeaders() } })
        .then(r => r.ok ? r.json() : { data: [] })
        .then(d => {
          const conns = (d.data || []).filter(c => c.host).map(c => ({ label: c.label || c.host, platform: c.platform }))
          setConnSources(conns)
          setCheckedConns(new Set(conns.map(c => c.label)))
        })
        .catch(() => {})
    }
    loadConns()
    const id = setInterval(loadConns, 30000)
    return () => clearInterval(id)
  }, [])

  const toggleConn = (label) => {
    setCheckedConns(prev => {
      const next = new Set(prev)
      if (next.has(label)) next.delete(label); else next.add(label)
      return next
    })
  }

  // Auto-scroll both inline and popout containers
  useEffect(() => {
    if (!paused) {
      if (scrollRef.current)       scrollRef.current.scrollTop       = scrollRef.current.scrollHeight
      if (popoutScrollRef.current) popoutScrollRef.current.scrollTop = popoutScrollRef.current.scrollHeight
    }
  }, [lines, paused])

  const togglePause = () => {
    const next = !paused
    setPaused(next)
    pausedRef.current = next
  }

  const clearLines = () => setLines([])

  const toggleAll = () => {
    const allChecked = containers.every(n => checkedContainers.has(n))
    const next = allChecked ? new Set() : new Set(containers)
    checkedRef.current = next
    setCheckedContainers(next)
  }

  const toggleContainer = (name) => {
    setCheckedContainers(prev => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name); else next.add(name)
      checkedRef.current = next
      return next
    })
  }

  // Client-side filter — containers + connection sources
  const visible = lines.filter(entry => {
    if (entry.container && !checkedContainers.has(entry.container)) return false
    // If any connection sources are unchecked, filter log lines matching those platforms
    if (connSources.length > 0) {
      const entryText = `${entry.msg ?? ''} ${entry.container ?? ''}`.toLowerCase()
      const matchedConn = connSources.find(c => entryText.includes(c.platform.toLowerCase()) || entryText.includes(c.label.toLowerCase()))
      if (matchedConn && !checkedConns.has(matchedConn.label)) return false
    }
    const lvl = (entry.level ?? 'info').toLowerCase()
    if (levelFilter === 'error' && !['error', 'critical', 'fatal'].includes(lvl)) return false
    if (levelFilter === 'warn'  && !['warn', 'warning', 'error', 'critical', 'fatal'].includes(lvl)) return false
    return matchesKeyword(entry, keyword)
  })

  const renderLine = (entry, i) => {
    const ts    = (() => { try { return new Date(entry.ts).toLocaleTimeString() } catch { return '' } })()
    const badge = LEVEL_BADGE[entry.level?.toLowerCase()] ?? 'bg-slate-800 text-slate-400'
    return (
      <div key={`${entry.ts}-${entry.container}-${i}`} className="flex gap-2 px-2 py-0.5 hover:bg-slate-800/40">
        <span className="text-slate-700 shrink-0 w-20 font-mono text-[11px]">{ts}</span>
        <span className={`shrink-0 px-1 rounded text-[10px] uppercase font-mono ${badge}`}>{entry.level}</span>
        {entry.container && (
          <span className="text-blue-500 shrink-0 truncate max-w-[140px] font-mono text-[11px]">[{entry.container}]</span>
        )}
        <span className="flex-1 break-all text-slate-300 font-mono text-[11px]">{entry.msg}</span>
      </div>
    )
  }

  const toolbar = (
    <div className="flex items-center gap-2 px-3 py-1.5 border-b border-slate-800 shrink-0 flex-wrap">
      {containers.length > 0 && (
        <button
          onClick={toggleAll}
          className={`text-[10px] px-1.5 py-0.5 rounded border font-mono transition-colors ${
            containers.every(n => checkedContainers.has(n))
              ? 'border-slate-500 text-slate-400 bg-slate-800'
              : 'border-slate-700 text-slate-600 hover:text-slate-400'
          }`}
        >
          all
        </button>
      )}
      {containers.map(name => (
        <button
          key={name}
          onClick={() => toggleContainer(name)}
          className={`text-[10px] px-1.5 py-0.5 rounded border font-mono transition-colors ${
            checkedContainers.has(name)
              ? 'border-blue-600 text-blue-400 bg-blue-950'
              : 'border-slate-700 text-slate-600 hover:text-slate-400'
          }`}
        >
          {name}
        </button>
      ))}
      {/* Connection sources — separated from container pills */}
      {connSources.length > 0 && (
        <>
          <span style={{ width: 1, height: 16, background: 'var(--border, #334155)', flexShrink: 0, margin: '0 2px' }} />
          {connSources.map(c => (
            <button
              key={c.label}
              onClick={() => toggleConn(c.label)}
              className={`text-[10px] px-1.5 py-0.5 rounded font-mono transition-colors ${
                checkedConns.has(c.label)
                  ? 'text-cyan-400 bg-cyan-950'
                  : 'text-slate-600 hover:text-slate-400'
              }`}
              style={{ borderLeft: '2px solid var(--cyan, #00c8ee)', border: `1px solid ${checkedConns.has(c.label) ? '#164e63' : '#334155'}`, borderLeftWidth: 2, borderLeftColor: 'var(--cyan, #00c8ee)' }}
            >
              {c.label}
            </button>
          ))}
        </>
      )}
      <input
        value={keyword}
        onChange={e => setKeyword(e.target.value)}
        placeholder="error OR timeout…"
        className="w-40 bg-slate-800 text-slate-300 text-xs rounded px-2 py-1 border border-slate-700 focus:outline-none focus:border-blue-600 placeholder-slate-600"
      />
      <select
        value={levelFilter}
        onChange={e => setLevelFilter(e.target.value)}
        className="bg-slate-800 text-slate-300 text-xs rounded px-2 py-1 border border-slate-700 focus:outline-none"
      >
        <option value="all">all levels</option>
        <option value="warn">warn+</option>
        <option value="error">error+</option>
      </select>
      <button
        onClick={togglePause}
        className={`text-xs px-2 py-0.5 rounded border transition-colors ${
          paused ? 'border-yellow-700 text-yellow-400 bg-yellow-950'
                 : 'border-slate-700 text-slate-500 hover:text-slate-300'
        }`}
      >
        {paused ? '▶ Resume' : '⏸ Pause'}
      </button>
      <button onClick={clearLines} className="text-xs text-slate-500 hover:text-slate-300">✕ Clear</button>
      <button onClick={() => setPopoutOpen(true)} className="text-xs text-slate-500 hover:text-slate-300">⤢ Pop out</button>
    </div>
  )

  const statusBar = (
    <div className="px-3 py-1 border-t border-slate-800 shrink-0 flex gap-4">
      <span className="text-xs text-slate-700">{containers.length} containers</span>
      <span className={`text-xs ${esStatus === 'online' ? 'text-green-700' : esStatus === 'offline' ? 'text-red-700' : 'text-slate-700'}`}>
        ES {esStatus}
      </span>
      <span className="text-xs text-slate-700">{lines.length}/500 lines</span>
      {paused && <span className="text-xs text-yellow-600">⏸ paused</span>}
    </div>
  )

  return (
    <>
      <div className="flex flex-col h-full">
        {toolbar}
        <div ref={scrollRef} className="flex-1 overflow-y-auto min-h-0">
          {lines.length === 0 && (
            <p className="text-xs text-slate-600 p-4 text-center italic">Connecting to log stream…</p>
          )}
          {visible.map(renderLine)}
        </div>
        {statusBar}
      </div>

      {popoutOpen && (
        <div
          className="fixed z-50 rounded border border-slate-700 bg-slate-950 shadow-2xl flex flex-col"
          style={{ top: '5vh', left: '5vw', width: '90vw', height: '85vh', resize: 'both', overflow: 'auto', minWidth: 600, minHeight: 300 }}
        >
          <div className="flex justify-between items-center px-3 py-1.5 border-b border-slate-800 shrink-0">
            <span className="text-xs text-slate-500 font-mono">live logs — all sources</span>
            <div className="flex gap-2">
              <button
                onClick={togglePause}
                className={`text-xs px-2 py-0.5 rounded border ${paused ? 'border-yellow-700 text-yellow-400' : 'border-slate-700 text-slate-500 hover:text-slate-300'}`}
              >
                {paused ? '▶ Resume' : '⏸ Pause'}
              </button>
              <button onClick={clearLines} className="text-xs text-slate-500 hover:text-slate-300">✕ Clear</button>
              <button onClick={() => setPopoutOpen(false)} className="text-xs text-slate-500 hover:text-slate-300">✕ Close</button>
            </div>
          </div>
          <div ref={popoutScrollRef} className="flex-1 overflow-y-auto font-mono p-2" style={{ minHeight: 0 }}>
            {visible.length === 0
              ? <span className="text-xs text-slate-600 italic">No lines match current filters…</span>
              : visible.map((entry, i) => {
                  const ts    = (() => { try { return new Date(entry.ts).toLocaleTimeString() } catch { return '' } })()
                  const badge = LEVEL_BADGE[entry.level?.toLowerCase()] ?? 'bg-slate-800 text-slate-400'
                  return (
                    <div key={`${entry.ts}-${entry.container}-${i}`} className="flex gap-2 py-0.5">
                      <span className="text-slate-700 shrink-0 w-20 text-xs">{ts}</span>
                      <span className={`shrink-0 px-1 rounded text-[10px] uppercase ${badge}`}>{entry.level}</span>
                      {entry.container && <span className="text-blue-500 shrink-0 text-xs">[{entry.container}]</span>}
                      <span className="flex-1 whitespace-pre text-slate-300 text-xs">{entry.msg}</span>
                    </div>
                  )
                })
            }
          </div>
        </div>
      )}
    </>
  )
}

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

function DataHealthView() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = () => {
    setLoading(true)
    fetchPipelineHealth()
      .then(d => setData(d))
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
    const id = setInterval(load, 30000)
    return () => clearInterval(id)
  }, [])

  const ageStr = (s) => {
    if (s === null || s === undefined) return '—'
    if (s < 60) return `${s}s ago`
    if (s < 3600) return `${Math.round(s / 60)}m ago`
    return `${Math.round(s / 3600)}h ago`
  }

  const dot = (ok, stale) => {
    if (stale) return { color: 'var(--red)', label: 'STALE' }
    if (!ok) return { color: 'var(--amber)', label: 'WARN' }
    return { color: 'var(--green)', label: 'OK' }
  }

  const healthColor = (h) =>
    h === 'healthy' ? 'var(--green)' : h === 'degraded' ? 'var(--amber)' : 'var(--red)'

  if (loading) return (
    <div className="p-4 text-xs font-mono" style={{ color: 'var(--text-3)' }}>Loading pipeline health…</div>
  )

  if (!data) return (
    <div className="p-4 text-xs font-mono" style={{ color: 'var(--text-3)' }}>Pipeline health unavailable</div>
  )

  const { collectors, postgres, elasticsearch, alerts } = data

  return (
    <div className="flex flex-col h-full overflow-auto" style={{ padding: 12, gap: 12, background: 'var(--bg-0)' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{ width: 8, height: 8, borderRadius: '50%', background: healthColor(data.health) }} />
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-1)', letterSpacing: '0.06em' }}>
            DATA PIPELINE — {data.health?.toUpperCase()}
          </span>
        </div>
        <button onClick={load} style={{ fontSize: 9, color: 'var(--text-3)', fontFamily: 'var(--font-mono)', background: 'none', border: 'none', cursor: 'pointer' }}>↻ refresh</button>
      </div>

      {/* Alert strip */}
      {(alerts?.stale_collectors?.length > 0 || alerts?.stale_pg_components?.length > 0 || alerts?.es_stale) && (
        <div style={{ padding: '6px 10px', background: 'var(--red-dim)', border: '1px solid var(--red)', borderRadius: 2, fontSize: 9, fontFamily: 'var(--font-mono)', color: 'var(--red)' }}>
          ⚠ STALE DATA:
          {alerts.stale_collectors?.length > 0 && ` collectors: ${alerts.stale_collectors.join(', ')}`}
          {alerts.stale_pg_components?.length > 0 && ` pg: ${alerts.stale_pg_components.join(', ')}`}
          {alerts.es_stale && ' elasticsearch ingest stale'}
        </div>
      )}

      {/* Two-column layout */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>

        {/* Collectors */}
        <div style={{ background: 'var(--bg-2)', border: '1px solid var(--border)', borderRadius: 2, padding: '8px 10px' }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-3)', letterSpacing: '0.08em', marginBottom: 8 }}>COLLECTORS ({collectors?.length})</div>
          {(collectors || []).map(c => {
            const d = dot(c.health === 'healthy' || c.health === 'unconfigured', c.stale)
            const dimmed = c.health === 'unconfigured'
            return (
              <div key={c.name} style={{
                display: 'flex', alignItems: 'center', gap: 6,
                padding: '3px 0', borderBottom: '1px solid var(--bg-3)',
                opacity: dimmed ? 0.45 : 1,
              }}>
                <div style={{ width: 6, height: 6, borderRadius: '50%', background: c.stale ? 'var(--red)' : c.health === 'healthy' ? 'var(--green)' : c.health === 'unconfigured' ? 'var(--text-3)' : c.health === 'degraded' ? 'var(--amber)' : 'var(--red)', flexShrink: 0 }} />
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-2)', flex: 1 }}>{c.name}</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 8, color: 'var(--text-3)' }}>{c.interval_s}s</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 8, color: c.stale ? 'var(--red)' : 'var(--text-3)' }}>
                  {c.age_s !== null ? ageStr(c.age_s) : '—'}
                </span>
                {c.stale && <span style={{ fontSize: 7, padding: '1px 4px', background: 'var(--red-dim)', color: 'var(--red)', borderRadius: 2, fontFamily: 'var(--font-mono)' }}>STALE</span>}
                {c.error && <span style={{ fontSize: 7, padding: '1px 4px', background: 'var(--red-dim)', color: 'var(--red)', borderRadius: 2, fontFamily: 'var(--font-mono)', maxWidth: 80, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={c.error}>ERR</span>}
              </div>
            )
          })}
        </div>

        {/* PostgreSQL */}
        <div style={{ background: 'var(--bg-2)', border: '1px solid var(--border)', borderRadius: 2, padding: '8px 10px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
            <div style={{ width: 6, height: 6, borderRadius: '50%', background: postgres?.connected ? 'var(--green)' : 'var(--red)', flexShrink: 0 }} />
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-3)', letterSpacing: '0.08em' }}>POSTGRESQL</span>
          </div>
          {/* Table counts */}
          <div style={{ marginBottom: 8 }}>
            {Object.entries(postgres?.table_counts || {}).map(([k, v]) => (
              <div key={k} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9, fontFamily: 'var(--font-mono)', color: 'var(--text-3)', padding: '2px 0' }}>
                <span>{k.replace(/_/g, '_')}</span>
                <span style={{ color: 'var(--text-2)' }}>{Number(v).toLocaleString()}</span>
              </div>
            ))}
          </div>
          {/* Snapshot freshness */}
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-3)', letterSpacing: '0.06em', marginBottom: 4 }}>SNAPSHOT FRESHNESS (24h)</div>
          {(postgres?.snapshots_by_component || []).map(s => (
            <div key={s.component} style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '2px 0', borderTop: '1px solid var(--bg-3)' }}>
              <div style={{ width: 5, height: 5, borderRadius: '50%', background: s.stale ? 'var(--red)' : 'var(--green)', flexShrink: 0 }} />
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 8, color: 'var(--text-2)', flex: 1 }}>{s.component}</span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 8, color: s.stale ? 'var(--red)' : 'var(--text-3)' }}>
                {s.age_s !== null ? ageStr(s.age_s) : '—'}
              </span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 7, color: 'var(--text-3)' }}>{s.snapshots_24h} snaps</span>
            </div>
          ))}
        </div>
      </div>

      {/* Elasticsearch */}
      <div style={{ background: 'var(--bg-2)', border: '1px solid var(--border)', borderRadius: 2, padding: '8px 10px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
          <div style={{ width: 6, height: 6, borderRadius: '50%',
            background: !elasticsearch?.configured ? 'var(--text-3)' : elasticsearch?.stale ? 'var(--red)' : elasticsearch?.error ? 'var(--amber)' : 'var(--green)',
            flexShrink: 0 }} />
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-3)', letterSpacing: '0.08em' }}>ELASTICSEARCH — hp1-logs-*</span>
          {elasticsearch?.stale && <span style={{ fontSize: 7, padding: '1px 4px', background: 'var(--red-dim)', color: 'var(--red)', borderRadius: 2, fontFamily: 'var(--font-mono)' }}>INGEST STALE</span>}
        </div>
        {!elasticsearch?.configured ? (
          <span style={{ fontSize: 9, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>ELASTIC_URL not configured</span>
        ) : elasticsearch?.error ? (
          <span style={{ fontSize: 9, color: 'var(--red)', fontFamily: 'var(--font-mono)' }}>Error: {elasticsearch.error}</span>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
            {[
              { label: 'TOTAL DOCS', value: elasticsearch.total_docs?.toLocaleString() },
              { label: 'LAST HOUR', value: elasticsearch.docs_last_1h?.toLocaleString() },
              { label: 'LAST 5 MIN', value: elasticsearch.docs_last_5m?.toLocaleString() },
              { label: 'INGEST RATE', value: `${elasticsearch.ingest_rate_per_min}/min` },
            ].map(({ label, value }) => (
              <div key={label} style={{ background: 'var(--bg-3)', borderRadius: 2, padding: '6px 8px' }}>
                <div style={{ fontSize: 7, color: 'var(--text-3)', fontFamily: 'var(--font-mono)', letterSpacing: '0.08em', marginBottom: 3 }}>{label}</div>
                <div style={{ fontSize: 13, color: 'var(--text-1)', fontFamily: 'var(--font-mono)' }}>{value ?? '—'}</div>
              </div>
            ))}
          </div>
        )}
        {elasticsearch?.last_document && (
          <div style={{ marginTop: 6, fontSize: 8, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>
            Last document: {ageStr(elasticsearch.last_document_age_s)} — {elasticsearch.last_document?.slice(0, 19).replace('T', ' ')}
            {elasticsearch.stale && <span style={{ color: 'var(--red)' }}> ⚠ STALE (&gt;10min)</span>}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Root ──────────────────────────────────────────────────────────────────────

const TABS = ['Live Logs', 'Tool Calls', 'Operations', 'Escalations', 'Stats', 'Result Refs', 'Data Health', 'Actions']

export default function LogsPanel() {
  const [tab, setTab] = useState('Live Logs')
  const [sessionOutputId, setSessionOutputId] = useState(null)

  // Listen for open-session-output events from AgentFeed
  useEffect(() => {
    const handler = (e) => {
      const sid = e.detail?.session_id
      if (sid) {
        setSessionOutputId(sid)
        setTab('Session Output')
      }
    }
    window.addEventListener('open-session-output', handler)
    return () => window.removeEventListener('open-session-output', handler)
  }, [])

  const allTabs = [...TABS, ...(sessionOutputId ? ['Session Output'] : [])]

  return (
    <div className="flex flex-col h-full bg-slate-950">
      {/* Sub-tab bar */}
      <div className="flex items-center border-b border-slate-700 shrink-0 px-3 pt-1 overflow-x-auto">
        {allTabs.map(t => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`text-xs px-3 py-1.5 border-b-2 transition-colors whitespace-nowrap ${
              tab === t
                ? 'border-blue-500 text-blue-400'
                : 'border-transparent text-slate-500 hover:text-slate-300'
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-hidden min-h-0">
        {tab === 'Live Logs'      && <LiveLogsView />}
        {tab === 'Tool Calls'     && <ToolCallsView refreshTick={0} />}
        {tab === 'Operations'     && <OpsView refreshTick={0} />}
        {tab === 'Escalations'    && <EscView refreshTick={0} />}
        {tab === 'Stats'          && <StatsView />}
        {tab === 'Result Refs'    && <ResultRefsView />}
        {tab === 'Data Health'    && <DataHealthView />}
        {tab === 'Actions'        && <AgentActionsTab />}
        {tab === 'Session Output' && sessionOutputId && (
          <SessionOutputView
            sessionId={sessionOutputId}
            onClose={() => { setTab('Operations'); setSessionOutputId(null) }}
          />
        )}
      </div>
    </div>
  )
}
