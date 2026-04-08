/**
 * EntityDrawer — slide-in detail panel for entity health records.
 * Opens from the right when an entity card is clicked.
 * Fetches data from GET /api/entities, filtered client-side by entity id.
 */
import { useEffect, useState, useCallback } from 'react'
import { authHeaders } from '../api'

const BASE = import.meta.env.VITE_API_BASE ?? ''

const STATUS_COLOR = {
  healthy:  { dot: 'var(--green)',  bg: 'var(--green-dim)',  text: 'var(--green)' },
  degraded: { dot: 'var(--amber)',  bg: 'var(--amber-dim)',  text: 'var(--amber)' },
  error:    { dot: 'var(--red)',    bg: 'var(--red-dim)',    text: 'var(--red)' },
  unknown:  { dot: 'var(--text-3)', bg: 'var(--bg-3)',       text: 'var(--text-3)' },
  maintenance: { dot: 'var(--text-3)', bg: 'var(--bg-3)',    text: 'var(--text-3)' },
}

function statusStyle(status) {
  return STATUS_COLOR[status] || STATUS_COLOR.unknown
}

function formatTimestamp(ts) {
  if (!ts) return '—'
  try {
    const d = new Date(ts)
    return d.toLocaleString()
  } catch {
    return ts
  }
}

export default function EntityDrawer({ entityId, onClose }) {
  const [entity, setEntity] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const load = useCallback(() => {
    if (!entityId) return
    setLoading(true)
    setError(null)
    fetch(`${BASE}/api/entities`, { headers: { ...authHeaders() } })
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then(entities => {
        const match = entities.find(e => e.id === entityId)
        setEntity(match || null)
        if (!match) setError('Entity not found')
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [entityId])

  useEffect(() => { load() }, [load])

  // Close on Escape
  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  if (!entityId) return null

  const s = statusStyle(entity?.status)
  const meta = entity?.metadata || {}
  const metaEntries = Object.entries(meta).filter(([, v]) => v != null && v !== '')

  return (
    <>
      {/* Overlay */}
      <div
        onClick={onClose}
        style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)',
          zIndex: 49,
        }}
      />

      {/* Drawer */}
      <div style={{
        position: 'fixed', top: 0, right: 0, bottom: 0, width: 400,
        background: 'var(--bg-1)', borderLeft: '1px solid var(--border)',
        zIndex: 50, display: 'flex', flexDirection: 'column',
        animation: 'slideInRight 0.15s ease-out',
      }}>
        {/* Header */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '12px 16px', borderBottom: '1px solid var(--border)',
        }}>
          <span style={{
            fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: 13,
            color: 'var(--text-1)', letterSpacing: 0.5,
          }}>
            ENTITY DETAIL
          </span>
          <button
            onClick={onClose}
            style={{
              background: 'none', border: 'none', color: 'var(--text-3)',
              cursor: 'pointer', fontSize: 16, padding: '2px 6px',
            }}
          >
            ✕
          </button>
        </div>

        {/* Content */}
        <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
          {loading && (
            <p style={{ fontSize: 11, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>
              Loading…
            </p>
          )}

          {error && !entity && (
            <p style={{ fontSize: 11, color: 'var(--red)', fontFamily: 'var(--font-mono)' }}>
              {error}
            </p>
          )}

          {entity && (
            <>
              {/* Status badge + label */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
                <span style={{
                  width: 10, height: 10, borderRadius: '50%',
                  background: s.dot, flexShrink: 0,
                }} />
                <span style={{
                  fontFamily: 'var(--font-sans)', fontWeight: 700,
                  fontSize: 15, color: 'var(--text-1)',
                }}>
                  {entity.label}
                </span>
                <span style={{
                  fontSize: 9, fontFamily: 'var(--font-mono)', padding: '2px 6px',
                  background: s.bg, color: s.text, borderRadius: 2,
                  fontWeight: 600, letterSpacing: 0.5, textTransform: 'uppercase',
                }}>
                  {entity.status}
                </span>
              </div>

              {/* Key-value rows */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
                <Row label="Platform" value={entity.platform} />
                <Row label="Section" value={entity.section} />
                <Row label="Component" value={entity.component} />
                <Row label="Last Seen" value={formatTimestamp(entity.last_seen)} />
                {entity.latency_ms != null && (
                  <Row label="Latency" value={`${entity.latency_ms}ms`} />
                )}
                {entity.last_error && (
                  <Row label="Last Error" value={entity.last_error} error />
                )}
                <Row label="ID" value={entity.id} mono />
              </div>

              {/* Metadata */}
              {metaEntries.length > 0 && (
                <div style={{ marginTop: 16 }}>
                  <div style={{
                    fontFamily: 'var(--font-sans)', fontWeight: 600, fontSize: 10,
                    color: 'var(--text-3)', letterSpacing: 1, textTransform: 'uppercase',
                    marginBottom: 6,
                  }}>
                    METADATA
                  </div>
                  <div style={{
                    background: 'var(--bg-2)', border: '1px solid var(--border)',
                    borderRadius: 2, padding: '4px 0',
                  }}>
                    {metaEntries.map(([k, v]) => (
                      <Row key={k} label={k} value={String(v)} mono />
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>

      <style>{`
        @keyframes slideInRight {
          from { transform: translateX(100%); }
          to   { transform: translateX(0); }
        }
      `}</style>
    </>
  )
}

function Row({ label, value, mono, error: isError }) {
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
      padding: '4px 8px', borderBottom: '1px solid var(--bg-3)',
      fontSize: 11,
    }}>
      <span style={{
        color: 'var(--text-3)', fontFamily: 'var(--font-mono)',
        fontSize: 9, letterSpacing: 0.5, textTransform: 'uppercase',
        minWidth: 80, flexShrink: 0,
      }}>
        {label}
      </span>
      <span style={{
        color: isError ? 'var(--red)' : 'var(--text-1)',
        fontFamily: mono ? 'var(--font-mono)' : 'var(--font-sans)',
        fontSize: 11, textAlign: 'right', wordBreak: 'break-all',
        maxWidth: 240,
      }}>
        {value || '—'}
      </span>
    </div>
  )
}
