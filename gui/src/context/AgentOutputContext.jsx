/**
 * AgentOutputContext — single persistent WebSocket for agent output.
 *
 * Uses a MODULE-LEVEL singleton so the WebSocket is created exactly once
 * per browser session, regardless of React StrictMode double-mounts,
 * component remounts, or tab switches. Components subscribe/unsubscribe
 * via listener sets without ever touching the WebSocket directly.
 */
import { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react'

const AgentOutputContext = createContext(null)

const API_BASE = import.meta.env.VITE_API_BASE || ''

// ── Module-level singleton ────────────────────────────────────────────────────

let _ws             = null
let _wsUrl          = null
let _pingTimer      = null
let _msgListeners   = new Set()
let _stateListeners = new Set()
let _replayListeners = new Set()

function _notifyState(state) {
  _stateListeners.forEach(fn => fn(state))
}

function _scheduleReconnect() {
  setTimeout(() => _ensureWS(_wsUrl), 3000)
}

function _ensureWS(url) {
  if (!url) return
  _wsUrl = url
  if (_ws && _ws.readyState < 2) return

  const ws = new WebSocket(url)
  _ws = ws
  _notifyState('connecting')

  ws.onopen = () => {
    _notifyState('connected')
    _pingTimer = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send('ping')
    }, 20_000)
    // Fetch replay for the most recent active session
    const token = localStorage.getItem('hp1_auth_token')
    if (token) {
      fetch(`${API_BASE}/api/agent/sessions/active`, {
        headers: { Authorization: `Bearer ${token}` },
      })
        .then(r => r.ok ? r.json() : null)
        .then(data => {
          const sessions = data?.sessions || []
          if (sessions.length > 0) {
            const latestSession = sessions[0]
            return fetch(`${API_BASE}/api/agent/session/${latestSession.session_id}/replay`, {
              headers: { Authorization: `Bearer ${token}` },
            })
          }
          return null
        })
        .then(r => r?.ok ? r.json() : null)
        .then(data => {
          if (data?.lines?.length) {
            const replayLines = data.lines.map((l, i) => ({
              id: `replay-${i}`,
              type: l.type || 'step',
              content: l.content || '',
              timestamp: l.timestamp,
              replayed: true,
            }))
            _replayListeners.forEach(fn => fn(replayLines))
          }
        })
        .catch(() => {})
    }
  }

  ws.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data)
      if (!msg || msg.type === 'pong') return
      if (!msg.content && !msg.text && !msg.message && !msg.type) return
      _msgListeners.forEach(fn => fn(msg))
    } catch { /* ignore parse errors */ }
  }

  ws.onclose = (event) => {
    clearInterval(_pingTimer)
    _pingTimer = null
    _notifyState('disconnected')
    if (event.code === 1008) {
      // Auth rejection — token expired or invalid. Stop retrying and signal re-login.
      _notifyState('auth_error')
      return
    }
    if (_ws === ws) _scheduleReconnect()
  }

  ws.onerror = () => { /* onclose will handle reconnect */ }
}
// ─────────────────────────────────────────────────────────────────────────────

