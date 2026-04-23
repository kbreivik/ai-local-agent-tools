/**
 * CollectorsTab — Monitor → Collectors
 * Shows each active collector: health, last poll, interval, error, trigger button.
 * Data source: /api/dashboard/summary → collectors (coll_mgr.status())
 *              /api/logs/snapshots/{component} for entity counts
 */
import { useState, useEffect, useCallback } from 'react'
import { authHeaders } from '../api'

const BASE = import.meta.env.VITE_API_BASE ?? ''

const DOT_COLOR = {
  healthy: 'var(--green)',
  ok:      'var(--green)',
  degraded:'var(--amber)',
  error:   'var(--red)',
  unknown: 'var(--text-3)',
  unconfigured: 'var(--text-3)',
}

function healthDot(h) {
  return (
    <span style={{
      display: 'inline-block', width: 7, height: 7, borderRadius: '50%',
      background: DOT_COLOR[h] || 'var(--text-3)', marginRight: 6, flexShrink: 0,
    }} />
  )
}

function ago(iso) {
  if (!iso) return 'never'
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 5) return 'just now'
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.round(s / 60)}m ago`
  return `${Math.round(s / 3600)}h ago`
}

export default function CollectorsTab() {
  const [collectors, setCollectors] = useState({})
  const [triggering, setTriggering] = useState({})
  const [triggerMsg, setTriggerMsg] = useState({})
  const [loading, setLoading] = useState(true)
  const [lastRefresh, setLastRefresh] = useState(null)

  const load = useCallback(async () => {
    try {
      const r = await fetch(`${BASE}/api/dashboard/summary`, { headers: authHeaders() })
      if (!r.ok) return
      const d = await r.json()
      setCollectors(d.collectors || {})
      setLastRefresh(new Date())
    } catch (_) {}
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load(); const t = setInterval(load, 15_000); return () => clearInterval(t) }, [load])

  const trigger = async (name) => {
    setTriggering(p => ({ ...p, [name]: true }))
    setTriggerMsg(p => ({ ...p, [name]: '' }))
    try {
      const r = await fetch(`${BASE}/api/dashboard/trigger-poll`, {
        method: 'POST', headers: { ...authHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ component: name }),
      })
      const d = await r.json().catch(() => ({}))
      setTriggerMsg(p => ({ ...p, [name]: r.ok ? 'triggered' : (d.detail || 'error') }))
      setTimeout(() => {
        setTriggerMsg(p => ({ ...p, [name]: '' }))
        load()
      }, 2500)
    } catch (e) {
      setTriggerMsg(p => ({ ...p, [name]: 'error' }))
    } finally {
      setTriggering(p => ({ ...p, [name]: false }))
    }
  }

  const sorted = Object.entries(collectors).sort(([a], [b]) => a.localeCompare(b))

  return (
    <div style={{ padding: '20px 24px', maxWidth: 900 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-3)', letterSpacing: '0.15em', textTransform: 'uppercase' }}>
          COLLECTORS
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {lastRefresh && (
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-3)' }}>
              refreshed {ago(lastRefresh.toISOString())}
            </span>
          )}
          <button onClick={load} style={{
            fontFamily: 'var(--font-mono)', fontSize: 9, padding: '3px 8px',
            background: 'transparent', border: '1px solid var(--border)', color: 'var(--text-2)',
            borderRadius: 2, cursor: 'pointer',
          }}>↻ refresh</button>
        </div>
      </div>

      {loading && (
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-3)' }}>Loading...</div>
      )}

      {!loading && sorted.length === 0 && (
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-3)' }}>No collectors running.</div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {sorted.map(([name, c]) => (
          <div key={name} style={{
            border: '1px solid var(--border)',
            background: c.last_error ? 'rgba(204,40,40,0.05)' : 'var(--bg-2)',
            borderColor: c.last_error ? 'rgba(204,40,40,0.25)' : 'var(--border)',
            borderRadius: 2, padding: '9px 12px',
            display: 'grid', gridTemplateColumns: '180px 80px 100px 80px 1fr auto',
            alignItems: 'center', gap: 12,
          }}>
            {/* Name + health dot */}
            <div style={{ display: 'flex', alignItems: 'center', minWidth: 0 }}>
              {healthDot(c.last_health)}
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-1)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {name}
              </span>
            </div>
            {/* Health label */}
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: DOT_COLOR[c.last_health] || 'var(--text-3)' }}>
              {c.last_health || 'unknown'}
            </span>
            {/* Last poll */}
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-2)' }}>
              {c.last_poll ? ago(c.last_poll) : '—'}
            </span>
            {/* Interval */}
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-3)' }}>
              every {c.interval_s}s
            </span>
            {/* Error */}
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--red)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {c.last_error || ''}
            </span>
            {/* Trigger button */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              {triggerMsg[name] && (
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: triggerMsg[name] === 'triggered' ? 'var(--green)' : 'var(--red)' }}>
                  {triggerMsg[name]}
                </span>
              )}
              <button
                onClick={() => trigger(name)}
                disabled={!!triggering[name]}
                style={{
                  fontFamily: 'var(--font-mono)', fontSize: 9, padding: '2px 7px',
                  background: 'transparent', border: '1px solid var(--border)',
                  color: triggering[name] ? 'var(--text-3)' : 'var(--text-2)',
                  borderRadius: 2, cursor: triggering[name] ? 'not-allowed' : 'pointer',
                  whiteSpace: 'nowrap',
                }}
              >
                {triggering[name] ? '...' : '⟳ poll'}
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
