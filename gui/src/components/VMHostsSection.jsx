/**
 * VMHostsSection — self-contained VM hosts dashboard section.
 * Fetches its own data, renders one card per vm_host connection.
 */
import { useState, useEffect, useCallback, useRef } from 'react'
import { authHeaders, dashboardAction } from '../api'
import { useDashboardData } from '../context/DashboardDataContext'

const BASE = import.meta.env.VITE_API_BASE ?? ''

const WATCHED = ['docker', 'elasticsearch', 'logstash', 'kibana', 'filebeat', 'kafka', 'nginx']

// Filter loopback from compact display
function _showIp(ip) {
  if (!ip) return ''
  if (ip === '127.0.0.1' || ip === 'localhost' || ip === '0.0.0.0') return ''
  return ip
}

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

function VMCard({ vm, onAction, onEntityDetail }) {
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState({})
  const [output, setOutput] = useState(null)
  const [historyData, setHistoryData] = useState(null)
  const [actionState, setActionState] = useState(null)  // null | {action, status, startedAt}
  const [rebootCountdown, setRebootCountdown] = useState(null)
  const [logsOpen, setLogsOpen] = useState(false)
  const [logLines, setLogLines]   = useState([])
  const [logService, setLogService] = useState('')
  const logEsRef = useRef(null)
  const logScrollRef = useRef(null)
  const [actionHistory, setActionHistory] = useState([])

  const id = vm.connection_id || vm.label
  const entityId = vm.label || vm.hostname || ''
  useEffect(() => {
    if (!entityId) return
    fetch(`${BASE}/api/dashboard/entity-history/${encodeURIComponent(entityId)}?hours=24`, { headers: authHeaders() })
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setHistoryData(d) })
      .catch(() => {})
  }, [entityId])

  useEffect(() => {
    if (!open || !id) return
    fetch(`${BASE}/api/dashboard/vm-hosts/${id}/actions?limit=5`, { headers: authHeaders() })
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d?.actions) setActionHistory(d.actions) })
      .catch(() => {})
  }, [open, id])

  useEffect(() => {
    if (logScrollRef.current) {
      logScrollRef.current.scrollTop = logScrollRef.current.scrollHeight
    }
  }, [logLines])

  useEffect(() => () => { logEsRef.current?.close() }, [])

  const openLogs = () => {
    if (logsOpen) {
      logEsRef.current?.close()
      logEsRef.current = null
      setLogLines([])
      setLogsOpen(false)
      return
    }
    setLogLines([])
    setLogsOpen(true)
    const token = localStorage.getItem('hp1_auth_token') || ''
    const svcParam = logService ? `&service=${encodeURIComponent(logService)}` : ''
    const url = `${BASE}/api/dashboard/vm-hosts/${id}/logs/stream?token=${encodeURIComponent(token)}${svcParam}`
    const es = new EventSource(url)
    es.onmessage = (e) => {
      try {
        const parsed = JSON.parse(e.data)
        const line = parsed.msg || e.data
        setLogLines(prev => [...prev, { msg: line, level: parsed.level || 'info' }].slice(-500))
      } catch {
        setLogLines(prev => [...prev, { msg: e.data, level: 'info' }].slice(-500))
      }
    }
    es.onerror = () => { es.close(); setLogsOpen(false) }
    logEsRef.current = es
  }

  // Listen for WebSocket vm_action events for this host
  useEffect(() => {
    const handler = (e) => {
      try {
        const msg = JSON.parse(e.detail || e.data || '{}')
        if (msg.type === 'vm_action' && (msg.host === (vm.label || vm.hostname))) {
          if (msg.status === 'started') {
            setActionState({ action: msg.action, status: 'started', startedAt: Date.now() })
            if (msg.action === 'reboot') {
              setRebootCountdown(90)
            }
          } else {
            setActionState(prev => prev ? { ...prev, status: msg.status } : null)
            if (msg.action !== 'reboot') {
              setTimeout(() => setActionState(null), 4000)
            }
          }
        }
      } catch (_) {}
    }
    window.addEventListener('ws:message', handler)
    return () => window.removeEventListener('ws:message', handler)
  }, [vm.label, vm.hostname])

  // Reboot countdown timer
  useEffect(() => {
    if (rebootCountdown === null) return
    if (rebootCountdown <= 0) {
      setRebootCountdown(null)
      setActionState(null)
      if (onAction) onAction()
      return
    }
    const t = setTimeout(() => setRebootCountdown(c => c !== null ? c - 1 : null), 1000)
    return () => clearTimeout(t)
  }, [rebootCountdown, onAction])

  const dot = vm.dot || 'grey'
  const dotColor = dot === 'green' ? 'var(--green)' : dot === 'amber' ? 'var(--amber)' : dot === 'red' ? 'var(--red)' : 'var(--text-3)'

  const act = async (key, path, confirmMsg) => {
    if (confirmMsg && !window.confirm(confirmMsg)) return
    setLoading(l => ({ ...l, [key]: true }))
    setOutput(null)
    try {
      const r = await dashboardAction(path)
      if (r && r.ok === false) {
        setOutput('Error: ' + (r.error || r.message || 'Action failed'))
      } else {
        setOutput(r.output || r.message || 'Done')
        if (onAction) setTimeout(onAction, 2000)
      }
    } catch (e) {
      setOutput('Error: ' + String(e))
    }
    setLoading(l => ({ ...l, [key]: false }))
  }

  return (
    <div style={{ border: '1px solid var(--border)', borderLeft: `3px solid ${dotColor}`, borderRadius: 2, background: 'var(--bg-2)', marginBottom: 4 }}>
      <div style={{ display: 'flex', alignItems: 'center', padding: '8px 10px', cursor: 'pointer', userSelect: 'none', gap: 8 }}
           onClick={() => setOpen(o => !o)}>
        <div style={{
          width: 8, height: 8, borderRadius: '50%', flexShrink: 0,
          background: actionState?.status === 'started' ? 'var(--amber)' : dotColor,
          animation: actionState?.status === 'started' ? 'pulse 1s infinite' : 'none',
        }} />
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-1)', flex: 1 }}>{vm.hostname || vm.label}</span>
        {_showIp(vm.host) && <span style={{ fontSize: 9, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>{vm.host}{vm.port && vm.port !== 22 ? `:${vm.port}` : ''}</span>}
        {vm.config?.is_jump_host && <span style={{ fontSize: 8, padding: '1px 5px', borderRadius: 2, background: 'rgba(204,136,0,0.15)', color: 'var(--amber)', border: '1px solid rgba(204,136,0,0.3)', fontFamily: 'var(--font-mono)', letterSpacing: '0.05em' }}>⇢ BASTION</span>}
        {vm.config?.shared_credentials && <span style={{ fontSize: 8, padding: '1px 5px', borderRadius: 2, background: 'rgba(0,200,238,0.1)', color: 'var(--cyan)', border: '1px solid rgba(0,200,238,0.25)', fontFamily: 'var(--font-mono)', letterSpacing: '0.05em' }}>⊕ SHARED</span>}
        {vm.jump_via_label && <span style={{ fontSize: 8, padding: '1px 5px', borderRadius: 2, background: 'var(--bg-3)', color: 'var(--text-3)', border: '1px solid var(--border)', fontFamily: 'var(--font-mono)' }}>via {vm.jump_via_label}</span>}
        {vm.uptime_fmt && <span style={{ fontSize: 9, color: 'var(--text-3)' }}>↑ {vm.uptime_fmt}</span>}
        {historyData && (historyData.change_count > 0 || historyData.event_count > 0) && (
          <span
            style={{
              fontSize: 8,
              fontFamily: 'var(--font-mono)',
              padding: '1px 5px',
              borderRadius: 2,
              background: historyData.has_critical ? 'rgba(204,40,40,0.2)' :
                          historyData.has_warning  ? 'rgba(204,136,0,0.15)' :
                          'var(--bg-3)',
              color: historyData.has_critical ? 'var(--red)' :
                     historyData.has_warning  ? 'var(--amber)' : 'var(--text-3)',
            }}
            title={`${historyData.change_count} changes, ${historyData.event_count} events (24h)`}
          >
            {historyData.change_count + historyData.event_count} changes
          </span>
        )}
        {vm.problem && <span style={{ fontSize: 9, color: dot === 'red' ? 'var(--red)' : 'var(--amber)', padding: '1px 5px', borderRadius: 2, background: dot === 'red' ? 'var(--red-dim)' : 'var(--amber-dim)' }}>⚠ {vm.problem}</span>}
        {actionState && (
          <span style={{
            fontSize: 8, padding: '1px 6px', borderRadius: 2, fontFamily: 'var(--font-mono)',
            letterSpacing: '0.06em',
            background: actionState.status === 'started' ? 'var(--amber-dim)' : actionState.status === 'ok' ? 'var(--green-dim)' : 'var(--red-dim)',
            color: actionState.status === 'started' ? 'var(--amber)' : actionState.status === 'ok' ? 'var(--green)' : 'var(--red)',
            border: `1px solid ${actionState.status === 'started' ? 'var(--amber)' : actionState.status === 'ok' ? 'var(--green)' : 'var(--red)'}`,
          }}>
            {actionState.action === 'reboot' && actionState.status === 'started'
              ? `↺ REBOOTING${rebootCountdown !== null ? ` ~${rebootCountdown}s` : '…'}`
              : actionState.action === 'update_packages' && actionState.status === 'started'
              ? '⬆ UPDATING…'
              : actionState.status === 'started'
              ? `↺ ${actionState.action.replace(/_/g, ' ').toUpperCase()}…`
              : actionState.status === 'ok' ? '✓ DONE' : '✕ FAILED'}
          </span>
        )}
        {entityId && onEntityDetail && (
          <>
            <button
              onClick={e => { e.stopPropagation(); onEntityDetail(entityId) }}
              title="Ask agent about this host"
              style={{
                background: 'none', border: 'none', cursor: 'pointer',
                fontSize: 10, padding: '1px 3px', color: 'var(--amber)',
                opacity: 0.65, lineHeight: 1, flexShrink: 0,
              }}
            >⌘</button>
            <button
              onClick={e => { e.stopPropagation(); onEntityDetail(entityId) }}
              title="Entity detail"
              style={{
                background: 'none', border: 'none', cursor: 'pointer',
                fontSize: 10, padding: '1px 3px', color: 'var(--cyan)',
                opacity: 0.65, lineHeight: 1, flexShrink: 0,
              }}
            >›</button>
          </>
        )}
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
          {vm.host && (
            <div style={{ fontSize: 9, color: 'var(--text-3)', marginBottom: 4, fontFamily: 'var(--font-mono)' }}>
              IP: <span style={{ color: 'var(--text-1)' }}>{vm.host}</span>
              {vm.port && vm.port !== 22 && <span> :{vm.port}</span>}
              {vm.hostname && vm.hostname !== vm.label && vm.hostname !== vm.host && (
                <span> · hostname: <span style={{ color: 'var(--text-1)' }}>{vm.hostname}</span></span>
              )}
            </div>
          )}
          {vm.config?.os_type && (
            <div style={{ fontSize: 9, color: 'var(--text-3)', marginBottom: 4, fontFamily: 'var(--font-mono)' }}>
              {vm.config.pkg_manager && `pkg: ${vm.config.pkg_manager}`}
              {vm.config.init_system && ` · init: ${vm.config.init_system}`}
            </div>
          )}
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
            <button onClick={() => act('status', `vm-hosts/${id}/exec`)} disabled={loading.status || (actionState?.status === 'started')}
              style={{ fontSize: 9, padding: '3px 8px', background: 'var(--bg-3)', border: '1px solid var(--border)', color: 'var(--text-2)', borderRadius: 2, cursor: 'pointer', fontFamily: 'var(--font-mono)' }}>
              {loading.status ? '…' : '⟳ Refresh'}
            </button>
            <button onClick={() => act('update', `vm-hosts/${id}/update`, `Run apt update + upgrade on ${vm.label}?`)} disabled={loading.update || (actionState?.status === 'started')}
              style={{ fontSize: 9, padding: '3px 8px', background: 'var(--amber-dim)', border: '1px solid var(--amber)', color: 'var(--amber)', borderRadius: 2, cursor: 'pointer', fontFamily: 'var(--font-mono)' }}>
              {loading.update ? '…' : '⬆ Update packages'}
            </button>
            <button onClick={() => act('reboot', `vm-hosts/${id}/reboot`, `Reboot ${vm.label}?`)} disabled={loading.reboot || (actionState?.status === 'started')}
              style={{ fontSize: 9, padding: '3px 8px', background: 'var(--red-dim)', border: '1px solid var(--red)', color: 'var(--red)', borderRadius: 2, cursor: 'pointer', fontFamily: 'var(--font-mono)' }}>
              {loading.reboot ? '…' : '↺ Reboot'}
            </button>
          </div>
          {Object.entries(vm.services || {}).filter(([, s]) => s === 'active' || s === 'failed').map(([name]) => (
            <button key={name} onClick={() => act(`svc_${name}`, `vm-hosts/${id}/service/${name}/restart`, `Restart ${name} on ${vm.label}?`)} disabled={loading[`svc_${name}`] || (actionState?.status === 'started')}
              style={{ fontSize: 9, padding: '2px 6px', marginTop: 4, marginRight: 4, background: 'var(--bg-3)', border: '1px solid var(--border)', color: 'var(--text-3)', borderRadius: 2, cursor: 'pointer', fontFamily: 'var(--font-mono)' }}>
              {loading[`svc_${name}`] ? '…' : `↺ ${name}`}
            </button>
          ))}
          {/* Log stream panel */}
          <div style={{ marginTop: 8 }}>
            <div style={{ display: 'flex', gap: 4, alignItems: 'center', marginBottom: 4 }}>
              <button
                onClick={openLogs}
                style={{
                  fontSize: 9, padding: '3px 8px', borderRadius: 2, cursor: 'pointer',
                  fontFamily: 'var(--font-mono)',
                  background: logsOpen ? 'var(--cyan)' : 'var(--bg-3)',
                  border: `1px solid ${logsOpen ? 'var(--cyan)' : 'var(--border)'}`,
                  color: logsOpen ? 'var(--bg-0)' : 'var(--text-3)',
                }}
              >
                {logsOpen ? '✕ Close Logs' : '◫ Live Logs'}
              </button>
              {!logsOpen && (
                <select
                  value={logService}
                  onChange={e => setLogService(e.target.value)}
                  style={{
                    fontSize: 9, padding: '2px 4px', fontFamily: 'var(--font-mono)',
                    background: 'var(--bg-3)', border: '1px solid var(--border)',
                    borderRadius: 2, color: 'var(--text-2)', cursor: 'pointer',
                  }}
                >
                  <option value="">all services</option>
                  {['docker', 'ssh', 'filebeat'].map(s => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                  {Object.keys(vm.services || {}).filter(n => vm.services[n] === 'active').map(n => (
                    <option key={n} value={n}>{n}</option>
                  ))}
                </select>
              )}
            </div>
            {logsOpen && (
              <div
                ref={logScrollRef}
                style={{
                  height: 180, overflowY: 'auto', background: 'var(--bg-0)',
                  border: '1px solid var(--border)', borderRadius: 2, padding: '6px 8px',
                  fontFamily: 'var(--font-mono)', fontSize: 9,
                }}
              >
                {logLines.length === 0 ? (
                  <span style={{ color: 'var(--text-3)' }}>Waiting for log lines…</span>
                ) : logLines.map((l, i) => (
                  <div key={i} style={{
                    color: l.level === 'error' || l.level === 'critical' ? 'var(--red)'
                         : l.level === 'warn' || l.level === 'warning' ? 'var(--amber)'
                         : 'var(--text-2)',
                    lineHeight: 1.5, wordBreak: 'break-all',
                  }}>
                    {l.msg}
                  </div>
                ))}
                <div style={{ color: 'var(--accent)', animation: 'pulse 1s infinite' }}>▋</div>
              </div>
            )}
          </div>
          {/* Recent action history */}
          {actionHistory.length > 0 && (
            <div style={{ marginTop: 8, borderTop: '1px solid var(--border)', paddingTop: 6 }}>
              <div style={{ fontSize: 8, color: 'var(--text-3)', fontFamily: 'var(--font-mono)', marginBottom: 4, letterSpacing: '0.06em' }}>RECENT ACTIONS</div>
              {actionHistory.map(a => (
                <div key={a.id} style={{ display: 'flex', gap: 6, fontSize: 9, fontFamily: 'var(--font-mono)', color: 'var(--text-3)', marginBottom: 2 }}>
                  <span style={{ color: a.status === 'ok' ? 'var(--green)' : a.status === 'error' ? 'var(--red)' : 'var(--amber)' }}>
                    {a.status === 'ok' ? '✓' : a.status === 'error' ? '✕' : '…'}
                  </span>
                  <span style={{ color: 'var(--text-2)' }}>{a.action.replace(/_/g, ' ')}</span>
                  <span>{a.owner_user}</span>
                  <span style={{ marginLeft: 'auto' }}>
                    {a.started_at ? new Date(a.started_at).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }) : ''}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function VMHostsSection({ showFilter, onEntityDetail }) {
  const { vmHostsData, summaryLoading, refreshSummary } = useDashboardData()
  const data = vmHostsData
  const loading = summaryLoading && !vmHostsData

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
      {visible.map(vm => <VMCard key={vm.label || vm.host} vm={vm} onAction={refreshSummary} onEntityDetail={onEntityDetail} />)}
    </div>
  )
}
