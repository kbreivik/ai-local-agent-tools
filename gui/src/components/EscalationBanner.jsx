/**
 * EscalationBanner — persistent amber banner shown when agent escalates.
 * Sits at the top of the dashboard content area, below the drill bar.
 * Stays until explicitly acknowledged.
 */
import { useState, useEffect, useCallback } from 'react'
import { authHeaders } from '../api'

const BASE = import.meta.env.VITE_API_BASE ?? ''

export default function EscalationBanner() {
  const [escalations, setEscalations] = useState([])

  const fetchEscalations = useCallback(() => {
    fetch(`${BASE}/api/escalations?unacked_only=true&limit=5`, {
      headers: { ...authHeaders() }
    })
      .then(r => r.ok ? r.json() : { escalations: [] })
      .then(d => setEscalations(d.escalations || []))
      .catch(() => {})
  }, [])

  // Poll every 15 seconds + listen for WebSocket event
  useEffect(() => {
    fetchEscalations()
    const id = setInterval(fetchEscalations, 15000)

    // Also update immediately on WebSocket escalation_recorded event
    const handler = (e) => {
      if (e.detail?.type === 'escalation_recorded') fetchEscalations()
    }
    window.addEventListener('ds:ws-message', handler)

    return () => {
      clearInterval(id)
      window.removeEventListener('ds:ws-message', handler)
    }
  }, [fetchEscalations])

  const acknowledge = async (id) => {
    await fetch(`${BASE}/api/escalations/${id}/acknowledge`, {
      method: 'POST',
      headers: { ...authHeaders() }
    })
    setEscalations(prev => prev.filter(e => e.id !== id))
  }

  const acknowledgeAll = async () => {
    await fetch(`${BASE}/api/escalations/acknowledge-all`, {
      method: 'POST',
      headers: { ...authHeaders() }
    })
    setEscalations([])
  }

  if (escalations.length === 0) return null

  const latest = escalations[0]
  const extra  = escalations.length - 1

  return (
    <div style={{
      background: 'rgba(204,136,0,0.12)',
      borderBottom: '1px solid var(--amber)',
      padding: '8px 16px',
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      flexShrink: 0,
    }}>
      {/* Pulsing dot */}
      <span style={{
        width: 8, height: 8, borderRadius: '50%',
        background: 'var(--amber)',
        boxShadow: '0 0 6px var(--amber)',
        animation: 'pulse 1.5s ease-in-out infinite',
        flexShrink: 0,
      }} />

      {/* Icon + label */}
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9,
                     color: 'var(--amber)', letterSpacing: 1, flexShrink: 0 }}>
        ⚑ ESCALATED
      </span>

      {/* Reason text */}
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10,
                     color: 'var(--text-2)', flex: 1, minWidth: 0 }}>
        {latest.reason?.slice(0, 160)}
        {extra > 0 && (
          <span style={{ color: 'var(--amber)', marginLeft: 6 }}>
            +{extra} more
          </span>
        )}
      </span>

      {/* Session link */}
      {latest.session_id && (
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 8,
                       color: 'var(--text-3)', flexShrink: 0 }}>
          session {latest.session_id.slice(0, 8)}
        </span>
      )}

      {/* Acknowledge buttons */}
      <button
        onClick={() => acknowledge(latest.id)}
        style={{
          padding: '2px 8px', fontSize: 9, fontFamily: 'var(--font-mono)',
          background: 'var(--amber-dim)', color: 'var(--amber)',
          border: '1px solid var(--amber)', borderRadius: 2,
          cursor: 'pointer', flexShrink: 0,
        }}
      >
        ACK
      </button>
      {escalations.length > 1 && (
        <button
          onClick={acknowledgeAll}
          style={{
            padding: '2px 8px', fontSize: 9, fontFamily: 'var(--font-mono)',
            background: 'transparent', color: 'var(--text-3)',
            border: '1px solid var(--border)', borderRadius: 2,
            cursor: 'pointer', flexShrink: 0,
          }}
        >
          ACK ALL ({escalations.length})
        </button>
      )}
    </div>
  )
}
