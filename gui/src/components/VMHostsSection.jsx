/**
 * VMHostsSection — renders VM host cards from vm_hosts collector data.
 * Each VM gets an InfraCard-style card with memory bar, disk bars,
 * service dots, and action buttons.
 */
import { useState } from 'react'
import { authHeaders } from '../api'

const BASE = import.meta.env.VITE_API_BASE ?? ''

const KNOWN_SERVICES = ['docker', 'elasticsearch', 'logstash', 'kibana', 'filebeat', 'kafka']

function MemBar({ used, total, pct }) {
  const color = pct > 90 ? 'var(--red)' : pct > 80 ? 'var(--amber)' : 'var(--green)'
  const usedGb = (used / 1e9).toFixed(1)
  const totalGb = (total / 1e9).toFixed(1)
  return (
    <div style={{ marginBottom: 6 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between',
                    fontSize: 9, color: 'var(--text-3)', marginBottom: 2 }}>
        <span>RAM</span>
        <span>{usedGb} / {totalGb} GB ({pct}%)</span>
      </div>
      <div style={{ height: 4, borderRadius: 2, background: 'var(--bg-3)', overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${pct}%`, background: color, borderRadius: 2 }} />
      </div>
    </div>
  )
}

function DiskBar({ disk }) {
  const pct = disk.usage_pct
  const color = pct > 90 ? 'var(--red)' : pct > 80 ? 'var(--amber)' : 'var(--green)'
  const usedGb = (disk.used_bytes / 1e9).toFixed(1)
  const totalGb = (disk.total_bytes / 1e9).toFixed(1)
  return (
    <div style={{ marginBottom: 4 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between',
                    fontSize: 9, color: 'var(--text-3)', marginBottom: 1 }}>
        <span>{disk.mountpoint}</span>
        <span>{usedGb} / {totalGb} GB ({pct}%)</span>
      </div>
      <div style={{ height: 3, borderRadius: 2, background: 'var(--bg-3)', overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${pct}%`, background: color, borderRadius: 2 }} />
      </div>
    </div>
  )
}

