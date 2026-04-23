/**
 * SessionOutputTab — Operate → Session Output
 * Lists recent operations and shows raw session output for each.
 */
import { useState, useEffect, useCallback } from 'react'
import { authHeaders } from '../api'

const BASE = import.meta.env.VITE_API_BASE ?? ''

function ago(iso) {
  if (!iso) return ''
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.round(s / 60)}m ago`
  return `${Math.round(s / 3600)}h ago`
}

const TYPE_COLOR = {
  step:      'var(--text-3)',
  tool:      'var(--cyan)',
  reasoning: 'var(--purple)',
  halt:      'var(--amber)',
  done:      'var(--green)',
  error:     'var(--red)',
  memory:    'var(--text-3)',
}

export default function SessionOutputTab({ initialSessionId }) {
  const [ops, setOps] = useState([])
  const [selectedOp, setSelectedOp] = useState(null)
  const [lines, setLines] = useState([])
  const [loadingOps, setLoadingOps] = useState(true)
  const [loadingLines, setLoadingLines] = useState(false)
  const [keyword, setKeyword] = useState('')
  const [typeFilter, setTypeFilter] = useState('')

  // Load recent operations
  useEffect(() => {
    fetch(`${BASE}/api/logs/operations?limit=30`, { headers: authHeaders() })
      .then(r => r.json())
      .then(d => { setOps(d.operations || []); setLoadingOps(false) })
      .catch(() => setLoadingOps(false))
  }, [])

  // Auto-select if initialSessionId provided
  useEffect(() => {
    if (initialSessionId && ops.length > 0) {
      const op = ops.find(o => o.session_id === initialSessionId || o.id === initialSessionId)
      if (op) selectOp(op)
    }
  }, [initialSessionId, ops])

  const selectOp = useCallback(async (op) => {
    setSelectedOp(op)
    setLines([])
    setLoadingLines(true)
    try {
      const params = new URLSearchParams({ limit: 1000 })
      if (typeFilter) params.set('type_filter', typeFilter)
      if (keyword) params.set('keyword', keyword)
      const r = await fetch(
        `${BASE}/api/logs/session/${op.session_id}/output?${params}`,
        { headers: authHeaders() }
      )
      const d = await r.json()
      setLines(d.lines || d.entries || [])
    } catch (_) {}
    finally { setLoadingLines(false) }
  }, [typeFilter, keyword])

  const reloadLines = () => { if (selectedOp) selectOp(selectedOp) }

  return (
    <div style={{ display: 'flex', height: 'calc(100vh - 90px)', overflow: 'hidden', padding: '16px 24px', gap: 16 }}>

      {/* Left: operations list */}
      <div style={{ width: 280, flexShrink: 0, display: 'flex', flexDirection: 'column', gap: 4, overflowY: 'auto' }}>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-3)', letterSpacing: '0.15em', textTransform: 'uppercase', marginBottom: 8 }}>
          RECENT SESSIONS
        </div>
        {loadingOps && <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-3)' }}>Loading...</div>}
        {ops.map(op => (
          <button
            key={op.id}
            onClick={() => selectOp(op)}
            style={{
              background: selectedOp?.id === op.id ? 'rgba(160,24,40,0.12)' : 'var(--bg-2)',
              border: `1px solid ${selectedOp?.id === op.id ? 'rgba(160,24,40,0.4)' : 'var(--border)'}`,
              borderRadius: 2, padding: '7px 10px', cursor: 'pointer',
              textAlign: 'left', display: 'flex', flexDirection: 'column', gap: 3,
            }}
          >
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-1)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {op.task?.slice(0, 45) || '(no task)'}
            </div>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 8, color: 'var(--text-3)' }}>{ago(op.started_at)}</span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 8, padding: '1px 4px', borderRadius: 1,
                background: op.status === 'completed' ? 'var(--green-dim)' : op.status === 'failed' ? 'rgba(204,40,40,0.12)' : 'var(--bg-1)',
                color: op.status === 'completed' ? 'var(--green)' : op.status === 'failed' ? 'var(--red)' : 'var(--text-3)',
                border: '1px solid transparent',
              }}>{op.status || '?'}</span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 8, color: 'var(--text-3)' }}>{op.agent_type}</span>
            </div>
          </button>
        ))}
      </div>

      {/* Right: output lines */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        {selectedOp ? (
          <>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10, flexShrink: 0 }}>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-3)', letterSpacing: '0.15em', textTransform: 'uppercase' }}>
                OUTPUT
              </div>
              <input
                value={keyword}
                onChange={e => setKeyword(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && reloadLines()}
                placeholder="filter keyword…"
                style={{
                  fontFamily: 'var(--font-mono)', fontSize: 9, padding: '3px 7px',
                  background: 'var(--bg-1)', border: '1px solid var(--border)',
                  color: 'var(--text-1)', borderRadius: 2, width: 150,
                }}
              />
              <select
                value={typeFilter}
                onChange={e => { setTypeFilter(e.target.value); setTimeout(reloadLines, 0) }}
                style={{
                  fontFamily: 'var(--font-mono)', fontSize: 9, padding: '3px 7px',
                  background: 'var(--bg-1)', border: '1px solid var(--border)',
                  color: 'var(--text-2)', borderRadius: 2,
                }}
              >
                <option value="">all types</option>
                {['step','tool','reasoning','halt','done','error','memory'].map(t =>
                  <option key={t} value={t}>{t}</option>
                )}
              </select>
              <button onClick={reloadLines} style={{
                fontFamily: 'var(--font-mono)', fontSize: 9, padding: '3px 7px',
                background: 'transparent', border: '1px solid var(--border)',
                color: 'var(--text-2)', borderRadius: 2, cursor: 'pointer',
              }}>↻</button>
            </div>
            <div style={{ flex: 1, overflowY: 'auto', background: 'var(--bg-1)', border: '1px solid var(--border)', borderRadius: 2, padding: '8px 10px' }}>
              {loadingLines && <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-3)' }}>Loading output...</div>}
              {!loadingLines && lines.length === 0 && (
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-3)' }}>No output lines found.</div>
              )}
              {lines.map((line, i) => (
                <div key={i} style={{ display: 'flex', gap: 8, marginBottom: 3, fontFamily: 'var(--font-mono)', fontSize: 9, lineHeight: 1.6 }}>
                  <span style={{ color: 'var(--text-3)', flexShrink: 0, minWidth: 50 }}>
                    {line.timestamp ? new Date(line.timestamp).toLocaleTimeString() : ''}
                  </span>
                  <span style={{ color: TYPE_COLOR[line.type] || 'var(--text-3)', flexShrink: 0, minWidth: 60 }}>
                    {line.type}
                  </span>
                  <span style={{ color: 'var(--text-2)', wordBreak: 'break-word' }}>
                    {line.content}
                  </span>
                </div>
              ))}
            </div>
          </>
        ) : (
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-3)', marginTop: 40 }}>
            ← select a session to view output
          </div>
        )}
      </div>
    </div>
  )
}
