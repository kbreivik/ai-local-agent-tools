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

// ── Module-level singleton ────────────────────────────────────────────────────
// These live outside React — they survive every re-render and re-mount.

let _ws             = null
let _wsUrl          = null
let _pingTimer      = null
let _msgListeners   = new Set()   // (msg: object) => void
let _stateListeners = new Set()   // (state: string) => void

function _notifyState(state) {
  _stateListeners.forEach(fn => fn(state))
}

function _scheduleReconnect() {
  setTimeout(() => _ensureWS(_wsUrl), 3000)
}

function _ensureWS(url) {
  if (!url) return
  _wsUrl = url

  // Already open or connecting — do nothing
  if (_ws && _ws.readyState < 2) return

  const ws = new WebSocket(url)
  _ws = ws
  _notifyState('connecting')

  ws.onopen = () => {
    _notifyState('connected')
    _pingTimer = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send('ping')
    }, 20_000)
  }

  ws.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data)
      // Drop pong keepalives and any message with no meaningful content
      if (!msg || msg.type === 'pong') return
      if (!msg.content && !msg.text && !msg.message && !msg.type) return
      _msgListeners.forEach(fn => fn(msg))
    } catch { /* ignore parse errors */ }
  }

  ws.onclose = () => {
    clearInterval(_pingTimer)
    _pingTimer = null
    _notifyState('disconnected')
    // Only reconnect if this is still the active WS (prevents stale sockets reconnecting)
    if (_ws === ws) _scheduleReconnect()
  }

  ws.onerror = () => { /* onclose will handle reconnect */ }
}
// ─────────────────────────────────────────────────────────────────────────────

export function AgentOutputProvider({ children }) {
  const [outputLines,         setOutputLines]         = useState([])
  const [isRunning,           setIsRunning]           = useState(false)
  const [wsState,             setWsState]             = useState('disconnected')
  const [pendingChoices,       setPendingChoices]       = useState([])
  const [pendingClarification, setPendingClarification] = useState(null)
  const [pendingPlan,          setPendingPlan]          = useState(null)
  const [agentType,            setAgentType]            = useState(null)
  const [lastAgentType,        setLastAgentType]        = useState(null)
  const agentTypeRef = useRef(null)

  useEffect(() => {
    const url = `ws://${location.hostname}:8000/ws/output`
    _ensureWS(url)

    // Sync wsState to current WS readyState on (re)mount
    if (_ws) {
      if (_ws.readyState === WebSocket.CONNECTING) setWsState('connecting')
      else if (_ws.readyState === WebSocket.OPEN)  setWsState('connected')
    }

    const onState = (s) => setWsState(s)

    const onMsg = (msg) => {
      const t = msg.type

      // Agent type broadcast at start of each run
      if (t === 'agent_start') {
        agentTypeRef.current = msg.agent_type || null
        setAgentType(msg.agent_type || null)
        return
      }

      // Plan pending — show confirm modal, don't add to output stream
      if (t === 'plan_pending') {
        setPendingPlan({
          ...(msg.plan || {}),
          sessionId: msg.session_id || '',
        })
        return
      }

      // Clarification request — don't add to output stream, show widget instead
      if (t === 'clarification_needed') {
        setPendingClarification({
          question:  msg.question  || '',
          options:   msg.options   || [],
          sessionId: msg.session_id || '',
        })
        return
      }

      setOutputLines(prev => [...prev.slice(-500), msg])

      if (t === 'step' || t === 'tool' || t === 'reasoning' || t === 'halt') {
        setIsRunning(true)
        setPendingChoices([])
      } else if (t === 'done' || t === 'error') {
        setIsRunning(false)
        setPendingClarification(null)
        setPendingPlan(null)
        if (agentTypeRef.current) setLastAgentType(agentTypeRef.current)
        agentTypeRef.current = null
        setAgentType(null)
        if (t === 'done') {
          console.log('[DEBUG] agent done received, choices:', msg.choices)
          const choices = msg.choices?.length > 0 ? msg.choices : []
          if (choices.length > 0) setPendingChoices(choices)
          window.dispatchEvent(new CustomEvent('agent-done', { detail: { choices } }))
        }
      }
    }

    _stateListeners.add(onState)
    _msgListeners.add(onMsg)

    // Cleanup only removes listeners — the WS itself stays alive
    return () => {
      _stateListeners.delete(onState)
      _msgListeners.delete(onMsg)
    }
  }, [])

  const clearOutput = useCallback(() => {
    setOutputLines([])
    setIsRunning(false)
    setPendingChoices([])
    setPendingClarification(null)
    setPendingPlan(null)
    agentTypeRef.current = null
    setAgentType(null)
  }, [])

  const clearChoices        = useCallback(() => setPendingChoices([]), [])
  const clearClarification  = useCallback(() => setPendingClarification(null), [])
  const clearPlan           = useCallback(() => setPendingPlan(null), [])

  return (
    <AgentOutputContext.Provider value={{
      outputLines, isRunning, wsState, clearOutput,
      pendingChoices, clearChoices,
      pendingClarification, clearClarification,
      pendingPlan, clearPlan,
      agentType, lastAgentType,
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
