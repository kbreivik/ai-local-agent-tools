import React from 'react'

/**
 * v2.36.2 — operator-visible gate modal.
 *
 * Listens on the WebSocket for `external_ai_confirm_pending` events from
 * wait_for_external_ai_confirmation. Renders modal with rule/reason/provider,
 * POSTs to /api/agent/operations/{op}/confirm-external on approve/reject.
 *
 * Auto-cancel countdown matches the server-side timeout.
 */
export default function ExternalAIConfirmModal({ event, onClose }) {
  const [secondsLeft, setSecondsLeft] = React.useState(event?.timeout_s || 300)
  const [submitting, setSubmitting] = React.useState(false)

  React.useEffect(() => {
    if (!event) return
    setSecondsLeft(event.timeout_s || 300)
    const id = setInterval(() => {
      setSecondsLeft(s => Math.max(0, s - 1))
    }, 1000)
    return () => clearInterval(id)
  }, [event])

  React.useEffect(() => {
    if (!event) return
    if (secondsLeft === 0) {
      onClose?.()
    }
  }, [secondsLeft, event, onClose])

  if (!event) return null

  const handle = async (approved) => {
    setSubmitting(true)
    try {
      const r = await fetch(
        `/api/agent/operations/${event.operation_id}/confirm-external`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ session_id: event.session_id, approved }),
        }
      )
      if (!r.ok) console.error('confirm-external failed', await r.text())
    } finally {
      setSubmitting(false)
      onClose?.()
    }
  }

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
      <div className="bg-[var(--bg-1)] border border-[var(--accent)] p-6 max-w-xl w-full">
        <h3 className="text-[var(--accent)] font-mono uppercase tracking-wider mb-3">
          External AI Escalation — Approval Required
        </h3>
        <div className="text-sm space-y-2 mb-4">
          <div>
            <span className="text-gray-400">Provider / Model:</span>{' '}
            <b>{event.provider}/{event.model}</b>
          </div>
          <div>
            <span className="text-gray-400">Rule fired:</span>{' '}
            <code className="text-[var(--cyan)]">{event.rule_fired}</code>
          </div>
          <div>
            <span className="text-gray-400">Reason:</span>{' '}
            <span className="text-gray-200">{event.reason}</span>
          </div>
          <div>
            <span className="text-gray-400">Output mode:</span>{' '}
            <b>{event.output_mode}</b>
          </div>
          <div className="pt-2 border-t border-white/10">
            <span className="text-gray-400">Auto-cancel in:</span>{' '}
            <span className="text-[var(--amber)]">{secondsLeft}s</span>
          </div>
        </div>
        <div className="flex gap-3 justify-end">
          <button
            disabled={submitting}
            onClick={() => handle(false)}
            className="px-4 py-2 border border-white/20 text-sm hover:bg-white/5"
          >Reject</button>
          <button
            disabled={submitting}
            onClick={() => handle(true)}
            className="px-4 py-2 bg-[var(--accent)] text-white text-sm
                       hover:bg-[var(--accent-dim)]"
          >Approve</button>
        </div>
      </div>
    </div>
  )
}
