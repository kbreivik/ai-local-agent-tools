/**
 * SubtaskPopup — minimal popup page for sub-agent execution.
 * Opened via window.open('/subtask/:sessionId', '_blank', 'popup,...')
 * Connects to WS, filters messages by sessionId.
 */
import { useState, useEffect, useRef } from 'react'
import { authHeaders } from '../api'

const BASE = import.meta.env.VITE_API_BASE ?? ''

const TYPE_ICON = {
  step:      { icon: '──', color: '#64748b' },
  reasoning: { icon: '💭', color: '#cbd5e1' },
  tool:      { icon: '⚙',  color: '#93c5fd' },
  memory:    { icon: '◈',  color: '#475569' },
  halt:      { icon: '⚠',  color: '#fb923c' },
  done:      { icon: '✓',  color: '#4ade80' },
  error:     { icon: '✗',  color: '#f87171' },
}

export default function SubtaskPopup({ sessionId }) {
  const [lines, setLines]         = useState([])
  const [status, setStatus]       = useState('connecting') // connecting|running|done|error
  const [task, setTask]           = useState('')
  const [pendingPlan, setPendingPlan] = useState(null)
  const [wsState, setWsState]     = useState('connecting')
  const bottomRef = useRef(null)
  const wsRef     = useRef(null)

  // Set page title
  useEffect(() => { document.title = `Sub-agent · ${sessionId.substring(0, 8)}` }, [sessionId])

  // Fetch replay on mount
  useEffect(() => {
    fetch(`${BASE}/api/logs/session/${sessionId}/output?limit=500`, {
      headers: authHeaders()
    }).then(r => r.ok ? r.json() : { lines: [] })
      .then(d => setLines(d.lines || []))
      .catch(() => {})
    // Also get the task from operations
    fetch(`${BASE}/api/logs/operations?session_id=${sessionId}&limit=1`, {
      headers: authHeaders()
    }).then(r => r.ok ? r.json() : { operations: [] })
      .then(d => { if (d.operations?.[0]) setTask(d.operations[0].label || '') })
      .catch(() => {})
  }, [sessionId])

  // WS connection
  useEffect(() => {
    const token = localStorage.getItem('hp1_auth_token')
    const proto  = location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${location.host}/ws/output${token ? `?token=${token}` : ''}`)
    wsRef.current = ws
    setWsState('connecting')

    ws.onopen = () => setWsState('connected')
    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data)
        if (!msg || msg.type === 'pong') return
        // Only process messages for our session
        if (msg.session_id && msg.session_id !== sessionId) return

        if (msg.type === 'agent_start') {
          setStatus('running')
          if (msg.task) setTask(msg.task)
        } else if (msg.type === 'plan_pending') {
          setPendingPlan({ ...(msg.plan || {}), sessionId: msg.session_id })
        } else if (msg.type === 'done') {
          setStatus('done')
          setPendingPlan(null)
        } else if (msg.type === 'error') {
          setStatus('error')
        }

        if (['step','tool','reasoning','memory','halt','done','error'].includes(msg.type)) {
          setLines(prev => [...prev.slice(-800), {
            id: Date.now() + Math.random(),
            type: msg.type,
            content: msg.content || msg.text || '',
            tool: msg.tool || '',
            status: msg.status || '',
            timestamp: msg.timestamp || new Date().toISOString(),
          }])
        }
      } catch { /* ignore */ }
    }
    ws.onclose = () => setWsState('disconnected')
    ws.onerror = () => setWsState('error')
    return () => ws.close()
  }, [sessionId])

  // Auto-scroll
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [lines.length])

  const confirmPlan = async (approved) => {
    if (!pendingPlan?.sessionId) return
    await fetch(`${BASE}/api/agent/confirm`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ session_id: pendingPlan.sessionId, approved }),
    })
    setPendingPlan(null)
  }

  const stopAgent = async () => {
    await fetch(`${BASE}/api/agent/stop`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ session_id: sessionId }),
    })
    setStatus('done')
  }

  const statusColor = { running: '#3b82f6', done: '#4ade80', error: '#f87171',
                         connecting: '#64748b' }[status] || '#64748b'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh',
                  background: '#05060a', color: '#e2e8f0',
                  fontFamily: "'Share Tech Mono', monospace" }}>
      {/* Title bar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10,
                    padding: '8px 14px', background: '#09090f',
                    borderBottom: '1px solid #1e293b', flexShrink: 0 }}>
        <span style={{ width: 8, height: 8, borderRadius: '50%',
                       background: statusColor, flexShrink: 0 }} />
        <span style={{ fontSize: 11, color: '#a01828', letterSpacing: 1,
                       fontWeight: 600 }}>⬡ SUB-AGENT</span>
        <span style={{ fontSize: 10, color: '#94a3b8', flex: 1, minWidth: 0,
                       overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {task || sessionId.substring(0, 16) + '…'}
        </span>
        <span style={{ fontSize: 9, color: '#334155' }}>{sessionId.substring(0, 8)}</span>
        {status === 'running' && (
          <button onClick={stopAgent}
            style={{ fontSize: 9, padding: '2px 8px', borderRadius: 2,
                     background: '#7f1d1d', color: '#fca5a5',
                     border: '1px solid #991b1b', cursor: 'pointer' }}>
            STOP
          </button>
        )}
      </div>

      {/* Plan confirmation overlay */}
      {pendingPlan && (
        <div style={{ padding: '10px 14px', background: 'rgba(251,146,60,0.08)',
                      borderBottom: '1px solid #f97316', flexShrink: 0 }}>
          <div style={{ fontSize: 10, color: '#fb923c', marginBottom: 4,
                        letterSpacing: 1 }}>⚡ PLAN PENDING APPROVAL</div>
          <div style={{ fontSize: 11, color: '#e2e8f0', marginBottom: 6,
                        whiteSpace: 'pre-wrap', maxHeight: 120, overflowY: 'auto' }}>
            {pendingPlan.summary || JSON.stringify(pendingPlan, null, 2)}
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={() => confirmPlan(true)}
              style={{ fontSize: 10, padding: '3px 12px', borderRadius: 2,
                       background: '#14532d', color: '#86efac',
                       border: '1px solid #166534', cursor: 'pointer' }}>
              APPROVE
            </button>
            <button onClick={() => confirmPlan(false)}
              style={{ fontSize: 10, padding: '3px 12px', borderRadius: 2,
                       background: '#7f1d1d', color: '#fca5a5',
                       border: '1px solid #991b1b', cursor: 'pointer' }}>
              CANCEL
            </button>
          </div>
        </div>
      )}

      {/* Output lines */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '6px 0' }}>
        {lines.map((line, i) => {
          const s = TYPE_ICON[line.type] ?? { icon: '·', color: '#475569' }
          const ts = line.timestamp ? new Date(line.timestamp).toLocaleTimeString() : ''
          return (
            <div key={line.id || i} style={{ display: 'flex', gap: 6, padding: '1px 14px',
                                             fontSize: 11, lineHeight: 1.5 }}>
              <span style={{ color: '#1e293b', flexShrink: 0, width: 58, fontSize: 9 }}>{ts}</span>
              <span style={{ color: s.color, flexShrink: 0, width: 16 }}>{s.icon}</span>
              <span style={{ color: line.type === 'done' ? s.color : '#94a3b8',
                             whiteSpace: 'pre-wrap', wordBreak: 'break-all', flex: 1 }}>
                {line.content}
              </span>
            </div>
          )
        })}
        <div ref={bottomRef} />
      </div>

      {/* Footer */}
      <div style={{ padding: '6px 14px', borderTop: '1px solid #1e293b',
                    flexShrink: 0, fontSize: 9, color: '#334155',
                    display: 'flex', justifyContent: 'space-between' }}>
        <span>WS: {wsState}</span>
        <span>{lines.length} lines</span>
        {status === 'done' && (
          <button onClick={() => window.close()}
            style={{ fontSize: 9, color: '#475569', background: 'none',
                     border: 'none', cursor: 'pointer' }}>close ×</button>
        )}
      </div>
    </div>
  )
}
