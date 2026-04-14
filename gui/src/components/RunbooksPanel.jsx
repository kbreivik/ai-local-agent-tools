/**
 * RunbooksPanel — browse, search, and re-open saved runbooks.
 * Shown as a sidebar tab under OPERATE → Runbooks.
 */
import { useState, useEffect, useCallback } from 'react'
import { authHeaders } from '../api'

const BASE = import.meta.env.VITE_API_BASE ?? ''

const SOURCE_BADGE = {
  manual_completion: { label: 'manual', color: '#22c55e' },
  agent_proposed:    { label: 'agent',  color: '#00c8ee' },
  user_created:      { label: 'user',   color: '#a855f7' },
}

export default function RunbooksPanel() {
  const [runbooks, setRunbooks] = useState([])
  const [query, setQuery]       = useState('')
  const [loading, setLoading]   = useState(true)
  const [expanded, setExpanded] = useState(null)

  const load = useCallback(() => {
    setLoading(true)
    fetch(`${BASE}/api/runbooks`, { headers: authHeaders() })
      .then(r => r.ok ? r.json() : { runbooks: [] })
      .then(d => setRunbooks(d.runbooks || []))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  const del = async (id) => {
    if (!confirm('Delete this runbook?')) return
    await fetch(`${BASE}/api/runbooks/${id}`, { method: 'DELETE', headers: authHeaders() })
    load()
  }

  const visible = query
    ? runbooks.filter(r =>
        r.title.toLowerCase().includes(query.toLowerCase()) ||
        r.description.toLowerCase().includes(query.toLowerCase()) ||
        (r.tags || []).some(t => t.includes(query.toLowerCase()))
      )
    : runbooks

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%',
                  background: 'var(--bg-0)', color: 'var(--text-1)' }}>
      {/* Header */}
      <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--border)',
                    flexShrink: 0, display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10,
                       color: 'var(--text-3)', letterSpacing: 1 }}>
          RUNBOOKS
        </span>
        <input
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder="Search runbooks…"
          style={{ fontSize: 10, padding: '3px 8px', borderRadius: 2, flex: 1,
                   background: 'var(--bg-2)', border: '1px solid var(--border)',
                   color: 'var(--text-1)', fontFamily: 'var(--font-mono)', outline: 'none' }}
        />
        <button onClick={load}
          style={{ color: 'var(--text-3)', background: 'none', border: 'none',
                   cursor: 'pointer', fontSize: 12 }}>↺</button>
      </div>

      {/* List */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '10px 14px' }}>
        {loading && <p style={{ fontSize: 10, color: 'var(--text-3)' }}>Loading…</p>}
        {!loading && visible.length === 0 && (
          <p style={{ fontSize: 10, color: 'var(--text-3)' }}>
            {query ? 'No runbooks match your search.' : 'No runbooks saved yet. Complete a manual runbook checklist to save one.'}
          </p>
        )}
        {visible.map(rb => {
          const badge = SOURCE_BADGE[rb.source] || { label: rb.source, color: '#64748b' }
          const isOpen = expanded === rb.id
          return (
            <div key={rb.id} style={{ marginBottom: 8, borderRadius: 3,
                                       border: '1px solid var(--border)',
                                       background: 'var(--bg-1)' }}>
              {/* Summary row */}
              <div
                onClick={() => setExpanded(isOpen ? null : rb.id)}
                style={{ padding: '10px 12px', cursor: 'pointer',
                         display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 10, color: badge.color,
                               fontFamily: 'var(--font-mono)', flexShrink: 0 }}>
                  {badge.label}
                </span>
                <span style={{ fontSize: 11, color: 'var(--text-1)', flex: 1 }}>
                  {rb.title}
                </span>
                <span style={{ fontSize: 9, color: 'var(--text-3)',
                               fontFamily: 'var(--font-mono)' }}>
                  {rb.steps?.length || 0} steps
                </span>
                {(rb.tags || []).map(t => (
                  <span key={t} style={{ fontSize: 8, padding: '1px 5px', borderRadius: 2,
                                          background: 'var(--bg-2)', color: 'var(--text-3)' }}>
                    {t}
                  </span>
                ))}
                <span style={{ color: 'var(--text-3)', fontSize: 12 }}>
                  {isOpen ? '▾' : '▸'}
                </span>
              </div>

              {/* Expanded steps */}
              {isOpen && (
                <div style={{ padding: '0 12px 12px', borderTop: '1px solid var(--border)' }}>
                  <p style={{ fontSize: 10, color: 'var(--text-3)', margin: '8px 0 6px' }}>
                    {rb.description}
                  </p>
                  {(rb.steps || []).map((step, i) => (
                    <div key={i} style={{ padding: '5px 0', borderBottom: '1px solid var(--border)',
                                          fontSize: 10, color: 'var(--text-2)' }}>
                      <span style={{ color: 'var(--text-3)', marginRight: 8 }}>
                        {String(i + 1).padStart(2, '0')}.
                      </span>
                      {step.title || step.description || String(step)}
                      {step.command && (
                        <div style={{ marginTop: 3, display: 'flex', gap: 6, alignItems: 'center' }}>
                          <code style={{ fontSize: 9, color: '#38bdf8',
                                         fontFamily: 'var(--font-mono)',
                                         background: 'var(--bg-2)',
                                         padding: '1px 6px', borderRadius: 2 }}>
                            {step.command}
                          </code>
                          <button
                            onClick={() => navigator.clipboard.writeText(step.command)}
                            style={{ fontSize: 8, color: 'var(--text-3)', background: 'none',
                                     border: '1px solid var(--border)', borderRadius: 2,
                                     cursor: 'pointer', padding: '1px 4px' }}>
                            copy
                          </button>
                        </div>
                      )}
                    </div>
                  ))}
                  {/* Actions */}
                  <div style={{ marginTop: 10, display: 'flex', gap: 8 }}>
                    <button
                      onClick={() => del(rb.id)}
                      style={{ fontSize: 9, padding: '3px 8px', borderRadius: 2,
                               background: 'transparent', color: 'var(--red)',
                               border: '1px solid var(--border)', cursor: 'pointer',
                               fontFamily: 'var(--font-mono)' }}>
                      delete
                    </button>
                    <span style={{ fontSize: 9, color: 'var(--text-3)', alignSelf: 'center' }}>
                      used {rb.run_count}x · by {rb.created_by}
                    </span>
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
