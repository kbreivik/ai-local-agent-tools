import React, { useState, useEffect, useCallback, useMemo } from 'react'
import { fmtDateTime as fmtTs } from '../utils/fmtTs'

const REFRESH_MS = 30_000

const RADIUS_COLOR = {
  node:    'var(--cyan)',
  service: 'var(--amber)',
  cluster: 'var(--red)',
  fleet:   'var(--red)',
  unknown: 'var(--text-3)',
}

function StatusPill({ status }) {
  const color = status === 'ok' ? 'var(--green)'
              : status === 'blocked' ? 'var(--amber)'
              : status === 'degraded' ? 'var(--amber)'
              : 'var(--red)'
  return (
    <span style={{
      fontSize: 9, fontFamily: 'var(--font-mono)',
      padding: '1px 5px', borderRadius: 2,
      background: `${color}22`, color, letterSpacing: 0.5,
      textTransform: 'uppercase',
    }}>{status}</span>
  )
}

function RadiusPill({ radius }) {
  const color = RADIUS_COLOR[radius] || RADIUS_COLOR.unknown
  return (
    <span style={{
      fontSize: 9, fontFamily: 'var(--font-mono)',
      padding: '1px 5px', borderRadius: 2,
      border: `1px solid ${color}`, color,
      letterSpacing: 0.5, textTransform: 'uppercase',
    }}>{radius}</span>
  )
}

