/**
 * DiscoveredView — shows devices found from passive harvest (Proxmox / UniFi / Swarm)
 * that are not yet linked to a connection. Allows manual test with credential profile
 * and one-click connection creation.
 */
import { useState, useEffect } from 'react'
import { authHeaders } from '../api'

const BASE = import.meta.env.VITE_API_BASE ?? ''

const SOURCE_COLORS = {
  proxmox: { bg: 'rgba(0,200,238,0.1)', color: 'var(--cyan)',  label: 'PROXMOX' },
  unifi:   { bg: 'rgba(0,170,68,0.1)',  color: 'var(--green)', label: 'UNIFI' },
  swarm:   { bg: 'rgba(204,136,0,0.1)', color: 'var(--amber)', label: 'SWARM' },
  manual:  { bg: 'var(--bg-3)',         color: 'var(--text-3)', label: 'MANUAL' },
}

const STATUS_DOT = {
  running: 'var(--green)',
  active:  'var(--green)',
  unknown: 'var(--text-3)',
  down:    'var(--red)',
  offline: 'var(--red)',
}

function SourceBadge({ source }) {
  const s = SOURCE_COLORS[source] || SOURCE_COLORS.manual
  return (
    <span style={{ fontSize: 8, padding: '1px 5px', borderRadius: 2, fontFamily: 'var(--font-mono)',
      background: s.bg, color: s.color, letterSpacing: 0.5, flexShrink: 0 }}>
      {s.label}
    </span>
  )
}

