/**
 * SkillsTab — Skills view with subtabs:
 *   - Skills:      the existing SkillsPanel
 *   - Candidates:  auto-promoted vm_exec / tool patterns awaiting approval
 *   - Metrics:     execution observability + promoter activity (v2.34.2)
 */
import { useEffect, useState, useCallback } from 'react'
import { authHeaders } from '../api'
import SkillsPanel from './SkillsPanel'
import { Panel, Stat } from './SharedPanels'

const BASE = import.meta.env.VITE_API_BASE ?? ''

function CandidatesPanel() {
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(false)
  const [msg, setMsg] = useState('')
  const [expanded, setExpanded] = useState({})

  const load = useCallback(async () => {
    setLoading(true)
    setMsg('')
    try {
      const res = await fetch(`${BASE}/api/skills/candidates`, { headers: authHeaders() })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setRows(Array.isArray(data) ? data : (data.candidates ?? []))
    } catch (e) {
      setMsg(`Load failed: ${e.message}`)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const scanNow = async () => {
    setLoading(true)
    setMsg('')
    try {
      const res = await fetch(`${BASE}/api/skills/candidates/scan-now`, {
        method: 'POST',
        headers: { ...authHeaders(), 'Content-Type': 'application/json' },
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setMsg(`Scan done: ${data.candidates_detected_or_updated ?? 0} candidates detected/updated`)
      await load()
    } catch (e) {
      setMsg(`Scan failed: ${e.message}`)
    } finally {
      setLoading(false)
    }
  }

  const decide = async (cid, action) => {
    setMsg('')
    try {
      const res = await fetch(`${BASE}/api/skills/candidates/${cid}/${action}`, {
        method: 'POST',
        headers: { ...authHeaders(), 'Content-Type': 'application/json' },
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setMsg(`${action} ok${data.skill_id ? ` — skill_id=${data.skill_id}` : ''}`)
      await load()
    } catch (e) {
      setMsg(`${action} failed: ${e.message}`)
    }
  }

  const toggle = (id) => setExpanded(prev => ({ ...prev, [id]: !prev[id] }))

  return (
    <div style={{ padding: '0.75rem' }}>
      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.75rem', alignItems: 'center' }}>
        <button
          onClick={scanNow}
          disabled={loading}
          style={{
            background: 'var(--accent-dim)',
            color: 'var(--accent)',
            border: '1px solid var(--accent)',
            borderRadius: 'var(--radius-btn)',
            padding: '0.35rem 0.75rem',
            fontFamily: 'var(--font-mono)',
            cursor: loading ? 'wait' : 'pointer',
          }}
        >
          {loading ? 'Scanning…' : 'Scan now'}
        </button>
        <button
          onClick={load}
          disabled={loading}
          style={{
            background: 'transparent',
            color: 'var(--cyan)',
            border: '1px solid var(--cyan)',
            borderRadius: 'var(--radius-btn)',
            padding: '0.35rem 0.75rem',
            fontFamily: 'var(--font-mono)',
            cursor: loading ? 'wait' : 'pointer',
          }}
        >
          Refresh
        </button>
        {msg && (
          <span style={{ color: 'var(--amber)', fontFamily: 'var(--font-mono)', fontSize: '0.85rem' }}>
            {msg}
          </span>
        )}
      </div>

      {rows.length === 0 ? (
        <div style={{ color: 'var(--fg-dim, #888)', fontStyle: 'italic', padding: '0.5rem' }}>
          No pending candidates. Try "Scan now" to look for repeated patterns.
        </div>
      ) : (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-mono)', fontSize: '0.85rem' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--accent)' }}>
              <th style={{ textAlign: 'left', padding: '0.35rem' }}>Tool</th>
              <th style={{ textAlign: 'left', padding: '0.35rem' }}>Suggested name</th>
              <th style={{ textAlign: 'right', padding: '0.35rem' }}>Occurrences</th>
              <th style={{ textAlign: 'right', padding: '0.35rem' }}>Distinct tasks</th>
              <th style={{ textAlign: 'left', padding: '0.35rem' }}>Sample args</th>
              <th style={{ textAlign: 'center', padding: '0.35rem' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.id} style={{ borderBottom: '1px solid var(--bg-2)' }}>
                <td style={{ padding: '0.35rem' }}>{r.tool}</td>
                <td style={{ padding: '0.35rem', color: 'var(--cyan)' }}>{r.suggested_name}</td>
                <td style={{ padding: '0.35rem', textAlign: 'right' }}>{r.occurrences}</td>
                <td style={{ padding: '0.35rem', textAlign: 'right' }}>{r.distinct_tasks}</td>
                <td style={{ padding: '0.35rem', maxWidth: '320px' }}>
                  <button
                    onClick={() => toggle(r.id)}
                    style={{
                      background: 'transparent',
                      color: 'var(--amber)',
                      border: '1px solid var(--bg-2)',
                      borderRadius: 'var(--radius-btn)',
                      padding: '0.15rem 0.5rem',
                      fontFamily: 'var(--font-mono)',
                      fontSize: '0.8rem',
                      cursor: 'pointer',
                    }}
                  >
                    {expanded[r.id] ? 'hide' : 'show'}
                  </button>
                  {expanded[r.id] && (
                    <pre style={{
                      marginTop: '0.25rem',
                      padding: '0.35rem',
                      background: 'var(--bg-1)',
                      color: 'var(--fg, #ccc)',
                      fontSize: '0.75rem',
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-all',
                      maxHeight: '200px',
                      overflowY: 'auto',
                    }}>
                      {JSON.stringify(r.sample_args, null, 2)}
                    </pre>
                  )}
                </td>
                <td style={{ padding: '0.35rem', textAlign: 'center' }}>
                  <button
                    onClick={() => decide(r.id, 'approve')}
                    style={{
                      background: 'var(--green)',
                      color: 'var(--bg-0)',
                      border: 'none',
                      borderRadius: 'var(--radius-btn)',
                      padding: '0.25rem 0.65rem',
                      marginRight: '0.35rem',
                      fontFamily: 'var(--font-mono)',
                      cursor: 'pointer',
                    }}
                  >
                    Approve
                  </button>
                  <button
                    onClick={() => decide(r.id, 'reject')}
                    style={{
                      background: 'var(--red)',
                      color: 'var(--bg-0)',
                      border: 'none',
                      borderRadius: 'var(--radius-btn)',
                      padding: '0.25rem 0.65rem',
                      fontFamily: 'var(--font-mono)',
                      cursor: 'pointer',
                    }}
                  >
                    Reject
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function SkillMetrics() {
  const [data, setData] = useState(null)
  const [windowDays, setWindow] = useState(7)
  const [err, setErr] = useState('')

  useEffect(() => {
    let cancelled = false
    setErr('')
    fetch(`${BASE}/api/skills/metrics?window_days=${windowDays}`, { headers: authHeaders() })
      .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then(d => { if (!cancelled) setData(d) })
      .catch(e => { if (!cancelled) setErr(e.message) })
    return () => { cancelled = true }
  }, [windowDays])

  if (err) return <div style={{ fontSize: 10, color: 'var(--red)', padding: 12 }}>Metrics failed: {err}</div>
  if (!data) return <div style={{ fontSize: 10, color: 'var(--text-3)', padding: 12 }}>Loading metrics…</div>

  const last = data.promoter?.last_scan
  const promoterHealthy = (data.promoter?.scans || 0) > 0 &&
    !!last &&
    (Date.now() - new Date(last).getTime()) < 8 * 24 * 3600 * 1000

  const pipelineKeys = ['pending', 'approved', 'rejected', 'promoted']

  return (
    <div style={{ padding: 12, display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
        <span style={{ fontSize: 10, color: 'var(--text-3)' }}>WINDOW</span>
        {[7, 30, 90].map(d => (
          <button key={d} onClick={() => setWindow(d)}
            style={{
              fontSize: 9, padding: '3px 8px', borderRadius: 2,
              background: windowDays === d ? 'var(--accent-dim)' : 'var(--bg-2)',
              color:      windowDays === d ? 'var(--accent)'     : 'var(--text-3)',
              border: `1px solid ${windowDays === d ? 'var(--accent)' : 'var(--border)'}`,
              cursor: 'pointer', fontFamily: 'var(--font-mono)',
            }}>
            {d}d
          </button>
        ))}
      </div>

      <div style={{
        padding: 8, borderRadius: 2,
        background: promoterHealthy ? 'rgba(0,170,68,0.06)' : 'rgba(204,136,0,0.06)',
        border: `1px solid ${promoterHealthy ? 'var(--green)' : 'var(--amber)'}`,
      }}>
        <div style={{
          fontSize: 10, fontFamily: 'var(--font-mono)',
          color: promoterHealthy ? 'var(--green)' : 'var(--amber)',
        }}>
          {promoterHealthy ? 'AUTO-PROMOTER HEALTHY' : 'AUTO-PROMOTER STALE'}
        </div>
        <div style={{ fontSize: 9, color: 'var(--text-3)', marginTop: 3 }}>
          Scans: {data.promoter?.scans || 0} ·
          Last scan: {last ? new Date(last).toLocaleString() : 'never'} ·
          New candidates: {data.promoter?.total_new_candidates || 0}
        </div>
      </div>

      <Panel title="CANDIDATE PIPELINE">
        <div style={{ display: 'flex', gap: 20 }}>
          {pipelineKeys.map(s => (
            <Stat key={s} label={s.replace('_', ' ')} value={data.pipeline?.[s] ?? 0} />
          ))}
        </div>
      </Panel>

      <Panel title="SKILL EXECUTION ACTIVITY">
        {(data.per_skill || []).length === 0 ? (
          <div style={{ fontSize: 10, color: 'var(--text-3)' }}>No skills yet.</div>
        ) : (
          <table style={{ width: '100%', fontSize: 10, fontFamily: 'var(--font-mono)' }}>
            <thead>
              <tr style={{ color: 'var(--text-3)' }}>
                <th align="left">Skill</th>
                <th align="right">Runs</th>
                <th align="right">Success</th>
                <th align="right">Errors</th>
                <th align="right">Avg duration</th>
                <th align="right">Last run</th>
              </tr>
            </thead>
            <tbody>
              {data.per_skill.map(s => {
                const runs = Number(s.execution_count || 0)
                const dead = runs === 0
                const errs = Number(s.errors || 0)
                return (
                  <tr key={s.id || s.name} style={{ color: dead ? 'var(--text-3)' : 'var(--text-1)' }}>
                    <td>{s.name}{dead && ' · (unused)'}</td>
                    <td align="right">{runs}</td>
                    <td align="right" style={{ color: 'var(--green)' }}>{Number(s.successes || 0)}</td>
                    <td align="right" style={{ color: errs > 0 ? 'var(--red)' : undefined }}>{errs}</td>
                    <td align="right">{s.avg_duration_ms ? `${Math.round(Number(s.avg_duration_ms))} ms` : '—'}</td>
                    <td align="right" style={{ color: 'var(--text-3)' }}>
                      {s.last_run ? new Date(s.last_run).toLocaleString() : '—'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </Panel>
    </div>
  )
}

export default function SkillsTab() {
  const [sub, setSub] = useState('skills')

  const tabStyle = (active) => ({
    background: active ? 'var(--accent-dim)' : 'transparent',
    color: active ? 'var(--accent)' : 'var(--cyan)',
    border: '1px solid ' + (active ? 'var(--accent)' : 'var(--bg-2)'),
    borderRadius: 'var(--radius-btn)',
    padding: '0.35rem 0.85rem',
    fontFamily: 'var(--font-mono)',
    cursor: 'pointer',
    marginRight: '0.35rem',
  })

  let body = <SkillsPanel />
  if (sub === 'candidates') body = <CandidatesPanel />
  else if (sub === 'metrics') body = <SkillMetrics />

  return (
    <div>
      <div style={{ padding: '0.5rem 0.75rem 0', display: 'flex' }}>
        <button style={tabStyle(sub === 'skills')} onClick={() => setSub('skills')}>Skills</button>
        <button style={tabStyle(sub === 'candidates')} onClick={() => setSub('candidates')}>Candidates</button>
        <button style={tabStyle(sub === 'metrics')} onClick={() => setSub('metrics')}>Metrics</button>
      </div>
      {body}
    </div>
  )
}