function ServiceDots({ services }) {
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 10px', marginTop: 4 }}>
      {KNOWN_SERVICES.map(name => {
        const state = services?.[name]
        if (!state || state === 'inactive') return null
        const color = state === 'active' ? 'var(--green)'
                    : state === 'activating' ? 'var(--amber)'
                    : 'var(--red)'
        return (
          <span key={name} style={{ fontSize: 9, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>
            <span style={{ color, marginRight: 3 }}>●</span>{name}
          </span>
        )
      })}
    </div>
  )
}

function ActionBtn({ label, onClick, loading, confirm }) {
  const [confirming, setConfirming] = useState(false)
  const handleClick = () => {
    if (confirm && !confirming) { setConfirming(true); setTimeout(() => setConfirming(false), 3000); return }
    setConfirming(false)
    onClick()
  }
  return (
    <button
      onClick={handleClick}
      disabled={loading}
      style={{
        fontSize: 9, padding: '3px 8px', fontFamily: 'var(--font-mono)',
        background: confirming ? 'var(--red-dim)' : 'var(--bg-3)',
        color: confirming ? 'var(--red)' : 'var(--text-2)',
        border: `1px solid ${confirming ? 'var(--red)' : 'var(--border)'}`,
        borderRadius: 2, cursor: loading ? 'wait' : 'pointer',
        opacity: loading ? 0.5 : 1,
      }}
    >
      {confirming ? `Confirm ${label}?` : loading ? '...' : label}
    </button>
  )
}

function VMCard({ vm, onRefresh }) {
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState({})

  const doAction = (action, url, method = 'POST') => {
    setLoading(l => ({ ...l, [action]: true }))
    fetch(`${BASE}${url}`, { method, headers: { 'Content-Type': 'application/json', ...authHeaders() } })
      .then(r => r.json())
      .then(() => { if (onRefresh) onRefresh() })
      .catch(() => {})
      .finally(() => setLoading(l => ({ ...l, [action]: false })))
  }

  const dot = vm.dot || 'grey'
  const dotColor = dot === 'green' ? 'var(--green)' : dot === 'amber' ? 'var(--amber)' : dot === 'red' ? 'var(--red)' : 'var(--text-3)'
  const id = vm.connection_id || vm.label

  return (
    <div style={{
      background: 'var(--bg-2)', border: '1px solid var(--border)', borderRadius: 2,
      borderLeft: `3px solid ${dotColor}`, marginBottom: 4,
    }}>
      {/* Header */}
      <div onClick={() => setOpen(!open)} style={{
        display: 'flex', alignItems: 'center', gap: 8, padding: '6px 10px',
        cursor: 'pointer', userSelect: 'none',
      }}>
        <span style={{ width: 6, height: 6, borderRadius: '50%', background: dotColor, flexShrink: 0 }} />
        <span style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: 11, color: 'var(--text-1)' }}>
          {vm.hostname || vm.label}
        </span>
        <span style={{ fontSize: 9, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>
          {vm.host}
        </span>
        {vm.uptime_fmt && (
          <span style={{ fontSize: 8, padding: '1px 4px', background: 'var(--bg-3)',
                         color: 'var(--text-3)', borderRadius: 2, fontFamily: 'var(--font-mono)' }}>
            {vm.uptime_fmt}
          </span>
        )}
        {vm.problem && (
          <span style={{ fontSize: 8, padding: '1px 4px', background: 'var(--red-dim)',
                         color: 'var(--red)', borderRadius: 2, fontFamily: 'var(--font-mono)' }}>
            {vm.problem}
          </span>
        )}
        <span style={{ flex: 1 }} />
        <span style={{ fontSize: 9, color: 'var(--text-3)', transition: 'transform 0.1s',
                       transform: open ? 'rotate(90deg)' : 'none' }}>▶</span>
      </div>

      {/* Collapsed preview */}
      {!open && (
        <div style={{ padding: '0 10px 8px', fontSize: 10, fontFamily: 'var(--font-mono)' }}>
          {vm.mem_total_bytes > 0 && (
            <MemBar used={vm.mem_used_bytes} total={vm.mem_total_bytes} pct={vm.mem_pct} />
          )}
          {vm.disks?.length > 0 && <DiskBar disk={vm.disks[0]} />}
          <div style={{ display: 'flex', gap: 12, fontSize: 9, color: 'var(--text-3)', marginTop: 4 }}>
            <span>Load: {vm.load_1?.toFixed(2)} / {vm.load_5?.toFixed(2)} / {vm.load_15?.toFixed(2)}</span>
            {vm.os && <span>{vm.os}</span>}
          </div>
          <ServiceDots services={vm.services} />
        </div>
      )}

      {/* Expanded */}
      {open && (
        <div style={{ padding: '4px 10px 10px', fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--text-3)' }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2px 16px', marginBottom: 8 }}>
            <div>OS: <span style={{ color: 'var(--text-1)' }}>{vm.os || '—'}</span></div>
            <div>Kernel: <span style={{ color: 'var(--text-1)' }}>{vm.kernel || '—'}</span></div>
            <div>Docker: <span style={{ color: 'var(--text-1)' }}>{vm.docker_version || '—'}</span></div>
            <div>Uptime: <span style={{ color: 'var(--text-1)' }}>{vm.uptime_fmt || '—'}</span></div>
            <div>Load: <span style={{ color: 'var(--text-1)' }}>{vm.load_1?.toFixed(2)} / {vm.load_5?.toFixed(2)} / {vm.load_15?.toFixed(2)}</span></div>
          </div>

          {vm.mem_total_bytes > 0 && (
            <MemBar used={vm.mem_used_bytes} total={vm.mem_total_bytes} pct={vm.mem_pct} />
          )}

          {(vm.disks || []).map((d, i) => <DiskBar key={i} disk={d} />)}

          <div style={{ marginTop: 8, paddingTop: 6, borderTop: '1px solid var(--bg-3)' }}>
            <div style={{ fontSize: 9, color: 'var(--text-3)', marginBottom: 4 }}>Services</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 2 }}>
              {KNOWN_SERVICES.map(name => {
                const state = vm.services?.[name]
                if (!state) return null
                const color = state === 'active' ? 'var(--green)' : state === 'activating' ? 'var(--amber)' : 'var(--red)'
                return (
                  <div key={name} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span style={{ color }}>●</span>
                    <span style={{ flex: 1, color: 'var(--text-2)' }}>{name}: {state}</span>
                    {state !== 'active' && (
                      <ActionBtn label="↺" onClick={() => doAction(`restart-${name}`, `/api/dashboard/vm-hosts/${id}/service/${name}/restart`)}
                        loading={loading[`restart-${name}`]} />
                    )}
                  </div>
                )
              })}
            </div>
          </div>

          <div style={{ marginTop: 8, paddingTop: 6, borderTop: '1px solid var(--bg-3)',
                        display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            <ActionBtn label="↻ Refresh" onClick={onRefresh} loading={false} />
            <ActionBtn label="⬆ Run Updates" confirm onClick={() => doAction('update', `/api/dashboard/vm-hosts/${id}/update`)} loading={loading.update} />
            <ActionBtn label="↺ Reboot" confirm onClick={() => doAction('reboot', `/api/dashboard/vm-hosts/${id}/reboot`)} loading={loading.reboot} />
          </div>
        </div>
      )}
    </div>
  )
}

export default function VMHostsSection({ data, onAction, compareMode, compareSet, onCompareAdd, showFilter }) {
  if (!data) return (
    <div style={{ padding: 12, color: 'var(--text-3)', fontSize: 10, fontFamily: 'var(--font-mono)' }}>
      Loading VM hosts…
    </div>
  )

  const vms = data.vms || []
  if (vms.length === 0 && data.health === 'unconfigured') return (
    <div style={{ padding: 12, color: 'var(--text-3)', fontSize: 10, fontFamily: 'var(--font-mono)' }}>
      No VM host connections configured — add via Settings → Connections (platform: vm_host)
    </div>
  )

  return (
    <div>
      {vms.map(vm => (
        <VMCard key={vm.id || vm.label} vm={vm} onRefresh={onAction} />
      ))}
    </div>
  )
}
