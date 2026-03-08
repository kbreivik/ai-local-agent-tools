/**
 * PlanConfirmModal — full-screen modal that appears when the agent calls
 * plan_action(). Cannot be dismissed by clicking outside. Must confirm or cancel.
 * Countdown auto-cancels at timeout.
 */
import { useState, useEffect, useCallback } from 'react'
import { useAgentOutput } from '../context/AgentOutputContext'
import { sendConfirmation } from '../api'

const TIMEOUT_SECONDS = 300

const RISK_STYLE = {
  low:    { border: 'border-green-500',  badge: 'bg-green-900 text-green-300',  label: 'LOW'    },
  medium: { border: 'border-yellow-500', badge: 'bg-yellow-900 text-yellow-300', label: 'MEDIUM' },
  high:   { border: 'border-red-500',    badge: 'bg-red-900 text-red-300',       label: 'HIGH'   },
}

function Countdown({ seconds, onExpire }) {
  const [remaining, setRemaining] = useState(seconds)

  useEffect(() => {
    if (remaining <= 0) { onExpire(); return }
    const t = setTimeout(() => setRemaining(r => r - 1), 1000)
    return () => clearTimeout(t)
  }, [remaining, onExpire])

  const mins = String(Math.floor(remaining / 60)).padStart(2, '0')
  const secs = String(remaining % 60).padStart(2, '0')
  const urgent = remaining <= 30

  return (
    <span className={`font-mono text-xs ${urgent ? 'text-red-400 animate-pulse' : 'text-slate-400'}`}>
      ⏱ Auto-cancels in {mins}:{secs}
    </span>
  )
}

export default function PlanConfirmModal() {
  const { pendingPlan, clearPlan } = useAgentOutput()
  const [sending,   setSending]   = useState(false)
  const [confirmed, setConfirmed] = useState(false)  // required checkbox for HIGH risk

  // Reset checkbox whenever a new plan arrives
  useEffect(() => {
    if (pendingPlan) setConfirmed(false)
  }, [pendingPlan?.summary])

  const respond = useCallback(async (approved) => {
    if (sending || !pendingPlan) return
    setSending(true)
    try {
      await sendConfirmation(pendingPlan.sessionId, approved)
      clearPlan()
    } catch (e) {
      console.error('[PlanConfirmModal] send failed:', e)
      setSending(false)
    }
  }, [sending, pendingPlan, clearPlan])

  const onTimeout = useCallback(() => respond(false), [respond])

  if (!pendingPlan) return null

  const riskLevel = pendingPlan.risk_level || 'medium'
  const risk      = RISK_STYLE[riskLevel] || RISK_STYLE.medium
  const steps     = pendingPlan.steps || []

  return (
    /* Backdrop — not dismissable */
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
      <div className={`w-full max-w-lg mx-4 bg-slate-900 border-2 ${risk.border} rounded-xl shadow-2xl`}>

        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-700">
          <div className="flex items-center gap-2">
            <span className="text-lg">⚠</span>
            <span className="text-white font-bold text-sm">Agent Action Plan</span>
          </div>
          <Countdown seconds={TIMEOUT_SECONDS} onExpire={onTimeout} />
        </div>

        {/* Summary */}
        <div className="px-5 py-4">
          <p className="text-slate-200 text-sm leading-relaxed">{pendingPlan.summary}</p>
        </div>

        {/* Risk + reversible */}
        <div className="flex items-center gap-3 px-5 pb-3">
          <span className={`text-xs font-bold px-2 py-0.5 rounded ${risk.badge}`}>
            Risk: {risk.label}
          </span>
          <span className={`text-xs font-bold px-2 py-0.5 rounded ${
            pendingPlan.reversible
              ? 'bg-green-900 text-green-300'
              : 'bg-red-900 text-red-300'
          }`}>
            {pendingPlan.reversible ? 'Reversible: YES' : 'Reversible: NO'}
          </span>
          {riskLevel === 'high' && (
            <span className="text-red-400 text-xs font-semibold">
              ⛔ High-risk operation — review carefully
            </span>
          )}
        </div>

        {/* Steps */}
        {steps.length > 0 && (
          <div className="px-5 pb-4">
            <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2">Steps</p>
            <div className="space-y-1.5">
              {steps.map((s, i) => {
                // Model sends steps as plain strings — handle both string and object format
                if (typeof s === 'string') {
                  return (
                    <div key={i} className="flex items-start gap-2 bg-slate-800 rounded px-3 py-2">
                      <span className="text-slate-500 text-xs font-mono shrink-0 w-5">{i + 1}.</span>
                      <p className="text-slate-200 text-xs leading-relaxed">{s}</p>
                    </div>
                  )
                }
                // Structured object format {tool, risk, args_preview, description}
                const stepRisk = RISK_STYLE[s.risk] || RISK_STYLE.medium
                const argsStr  = typeof s.args_preview === 'object'
                  ? Object.entries(s.args_preview || {}).map(([k, v]) => `${k}: ${v}`).join(', ')
                  : (s.args_preview || '')
                return (
                  <div key={i} className="flex items-start gap-2 bg-slate-800 rounded px-3 py-2">
                    <span className="text-slate-500 text-xs font-mono shrink-0 w-5">{i + 1}.</span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        {s.tool && <span className="text-blue-300 text-xs font-mono">{s.tool}</span>}
                        <span className={`text-xs px-1.5 py-0.5 rounded ${stepRisk.badge}`}>
                          {(s.risk || 'medium').toLowerCase()}
                        </span>
                        {s.description && <span className="text-slate-200 text-xs">{s.description}</span>}
                      </div>
                      {argsStr && (
                        <p className="text-slate-400 text-xs mt-0.5 truncate">{argsStr}</p>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {/* High-risk confirmation checkbox */}
        {riskLevel === 'high' && (
          <div className="px-5 pb-3">
            <label className="flex items-center gap-2 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={confirmed}
                onChange={e => setConfirmed(e.target.checked)}
                className="w-4 h-4 accent-red-500"
              />
              <span className="text-red-300 text-xs font-semibold">
                I have reviewed this plan and understand the risks
              </span>
            </label>
          </div>
        )}

        {/* Actions */}
        <div className="flex gap-3 px-5 py-4 border-t border-slate-700">
          <button
            onClick={() => respond(false)}
            disabled={sending}
            className="flex-1 py-2.5 rounded-lg text-sm font-semibold transition-colors bg-slate-700 hover:bg-slate-600 text-slate-200 disabled:opacity-50"
          >
            ✕ Cancel
          </button>
          <button
            onClick={() => respond(true)}
            disabled={sending || (riskLevel === 'high' && !confirmed)}
            title={riskLevel === 'high' && !confirmed ? 'Check the confirmation box first' : ''}
            className={`flex-1 py-2.5 rounded-lg text-sm font-semibold transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
              riskLevel === 'high'
                ? 'bg-red-700 hover:bg-red-600 text-white'
                : 'bg-green-700 hover:bg-green-600 text-white'
            }`}
          >
            {sending ? '⏳ Sending…' : '✓ Confirm & Run'}
          </button>
        </div>
      </div>
    </div>
  )
}
