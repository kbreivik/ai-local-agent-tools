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
let _authRetried    = false
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
    // v2.31.3: cookie-based auth — no localStorage token to check
    fetch(`${API_BASE}/api/agent/sessions/active`, {
      credentials: 'include',
    })
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        const sessions = data?.sessions || []
        if (sessions.length > 0) {
          const latestSession = sessions[0]
          return fetch(`${API_BASE}/api/agent/session/${latestSession.session_id}/replay`, {
            credentials: 'include',
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

  ws.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data)
      if (!msg || msg.type === 'pong') return
      if (msg.type === 'escalation_recorded') {
        window.dispatchEvent(new CustomEvent('ds:ws-message', { detail: msg }))
      }
      if (msg.type === 'subtask_proposed') {
        window.dispatchEvent(new CustomEvent('ds:ws-message', { detail: msg }))
      }
      if (msg.type === 'subtask_proposed' && msg.proposal_id) {
        // Accumulate — deduplicate by proposal_id via listener set
        _msgListeners.forEach(fn => fn({ ...msg, _isProposal: true }))
      }
      // Dispatch ws:message for cross-component WS access (vm_action, etc.)
      window.dispatchEvent(new CustomEvent('ws:message', { detail: e.data }))
      if (!msg.content && !msg.text && !msg.message && !msg.type) return
      _msgListeners.forEach(fn => fn(msg))
    } catch { /* ignore parse errors */ }
  }

  ws.onclose = (event) => {
    clearInterval(_pingTimer)
    _pingTimer = null
    _notifyState('disconnected')
    if (event.code === 1008) {
      // Auth rejection. Under cookie-based auth (v2.31.3) this can fire on
      // a transient backend restart before the cookie is re-validated. Try
      // one retry after a longer delay; if it fails again the onclose will
      // re-enter this branch and settle on auth_error.
      if (!_authRetried) {
        _authRetried = true
        setTimeout(() => _ensureWS(_wsUrl), 6000)
        return
      }
      _notifyState('auth_error')
      return
    }
    _authRetried = false  // successful connection clears the one-shot flag
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
  const [pendingProposals,     setPendingProposals]     = useState([])
  const [zeroPivot,            setZeroPivot]            = useState(null)
  const [contradictions,       setContradictions]       = useState([])
  const agentTypeRef    = useRef(null)
  const sessionIdRef    = useRef(null)
  const feedStartRef    = useRef(null)  // timestamp when current run started

  useEffect(() => {
    // v2.31.3: cookie-based auth. The WS handshake automatically sends same-origin
    // cookies, so no ?token= param is needed. Keeps the URL clean of secrets in
    // server logs and browser history.
    const wsProto = location.protocol === 'https:' ? 'wss' : 'ws'
    const url = `${wsProto}://${location.host}/ws/output`
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
        setPendingProposals([])           // ← clear proposals on new run
        setZeroPivot(null)                // ← clear pivot banner on new run
        setContradictions([])             // ← clear contradiction banner on new run
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

      // ── zero_result_pivot (v2.33.12) ───────────────────────────────────────
      if (t === 'zero_result_pivot') {
        setZeroPivot({
          tool:              msg.tool              || '',
          consecutive_zeros: msg.consecutive_zeros || 0,
          prior_nonzero:     msg.prior_nonzero     || 0,
        })
        return
      }

      // ── contradiction_detected (v2.33.13) ─────────────────────────────────
      if (t === 'contradiction_detected') {
        setContradictions(Array.isArray(msg.contradictions) ? msg.contradictions : [])
        return
      }

      // ── accumulate subtask proposals ───────────────────────────────────────
      if (msg._isProposal) {
        setPendingProposals(prev => {
          if (prev.some(p => p.proposal_id === msg.proposal_id)) return prev
          return [...prev, {
            proposal_id:       msg.proposal_id,
            task:              msg.task              || '',
            executable_steps:  msg.executable_steps  || [],
            manual_steps:      msg.manual_steps      || [],
            confidence:        msg.confidence        || 'medium',
            parent_session_id: msg.parent_session_id || '',
          }]
        })
        return  // don't add raw proposal messages to outputLines
      }

      // ── add every non-start message to the raw log ─────────────────────────
      setOutputLines(prev => [...prev.slice(-500), msg])

      // ── update inline feed ─────────────────────────────────────────────────
      if (t === 'tool') {
        const toolName = msg.tool   || ''
        const rawStatus = msg.status || 'ok'
        // Map 'escalated' status to its own category (not 'error')
        const status = rawStatus === 'escalated' ? 'escalated' : rawStatus
        // Skip audit_log and blocked calls in the inline feed
        if (toolName !== 'audit_log' && status !== 'blocked') {
          setFeedLines(prev => {
            // Deduplicate escalate entries
            if (toolName === 'escalate') {
              const alreadyEscalated = prev.some(l => l.type === 'tool' && l.toolName === 'escalate')
              if (alreadyEscalated) return prev
            }
            return [...prev, { type: 'tool', toolName, status, content: msg.content }]
          })
        }
      } else if (t === 'reasoning') {
        // Keep only the latest thought — replace any previous one
        setFeedLines(prev => {
          const without = prev.filter(l => l.type !== 'thought')
          return [...without, { type: 'thought', content: msg.content }]
        })
      } else if (t === 'halt') {
        // Deduplicate: only add if no escalate line already present
        setFeedLines(prev => {
          const alreadyEscalated = prev.some(l => l.type === 'tool' && l.toolName === 'escalate')
          if (alreadyEscalated) return prev
          return [...prev, { type: 'tool', toolName: 'escalate', status: 'escalated', content: msg.content }]
        })
      } else if (t === 'done') {
        const elapsed = feedStartRef.current
          ? ((Date.now() - feedStartRef.current) / 1000).toFixed(1)
          : '?'
        const stepsMatch = msg.content?.match(/after (\d+) steps/)
        const steps = stepsMatch ? parseInt(stepsMatch[1]) : '?'
        const doneSessionId = sessionIdRef.current || msg.session_id || ''
        setFeedLines(prev => {
            const next = [...prev, { type: 'done', steps, elapsed, sessionId: doneSessionId }]
            // Inject proposal offer inline if proposals were recorded for this run
            setPendingProposals(proposals => {
              if (proposals.length > 0) {
                next.push({ type: 'subtask_offer', proposals })
              }
              return []  // clear after injecting
            })
            return next
          })
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
    setZeroPivot(null)
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
      pendingProposals,
      zeroPivot,
      contradictions,
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
