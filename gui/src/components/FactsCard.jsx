// FactsCard — v2.35.0.1 Dashboard widget.
// Summarises the known_facts store:
//   - total + confident counts
//   - tier breakdown
//   - last-refresh freshness, stale + recently-changed counts
//   - pending admin-review count with a red pulse when >0

import { useEffect, useState } from 'react'
import { authHeaders } from '../api'

const BASE = import.meta.env.VITE_API_BASE ?? ''

function ago(iso) {
  if (!iso) return '—'
  const sec = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000))
  if (sec < 60) return `${sec}s ago`
  if (sec < 3600) return `${Math.round(sec / 60)}m ago`
  if (sec < 86400) return `${Math.round(sec / 3600)}h ago`
  return `${Math.round(sec / 86400)}d ago`
}

export default function FactsCard({ onNavigate }) {
  const [summary, setSummary] = useState(null)
  const [stale, setStale]     = useState(0)
  const [changed, setChanged] = useState(0)
  const [err, setErr]         = useState('')

  const load = async () => {
    try {
      const headers = { ...authHeaders() }
      const [s, st, ch] = await Promise.all([
        fetch(`${BASE}/api/facts/summary`,  { headers }).then(r => r.ok ? r.json() : null),
        fetch(`${BASE}/api/facts/stale`,    { headers }).then(r => r.ok ? r.json() : { stale: [] }),
        fetch(`${BASE}/api/facts/changed?hours=1`, { headers }).then(r => r.ok ? r.json() : { changes: [] }),
      ])
      setSummary(s || { total: 0, by_tier: {}, pending_conflicts: 0, last_refresh: null })
      setStale((st.stale || []).length)
      setChanged((ch.changes || []).length)
      setErr('')
    } catch (e) {
      setErr(e.message || 'Failed to load')
    }
  }

  useEffect(() => {
    load()
    const id = setInterval(load, 30000)
    return () => clearInterval(id)
  }, [])

  const s = summary || {}
  const tiers = s.by_tier || {}
  const confident = (tiers.very_high || 0) + (tiers.high || 0)
  const pending = s.pending_conflicts || 0

  return (
    <div data-testid="facts-card" style={{
      background: 'var(--bg-1)', border: '1px solid var(--border)',
      borderRadius: 2, padding: 14, fontFamily: 'var(--font-mono)',
      display: 'flex', flexDirection: 'column', gap: 8, minWidth: 220,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 10, letterSpacing: 1, color: 'var(--accent)' }}>◉ FACTS &amp; KNOWLEDGE</span>
        {pending > 0 && (
          <span data-testid="pending-badge" className="dot-pulse" style={{
            fontSize: 9, background: 'var(--red)', color: '#fff', padding: '1px 6px', borderRadius: 2,
          }}>{pending} PENDING</span>
        )}
      </div>

      {err && <div style={{ color: 'var(--red)', fontSize: 9 }}>{err}</div>}

      <div style={{ fontSize: 10, color: 'var(--text-1)' }}>
        <b>{s.total || 0}</b> total · <b style={{ color: 'var(--cyan)' }}>{confident}</b> confident
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 3, fontSize: 9 }}>
        <div style={{ color: 'var(--text-3)', letterSpacing: 1 }}>BY TIER</div>
        <Row label="Very High (≥0.9)" count={tiers.very_high || 0} colour="var(--green)" />
        <Row label="High      (0.7–0.9)" count={tiers.high || 0} colour="var(--cyan)" />
        <Row label="Medium    (0.5–0.7)" count={tiers.medium || 0} colour="var(--amber)" />
        <Row label="Low       (<0.5)" count={(tiers.low || 0) + (tiers.reject || 0)} colour="var(--red)" />
      </div>

      <div style={{ fontSize: 9, color: 'var(--text-3)' }}>
        <div>Last refresh: <span style={{ color: 'var(--text-2)' }}>{ago(s.last_refresh)}</span></div>
        <div style={{ color: stale > 0 ? 'var(--amber)' : 'var(--text-3)' }}>
          Stale (past cadence): {stale}{stale > 0 ? ' ⚠' : ''}
        </div>
        <div>Recently changed (1h): {changed}</div>
        {pending > 0 && (
          <div style={{ color: 'var(--red)', marginTop: 2 }}>⚠ Pending admin reviews: {pending}</div>
        )}
      </div>

      <button
        onClick={() => onNavigate ? onNavigate('Facts') : (window.location.hash = '#/facts')}
        data-testid="facts-card-nav"
        style={{
          alignSelf: 'flex-start', marginTop: 4, padding: '4px 10px',
          background: 'none', border: '1px solid var(--border)',
          color: 'var(--accent)', cursor: 'pointer',
          fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: 1,
        }}
      >
        VIEW FACTS →
      </button>
    </div>
  )
}

function Row({ label, count, colour }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <span style={{ width: 5, height: 5, borderRadius: '50%', background: colour, flexShrink: 0 }} />
      <span style={{ flex: 1, color: 'var(--text-2)' }}>{label}</span>
      <span style={{ color: 'var(--text-1)', fontWeight: 600 }}>{count}</span>
    </div>
  )
}
