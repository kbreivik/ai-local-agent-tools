/**
 * VMHostsSection — self-contained VM hosts dashboard section.
 * Fetches its own data, renders one card per vm_host connection.
 */
import { useState, useEffect, useCallback } from 'react'
import { authHeaders, dashboardAction } from '../api'

const BASE = import.meta.env.VITE_API_BASE ?? ''

const WATCHED = ['docker', 'elasticsearch', 'logstash', 'kibana', 'filebeat', 'kafka', 'nginx']

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
  const present = WATCHED.filter(name => services?.[name] && services[name] !== 'inactive')
  if (!present.length) return null
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '3px 8px', marginTop: 4 }}>
      {present.map(name => {
        const state = services[name]
        const color = state === 'active' ? 'var(--green)' : state === 'activating' ? 'var(--amber)' : 'var(--red)'
        return (
          <span key={name} style={{ fontSize: 9, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>
            <span style={{ color, marginRight: 2 }}>●</span>{name}
          </span>
        )
      })}
    </div>
  )
}

function VMCard({ vm, onAction }) {
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState({})
  const [output, setOutput] = useState(null)

  const dot = vm.dot || 'grey'
  const dotColor = dot === 'green' ? 'var(--green)' : dot === 'amber' ? 'var(--amber)' : dot === 'red' ? 'var(--red)' : 'var(--text-3)'
  const id = vm.connection_id || vm.label

  const act = async (key, path, confirmMsg) => {
    if (confirmMsg && !window.confirm(confirmMsg)) return
    setLoading(l => ({ ...l, [key]: true }))
    setOutput(null)
    try {
      const r = await dashboardAction(path)
      setOutput(r.output || r.message || 'Done')
      if (onAction) setTimeout(onAction, 2000)
    } catch (e) {
      setOutput('Error: ' + String(e))
    }
    setLoading(l => ({ ...l, [key]: false }))
  }

  return (
    <div style={{ border: '1px solid var(--border)', borderLeft: `3px solid ${dotColor}`, borderRadius: 2, background: 'var(--bg-2)', marginBottom: 4 }}>
      <div style={{ display: 'flex', alignItems: 'center', padding: '8px 10px', cursor: 'pointer', userSelect: 'none', gap: 8 }}
           onClick={() => setOpen(o => !o)}>
        <div style={{ width: 8, height: 8, borderRadius: '50%', background: dotColor, flexShrink: 0 }} />
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-1)', flex: 1 }}>{vm.hostname || vm.label}</span>
        <span style={{ fontSize: 9, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>{vm.host}</span>
        {vm.uptime_fmt && <span style={{ fontSize: 9, color: 'var(--text-3)' }}>↑ {vm.uptime_fmt}</span>}
        {vm.problem && <span style={{ fontSize: 9, color: dot === 'red' ? 'var(--red)' : 'var(--amber)', padding: '1px 5px', borderRadius: 2, background: dot === 'red' ? 'var(--red-dim)' : 'var(--amber-dim)' }}>⚠ {vm.problem}</span>}
        <span style={{ fontSize: 8, color: 'var(--text-3)', transform: open ? 'rotate(90deg)' : 'none', display: 'inline-block', transition: 'transform 0.1s' }}>▶</span>
      </div>

      {!open && !vm.problem && (
        <div style={{ padding: '0 10px 8px', display: 'flex', gap: 12, fontSize: 9, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>
          {vm.os && <span>{vm.os}</span>}
          {vm.mem_pct !== undefined && <span>RAM {vm.mem_pct}%</span>}
          {vm.load_1 !== undefined && <span>load {vm.load_1?.toFixed(2)}</span>}
          <ServiceDots services={vm.services} />
        </div>
      )}

      {open && (
        <div style={{ padding: '0 10px 10px' }} onClick={e => e.stopPropagation()}>
          <div style={{ fontSize: 9, color: 'var(--text-3)', marginBottom: 6, fontFamily: 'var(--font-mono)' }}>
            {vm.os && <span>{vm.os} · </span>}
            {vm.kernel && <span>kernel {vm.kernel}</span>}
          </div>
          {vm.load_1 !== undefined && (
            <div style={{ fontSize: 9, color: 'var(--text-3)', marginBottom: 6 }}>
              Load avg: <span style={{ color: vm.load_1 > 4 ? 'var(--red)' : 'var(--text-1)' }}>{vm.load_1?.toFixed(2)}</span>
              {' / '}{vm.load_5?.toFixed(2)}{' / '}{vm.load_15?.toFixed(2)} (1m / 5m / 15m)
            </div>
          )}
          {vm.mem_total_bytes > 0 && <MemBar usedBytes={vm.mem_used_bytes} totalBytes={vm.mem_total_bytes} pct={vm.mem_pct} />}
          {(vm.disks || []).filter(d => d.mountpoint === '/' || d.total_bytes > 1e9).map(d => <DiskBar key={d.mountpoint} disk={d} />)}
          <ServiceDots services={vm.services} />
          {vm.docker_version && vm.docker_version !== 'not installed' && (
            <div style={{ fontSize: 9, color: 'var(--text-3)', marginTop: 4, fontFamily: 'var(--font-mono)' }}>{vm.docker_version}</div>
          )}
          {output && (
            <div style={{ marginTop: 8, padding: '6px 8px', background: 'var(--bg-3)', borderRadius: 2, fontSize: 9, fontFamily: 'var(--font-mono)', color: 'var(--text-2)', maxHeight: 120, overflowY: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
              {output}
            </div>
          )}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 8 }}>
            <button onClick={() => act('status', `vm-hosts/${id}/exec`)} disabled={loading.status}
              style={{ fontSize: 9, padding: '3px 8px', background: 'var(--bg-3)', border: '1px solid var(--border)', color: 'var(--text-2)', borderRadius: 2, cursor: 'pointer', fontFamily: 'var(--font-mono)' }}>
              {loading.status ? '…' : '⟳ Refresh'}
            </button>
            <button onClick={() => act('update', `vm-hosts/${id}/update`, `Run apt update + upgrade on ${vm.label}?`)} disabled={loading.update}
              style={{ fontSize: 9, padding: '3px 8px', background: 'var(--amber-dim)', border: '1px solid var(--amber)', color: 'var(--amber)', borderRadius: 2, cursor: 'pointer', fontFamily: 'var(--font-mono)' }}>
              {loading.update ? '…' : '⬆ Update packages'}
            </button>
            <button onClick={() => act('reboot', `vm-hosts/${id}/reboot`, `Reboot ${vm.label}?`)} disabled={loading.reboot}
              style={{ fontSize: 9, padding: '3px 8px', background: 'var(--red-dim)', border: '1px solid var(--red)', color: 'var(--red)', borderRadius: 2, cursor: 'pointer', fontFamily: 'var(--font-mono)' }}>
              {loading.reboot ? '…' : '↺ Reboot'}
            </button>
          </div>
          {Object.entries(vm.services || {}).filter(([, s]) => s === 'active' || s === 'failed').map(([name]) => (
            <button key={name} onClick={() => act(`svc_${name}`, `vm-hosts/${id}/service/${name}/restart`, `Restart ${name} on ${vm.label}?`)} disabled={loading[`svc_${name}`]}
              style={{ fontSize: 9, padding: '2px 6px', marginTop: 4, marginRight: 4, background: 'var(--bg-3)', border: '1px solid var(--border)', color: 'var(--text-3)', borderRadius: 2, cursor: 'pointer', fontFamily: 'var(--font-mono)' }}>
              {loading[`svc_${name}`] ? '…' : `↺ ${name}`}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export default function VMHostsSection({ showFilter }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(() => {
    fetch(`${BASE}/api/dashboard/vm-hosts`, { headers: { ...authHeaders() } })
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setData(d); setLoading(false) })
      .catch(() => setLoading(false))
  }, [])

  useEffect(() => { load(); const id = setInterval(load, 60000); return () => clearInterval(id) }, [load])

  if (loading) return <div style={{ padding: 12, color: 'var(--text-3)', fontSize: 10, fontFamily: 'var(--font-mono)' }}>Loading VM hosts…</div>

  const vms = data?.vms || []
  if (!vms.length) return <div style={{ padding: 12, color: 'var(--text-3)', fontSize: 10, fontFamily: 'var(--font-mono)' }}>No VM hosts configured — add vm_host connections in Settings → Connections</div>

  const visible = vms.filter(vm => {
    if (!showFilter || showFilter === 'ALL') return true
    if (showFilter === 'ERRORS') return vm.dot === 'red'
    if (showFilter === 'DEGRADED') return vm.dot === 'amber'
    return true
  })

  const ok = vms.filter(v => v.dot !== 'red').length
  const issues = vms.filter(v => v.dot === 'red').length

  return (
    <div>
      <div style={{ display: 'flex', gap: 12, marginBottom: 8, fontSize: 9, fontFamily: 'var(--font-mono)', color: 'var(--text-3)' }}>
        <span><span style={{ color: 'var(--green)' }}>{ok}</span> ok</span>
        {issues > 0 && <span><span style={{ color: 'var(--red)' }}>{issues}</span> issues</span>}
        <span>{vms.length} total</span>
      </div>
      {visible.map(vm => <VMCard key={vm.label || vm.host} vm={vm} onAction={load} />)}
    </div>
  )
}