export function AgentOutputProvider({ children }) {
  const [outputLines,          setOutputLines]          = useState([])
  const [feedLines,            setFeedLines]            = useState([])
  const [isRunning,            setIsRunning]            = useState(false)
  const [runState,             setRunState]             = useState('idle')  // 'idle'|'running'|'stopping'
  const [wsState,              setWsState]              = useState('disconnected')
  const [pendingChoices,       setPendingChoices]       = useState([])
  const [pendingClarification, setPendingClarification] = useState(null)
  const [pendingPlan,          setPendingPlan]          = useState(null)
  const [agentType,            setAgentType]            = useState(null)
  const [lastAgentType,        setLastAgentType]        = useState(null)
  const [currentSessionId,     setCurrentSessionId]     = useState(null)
  const agentTypeRef    = useRef(null)
  const sessionIdRef    = useRef(null)
  const feedStartRef    = useRef(null)  // timestamp when current run started

  useEffect(() => {
    const token = localStorage.getItem('hp1_auth_token')
    const url = `ws://${location.hostname}:8000/ws/output${token ? `?token=${token}` : ''}`
    _ensureWS(url)

    if (_ws) {
      if (_ws.readyState === WebSocket.CONNECTING) setWsState('connecting')
      else if (_ws.readyState === WebSocket.OPEN)  setWsState('connected')
    }

    const onState = (s) => setWsState(s)

    const onMsg = (msg) => {
      const t = msg.type

      // ── agent_start ────────────────────────────────────────────────────────
      if (t === 'agent_start') {
        agentTypeRef.current  = msg.agent_type || null
        sessionIdRef.current  = msg.session_id || null
        feedStartRef.current  = Date.now()
        setAgentType(msg.agent_type || null)
        setCurrentSessionId(msg.session_id || null)
        setRunState('running')
        // Add to raw log stream
        setOutputLines(prev => [...prev.slice(-500), msg])
        // Reset inline feed
        setFeedLines([{ type: 'start' }])
        return
      }

      // ── plan_pending ───────────────────────────────────────────────────────
      if (t === 'plan_pending') {
        setPendingPlan({ ...(msg.plan || {}), sessionId: msg.session_id || '' })
        return
      }

      // ── clarification_needed ───────────────────────────────────────────────
      if (t === 'clarification_needed') {
        setPendingClarification({
          question:  msg.question  || '',
          options:   msg.options   || [],
          sessionId: msg.session_id || '',
        })
        return
      }

      // ── add every non-start message to the raw log ─────────────────────────
      setOutputLines(prev => [...prev.slice(-500), msg])

      // ── update inline feed ─────────────────────────────────────────────────
      if (t === 'tool') {
        const toolName = msg.tool   || ''
        const status   = msg.status || 'ok'
        // Skip audit_log and blocked calls in the inline feed
        if (toolName !== 'audit_log' && status !== 'blocked') {
          setFeedLines(prev => [...prev, { type: 'tool', toolName, status, content: msg.content }])
        }
      } else if (t === 'reasoning') {
        // Keep only the latest thought — replace any previous one
        setFeedLines(prev => {
          const without = prev.filter(l => l.type !== 'thought')
          return [...without, { type: 'thought', content: msg.content }]
        })
      } else if (t === 'halt') {
        setFeedLines(prev => [...prev, { type: 'tool', toolName: 'escalate', status: 'error', content: msg.content }])
      } else if (t === 'done') {
        const elapsed = feedStartRef.current
          ? ((Date.now() - feedStartRef.current) / 1000).toFixed(1)
          : '?'
        const stepsMatch = msg.content?.match(/after (\d+) steps/)
        const steps = stepsMatch ? parseInt(stepsMatch[1]) : '?'
        const doneSessionId = sessionIdRef.current || msg.session_id || ''
        setFeedLines(prev => [...prev, { type: 'done', steps, elapsed, sessionId: doneSessionId }])
      } else if (t === 'error') {
        const isCancelled = msg.status === 'cancelled'
        setFeedLines(prev => [
          ...prev,
          { type: isCancelled ? 'cancelled' : 'error', text: msg.content },
        ])
      }

      // ── isRunning / terminal state ─────────────────────────────────────────
      if (t === 'step' || t === 'tool' || t === 'reasoning' || t === 'halt') {
        setIsRunning(true)
        setPendingChoices([])
      } else if (t === 'done' || t === 'error') {
        setIsRunning(false)
        setPendingClarification(null)
        setPendingPlan(null)
        setTimeout(() => setRunState('idle'), 500)
        if (agentTypeRef.current) setLastAgentType(agentTypeRef.current)
        agentTypeRef.current = null
        sessionIdRef.current = null
        setAgentType(null)
        setCurrentSessionId(null)
        if (t === 'done') {
          console.log('[DEBUG] agent done received, choices:', msg.choices)
          const choices = msg.choices?.length > 0 ? msg.choices : []
          if (choices.length > 0) setPendingChoices(choices)
          window.dispatchEvent(new CustomEvent('agent-done', { detail: { choices } }))
        }
      }
    }

    const onReplay = (replayLines) => {
      setOutputLines(prev => [...replayLines, ...prev])
    }

    _stateListeners.add(onState)
    _msgListeners.add(onMsg)
    _replayListeners.add(onReplay)

    return () => {
      _stateListeners.delete(onState)
      _msgListeners.delete(onMsg)
      _replayListeners.delete(onReplay)
    }
  }, [])

  const clearOutput = useCallback(() => {
    setOutputLines([])
    setFeedLines([])
    setIsRunning(false)
    setRunState('idle')
    setPendingChoices([])
    setPendingClarification(null)
    setPendingPlan(null)
    agentTypeRef.current = null
    sessionIdRef.current = null
    setAgentType(null)
    setCurrentSessionId(null)
  }, [])

  const stopAgent = useCallback(async () => {
    setRunState('stopping')
    const sid = sessionIdRef.current
    if (!sid) { setRunState('idle'); return }
    try {
      await fetch('/api/agent/stop', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sid }),
      })
    } catch { /* ignore — optimistic UI already updated */ }
  }, [])

  const clearChoices       = useCallback(() => setPendingChoices([]), [])
  const clearClarification = useCallback(() => setPendingClarification(null), [])
  const clearPlan          = useCallback(() => setPendingPlan(null), [])

  return (
    <AgentOutputContext.Provider value={{
      outputLines, feedLines,
      isRunning, runState, setRunState,
      wsState, clearOutput,
      pendingChoices, clearChoices,
      pendingClarification, clearClarification,
      pendingPlan, clearPlan,
      agentType, lastAgentType,
      currentSessionId, stopAgent,
    }}>
      {children}
    </AgentOutputContext.Provider>
  )
}

export function useAgentOutput() {
  const ctx = useContext(AgentOutputContext)
  if (!ctx) throw new Error('useAgentOutput must be used inside AgentOutputProvider')
  return ctx
}
