/**
 * SubtaskOfferBanner — cyan banner offering sub-agent or manual runbook.
 * Appears when agent calls propose_subtask(). Polls for pending proposals.
 * Different from EscalationBanner (amber): this is cyan and actionable.
 */
import { useState, useEffect, useCallback } from 'react'
import { authHeaders } from '../api'

const BASE = import.meta.env.VITE_API_BASE ?? ''

const POPUP_FEATURES = 'popup,width=760,height=560,resizable=yes'

export default function SubtaskOfferBanner() {
  const [proposals, setProposals] = useState([])

  const fetchProposals = useCallback(() => {
    fetch(`${BASE}/api/agent/proposals?status=pending&limit=5`, {
      headers: authHeaders()
    }).then(r => r.ok ? r.json() : { proposals: [] })
      .then(d => setProposals(d.proposals || []))
      .catch(() => {})
  }, [])

  useEffect(() => {
    fetchProposals()
    const id = setInterval(fetchProposals, 15000)

    // Listen for real-time WS event
    const handler = (e) => {
      if (e.detail?.type === 'subtask_proposed') fetchProposals()
    }
    window.addEventListener('ds:ws-message', handler)
    return () => { clearInterval(id); window.removeEventListener('ds:ws-message', handler) }
  }, [fetchProposals])

  const dismiss = async (id) => {
    await fetch(`${BASE}/api/agent/proposals/${id}/dismiss`, {
      method: 'POST', headers: authHeaders()
    })
    setProposals(prev => prev.filter(p => p.id !== id))
  }

  const runSubAgent = async (proposal) => {
    // Start subtask, get session_id, open popup
    try {
      const r = await fetch(`${BASE}/api/agent/subtask`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          proposal_id: proposal.id,
          task: proposal.task,
          parent_session_id: proposal.parent_session_id,
        }),
      })
      const d = await r.json()
      if (d.session_id) {
        window.open(`/subtask/${d.session_id}`, `subtask-${d.session_id}`, POPUP_FEATURES)
        setProposals(prev => prev.filter(p => p.id !== proposal.id))
      }
    } catch (e) { console.error('run subtask failed', e) }
  }

  const openRunbook = (proposal) => {
    window.open(`/runbook/${proposal.id}`, `runbook-${proposal.id}`, POPUP_FEATURES)
    setProposals(prev => prev.filter(p => p.id !== proposal.id))
  }

  if (proposals.length === 0) return null

  const latest = proposals[0]
  const extra  = proposals.length - 1
  const confColor = { high: '#22c55e', medium: '#00c8ee', low: '#f59e0b' }[latest.confidence] || '#94a3b8'

  return (
    <div style={{
      background: 'rgba(0,200,238,0.07)',
      borderBottom: '1px solid var(--cyan)',
      padding: '7px 16px',
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      flexShrink: 0,
    }}>
      {/* Pulsing dot */}
      <span style={{
        width: 7, height: 7, borderRadius: '50%',
        background: 'var(--cyan)', flexShrink: 0,
        boxShadow: '0 0 5px var(--cyan)',
        animation: 'pulse 1.8s ease-in-out infinite',
      }} />

      {/* Label */}
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9,
                     color: 'var(--cyan)', letterSpacing: 1, flexShrink: 0 }}>
        ⬡ SUB-TASK READY
      </span>

      {/* Confidence */}
      <span style={{ fontSize: 8, padding: '1px 5px', borderRadius: 2, flexShrink: 0,
                     background: `${confColor}22`, color: confColor,
                     fontFamily: 'var(--font-mono)', border: `1px solid ${confColor}44` }}>
        {latest.confidence}
      </span>

      {/* Task text */}
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10,
                     color: 'var(--text-2)', maxWidth: 340, minWidth: 0,
                     overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {latest.task?.slice(0, 80)}
        {extra > 0 && (
          <span style={{ color: 'var(--cyan)', marginLeft: 6 }}>+{extra} more</span>
        )}
      </span>

      {/* Step counts */}
      <span style={{ fontSize: 9, color: 'var(--text-3)', fontFamily: 'var(--font-mono)',
                     flexShrink: 0 }}>
        {latest.executable_steps?.length || 0} auto
        {(latest.manual_steps?.length || 0) > 0 &&
          ` · ${latest.manual_steps.length} manual`}
      </span>

      {/* Actions */}
      <button onClick={() => runSubAgent(latest)}
        style={{ padding: '2px 10px', fontSize: 9, fontFamily: 'var(--font-mono)',
                 background: 'rgba(0,200,238,0.15)', color: 'var(--cyan)',
                 border: '1px solid var(--cyan)', borderRadius: 2,
                 cursor: 'pointer', flexShrink: 0 }}>
        Run Sub-agent
      </button>
      <button onClick={() => openRunbook(latest)}
        style={{ padding: '2px 10px', fontSize: 9, fontFamily: 'var(--font-mono)',
                 background: 'transparent', color: 'var(--text-2)',
                 border: '1px solid var(--border)', borderRadius: 2,
                 cursor: 'pointer', flexShrink: 0 }}>
        Manual Runbook
      </button>
      <button onClick={() => dismiss(latest.id)}
        style={{ padding: '2px 6px', fontSize: 9, fontFamily: 'var(--font-mono)',
                 background: 'transparent', color: 'var(--text-3)',
                 border: '1px solid var(--border)', borderRadius: 2,
                 cursor: 'pointer', flexShrink: 0 }}>
        ×
      </button>
    </div>
  )
}
