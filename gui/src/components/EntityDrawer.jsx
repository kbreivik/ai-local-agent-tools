/**
 * EntityDrawer — slide-in detail panel for entity health records.
 * Opens from the right when an entity card is clicked.
 * Fetches data from GET /api/entities, filtered client-side by entity id.
 */
import { useEffect, useState, useCallback, useRef } from 'react'
import { createPortal } from 'react-dom'
import { authHeaders, askAgent, fetchAskSuggestions, fetchEntityHistory } from '../api'

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
  const [question, setQuestion]       = useState('')
  const [answer, setAnswer]           = useState('')
  const [asking, setAsking]           = useState(false)
  const [suggestions, setSuggestions] = useState([])
  const [timeline, setTimeline]       = useState(null)   // { changes, events } | null
  const [tlLoading, setTlLoading]     = useState(false)
  const [tlHours, setTlHours]         = useState(48)
  const [tlOpen, setTlOpen]           = useState(false)
  const textareaRef                   = useRef(null)

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

  // Fetch suggestions when entity loads
  useEffect(() => {
    if (!entity) return
    setAnswer('')
    setQuestion('')
    fetchAskSuggestions(entity.status, entity.section)
      .then(setSuggestions)
  }, [entity])

  // Load timeline when drawer opens or hours changes (lazy — only when tlOpen)
  useEffect(() => {
    if (!entityId || !tlOpen) return
    setTlLoading(true)
    fetchEntityHistory(entityId, tlHours)
      .then(d => setTimeline(d))
      .catch(() => setTimeline({ changes: [], events: [] }))
      .finally(() => setTlLoading(false))
  }, [entityId, tlOpen, tlHours])

  const sendQuestion = () => {
    if (!question.trim() || asking || !entity) return
    setAsking(true)
    setAnswer('')
    askAgent(
      entity,
      question,
      (chunk) => setAnswer(prev => prev + chunk),
      ()      => setAsking(false),
      (err)   => { setAnswer(`Error: ${err}`); setAsking(false) }
    )
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) sendQuestion()
  }

  if (!entityId) return null

  const s = statusStyle(entity?.status)
  const meta = entity?.metadata || {}
  const metaEntries = Object.entries(meta).filter(([, v]) => v != null && v !== '')

  return createPortal(
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

              {/* ── Ask panel ── */}
              <div style={{
                borderTop: '1px solid var(--accent-dim)',
                marginTop: 16, paddingTop: 14,
              }}>
                <p style={{
                  fontSize: '0.65rem', fontWeight: 700, letterSpacing: '0.08em',
                  color: 'var(--text-3)', textTransform: 'uppercase', marginBottom: 8,
                }}>Ask</p>

                {suggestions.length > 0 && !answer && (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 10 }}>
                    {suggestions.map((s, i) => (
                      <button key={i}
                        onClick={() => { setQuestion(s); textareaRef.current?.focus() }}
                        style={{
                          fontSize: '0.65rem', padding: '3px 8px',
                          border: '1px solid var(--accent-dim)', borderRadius: 2,
                          background: 'transparent', color: 'var(--cyan)',
                          cursor: 'pointer', fontFamily: 'var(--font-mono)', lineHeight: 1.4,
                        }}
                      >{s}</button>
                    ))}
                  </div>
                )}

                <textarea ref={textareaRef} rows={2}
                  value={question} onChange={e => setQuestion(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Ask about this entity… (Ctrl+Enter to send)"
                  disabled={asking}
                  style={{
                    width: '100%', background: 'var(--bg-2)',
                    border: '1px solid var(--accent-dim)', borderRadius: 2,
                    color: 'var(--text-1)', fontFamily: 'var(--font-mono)',
                    fontSize: '0.72rem', padding: '6px 8px',
                    resize: 'none', outline: 'none', boxSizing: 'border-box',
                  }}
                />

                <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 6, gap: 6 }}>
                  {answer && (
                    <button onClick={() => { setAnswer(''); setQuestion('') }}
                      style={{
                        fontSize: '0.65rem', padding: '4px 10px',
                        border: '1px solid var(--accent-dim)', borderRadius: 2,
                        background: 'transparent', color: 'var(--text-3)',
                        cursor: 'pointer', fontFamily: 'var(--font-mono)',
                      }}>Clear</button>
                  )}
                  <button onClick={sendQuestion}
                    disabled={!question.trim() || asking}
                    style={{
                      fontSize: '0.65rem', padding: '4px 12px',
                      border: '1px solid var(--accent)', borderRadius: 2,
                      background: asking ? 'transparent' : 'var(--accent-dim)',
                      color: asking ? 'var(--text-3)' : 'var(--cyan)',
                      cursor: !question.trim() || asking ? 'not-allowed' : 'pointer',
                      fontFamily: 'var(--font-mono)',
                      opacity: !question.trim() || asking ? 0.5 : 1,
                    }}>{asking ? 'Asking…' : 'Ask'}</button>
                </div>

                {answer && (
                  <div style={{
                    marginTop: 10, padding: 10,
                    background: 'var(--bg-2)', border: '1px solid var(--accent-dim)',
                    borderRadius: 2, fontFamily: 'var(--font-mono)',
                    fontSize: '0.72rem', color: 'var(--cyan)',
                    lineHeight: 1.6, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
                  }}>
                    {answer}
                    {asking && <span style={{ opacity: 0.5 }}>█</span>}
                  </div>
                )}
              </div>

              {/* ── TIMELINE ────────────────────────────────────────────── */}
              <div style={{ marginTop: 16, borderTop: '1px solid var(--border)' }}>
                <button
                  onClick={() => setTlOpen(o => !o)}
                  style={{
                    width: '100%', display: 'flex', alignItems: 'center',
                    justifyContent: 'space-between', padding: '8px 0',
                    background: 'none', border: 'none', cursor: 'pointer',
                    fontFamily: 'var(--font-mono)', fontSize: 9,
                    letterSpacing: '0.08em', color: 'var(--text-3)',
                  }}
                >
                  <span>TIMELINE</span>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    {tlOpen && (
                      <select
                        value={tlHours}
                        onChange={e => { e.stopPropagation(); setTlHours(Number(e.target.value)) }}
                        onClick={e => e.stopPropagation()}
                        style={{
                          fontSize: 8, fontFamily: 'var(--font-mono)', background: 'var(--bg-2)',
                          border: '1px solid var(--border)', borderRadius: 2,
                          color: 'var(--text-2)', padding: '1px 4px', cursor: 'pointer',
                        }}
                      >
                        <option value={24}>24h</option>
                        <option value={48}>48h</option>
                        <option value={168}>7d</option>
                      </select>
                    )}
                    <span style={{ fontSize: 8 }}>{tlOpen ? '▲' : '▼'}</span>
                  </div>
                </button>

                {tlOpen && (
                  <div style={{ paddingBottom: 12 }}>
                    {tlLoading && (
                      <div style={{ fontSize: 9, color: 'var(--text-3)', fontFamily: 'var(--font-mono)', padding: '4px 0' }}>
                        Loading timeline…
                      </div>
                    )}

                    {!tlLoading && timeline && (() => {
                      const items = [
                        ...(timeline.changes || []).map(c => ({
                          kind: 'change',
                          ts: c.detected_at,
                          label: c.field_name,
                          detail: `${c.old_value ?? '—'} → ${c.new_value}`,
                          color: 'var(--cyan)',
                        })),
                        ...(timeline.events || []).map(e => ({
                          kind: 'event',
                          ts: e.occurred_at,
                          label: e.event_type,
                          detail: e.description,
                          color: e.severity === 'critical' ? 'var(--red)'
                               : e.severity === 'error'    ? 'var(--red)'
                               : e.severity === 'warning'  ? 'var(--amber)'
                               : 'var(--green)',
                        })),
                      ].sort((a, b) => new Date(b.ts) - new Date(a.ts))

                      if (items.length === 0) {
                        return (
                          <div style={{ fontSize: 9, color: 'var(--text-3)', fontFamily: 'var(--font-mono)', padding: '4px 0' }}>
                            No changes or events in the last {tlHours}h
                          </div>
                        )
                      }

                      // Group by calendar day
                      const byDay = {}
                      for (const item of items) {
                        const day = item.ts ? new Date(item.ts).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' }) : 'Unknown'
                        if (!byDay[day]) byDay[day] = []
                        byDay[day].push(item)
                      }

                      return Object.entries(byDay).map(([day, dayItems]) => (
                        <div key={day} style={{ marginBottom: 10 }}>
                          <div style={{
                            fontSize: 8, fontFamily: 'var(--font-mono)', color: 'var(--text-3)',
                            letterSpacing: '0.08em', marginBottom: 4, textTransform: 'uppercase',
                          }}>{day}</div>
                          {dayItems.map((item, i) => (
                            <div key={i} style={{
                              display: 'flex', gap: 8, marginBottom: 4, alignItems: 'flex-start',
                            }}>
                              <div style={{
                                width: 6, height: 6, borderRadius: '50%',
                                background: item.color, flexShrink: 0, marginTop: 3,
                              }} />
                              <div style={{ flex: 1, minWidth: 0 }}>
                                <div style={{ display: 'flex', gap: 6, alignItems: 'baseline' }}>
                                  <span style={{
                                    fontSize: 9, fontFamily: 'var(--font-mono)',
                                    color: item.color, letterSpacing: '0.04em',
                                  }}>{item.label}</span>
                                  <span style={{ fontSize: 8, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>
                                    {item.ts ? new Date(item.ts).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }) : ''}
                                  </span>
                                </div>
                                <div style={{
                                  fontSize: 9, color: 'var(--text-2)', fontFamily: 'var(--font-mono)',
                                  wordBreak: 'break-word',
                                }}>{item.detail}</div>
                              </div>
                            </div>
                          ))}
                        </div>
                      ))
                    })()}

                    {!tlLoading && !timeline && (
                      <div style={{ fontSize: 9, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>
                        Timeline unavailable
                      </div>
                    )}
                  </div>
                )}
              </div>
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
    </>,
    document.body
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