function DeviceRow({ device, profiles, onCreateConnection }) {
  const [selectedProfileId, setSelectedProfileId] = useState('')
  const [testResult, setTestResult] = useState(null)  // {ok, message, duration_ms}
  const [testing, setTesting] = useState(false)

  const discoverableProfiles = profiles.filter(p => p.discoverable && p.name !== '__no_credential__')

  const handleTest = async () => {
    if (!selectedProfileId) return
    setTesting(true)
    setTestResult(null)
    try {
      const r = await fetch(`${BASE}/api/discovery/test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          host:       device.host,
          port:       device.meta?.port || (device.platform_guess === 'windows' ? 5985 : 22),
          platform:   device.platform_guess || 'vm_host',
          profile_id: selectedProfileId,
        }),
      })
      const d = await r.json()
      setTestResult(d)
    } catch (e) {
      setTestResult({ ok: false, message: e.message })
    } finally {
      setTesting(false)
    }
  }

  const statusColor = STATUS_DOT[device.status?.toLowerCase()] || 'var(--text-3)'

  return (
    <div style={{
      padding: '8px 10px', borderBottom: '1px solid var(--bg-3)',
      opacity: device.linked ? 0.5 : 1,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        {/* Status dot */}
        <span style={{ width: 6, height: 6, borderRadius: '50%', background: statusColor,
          display: 'inline-block', flexShrink: 0 }} />
        {/* Source badge */}
        <SourceBadge source={device.source} />
        {/* Name / host */}
        <span style={{ fontSize: 11, color: 'var(--text-1)', fontWeight: 500, fontFamily: 'var(--font-mono)' }}>
          {device.name !== device.host ? device.name : ''}
        </span>
        <span style={{ fontSize: 10, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>
          {device.host}
        </span>
        {/* Platform guess */}
        <span style={{ fontSize: 8, padding: '1px 5px', borderRadius: 2,
          background: 'var(--bg-3)', color: 'var(--text-3)' }}>
          {device.platform_guess || 'unknown'}
        </span>
        {/* Source label */}
        {device.source_label && device.source_label !== 'Docker Swarm' && (
          <span style={{ fontSize: 8, color: 'var(--text-3)' }}>via {device.source_label}</span>
        )}
        {/* Linked badge */}
        {device.linked ? (
          <span style={{ fontSize: 8, padding: '1px 5px', borderRadius: 2, marginLeft: 'auto',
            background: 'rgba(0,170,68,0.1)', color: 'var(--green)' }}>
            ✓ Linked
          </span>
        ) : (
          <span style={{ fontSize: 8, color: 'var(--text-3)', marginLeft: 'auto' }}>
            Not linked
          </span>
        )}
      </div>

      {/* Test row — only for unlinked devices */}
      {!device.linked && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 6, flexWrap: 'wrap' }}>
          <select
            value={selectedProfileId}
            onChange={e => { setSelectedProfileId(e.target.value); setTestResult(null) }}
            style={{ fontSize: 9, background: 'var(--bg-2)', border: '1px solid var(--border)',
              borderRadius: 2, padding: '2px 6px', color: 'var(--text-2)', fontFamily: 'var(--font-mono)' }}>
            <option value="">— select profile to test —</option>
            {discoverableProfiles.map(p => (
              <option key={p.id} value={p.id}>#{p.seq_id} {p.name} ({p.auth_type})</option>
            ))}
            {discoverableProfiles.length === 0 && (
              <option disabled>No discoverable profiles — enable "Available for discovery" on a profile</option>
            )}
          </select>

          <button
            onClick={handleTest}
            disabled={testing || !selectedProfileId}
            style={{ fontSize: 9, padding: '2px 10px', borderRadius: 2, cursor: 'pointer',
              background: 'var(--bg-3)', border: '1px solid var(--border)', color: 'var(--text-2)',
              opacity: (!selectedProfileId || testing) ? 0.5 : 1 }}>
            {testing ? '…' : 'Test'}
          </button>

          {/* Test result */}
          {testResult && (
            <span style={{ fontSize: 9, color: testResult.ok ? 'var(--green)' : 'var(--red)' }}>
              {testResult.ok ? '✓' : '✕'} {testResult.message}
              {testResult.duration_ms != null && ` (${testResult.duration_ms}ms)`}
            </span>
          )}

          {/* Create connection button — only on success */}
          {testResult?.ok && (
            <button
              onClick={() => onCreateConnection(device, selectedProfileId)}
              style={{ fontSize: 9, padding: '2px 10px', borderRadius: 2, cursor: 'pointer',
                background: 'var(--green)', border: 'none', color: '#fff', fontWeight: 600 }}>
              + Create connection
            </button>
          )}
        </div>
      )}
    </div>
  )
}

export default function DiscoveredView() {
  const [devices, setDevices] = useState([])
  const [loading, setLoading] = useState(false)
  const [harvesting, setHarvesting] = useState(false)
  const [profiles, setProfiles] = useState([])
  const [filterSource, setFilterSource] = useState('all')
  const [filterLinked, setFilterLinked] = useState('unlinked')
  const [harvestCounts, setHarvestCounts] = useState(null)
  const [createModal, setCreateModal] = useState(null)  // {device, profileId}
  const [createForm, setCreateForm] = useState({ label: '', platform: '', role: '' })
  const [creating, setCreating] = useState(false)
  const [createResult, setCreateResult] = useState(null)
  const [manualIp, setManualIp] = useState('')
  const [manualIps, setManualIps] = useState([])

  useEffect(() => {
    fetchDevices()
    fetchProfiles()
  }, [])

  const fetchDevices = async () => {
    setLoading(true)
    try {
      const r = await fetch(`${BASE}/api/discovery/devices`, { headers: authHeaders() })
      const d = await r.json()
      setDevices(d.devices || [])
    } catch (e) { /* silent */ }
    setLoading(false)
  }

  const fetchProfiles = async () => {
    try {
      const r = await fetch(`${BASE}/api/credential-profiles`, { headers: authHeaders() })
      const d = await r.json()
      setProfiles(d.profiles || [])
    } catch (e) { /* silent */ }
  }

  const harvest = async () => {
    setHarvesting(true)
    setHarvestCounts(null)
    try {
      const r = await fetch(`${BASE}/api/discovery/harvest`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ manual_ips: manualIps }),
      })
      const d = await r.json()
      setDevices(d.devices || [])
      setHarvestCounts(d.counts || null)
      setManualIps([])
      setManualIp('')
    } catch (e) { /* silent */ }
    setHarvesting(false)
  }

  const addManualIp = () => {
    const ip = manualIp.trim()
    if (!ip || manualIps.includes(ip)) return
    setManualIps(ips => [...ips, ip])
    setManualIp('')
  }

  const createConnection = async () => {
    if (!createModal) return
    setCreating(true)
    setCreateResult(null)
    try {
      const r = await fetch(`${BASE}/api/discovery/link`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          host:       createModal.device.host,
          port:       createModal.device.meta?.port || 22,
          platform:   createForm.platform || createModal.device.platform_guess || 'vm_host',
          label:      createForm.label || createModal.device.name || createModal.device.host,
          profile_id: createModal.profileId,
          role:       createForm.role || '',
        }),
      })
      const d = await r.json()
      setCreateResult(d)
      if (d.status === 'ok') {
        setTimeout(() => { setCreateModal(null); fetchDevices() }, 1200)
      }
    } catch (e) {
      setCreateResult({ status: 'error', message: e.message })
    }
    setCreating(false)
  }

  // Filtered devices
  const filtered = devices.filter(d => {
    if (filterSource !== 'all' && d.source !== filterSource) return false
    if (filterLinked === 'unlinked' && d.linked) return false
    return true
  })

  const sources = ['all', ...new Set(devices.map(d => d.source).filter(Boolean))]

  return (
    <div style={{ padding: 16, maxWidth: 900 }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <div>
          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-1)',
            fontFamily: 'var(--font-mono)', letterSpacing: 1 }}>DISCOVERED DEVICES</div>
          <div style={{ fontSize: 10, color: 'var(--text-3)', marginTop: 2 }}>
            Passive harvest from Proxmox, UniFi, Swarm — cross-referenced vs existing connections
          </div>
        </div>
        <button onClick={harvest} disabled={harvesting}
          style={{ fontSize: 10, padding: '5px 14px', borderRadius: 2, cursor: 'pointer',
            background: 'var(--accent)', border: 'none', color: '#fff', fontWeight: 600,
            opacity: harvesting ? 0.6 : 1, fontFamily: 'var(--font-mono)' }}>
          {harvesting ? '◌ Harvesting…' : '⟳ HARVEST NOW'}
        </button>
      </div>

      {/* Manual IP input */}
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 12,
        padding: '8px 10px', border: '1px solid var(--border)', borderRadius: 2,
        background: 'var(--bg-2)' }}>
        <span style={{ fontSize: 9, color: 'var(--text-3)', flexShrink: 0, fontFamily: 'var(--font-mono)' }}>
          + MANUAL IP
        </span>
        <input
          value={manualIp}
          onChange={e => setManualIp(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && addManualIp()}
          placeholder="192.168.1.5"
          style={{ flex: 1, background: 'var(--bg-3)', border: '1px solid var(--border)',
            borderRadius: 2, padding: '3px 8px', fontSize: 9, color: 'var(--text-1)',
            fontFamily: 'var(--font-mono)', outline: 'none' }}
        />
        <button onClick={addManualIp} style={{ fontSize: 9, padding: '2px 8px', borderRadius: 2,
          background: 'var(--bg-3)', border: '1px solid var(--border)', color: 'var(--text-2)', cursor: 'pointer' }}>
          Add
        </button>
        {manualIps.map(ip => (
          <span key={ip} style={{ fontSize: 9, padding: '2px 6px', borderRadius: 2,
            background: 'rgba(0,200,238,0.1)', color: 'var(--cyan)', display: 'flex', gap: 4 }}>
            {ip}
            <button onClick={() => setManualIps(ips => ips.filter(i => i !== ip))}
              style={{ background: 'none', border: 'none', color: 'var(--red)', cursor: 'pointer', padding: 0, fontSize: 9 }}>✕</button>
          </span>
        ))}
      </div>

      {/* Harvest counts */}
      {harvestCounts && (
        <div style={{ display: 'flex', gap: 12, marginBottom: 10, fontSize: 10,
          fontFamily: 'var(--font-mono)', color: 'var(--text-3)' }}>
          {Object.entries(harvestCounts).map(([k, v]) => (
            <span key={k}>{k}: <span style={{ color: 'var(--text-1)' }}>{v}</span></span>
          ))}
        </div>
      )}

      {/* Filters */}
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 10 }}>
        <span style={{ fontSize: 9, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>SOURCE:</span>
        {sources.map(s => (
          <button key={s} onClick={() => setFilterSource(s)}
            style={{ fontSize: 9, padding: '2px 8px', borderRadius: 2, cursor: 'pointer', fontFamily: 'var(--font-mono)',
              background: filterSource === s ? 'var(--accent-dim)' : 'var(--bg-3)',
              border: `1px solid ${filterSource === s ? 'var(--accent)' : 'var(--border)'}`,
              color: filterSource === s ? 'var(--accent)' : 'var(--text-3)' }}>
            {s.toUpperCase()}
          </button>
        ))}
        <span style={{ fontSize: 9, color: 'var(--text-3)', marginLeft: 8, fontFamily: 'var(--font-mono)' }}>SHOW:</span>
        {[['unlinked','Unlinked only'],['all','All devices']].map(([v, l]) => (
          <button key={v} onClick={() => setFilterLinked(v)}
            style={{ fontSize: 9, padding: '2px 8px', borderRadius: 2, cursor: 'pointer',
              background: filterLinked === v ? 'var(--accent-dim)' : 'var(--bg-3)',
              border: `1px solid ${filterLinked === v ? 'var(--accent)' : 'var(--border)'}`,
              color: filterLinked === v ? 'var(--accent)' : 'var(--text-3)' }}>
            {l}
          </button>
        ))}
        <span style={{ marginLeft: 'auto', fontSize: 9, color: 'var(--text-3)' }}>
          {filtered.length} device{filtered.length !== 1 ? 's' : ''}
        </span>
      </div>

      {/* Device list */}
      <div style={{ border: '1px solid var(--border)', borderRadius: 2, background: 'var(--bg-1)' }}>
        {loading && <div style={{ fontSize: 10, color: 'var(--text-3)', padding: 12 }}>Loading…</div>}
        {!loading && filtered.length === 0 && (
          <div style={{ fontSize: 10, color: 'var(--text-3)', padding: 16, textAlign: 'center' }}>
            {devices.length === 0
              ? 'No harvest data — click HARVEST NOW to scan your infrastructure'
              : 'No devices match the current filter'}
          </div>
        )}
        {filtered.map((device, i) => (
          <DeviceRow
            key={`${device.source}-${device.host}-${i}`}
            device={device}
            profiles={profiles}
            onCreateConnection={(dev, profileId) => {
              setCreateModal({ device: dev, profileId })
              setCreateForm({
                label:    dev.name || dev.host,
                platform: dev.platform_guess || 'vm_host',
                role:     '',
              })
              setCreateResult(null)
            }}
          />
        ))}
      </div>

      {/* Create connection modal */}
      {createModal && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 200,
          display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div style={{ background: 'var(--bg-1)', border: '1px solid var(--border)', borderRadius: 4,
            width: 380, padding: 16 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-1)',
              fontFamily: 'var(--font-mono)', marginBottom: 10 }}>
              CREATE CONNECTION
            </div>
            <div style={{ marginBottom: 8 }}>
              <label style={{ fontSize: 9, color: 'var(--text-3)', display: 'block', marginBottom: 3 }}>Label</label>
              <input value={createForm.label} onChange={e => setCreateForm(f => ({ ...f, label: e.target.value }))}
                style={{ width: '100%', background: 'var(--bg-2)', border: '1px solid var(--border)',
                  borderRadius: 2, padding: '4px 8px', fontSize: 10, color: 'var(--text-1)', outline: 'none' }} />
            </div>
            <div style={{ marginBottom: 8 }}>
              <label style={{ fontSize: 9, color: 'var(--text-3)', display: 'block', marginBottom: 3 }}>Platform</label>
              <select value={createForm.platform} onChange={e => setCreateForm(f => ({ ...f, platform: e.target.value }))}
                style={{ width: '100%', background: 'var(--bg-2)', border: '1px solid var(--border)',
                  borderRadius: 2, padding: '4px 8px', fontSize: 10, color: 'var(--text-1)' }}>
                <option value="vm_host">vm_host (SSH)</option>
                <option value="windows">windows (WinRM)</option>
                <option value="docker_host">docker_host</option>
              </select>
            </div>
            <div style={{ marginBottom: 10 }}>
              <label style={{ fontSize: 9, color: 'var(--text-3)', display: 'block', marginBottom: 3 }}>Role</label>
              <select value={createForm.role} onChange={e => setCreateForm(f => ({ ...f, role: e.target.value }))}
                style={{ width: '100%', background: 'var(--bg-2)', border: '1px solid var(--border)',
                  borderRadius: 2, padding: '4px 8px', fontSize: 10, color: 'var(--text-1)' }}>
                <option value="">— general —</option>
                <option value="swarm_manager">Swarm Manager</option>
                <option value="swarm_worker">Swarm Worker</option>
                <option value="storage">Storage</option>
                <option value="monitoring">Monitoring</option>
              </select>
            </div>
            <div style={{ fontSize: 9, color: 'var(--cyan)', marginBottom: 10, fontFamily: 'var(--font-mono)' }}>
              Host: {createModal.device.host} · Profile: {profiles.find(p => p.id === createModal.profileId)?.name || '?'}
            </div>
            {createResult && (
              <div style={{ fontSize: 9, color: createResult.status === 'ok' ? 'var(--green)' : 'var(--red)',
                marginBottom: 8 }}>
                {createResult.status === 'ok' ? '✓ Connection created' : `✕ ${createResult.message}`}
              </div>
            )}
            <div style={{ display: 'flex', gap: 8 }}>
              <button onClick={createConnection} disabled={creating}
                style={{ fontSize: 10, padding: '4px 14px', borderRadius: 2, cursor: 'pointer',
                  background: 'var(--accent)', border: 'none', color: '#fff', fontWeight: 600,
                  opacity: creating ? 0.6 : 1 }}>
                {creating ? 'Creating…' : 'Create Connection'}
              </button>
              <button onClick={() => setCreateModal(null)}
                style={{ fontSize: 10, padding: '4px 12px', borderRadius: 2, cursor: 'pointer',
                  background: 'var(--bg-3)', border: '1px solid var(--border)', color: 'var(--text-2)' }}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
