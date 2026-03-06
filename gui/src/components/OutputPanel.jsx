import { useEffect, useRef, useState } from 'react'
import { createOutputStream } from '../api'

const TYPE_STYLE = {
  step:      { line: 'text-slate-400',  icon: '──' },
  reasoning: { line: 'text-slate-300',  icon: '💭' },
  tool:      { line: 'text-blue-300',   icon: '⚙' },
  halt:      { line: 'text-orange-400', icon: '⚠' },
  done:      { line: 'text-green-400',  icon: '✓' },
  error:     { line: 'text-red-400',    icon: '✗' },
  pong:      { line: 'text-slate-600',  icon: '·' },
}

const STATUS_COLOR = {
  ok:        'text-green-400',
  degraded:  'text-yellow-400',
  failed:    'text-red-400',
  escalated: 'text-orange-400',
  error:     'text-red-400',
  '':        '',
}

function Line({ msg }) {
  const { line, icon } = TYPE_STYLE[msg.type] ?? TYPE_STYLE.step
  const statusColor = STATUS_COLOR[msg.status] ?? ''
  const ts = (() => {
    if (!msg.timestamp) return 'N/A'
    const d = new Date(msg.timestamp)
    return isNaN(d.getTime()) ? 'N/A' : d.toLocaleTimeString()
  })()

  return (
    <div className={`flex gap-2 py-0.5 font-mono text-xs leading-relaxed ${line}`}>
      <span className="text-slate-600 shrink-0 w-16">{ts}</span>
      <span className="shrink-0 w-4">{icon}</span>
      <span className={`flex-1 whitespace-pre-wrap break-all ${
        msg.type === 'tool' ? statusColor : ''
      }`}>
        {msg.content}
      </span>
    </div>
  )
}

export default function OutputPanel({ running }) {
  const [lines, setLines]   = useState([])
  const [wsState, setWsState] = useState('disconnected')
  const bottomRef = useRef(null)
  const wsRef     = useRef(null)

  useEffect(() => {
    let reconnect = true
    let timeout

    function connect() {
      if (!reconnect) return
      const ws = createOutputStream(
        (msg) => setLines(prev => [...prev.slice(-500), msg]),  // cap at 500 lines
        () => setWsState('connected'),
        () => {
          setWsState('disconnected')
          if (reconnect) timeout = setTimeout(connect, 3000)
        },
      )
      wsRef.current = ws
      setWsState('connecting')
    }

    connect()

    return () => {
      reconnect = false
      clearTimeout(timeout)
      wsRef.current?.close()
    }
  }, [])

  // Auto-scroll when new lines arrive while running
  useEffect(() => {
    if (running) bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [lines, running])

  const clear = () => setLines([])

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-slate-700">
        <span className="text-xs font-bold uppercase tracking-wider text-slate-400">
          Live Output
        </span>
        <div className="flex items-center gap-3">
          <span className={`flex items-center gap-1 text-xs ${
            wsState === 'connected' ? 'text-green-400' :
            wsState === 'connecting' ? 'text-yellow-400 animate-pulse' : 'text-red-400'
          }`}>
            <span className="w-1.5 h-1.5 rounded-full bg-current inline-block" />
            {wsState}
          </span>
          <button onClick={clear} className="text-xs text-slate-500 hover:text-slate-300">
            clear
          </button>
        </div>
      </div>

      {/* Output stream */}
      <div className="flex-1 overflow-y-auto px-3 py-2 bg-slate-950">
        {lines.length === 0 && (
          <p className="text-xs text-slate-600 mt-4">
            Waiting for agent output…<br />
            Run a tool or agent task from the Commands panel.
          </p>
        )}
        {lines.map((m, i) => <Line key={i} msg={m} />)}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
