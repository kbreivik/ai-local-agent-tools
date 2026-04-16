/**
 * WindowsSection — self-contained Windows hosts dashboard section.
 * Fetches data from the windows collector, renders one card per host.
 */
import { useState, useEffect } from 'react'
import { authHeaders } from '../api'

const BASE = import.meta.env.VITE_API_BASE ?? ''

function MemBar({ usedBytes, totalBytes, pct }) {
  const color = pct > 90 ? 'var(--red)' : pct > 80 ? 'var(--amber)' : 'var(--green)'
  const usedGb  = usedBytes  ? (usedBytes  / 1e9).toFixed(1) : '?'
  const totalGb = totalBytes ? (totalBytes / 1e9).toFixed(1) : '?'
  return (
    <div style={{ marginBottom: 5 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9, color: 'var(--text-3)', marginBottom: 2 }}>
        <span>RAM</span>
        <span>{usedGb} / {totalGb} GB ({pct}%)</span>
      </div>
      <div style={{ height: 4, borderRadius: 2, background: 'var(--bg-3)', overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${Math.min(pct, 100)}%`, background: color, borderRadius: 2 }} />
      </div>
    </div>
  )
}

function DiskBar({ disk }) {
  const pct = disk.usage_pct || 0
  const color = pct > 90 ? 'var(--red)' : pct > 80 ? 'var(--amber)' : 'var(--green)'
  const used  = disk.used_bytes  ? (disk.used_bytes  / 1e9).toFixed(0) : '?'
  const total = disk.total_bytes ? (disk.total_bytes / 1e9).toFixed(0) : '?'
  return (
    <div style={{ marginBottom: 4 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9, color: 'var(--text-3)', marginBottom: 1 }}>
        <span style={{ color: 'var(--text-2)' }}>{disk.mountpoint}</span>
        <span>{used}/{total} GB ({pct}%)</span>
      </div>
      <div style={{ height: 3, borderRadius: 2, background: 'var(--bg-3)', overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${Math.min(pct, 100)}%`, background: color, borderRadius: 2 }} />
      </div>
    </div>
  )
}

function ServiceDots({ services }) {
  if (!services || Object.keys(services).length === 0) return null
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '3px 8px', marginTop: 4 }}>
      {Object.entries(services).map(([name, state]) => {
        const running = state.toLowerCase() === 'running'
        const color = running ? 'var(--green)' : state === 'missing' ? 'var(--text-3)' : 'var(--red)'
        return (
          <span key={name} style={{ fontSize: 9, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>
            <span style={{ color, marginRight: 2 }}>●</span>{name}
          </span>
        )
      })}
    </div>
  )
}

function WinCard({ host, onEntityDetail }) {
  const [open, setOpen] = useState(false)
  const dotColor = host.dot === 'green' ? 'var(--green)' : host.dot === 'amber' ? 'var(--amber)' : host.dot === 'red' ? 'var(--red)' : 'var(--text-3)'

  return (
    <div
      onClick={() => onEntityDetail?.(`windows:${host.label}`)}
      style={{
        background: 'var(--bg-2)', border: '1px solid var(--border)',
        borderLeft: `3px solid ${dotColor}`, borderRadius: 2, padding: '8px 10px',
        cursor: onEntityDetail ? 'pointer' : 'default',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
        <span style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: 11, color: 'var(--text-1)', flex: 1, letterSpacing: 0.5 }}>
          {host.hostname || host.label}
        </span>
        <span style={{ fontSize: 7, fontFamily: 'var(--font-mono)', padding: '1px 4px', background: 'var(--bg-3)', color: 'var(--text-3)', borderRadius: 2, letterSpacing: 1 }}>WINDOWS</span>
        <span style={{ width: 6, height: 6, borderRadius: '50%', background: dotColor, flexShrink: 0 }} />
        <button onClick={(e) => { e.stopPropagation(); setOpen(!open) }} style={{
          background: 'none', border: 'none', color: 'var(--text-3)', cursor: 'pointer', fontSize: 10, padding: 0,
        }}>{open ? '−' : '+'}</button>
      </div>

      {/* Compact summary */}
      <div style={{ display: 'flex', gap: 12, fontSize: 9, fontFamily: 'var(--font-mono)', color: 'var(--text-3)' }}>
        {host.uptime_fmt && <span>UP {host.uptime_fmt}</span>}
        {host.cpu_pct != null && host.cpu_pct >= 0 && <span>CPU {host.cpu_pct}%</span>}
        {host.mem_pct != null && <span>MEM {host.mem_pct}%</span>}
        {host.problem && <span style={{ color: 'var(--amber)' }}>{host.problem}</span>}
      </div>

      {open && (
        <div style={{ marginTop: 6, paddingTop: 6, borderTop: '1px solid var(--bg-3)' }}>
          {host.os && (
            <div style={{ fontSize: 9, color: 'var(--text-3)', fontFamily: 'var(--font-mono)', marginBottom: 4 }}>
              {host.os} {host.os_version || ''}
            </div>
          )}
          <MemBar usedBytes={host.mem_used_bytes} totalBytes={host.mem_total_bytes} pct={host.mem_pct || 0} />
          {(host.disks || []).map((d, i) => <DiskBar key={i} disk={d} />)}
          <ServiceDots services={host.services} />
        </div>
      )}
    </div>
  )
}

export default function WindowsSection({ showFilter, onEntityDetail }) {
  const [data, setData] = useState(null)

  useEffect(() => {
    const load = () => {
      fetch(`${BASE}/api/collectors/windows/data`, { headers: authHeaders() })
        .then(r => r.ok ? r.json() : null)
        .then(d => { if (d?.data) setData(d.data) })
        .catch(() => {})
    }
    load()
    const id = setInterval(load, 60000)
    return () => clearInterval(id)
  }, [])

  if (!data || !data.hosts || data.hosts.length === 0) {
    return (
      <div style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--text-3)', padding: 12 }}>
        {data?.health === 'unconfigured'
          ? 'No Windows connections configured — add one in Settings → Connections'
          : 'Loading Windows hosts…'}
      </div>
    )
  }

  const hosts = data.hosts.filter(h => {
    if (!showFilter || showFilter === 'ALL') return true
    if (showFilter === 'ERRORS') return h.dot === 'red'
    if (showFilter === 'DEGRADED') return h.dot === 'amber'
    return true
  })

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 8 }}>
      {hosts.map(h => <WinCard key={h.id || h.label} host={h} onEntityDetail={onEntityDetail} />)}
    </div>
  )
}
