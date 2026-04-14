/**
 * RunbookPopup — manual runbook checklist popup.
 * Opened via window.open('/runbook/:proposalId', '_blank', 'popup,...')
 * Shows executable + manual steps as checkboxes. When all checked, Save saves to DB.
 */
import { useState, useEffect } from 'react'
import { authHeaders } from '../api'

const BASE = import.meta.env.VITE_API_BASE ?? ''

function extractCommand(text) {
  // Extract backtick or `ssh`/`docker`/shell commands from step text
  const bt = text.match(/`([^`]{5,})`/)
  if (bt) return bt[1]
  const ssh = text.match(/(?:ssh|docker|kubectl|systemctl|journalctl)\s+\S[^\n]{3,}/)
  return ssh ? ssh[0] : null
}

function StepCard({ step, index, total, checked, onCheck }) {
  const cmd = typeof step === 'string' ? extractCommand(step) : extractCommand(step.description || step.title || '')
  const text = typeof step === 'string' ? step : (step.description || step.title || JSON.stringify(step))

  return (
    <div style={{
      padding: '12px 14px', marginBottom: 8, borderRadius: 3,
      background: checked ? 'rgba(0,170,68,0.06)' : '#09090f',
      border: `1px solid ${checked ? '#166534' : '#1e293b'}`,
      transition: 'all 0.15s',
    }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
        {/* Checkbox */}
        <div onClick={onCheck} style={{
          width: 18, height: 18, borderRadius: 2, flexShrink: 0, marginTop: 1,
          border: `2px solid ${checked ? '#22c55e' : '#334155'}`,
          background: checked ? '#22c55e' : 'transparent',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          cursor: 'pointer', transition: 'all 0.1s',
        }}>
          {checked && <span style={{ color: '#0f172a', fontSize: 11, fontWeight: 800 }}>✓</span>}
        </div>
        <div style={{ flex: 1 }}>
          {/* Step number + text */}
          <div style={{ fontSize: 11, color: checked ? '#4ade80' : '#cbd5e1',
                        lineHeight: 1.5, textDecoration: checked ? 'line-through' : 'none',
                        fontFamily: "'Rajdhani', sans-serif" }}>
            <span style={{ color: '#475569', marginRight: 6 }}>
              {String(index + 1).padStart(2, '0')}/{String(total).padStart(2, '0')}
            </span>
            {text}
          </div>
          {/* Command hint */}
          {cmd && (
            <div style={{ marginTop: 6, display: 'flex', alignItems: 'center', gap: 6 }}>
              <code style={{ fontSize: 10, color: '#38bdf8', background: '#0f172a',
                             padding: '2px 8px', borderRadius: 2, flex: 1,
                             fontFamily: "'Share Tech Mono', monospace",
                             borderLeft: '2px solid #0369a1' }}>
                {cmd}
              </code>
              <button
                onClick={() => navigator.clipboard.writeText(cmd)}
                style={{ fontSize: 9, padding: '2px 6px', borderRadius: 2,
                         background: '#1e293b', color: '#64748b',
                         border: '1px solid #334155', cursor: 'pointer' }}>
                copy
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default function RunbookPopup({ proposalId }) {
  const [proposal, setProposal] = useState(null)
  const [checked, setChecked]   = useState({})
  const [saving, setSaving]     = useState(false)
  const [saved, setSaved]       = useState(false)
  const [saveError, setSaveError] = useState('')
  const [title, setTitle]       = useState('')
  const [tags, setTags]         = useState('')

  useEffect(() => {
    fetch(`${BASE}/api/agent/proposals/${proposalId}`, { headers: authHeaders() })
      .then(r => r.ok ? r.json() : null)
      .then(d => {
        if (d) {
          setProposal(d)
          setTitle(d.task?.substring(0, 80) || 'Runbook')
          document.title = `Runbook · ${d.task?.substring(0, 40) || proposalId.substring(0, 8)}`
        }
      })
      .catch(() => {})
  }, [proposalId])

  if (!proposal) return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center',
                  height: '100vh', background: '#05060a',
                  color: '#475569', fontFamily: "'Share Tech Mono', monospace",
                  fontSize: 12 }}>
      Loading runbook…
    </div>
  )

  const allSteps = [
    ...(proposal.executable_steps || []).map(s => ({ text: s, type: 'auto' })),
    ...(proposal.manual_steps || []).map(s => ({ text: s, type: 'manual' })),
  ]
  const totalSteps = allSteps.length
  const checkedCount = Object.values(checked).filter(Boolean).length
  const allDone = totalSteps > 0 && checkedCount === totalSteps

  const toggleStep = (i) => setChecked(prev => ({ ...prev, [i]: !prev[i] }))

  const save = async () => {
    if (!allDone || saving || saved) return
    setSaving(true); setSaveError('')
    const steps = allSteps.map((s, i) => ({
      order: i + 1,
      title: (typeof s.text === 'string' ? s.text : s.text?.title || '').substring(0, 120),
      description: typeof s.text === 'string' ? s.text : JSON.stringify(s.text),
      command: typeof s.text === 'string' ? (extractCommand(s.text) || '') : '',
      type: s.type,
    }))
    try {
      const r = await fetch(`${BASE}/api/runbooks`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          title,
          description: proposal.task || '',
          steps,
          source: 'manual_completion',
          proposal_id: proposalId,
          tags: tags.split(',').map(t => t.trim().toLowerCase()).filter(Boolean),
        }),
      })
      if (r.ok) {
        setSaved(true)
        // Dismiss the proposal
        await fetch(`${BASE}/api/agent/proposals/${proposalId}/dismiss`, {
          method: 'POST', headers: authHeaders()
        })
      } else {
        const d = await r.json()
        setSaveError(d.detail || 'Save failed')
      }
    } catch (e) { setSaveError(e.message) }
    setSaving(false)
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh',
                  background: '#05060a', color: '#e2e8f0',
                  fontFamily: "'Share Tech Mono', monospace" }}>
      {/* Header */}
      <div style={{ padding: '10px 14px', background: '#09090f',
                    borderBottom: '1px solid #1e293b', flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
          <span style={{ fontSize: 11, color: '#00c8ee', letterSpacing: 1 }}>◫ MANUAL RUNBOOK</span>
          <span style={{ fontSize: 9, color: '#334155', marginLeft: 'auto' }}>
            {checkedCount}/{totalSteps} steps complete
          </span>
        </div>
        <div style={{ fontSize: 11, color: '#94a3b8', lineHeight: 1.4 }}>
          {proposal.task}
        </div>
        {proposal.parent_session_id && (
          <div style={{ fontSize: 9, color: '#334155', marginTop: 3 }}>
            from session {proposal.parent_session_id.substring(0, 8)}
          </div>
        )}
        {/* Progress bar */}
        <div style={{ marginTop: 8, height: 2, background: '#1e293b', borderRadius: 1 }}>
          <div style={{ height: '100%', background: allDone ? '#22c55e' : '#00c8ee',
                        width: `${totalSteps > 0 ? (checkedCount / totalSteps) * 100 : 0}%`,
                        borderRadius: 1, transition: 'width 0.2s' }} />
        </div>
      </div>

      {/* Steps */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '12px 14px' }}>
        {allSteps.length === 0 && (
          <p style={{ color: '#475569', fontSize: 11 }}>No steps in this proposal.</p>
        )}
        {allSteps.map((step, i) => (
          <StepCard
            key={i} step={step.text} index={i} total={totalSteps}
            checked={!!checked[i]} onCheck={() => toggleStep(i)}
          />
        ))}
      </div>

      {/* Save section */}
      <div style={{ padding: '10px 14px', borderTop: '1px solid #1e293b',
                    flexShrink: 0, background: '#09090f' }}>
        {!saved ? (
          <>
            {allDone && (
              <div style={{ marginBottom: 8, display: 'flex', gap: 8 }}>
                <input
                  value={title}
                  onChange={e => setTitle(e.target.value)}
                  placeholder="Runbook title"
                  style={{ flex: 1, fontSize: 10, padding: '4px 8px', borderRadius: 2,
                           background: '#0d0f1a', border: '1px solid #334155',
                           color: '#e2e8f0', outline: 'none' }}
                />
                <input
                  value={tags}
                  onChange={e => setTags(e.target.value)}
                  placeholder="tags (comma-separated)"
                  style={{ width: 160, fontSize: 10, padding: '4px 8px', borderRadius: 2,
                           background: '#0d0f1a', border: '1px solid #334155',
                           color: '#e2e8f0', outline: 'none' }}
                />
              </div>
            )}
            {saveError && (
              <p style={{ fontSize: 10, color: '#f87171', marginBottom: 6 }}>{saveError}</p>
            )}
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <button
                onClick={save}
                disabled={!allDone || saving}
                style={{
                  fontSize: 10, padding: '4px 16px', borderRadius: 2, cursor: allDone ? 'pointer' : 'not-allowed',
                  background: allDone ? '#14532d' : '#1e293b',
                  color: allDone ? '#86efac' : '#475569',
                  border: `1px solid ${allDone ? '#166534' : '#334155'}`,
                  opacity: saving ? 0.5 : 1, transition: 'all 0.15s',
                }}>
                {saving ? 'Saving…' : 'Save Runbook'}
              </button>
              {!allDone && (
                <span style={{ fontSize: 10, color: '#475569' }}>
                  Check all {totalSteps - checkedCount} remaining steps to save
                </span>
              )}
            </div>
          </>
        ) : (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 11, color: '#4ade80' }}>
              Runbook saved — accessible in Logs → Runbooks
            </span>
            <button onClick={() => window.close()}
              style={{ fontSize: 9, color: '#475569', background: 'none',
                       border: 'none', cursor: 'pointer', marginLeft: 'auto' }}>
              close ×
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