export default function AgentActionsTab() {
  const [rows, setRows] = useState([])
  const [count, setCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [forbidden, setForbidden] = useState(false)
  const [expandedId, setExpandedId] = useState(null)

  // Filters
  const [toolFilter, setToolFilter] = useState('')
  const [userFilter, setUserFilter] = useState('')
  const [radiusFilter, setRadiusFilter] = useState('')
  const [sinceFilter, setSinceFilter] = useState('')
  const [limit, setLimit] = useState(100)

  const fetchRows = useCallback(async () => {
    setError('')
    const params = new URLSearchParams()
    if (toolFilter) params.set('tool_name', toolFilter)
    if (userFilter) params.set('user',      userFilter)
    if (sinceFilter) params.set('since',    sinceFilter)
    params.set('limit', String(limit))
    try {
      const r = await fetch(`/api/agent/actions?${params.toString()}`, {
        credentials: 'include',
      })
      if (r.status === 403) { setForbidden(true); setLoading(false); return }
      if (!r.ok) { setError(`HTTP ${r.status}`); setLoading(false); return }
      const data = await r.json()
      let filtered = data.actions || []
      if (radiusFilter) filtered = filtered.filter(a => a.blast_radius === radiusFilter)
      setRows(filtered)
      setCount(data.count || 0)
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }, [toolFilter, userFilter, radiusFilter, sinceFilter, limit])

  useEffect(() => {
    fetchRows()
    const id = setInterval(fetchRows, REFRESH_MS)
    return () => clearInterval(id)
  }, [fetchRows])

  // Derive distinct tool/user lists from current rows for filter dropdowns
  const toolOptions = useMemo(() =>
    Array.from(new Set(rows.map(r => r.tool_name).filter(Boolean))).sort(),
  [rows])
  const userOptions = useMemo(() =>
    Array.from(new Set(rows.map(r => r.owner_user).filter(Boolean))).sort(),
  [rows])

  if (forbidden) {
    return (
      <div style={{
        padding: 40, textAlign: 'center',
        fontFamily: 'var(--font-mono)', color: 'var(--text-3)',
      }}>
        <div style={{ fontSize: 12, marginBottom: 6 }}>403 — AUDIT LOG RESTRICTED</div>
        <div style={{ fontSize: 10 }}>
          imperial_officer or sith_lord role required.
        </div>
      </div>
    )
  }

  const _input = {
    padding: '3px 6px', background: 'var(--bg-2)',
    border: '1px solid var(--border)', borderRadius: 2,
    color: 'var(--text-1)', fontSize: 10, fontFamily: 'var(--font-mono)',
    outline: 'none',
  }
  const _select = { ..._input, minWidth: 90 }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Filter bar */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px',
        background: 'var(--bg-1)', borderBottom: '1px solid var(--border)',
        fontFamily: 'var(--font-mono)', fontSize: 10, flexShrink: 0,
      }}>
        <span style={{ color: 'var(--text-3)', fontSize: 8 }}>TOOL</span>
        <select value={toolFilter} onChange={e => setToolFilter(e.target.value)} style={_select}>
          <option value="">all</option>
          {toolOptions.map(t => <option key={t} value={t}>{t}</option>)}
        </select>

        <span style={{ color: 'var(--text-3)', fontSize: 8 }}>USER</span>
        <select value={userFilter} onChange={e => setUserFilter(e.target.value)} style={_select}>
          <option value="">all</option>
          {userOptions.map(u => <option key={u} value={u}>{u}</option>)}
        </select>

        <span style={{ color: 'var(--text-3)', fontSize: 8 }}>RADIUS</span>
        <select value={radiusFilter} onChange={e => setRadiusFilter(e.target.value)} style={_select}>
          <option value="">all</option>
          <option value="node">node</option>
          <option value="service">service</option>
          <option value="cluster">cluster</option>
          <option value="fleet">fleet</option>
        </select>

        <span style={{ color: 'var(--text-3)', fontSize: 8 }}>SINCE</span>
        <input type="datetime-local" value={sinceFilter}
               onChange={e => setSinceFilter(e.target.value ? e.target.value + 'Z' : '')}
               style={_input} />

        <span style={{ color: 'var(--text-3)', fontSize: 8 }}>LIMIT</span>
        <select value={limit} onChange={e => setLimit(Number(e.target.value))} style={_select}>
          <option value={50}>50</option>
          <option value={100}>100</option>
          <option value={250}>250</option>
          <option value={500}>500</option>
        </select>

        <button onClick={fetchRows} style={{
          ..._input, cursor: 'pointer',
          background: 'var(--accent-dim)', color: 'var(--accent)',
        }}>↻ refresh</button>

        <div style={{ flex: 1 }} />
        <span style={{ color: 'var(--text-3)', fontSize: 9 }}>
          {loading ? 'loading…' : `${rows.length} / ${count} shown`}
          {error && <span style={{ color: 'var(--red)', marginLeft: 8 }}>{error}</span>}
        </span>
      </div>

      {/* Table */}
      <div style={{ flex: 1, overflow: 'auto', fontFamily: 'var(--font-mono)', fontSize: 10 }}>
        {rows.length === 0 && !loading && (
          <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-3)' }}>
            No audit events matching the filters.
          </div>
        )}
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead style={{ position: 'sticky', top: 0, background: 'var(--bg-1)', zIndex: 1 }}>
            <tr style={{ borderBottom: '1px solid var(--border)' }}>
              {['Time', 'Tool', 'Radius', 'Planned', 'Status', 'User', 'Duration', 'Host/Target'].map(h => (
                <th key={h} style={{
                  textAlign: 'left', padding: '6px 8px',
                  fontSize: 8, color: 'var(--text-3)', letterSpacing: 1,
                  fontWeight: 'normal', textTransform: 'uppercase',
                }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(r => {
              const args = r.args_redacted || {}
              const hostLike = args.host || args.vm_label || args.service_name || args.node || ''
              const isExpanded = expandedId === r.id
              return (
                <React.Fragment key={r.id}>
                  <tr
                    onClick={() => setExpandedId(isExpanded ? null : r.id)}
                    style={{
                      borderBottom: '1px solid var(--bg-3)', cursor: 'pointer',
                      background: isExpanded ? 'var(--bg-2)' : 'transparent',
                    }}
                    onMouseEnter={e => { if (!isExpanded) e.currentTarget.style.background = 'var(--bg-2)' }}
                    onMouseLeave={e => { if (!isExpanded) e.currentTarget.style.background = 'transparent' }}
                  >
                    <td style={{ padding: '5px 8px', color: 'var(--text-2)', whiteSpace: 'nowrap' }}>
                      {fmtTs(r.timestamp)}
                    </td>
                    <td style={{ padding: '5px 8px', color: 'var(--text-1)', fontWeight: 500 }}>
                      {r.tool_name}
                    </td>
                    <td style={{ padding: '5px 8px' }}>
                      <RadiusPill radius={r.blast_radius} />
                    </td>
                    <td style={{ padding: '5px 8px', color: r.was_planned ? 'var(--green)' : 'var(--text-3)' }}>
                      {r.was_planned ? 'yes' : 'no'}
                    </td>
                    <td style={{ padding: '5px 8px' }}>
                      <StatusPill status={r.result_status} />
                    </td>
                    <td style={{ padding: '5px 8px', color: 'var(--text-2)' }}>{r.owner_user || '—'}</td>
                    <td style={{ padding: '5px 8px', color: 'var(--text-3)', textAlign: 'right' }}>
                      {r.duration_ms}ms
                    </td>
                    <td style={{ padding: '5px 8px', color: 'var(--cyan)', maxWidth: 200,
                                 overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {hostLike || '—'}
                    </td>
                  </tr>
                  {isExpanded && (
                    <tr style={{ background: 'var(--bg-2)' }}>
                      <td colSpan={8} style={{ padding: '8px 20px' }}>
                        <div style={{ display: 'grid', gridTemplateColumns: '120px 1fr', gap: '4px 12px', fontSize: 10 }}>
                          <span style={{ color: 'var(--text-3)' }}>session_id</span>
                          <span style={{ color: 'var(--cyan)' }}>{r.session_id}</span>
                          <span style={{ color: 'var(--text-3)' }}>operation_id</span>
                          <span style={{ color: 'var(--cyan)' }}>{r.operation_id || '—'}</span>
                          <span style={{ color: 'var(--text-3)' }}>summary</span>
                          <span style={{ color: 'var(--text-1)' }}>{r.result_summary || '—'}</span>
                          <span style={{ color: 'var(--text-3)' }}>args (redacted)</span>
                          <pre style={{
                            margin: 0, color: 'var(--text-2)', fontSize: 9,
                            background: 'var(--bg-0)', padding: 6, borderRadius: 2,
                            border: '1px solid var(--border)', overflow: 'auto', maxHeight: 160,
                          }}>{JSON.stringify(args, null, 2)}</pre>
                        </div>
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
