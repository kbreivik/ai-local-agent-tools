import React from 'react'

/**
 * Compact live diagnostics overlay for agent runs.
 * Renders inline at the top of OutputPanel whenever an investigate task is active.
 */
export default function AgentDiagnostics({ diag }) {
  if (!diag || diag.agent_type !== 'investigate') return null

  const pct = diag.budget_pct ?? 0
  const barColor = pct >= 80 ? 'var(--red)'
                  : pct >= 60 ? 'var(--amber)'
                  : 'var(--cyan)'

  const diagOk = diag.has_diagnosis
  const zeroAlerts = Object.entries(diag.zero_streaks || {}).filter(([, n]) => n >= 2)

  return (
    <div className="mono" style={{
      display: 'flex', alignItems: 'center', gap: 12,
      padding: '6px 10px', marginBottom: 6,
      background: 'var(--bg-1)',
      border: '1px solid var(--border)',
      borderLeft: `3px solid ${barColor}`,
      borderRadius: 2, fontSize: 10,
      letterSpacing: '0.08em',
    }}>
      {/* Budget */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 90 }}>
        <span style={{ color: 'var(--text-2)', fontSize: 9 }}>BUDGET</span>
        <div>
          <span style={{ color: 'var(--text-0)' }}>{diag.tools_used}</span>
          <span style={{ color: 'var(--text-3)' }}> / {diag.budget}</span>
        </div>
        <div style={{ height: 2, background: 'var(--bg-3)', borderRadius: 1, overflow: 'hidden', width: 80 }}>
          <div style={{
            height: '100%', width: `${Math.min(100, pct)}%`,
            background: barColor, transition: 'width 0.3s',
          }} />
        </div>
      </div>

      {/* DIAGNOSIS status */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        <span style={{ color: 'var(--text-2)', fontSize: 9 }}>DIAGNOSIS</span>
        <span style={{ color: diagOk ? 'var(--green)' : 'var(--text-3)' }}>
          {diagOk ? '✓ emitted' : '· not yet'}
        </span>
      </div>

      {/* Zero-result streaks */}
      {zeroAlerts.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <span style={{ color: 'var(--text-2)', fontSize: 9 }}>ZERO-STREAKS</span>
          <div style={{ display: 'flex', gap: 4 }}>
            {zeroAlerts.map(([tool, n]) => (
              <span key={tool} title={`${tool}: ${n} consecutive zero results`}
                style={{
                  color: n >= 3 ? 'var(--red)' : 'var(--amber)',
                  padding: '0 4px',
                  border: `1px solid ${n >= 3 ? 'var(--red)' : 'var(--amber)'}`,
                  borderRadius: 1, fontSize: 9,
                }}>
                {tool.replace('elastic_', 'e_').replace('_logs', '')}×{n}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Pivot nudges fired */}
      {(diag.pivot_nudges_fired || []).length > 0 && (
        <div style={{ color: 'var(--amber)', fontSize: 9 }}>
          ⚠ {diag.pivot_nudges_fired.length} pivot nudge{diag.pivot_nudges_fired.length > 1 ? 's' : ''}
        </div>
      )}

      {/* Subtask proposed */}
      {diag.subtask_proposed && (
        <div style={{ color: 'var(--accent-hi)', fontSize: 9 }}>
          ◈ SUBTASK PROPOSED
        </div>
      )}

      <div style={{ flex: 1 }} />

      {/* Type indicator */}
      <div style={{ color: 'var(--text-3)', fontSize: 9 }}>
        {diag.agent_type?.toUpperCase()}
      </div>
    </div>
  )
}
