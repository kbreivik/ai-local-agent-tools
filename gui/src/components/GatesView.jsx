/**
 * GatesView — aggregate safety-gate dashboard.
 *
 * Polls /api/gates/overview every 30s and renders each gate as its own
 * panel: plan confirmations by blast radius, escalations, drift (with
 * maintenance-suppressed count), hard caps, tool refusals and active
 * maintenance windows.
 */
import { useEffect, useState } from 'react'
import { authHeaders } from '../api'

const BASE = import.meta.env.VITE_API_BASE ?? ''

const RADIUS_COLORS = {
  none:    'var(--green)',
  node:    'var(--cyan)',
  service: 'var(--amber)',
  cluster: 'var(--red)',
  fleet:   '#a366ff',
  unknown: 'var(--text-3)',
}

export default function GatesView() {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  const [windowH, setWindowH] = useState(24)

  useEffect(() => {
    let cancelled = false
    const load = () => {
      fetch(`${BASE}/api/gates/overview?window_hours=${windowH}`, {
        headers: { ...authHeaders() },
        credentials: 'include',
      })
        .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
        .then(d => { if (!cancelled) { setData(d); setErr('') } })
        .catch(e => { if (!cancelled) setErr(e?.message || 'load failed') })
    }
    load()
    const id = setInterval(load, 30_000)
    return () => { cancelled = true; clearInterval(id) }
  }, [windowH])

  if (err && !data) {
    return (
      <div style={{ padding: 16, fontSize: 11, color: 'var(--red)', fontFamily: 'var(--font-mono)' }}>
        Gates unavailable: {err}
      </div>
    )
  }
  if (!data) {
    return <div style={{ padding: 16, fontSize: 11, color: 'var(--text-3)' }}>Loading gates…</div>
  }

  const planRows = data.plan_confirmations || []
  const esc      = data.escalations        || { total: 0, open: 0, acknowledged: 0 }
  const drift    = data.drift              || { total: 0, open: 0, acknowledged: 0, suppressed: 0 }
  const caps     = data.hard_caps          || {}
  const refusals = data.tool_refusals      || []
  const windows  = data.maintenance_active || []

  return (
    <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 16, overflowY: 'auto' }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <span style={{ fontSize: 10, color: 'var(--text-3)', fontFamily: 'var(--font-mono)', letterSpacing: 1 }}>WINDOW</span>
        {[6, 24, 72, 168].map(h => (
          <button key={h} onClick={() => setWindowH(h)}
            style={{
              fontSize: 9, padding: '3px 8px', borderRadius: 2,
              fontFamily: 'var(--font-mono)', cursor: 'pointer',
              background: windowH === h ? 'var(--accent-dim)' : 'var(--bg-2)',
              color:      windowH === h ? 'var(--accent)'     : 'var(--text-3)',
              border: `1px solid ${windowH === h ? 'var(--accent)' : 'var(--border)'}`,
            }}>
            {h < 24 ? `${h}h` : `${h / 24}d`}
          </button>
        ))}
        {err && (
          <span style={{ marginLeft: 'auto', fontSize: 9, color: 'var(--amber)', fontFamily: 'var(--font-mono)' }}>
            refresh error: {err}
          </span>
        )}
      </div>

      <Panel title="PLAN CONFIRMATIONS BY BLAST RADIUS">
        {planRows.length === 0 ? <Empty /> : planRows.map(row => {
          const radius = row.blast_radius || 'unknown'
          const color  = RADIUS_COLORS[radius] || RADIUS_COLORS.unknown
          return (
            <div key={radius} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '4px 0' }}>
              <span style={{
                fontSize: 9, padding: '1px 6px', borderRadius: 2,
                background: `${color}22`, color, border: `1px solid ${color}`,
                fontFamily: 'var(--font-mono)', letterSpacing: 1,
                minWidth: 72, textAlign: 'center',
              }}>{radius.toUpperCase()}</span>
              <Stat label="total"    value={row.total}    />
              <Stat label="approved" value={row.approved} color="var(--green)" />
              <Stat label="rejected" value={row.rejected} color="var(--red)"   />
              <Stat label="executed" value={row.executed} />
              <Stat label="failed"   value={row.failed}   color="var(--amber)" />
            </div>
          )
        })}
      </Panel>

      <Panel title="ESCALATIONS">
        <div style={{ display: 'flex', gap: 32, padding: '4px 0' }}>
          <Stat label="total"        value={esc.total} />
          <Stat label="open"         value={esc.open}         color="var(--amber)" />
          <Stat label="acknowledged" value={esc.acknowledged} color="var(--green)" />
        </div>
      </Panel>

      <Panel title="DRIFT EVENTS">
        <div style={{ display: 'flex', gap: 32, padding: '4px 0' }}>
          <Stat label="total"        value={drift.total} />
          <Stat label="open"         value={drift.open}         color="var(--amber)" />
          <Stat label="acknowledged" value={drift.acknowledged} color="var(--green)" />
          <Stat label="suppressed"   value={drift.suppressed}   color="var(--text-3)"
                tooltip="Auto-suppressed because the entity was in a maintenance window when drift fired" />
        </div>
      </Panel>

      <Panel title="AGENT HARD CAPS TRIGGERED">
        <div style={{ display: 'flex', gap: 32, padding: '4px 0' }}>
          <Stat label="wall clock"      value={caps.wall_clock}      color={caps.wall_clock      > 0 ? 'var(--amber)' : undefined} />
          <Stat label="token cap"       value={caps.token_cap}       color={caps.token_cap       > 0 ? 'var(--amber)' : undefined} />
          <Stat label="failure cap"     value={caps.failure_cap}     color={caps.failure_cap     > 0 ? 'var(--red)'   : undefined} />
          <Stat label="destructive cap" value={caps.destructive_cap} color={caps.destructive_cap > 0 ? 'var(--red)'   : undefined} />
        </div>
      </Panel>

      <Panel title="TOOL REFUSALS (TOP 20)">
        {refusals.length === 0 ? <Empty /> : (
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}>
            {refusals.map(r => (
              <div key={r.tool} style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0' }}>
                <span style={{ color: 'var(--text-2)' }}>{r.tool}</span>
                <span style={{ color: 'var(--red)' }}>{r.count}</span>
              </div>
            ))}
          </div>
        )}
      </Panel>

      <Panel title={`ACTIVE MAINTENANCE WINDOWS (${windows.length})`}>
        {windows.length === 0 ? <Empty /> : (
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}>
            {windows.map((m, i) => (
              <div key={m.entity_id || i} style={{ padding: '3px 0', borderBottom: '1px solid var(--bg-3)' }}>
                <div style={{ color: 'var(--text-1)' }}>{m.entity_id}</div>
                <div style={{ color: 'var(--text-3)', fontSize: 9 }}>
                  {m.starts_at ? new Date(m.starts_at).toLocaleString() : '—'}
                  {' → '}
                  {m.ends_at ? new Date(m.ends_at).toLocaleString() : '∞'}
                  {m.reason ? ` · ${m.reason}` : ''}
                  {m.created_by ? ` · by ${m.created_by}` : ''}
                </div>
              </div>
            ))}
          </div>
        )}
      </Panel>
    </div>
  )
}

function Panel({ title, children }) {
  return (
    <div style={{ border: '1px solid var(--border)', borderRadius: 2, background: 'var(--bg-1)' }}>
      <div style={{
        padding: '6px 10px', borderBottom: '1px solid var(--border)',
        fontSize: 9, color: 'var(--text-3)', fontFamily: 'var(--font-mono)', letterSpacing: 1.5,
      }}>
        {title}
      </div>
      <div style={{ padding: 10 }}>{children}</div>
    </div>
  )
}

function Stat({ label, value, color, tooltip }) {
  return (
    <div title={tooltip} style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 72 }}>
      <span style={{
        fontSize: 16, color: color || 'var(--text-1)',
        fontFamily: 'var(--font-mono)', lineHeight: 1,
      }}>
        {value ?? '—'}
      </span>
      <span style={{
        fontSize: 8, color: 'var(--text-3)',
        letterSpacing: 0.5, textTransform: 'uppercase',
      }}>
        {label}
      </span>
    </div>
  )
}

function Empty() {
  return <div style={{ fontSize: 10, color: 'var(--text-3)', padding: '4px 0' }}>none</div>
}
