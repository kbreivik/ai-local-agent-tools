/**
 * LogsPanel — unified Logs tab.
 * Sub-tabs: Live Logs | Tool Calls | Operations | Escalations | Stats
 * Live Logs: unified SSE stream — all local Docker containers + Elasticsearch.
 * Other tabs: agent tool-call / operation / escalation / stats tables.
 */
import { useEffect, useState, useRef } from 'react'
import { ToolCallsView, OpsView, EscView, StatsView } from './LogTable'
import { createUnifiedLogStream } from '../api'

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

  const toggleContainer = (name) => {
    setCheckedContainers(prev => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name); else next.add(name)
      checkedRef.current = next
      return next
    })
  }

  // Client-side filter
  const visible = lines.filter(entry => {
    if (entry.container && !checkedContainers.has(entry.container)) return false
    const lvl = (entry.level ?? 'info').toLowerCase()
    if (levelFilter === 'error' && !['error', 'critical', 'fatal'].includes(lvl)) return false
    if (levelFilter === 'warn'  && !['warn', 'warning', 'error', 'critical', 'fatal'].includes(lvl)) return false
    return matchesKeyword(entry, keyword)
  })

  const renderLine = (entry, i) => {
    const ts    = (() => { try { return new Date(entry.ts).toLocaleTimeString() } catch { return '' } })()
    const badge = LEVEL_BADGE[entry.level] ?? 'bg-slate-800 text-slate-400'
    return (
      <div key={i} className="flex gap-2 px-2 py-0.5 hover:bg-slate-800/40">
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
                  const badge = LEVEL_BADGE[entry.level] ?? 'bg-slate-800 text-slate-400'
                  return (
                    <div key={i} className="flex gap-2 py-0.5">
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

// ── Root ──────────────────────────────────────────────────────────────────────

const TABS = ['Live Logs', 'Tool Calls', 'Operations', 'Escalations', 'Stats']

export default function LogsPanel() {
  const [tab, setTab] = useState('Live Logs')

  return (
    <div className="flex flex-col h-full bg-slate-950">
      {/* Sub-tab bar */}
      <div className="flex items-center border-b border-slate-700 shrink-0 px-3 pt-1">
        {TABS.map(t => (
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
        {tab === 'Live Logs'   && <LiveLogsView />}
        {tab === 'Tool Calls'  && <ToolCallsView refreshTick={0} />}
        {tab === 'Operations'  && <OpsView refreshTick={0} />}
        {tab === 'Escalations' && <EscView refreshTick={0} />}
        {tab === 'Stats'       && <StatsView />}
      </div>
    </div>
  )
}
