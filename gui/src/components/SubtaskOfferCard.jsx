/**
 * SubtaskOfferCard — inline offer shown at the bottom of AgentFeed / OutputPanel
 * when an investigate run completes with propose_subtask() proposals.
 * Replaces SubtaskOfferBanner (which was a persistent dashboard banner — wrong UX).
 */
import { useState } from 'react'
import { authHeaders } from '../api'

const BASE = import.meta.env.VITE_API_BASE ?? ''
const POPUP_FEATURES = 'popup,width=760,height=560,resizable=yes'

export default function SubtaskOfferCard({ proposals, onDismiss }) {
  const [launched, setLaunched] = useState(false)

  if (!proposals || proposals.length === 0) return null
  const latest = proposals[0]
  const extra  = proposals.length - 1
  const confColor = { high: '#22c55e', medium: '#00c8ee', low: '#f59e0b' }[latest.confidence] ?? '#94a3b8'

  const runSubAgent = async () => {
    try {
      const r = await fetch(`${BASE}/api/agent/subtask`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          proposal_id:       latest.proposal_id,
          task:              latest.task,
          parent_session_id: latest.parent_session_id,
        }),
      })
      const d = await r.json()
      if (d.session_id) {
        window.open(`/subtask/${d.session_id}`, `subtask-${d.session_id}`, POPUP_FEATURES)
        setLaunched(true)
        onDismiss?.()
      }
    } catch (e) { console.error('run subtask failed', e) }
  }

  const openRunbook = () => {
    window.open(`/runbook/${latest.proposal_id}`, `runbook-${latest.proposal_id}`, POPUP_FEATURES)
    setLaunched(true)
    onDismiss?.()
  }

  if (launched) return null

  return (
    <div style={{
      marginTop: 10,
      padding: '8px 10px',
      background: 'rgba(0,200,238,0.06)',
      border: '1px solid rgba(0,200,238,0.25)',
      borderLeft: '3px solid var(--cyan, #00c8ee)',
      borderRadius: 2,
      fontFamily: 'var(--font-mono, monospace)',
    }}>
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
        <span style={{ fontSize: 9, color: 'var(--cyan, #00c8ee)', letterSpacing: 1 }}>
          ⬡ SUB-TASK READY
        </span>
        <span style={{
          fontSize: 8, padding: '1px 5px', borderRadius: 2,
          background: `${confColor}22`, color: confColor,
          border: `1px solid ${confColor}44`,
        }}>
          {latest.confidence}
        </span>
        {extra > 0 && (
          <span style={{ fontSize: 9, color: 'var(--cyan, #00c8ee)' }}>+{extra} more</span>
        )}
      </div>

      {/* Task */}
      <div style={{ fontSize: 11, color: '#e2e8f0', marginBottom: 6, lineHeight: 1.5 }}>
        {latest.task}
      </div>

      {/* Steps summary */}
      {(latest.executable_steps?.length > 0 || latest.manual_steps?.length > 0) && (
        <div style={{ fontSize: 9, color: '#64748b', marginBottom: 8 }}>
          {latest.executable_steps?.length > 0 && (
            <span style={{ marginRight: 10 }}>
              ⚡ {latest.executable_steps.length} auto step{latest.executable_steps.length !== 1 ? 's' : ''}
            </span>
          )}
          {latest.manual_steps?.length > 0 && (
            <span>📋 {latest.manual_steps.length} manual step{latest.manual_steps.length !== 1 ? 's' : ''}</span>
          )}
        </div>
      )}

      {/* Action buttons */}
      <div style={{ display: 'flex', gap: 8 }}>
        <button
          onClick={runSubAgent}
          style={{
            padding: '3px 12px', fontSize: 10, fontFamily: 'inherit',
            background: 'rgba(0,200,238,0.15)', color: 'var(--cyan, #00c8ee)',
            border: '1px solid var(--cyan, #00c8ee)', borderRadius: 2, cursor: 'pointer',
          }}
        >
          ▶ Run Sub-agent
        </button>
        <button
          onClick={openRunbook}
          style={{
            padding: '3px 12px', fontSize: 10, fontFamily: 'inherit',
            background: 'transparent', color: '#94a3b8',
            border: '1px solid #334155', borderRadius: 2, cursor: 'pointer',
          }}
        >
          ✎ Manual Runbook
        </button>
        <button
          onClick={() => onDismiss?.()}
          style={{
            padding: '3px 8px', fontSize: 10, fontFamily: 'inherit',
            background: 'transparent', color: '#475569',
            border: '1px solid #1e293b', borderRadius: 2, cursor: 'pointer',
          }}
        >
          ×
        </button>
      </div>
    </div>
  )
}
