/**
 * OptionsModal — 4-tab settings modal.
 * Reads/writes via OptionsContext → localStorage + POST /api/settings.
 */
import { useState, useEffect } from 'react'
import { Settings, X } from 'lucide-react'
import { useOptions } from '../context/OptionsContext'
import { authHeaders } from '../api'

const BASE = import.meta.env.VITE_API_BASE ?? ''

export const TABS = ['General', 'Infrastructure', 'AI Services', 'Connections', 'Display']

// ── Shared form helpers ────────────────────────────────────────────────────────

function Field({ label, hint, children }) {
  return (
    <div className="mb-4">
      <label className="block text-xs font-semibold text-[color:var(--text-1)] mb-1">{label}</label>
      {hint && <p className="text-xs text-[color:var(--text-3)] mb-1">{hint}</p>}
      {children}
    </div>
  )
}

function TextInput({ value, onChange, placeholder, type = 'text' }) {
  return (
    <input
      type={type}
      value={value ?? ''}
      onChange={e => onChange(e.target.value)}
      placeholder={placeholder}
      autoComplete="off"
      className="w-full bg-[color:var(--bg-2)] border border-[color:var(--border)] rounded px-3 py-1.5 text-xs text-[color:var(--text-1)] focus:outline-none focus:border-blue-500"
    />
  )
}

function Textarea({ value, onChange, placeholder, rows = 3 }) {
  return (
    <textarea
      value={value ?? ''}
      onChange={e => onChange(e.target.value)}
      placeholder={placeholder}
      rows={rows}
      className="w-full bg-[color:var(--bg-2)] border border-[color:var(--border)] rounded px-3 py-1.5 text-xs text-[color:var(--text-1)] resize-none focus:outline-none focus:border-blue-500"
    />
  )
}

function Radio({ name, value, current, onChange, label }) {
  return (
    <label className="flex items-center gap-2 cursor-pointer text-xs text-[color:var(--text-1)] hover:text-[color:var(--text-1)]">
      <input
        type="radio"
        name={name}
        value={value}
        checked={current === value}
        onChange={() => onChange(value)}
        className="accent-blue-500"
      />
      {label}
    </label>
  )
}

function Toggle({ value, onChange, label }) {
  return (
    <label className="flex items-center gap-3 cursor-pointer">
      <div
        onClick={() => onChange(!value)}
        className={`w-9 h-5 rounded-full transition-colors flex items-center px-0.5 cursor-pointer ${
          value ? 'bg-blue-600' : 'bg-[color:var(--bg-3)]'
        }`}
      >
        <div className={`w-4 h-4 rounded-full bg-white shadow transition-transform ${value ? 'translate-x-4' : ''}`} />
      </div>
      <span className="text-xs text-[color:var(--text-1)]">{label}</span>
    </label>
  )
}

function Select({ value, onChange, options }) {
  return (
    <select
      value={value}
      onChange={e => onChange(e.target.value)}
      className="w-full bg-[color:var(--bg-2)] border border-[color:var(--border)] rounded px-3 py-1.5 text-xs text-[color:var(--text-1)] focus:outline-none focus:border-blue-500"
    >
      {options.map(([v, label]) => (
        <option key={v} value={v}>{label}</option>
      ))}
    </select>
  )
}

// ── Tab: General ──────────────────────────────────────────────────────────────

function GeneralTab({ draft, update }) {
  return (
    <div>
      <Field label="Theme">
        <div className="flex flex-col gap-2">
          {[['dark', 'Dark'], ['light', 'Light'], ['system', 'System']].map(([v, l]) => (
            <Radio key={v} name="theme" value={v} current={draft.theme} onChange={v => update('theme', v)} label={l} />
          ))}
        </div>
      </Field>

      <Field label="Dashboard Refresh Interval">
        <Select
          value={draft.dashboardRefreshInterval}
          onChange={v => update('dashboardRefreshInterval', Number(v))}
          options={[
            ['15000', '15 seconds'],
            ['30000', '30 seconds'],
            ['60000', '60 seconds'],
          ]}
        />
      </Field>
    </div>
  )
}

// ── Tab: Infrastructure ───────────────────────────────────────────────────────

function SectionHeader({ label }) {
  return (
    <h3 className="text-xs font-bold text-[color:var(--text-2)] uppercase tracking-wider mb-3 border-b border-[color:var(--border)] pb-1">
      {label}
    </h3>
  )
}

function InfrastructureTab({ draft, update }) {
  return (
    <div>
      {/* Docker / Swarm */}
      <div className="mb-5">
        <SectionHeader label="Docker / Swarm" />
        <Field label="Docker Host" hint="TCP endpoint of the swarm manager — gives full swarm API access">
          <TextInput value={draft.dockerHost} onChange={v => update('dockerHost', v)} placeholder="tcp://192.168.199.21:2375" />
        </Field>
        <Field label="Swarm Manager IPs" hint="Comma-separated manager IPs">
          <TextInput value={draft.swarmManagerIPs} onChange={v => update('swarmManagerIPs', v)} placeholder="192.168.199.21:2375" />
        </Field>
        <Field label="Swarm Worker IPs">
          <TextInput value={draft.swarmWorkerIPs} onChange={v => update('swarmWorkerIPs', v)} placeholder="192.168.199.31,192.168.199.32,192.168.199.33" />
        </Field>
        <Field label="GHCR Token" hint="GitHub PAT with read:packages scope — enables version checking">
          <TextInput type="password" value={draft.ghcrToken} onChange={v => update('ghcrToken', v)} placeholder="ghp_..." />
        </Field>
        <Field label="Auto-Update" hint="Check GHCR every 5 min and auto-pull + restart when a newer version is available">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={draft.autoUpdate === true || draft.autoUpdate === 'true'}
              onChange={e => update('autoUpdate', e.target.checked)}
              className="accent-blue-500"
            />
            <span className="text-xs text-gray-300">Enable automatic updates</span>
          </label>
          <UpdateStatus />
        </Field>
        <Field label="Agent Docker Host">
          <TextInput value={draft.agentDockerHost} onChange={v => update('agentDockerHost', v)} placeholder="unix:///var/run/docker.sock" />
        </Field>
      </div>

      {/* Messaging / Observability */}
      <div className="mb-5">
        <SectionHeader label="Messaging / Observability" />
        <Field label="Kafka Bootstrap Servers" hint="Comma-separated host:port pairs">
          <TextInput value={draft.kafkaBootstrapServers} onChange={v => update('kafkaBootstrapServers', v)} placeholder="192.168.199.31:9092,192.168.199.32:9093" />
        </Field>
        <Field label="Elasticsearch URL">
          <TextInput value={draft.elasticsearchUrl} onChange={v => update('elasticsearchUrl', v)} placeholder="http://192.168.199.40:9200" />
        </Field>
        <Field label="Kibana URL">
          <TextInput value={draft.kibanaUrl} onChange={v => update('kibanaUrl', v)} placeholder="http://192.168.199.40:5601" />
        </Field>
        <Field label="MuninnDB URL">
          <TextInput value={draft.muninndbUrl} onChange={v => update('muninndbUrl', v)} placeholder="http://muninndb:9475" />
        </Field>
      </div>

      {/* Service connections note */}
      <div className="text-[11px] p-3 rounded-md" style={{ background: 'var(--accent-dim)', color: 'var(--accent)' }}>
        Proxmox, FortiGate, TrueNAS, and other service connections are managed in the <strong>Connections</strong> tab.
      </div>
    </div>
  )
}

// ── Tab: AI Services ──────────────────────────────────────────────────────────

const MODEL_DEFAULTS = {
  claude:  'claude-sonnet-4-6',
  openai:  'gpt-4o',
  grok:    'grok-2-latest',
}

function AIServicesTab({ draft, update }) {
  const [localTest, setLocalTest]  = useState(null)
  const [extTest,   setExtTest]    = useState(null)
  const [testing,   setTesting]    = useState(false)

  const testLocal = async () => {
    setTesting('local')
    setLocalTest(null)
    try {
      const t0 = Date.now()
      const r  = await fetch(`${BASE}/api/agent/models`)
      const ms = Date.now() - t0
      if (r.ok) {
        const d = await r.json()
        setLocalTest({ ok: true, ms, info: d.models?.[0]?.id ?? 'connected' })
      } else {
        setLocalTest({ ok: false, msg: `HTTP ${r.status}` })
      }
    } catch (e) {
      setLocalTest({ ok: false, msg: e.message })
    } finally {
      setTesting(false)
    }
  }

  const testExternal = async () => {
    setTesting('ext')
    setExtTest(null)
    try {
      // Basic connectivity check — just verify key is non-empty
      if (!draft.externalApiKey?.trim()) {
        setExtTest({ ok: false, msg: 'No API key set' })
        setTesting(false)
        return
      }
      setExtTest({ ok: true, msg: 'API key present — connectivity not verified in browser' })
    } finally {
      setTesting(false)
    }
  }

  const onProviderChange = (v) => {
    update('externalProvider', v)
    if (!draft.externalModel) {
      update('externalModel', MODEL_DEFAULTS[v] ?? '')
    }
  }

  return (
    <div>
      {/* Local AI */}
      <div className="mb-5">
        <h3 className="text-xs font-bold text-[color:var(--text-2)] uppercase tracking-wider mb-3 border-b border-[color:var(--border)] pb-1">
          Local AI
        </h3>
        <Field label="LM Studio URL">
          <TextInput value={draft.lmStudioUrl} onChange={v => update('lmStudioUrl', v)} placeholder="http://localhost:1234/v1" />
        </Field>
        <Field label="LM Studio API Key">
          <TextInput type="password" value={draft.lmStudioApiKey} onChange={v => update('lmStudioApiKey', v)} placeholder="lm-studio" />
        </Field>
        <Field label="Model Name">
          <TextInput value={draft.modelName} onChange={v => update('modelName', v)} placeholder="lmstudio-community/qwen3-coder-30b-a3b-instruct" />
        </Field>
        <button
          onClick={testLocal}
          disabled={testing === 'local'}
          className="px-3 py-1.5 bg-[color:var(--bg-3)] hover:bg-[color:var(--bg-3)] text-xs text-[color:var(--text-1)] rounded transition-colors disabled:opacity-50"
        >
          {testing === 'local' ? 'Testing…' : 'Test Connection'}
        </button>
        {localTest && (
          <p className={`text-xs mt-1 ${localTest.ok ? 'text-green-400' : 'text-red-400'}`}>
            {localTest.ok ? `OK (${localTest.ms}ms) — ${localTest.info}` : localTest.msg}
          </p>
        )}
      </div>

      {/* External AI */}
      <div className="mb-5">
        <h3 className="text-xs font-bold text-[color:var(--text-2)] uppercase tracking-wider mb-3 border-b border-[color:var(--border)] pb-1">
          External AI (Escalation)
        </h3>
        <Field label="Provider">
          <div className="flex gap-4">
            {['claude', 'openai', 'grok'].map(p => (
              <Radio key={p} name="extProvider" value={p} current={draft.externalProvider} onChange={onProviderChange}
                label={p.charAt(0).toUpperCase() + p.slice(1)} />
            ))}
          </div>
        </Field>
        <Field label="API Key">
          <TextInput type="password" value={draft.externalApiKey} onChange={v => update('externalApiKey', v)} placeholder="sk-…" />
        </Field>
        <Field label="Model">
          <TextInput value={draft.externalModel} onChange={v => update('externalModel', v)}
            placeholder={MODEL_DEFAULTS[draft.externalProvider] ?? ''} />
        </Field>
        <button
          onClick={testExternal}
          disabled={testing === 'ext'}
          className="px-3 py-1.5 bg-[color:var(--bg-3)] hover:bg-[color:var(--bg-3)] text-xs text-[color:var(--text-1)] rounded transition-colors disabled:opacity-50"
        >
          {testing === 'ext' ? 'Testing…' : 'Test Connection'}
        </button>
        {extTest && (
          <p className={`text-xs mt-1 ${extTest.ok ? 'text-green-400' : 'text-red-400'}`}>
            {extTest.ok ? extTest.msg : extTest.msg}
          </p>
        )}
      </div>

      {/* Escalation Policy */}
      <div>
        <h3 className="text-xs font-bold text-[color:var(--text-2)] uppercase tracking-wider mb-3 border-b border-[color:var(--border)] pb-1">
          Escalation Policy
        </h3>
        <Field label="Auto-escalate on">
          <div className="flex gap-4">
            {[['failure', 'Failure'], ['degraded', 'Degraded'], ['both', 'Both']].map(([v, l]) => (
              <Radio key={v} name="autoEscalate" value={v} current={draft.autoEscalate} onChange={v => update('autoEscalate', v)} label={l} />
            ))}
          </div>
        </Field>
        <Field label="">
          <Toggle value={draft.requireConfirmation} onChange={v => update('requireConfirmation', v)}
            label="Require confirmation before external AI call" />
        </Field>
      </div>
    </div>
  )
}

// ── Tab: Display ──────────────────────────────────────────────────────────────

const CARD_DEFAULTS = { cardMinHeight: 70, cardMaxHeight: 200, cardMinWidth: 300, cardMaxWidth: null }

function DimRow({ label, fieldKey, value, defaultVal, min, max, invalid, update }) {
  const inputStyle = {
    width: 72, background: '#1e293b',
    border: `1px solid ${invalid ? '#ef4444' : '#475569'}`,
    borderRadius: 4, padding: '3px 8px',
    fontSize: 11, color: '#e2e8f0', outline: 'none',
  }
  const isEmpty = value === null || value === undefined || value === ''
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
      <span style={{ fontSize: 11, color: '#94a3b8', width: 82, flexShrink: 0 }}>{label}</span>
      <input
        type="number" step={10} min={min} max={max}
        value={isEmpty ? '' : value}
        placeholder={defaultVal === null ? 'no limit' : String(defaultVal)}
        onChange={e => update(fieldKey, e.target.value === '' ? null : Number(e.target.value))}
        style={inputStyle}
      />
      <span style={{ fontSize: 10, color: '#475569' }}>px</span>
      <button
        onClick={() => update(fieldKey, defaultVal)}
        style={{ fontSize: 12, color: '#64748b', background: 'none', border: 'none', cursor: 'pointer', padding: 0, lineHeight: 1 }}
        title="Reset to default"
      >↺</button>
    </div>
  )
}

function DisplayTab({ draft, update }) {
  const minH = draft.cardMinHeight ?? 70
  const maxH = draft.cardMaxHeight ?? 200
  const minW = draft.cardMinWidth  ?? 300
  const maxW = draft.cardMaxWidth

  const heightInvalid = minH != null && maxH != null && Number(minH) >= Number(maxH)
  const widthInvalid  = minW != null && maxW != null && Number(minW) >= Number(maxW)

  return (
    <div>
      {/* Dashboard Cards */}
      <div className="mb-5">
        <h3 className="text-xs font-bold text-[color:var(--text-2)] uppercase tracking-wider mb-3 border-b border-[color:var(--border)] pb-1">
          Dashboard Cards
        </h3>
        <DimRow label="Min Height" fieldKey="cardMinHeight" value={draft.cardMinHeight} defaultVal={70}  min={50}  max={200}  invalid={heightInvalid} update={update} />
        <DimRow label="Max Height" fieldKey="cardMaxHeight" value={draft.cardMaxHeight} defaultVal={200} min={100} max={600}  invalid={heightInvalid} update={update} />
        <DimRow label="Min Width"  fieldKey="cardMinWidth"  value={draft.cardMinWidth}  defaultVal={300} min={200} max={800}  invalid={widthInvalid}  update={update} />
        <DimRow label="Max Width"  fieldKey="cardMaxWidth"  value={draft.cardMaxWidth}  defaultVal={null} min={200} max={1200} invalid={widthInvalid} update={update} />
        {(heightInvalid || widthInvalid) && (
          <p style={{ color: '#ef4444', fontSize: 11, marginBottom: 8 }}>Min must be less than Max</p>
        )}

        {/* Live preview card */}
        <p style={{ fontSize: 11, color: '#64748b', marginBottom: 6, marginTop: 12 }}>Preview</p>
        <div style={{
          minHeight:   minH  ? `${minH}px`  : undefined,
          maxHeight:   maxH  ? `${maxH}px`  : undefined,
          minWidth:    minW  ? `${minW}px`  : undefined,
          maxWidth:    maxW  ? `${maxW}px`  : undefined,
          border: '1px solid #e5e7eb', borderRadius: 6,
          padding: 8, fontSize: 12, color: '#6b7280',
          overflow: 'auto', resize: 'both',
          background: '#fff',
        }}>
          Preview card — resize to test<br />
          <span style={{ fontSize: 10, color: '#9ca3af' }}>
            min {minH}×{minW}px / max {maxH ?? '∞'}×{maxW ?? '∞'}px
          </span>
        </div>
      </div>

      {/* Node card size */}
      <Field label="Node Card Size (Cluster view)">
        <div className="flex gap-4">
          {[['small', 'Small'], ['medium', 'Medium'], ['large', 'Large']].map(([v, l]) => (
            <Radio key={v} name="nodeCardSize" value={v} current={draft.nodeCardSize} onChange={v => update('nodeCardSize', v)} label={l} />
          ))}
        </div>
      </Field>
      <Field label="">
        <Toggle value={draft.showVersionBadges} onChange={v => update('showVersionBadges', v)} label="Show version badges" />
      </Field>
      <Field label="">
        <Toggle value={draft.showMemoryEngrams} onChange={v => update('showMemoryEngrams', v)} label="Show memory engram count in header" />
      </Field>
      <Field label="Commands panel default">
        <div className="flex gap-4">
          {[['hidden', 'Hidden'], ['visible', 'Visible']].map(([v, l]) => (
            <Radio key={v} name="commandsPanelDefault" value={v} current={draft.commandsPanelDefault}
              onChange={v => update('commandsPanelDefault', v)} label={l} />
          ))}
        </div>
      </Field>
    </div>
  )
}

// ── Connections tab ──────────────────────────────────────────────────────────

const PLATFORMS = [
  'proxmox', 'fortigate', 'fortiswitch', 'truenas', 'pbs', 'unifi',
  'wazuh', 'grafana', 'portainer', 'kibana', 'netbox', 'synology',
  'security_onion', 'syncthing', 'caddy', 'traefik', 'opnsense',
  'adguard', 'bookstack', 'trilium', 'nginx', 'pihole', 'technitium',
  'cisco', 'juniper',
]

const PLATFORM_AUTH = {
  proxmox:         { auth_type: 'token',  defaultPort: 8006, fields: [{ key: 'token_id', label: 'Token ID', placeholder: 'user@realm!tokenname' }, { key: 'secret', label: 'Token Secret', type: 'password' }] },
  fortigate:       { auth_type: 'apikey', fields: [{ key: 'api_key', label: 'API Key', type: 'password' }] },
  fortiswitch:     { auth_type: 'ssh', defaultPort: 22, fields: [{ key: 'username', label: 'Username', placeholder: 'admin' }, { key: 'password', label: 'Password', type: 'password' }, { key: 'device_type', label: 'Device Type', placeholder: 'fortinet' }] },
  truenas:         { auth_type: 'apikey', fields: [{ key: 'api_key', label: 'API Key', type: 'password' }] },
  pbs:             { auth_type: 'token',  defaultPort: 8007, fields: [{ key: 'token_id', label: 'Token ID', placeholder: 'user@realm!tokenname' }, { key: 'secret', label: 'Token Secret', type: 'password' }] },
  unifi:           { auth_type: 'basic',  fields: [{ key: 'username', label: 'Username', placeholder: 'admin' }, { key: 'password', label: 'Password', type: 'password' }] },
  wazuh:           { auth_type: 'basic',  fields: [{ key: 'username', label: 'Username' }, { key: 'password', label: 'Password', type: 'password' }] },
  grafana:         { auth_type: 'apikey', fields: [{ key: 'api_key', label: 'API Key', type: 'password' }] },
  portainer:       { auth_type: 'apikey', fields: [{ key: 'api_key', label: 'API Key', type: 'password' }] },
  kibana:          { auth_type: 'basic',  fields: [{ key: 'username', label: 'Username' }, { key: 'password', label: 'Password', type: 'password' }] },
  netbox:          { auth_type: 'apikey', fields: [{ key: 'api_key', label: 'API Token', type: 'password' }] },
  synology:        { auth_type: 'basic',  fields: [{ key: 'username', label: 'Username', placeholder: 'admin' }, { key: 'password', label: 'Password', type: 'password' }] },
  security_onion:  { auth_type: 'basic',  fields: [{ key: 'username', label: 'Username' }, { key: 'password', label: 'Password', type: 'password' }] },
  syncthing:       { auth_type: 'apikey', fields: [{ key: 'api_key', label: 'API Key', type: 'password' }] },
  caddy:           { auth_type: 'basic',  fields: [{ key: 'username', label: 'Username', placeholder: 'admin' }, { key: 'password', label: 'Password', type: 'password' }] },
  traefik:         { auth_type: 'basic',  fields: [{ key: 'username', label: 'Username', placeholder: 'admin' }, { key: 'password', label: 'Password', type: 'password' }] },
  opnsense:        { auth_type: 'token',  fields: [{ key: 'token_id', label: 'API Key' }, { key: 'secret', label: 'API Secret', type: 'password' }] },
  adguard:         { auth_type: 'basic',  fields: [{ key: 'username', label: 'Username', placeholder: 'admin' }, { key: 'password', label: 'Password', type: 'password' }] },
  bookstack:       { auth_type: 'token',  fields: [{ key: 'token_id', label: 'Token ID' }, { key: 'secret', label: 'Token Secret', type: 'password' }] },
  trilium:         { auth_type: 'apikey', fields: [{ key: 'api_key', label: 'ETAPI Token', type: 'password' }] },
  nginx:           { auth_type: 'basic',  fields: [{ key: 'username', label: 'Username', placeholder: 'admin' }, { key: 'password', label: 'Password', type: 'password' }] },
  pihole:          { auth_type: 'apikey', fields: [{ key: 'api_key', label: 'API Key / Password', type: 'password' }] },
  technitium:      { auth_type: 'apikey', fields: [{ key: 'api_key', label: 'API Key', type: 'password' }] },
  cisco:           { auth_type: 'ssh', defaultPort: 22, fields: [{ key: 'username', label: 'Username', placeholder: 'admin' }, { key: 'password', label: 'Password', type: 'password' }, { key: 'device_type', label: 'Device Type', placeholder: 'cisco_ios' }] },
  juniper:         { auth_type: 'ssh', defaultPort: 22, fields: [{ key: 'username', label: 'Username', placeholder: 'admin' }, { key: 'password', label: 'Password', type: 'password' }, { key: 'device_type', label: 'Device Type', placeholder: 'juniper_junos' }] },
}
const _FL = (/** @type {string} */ txt) => <label className="text-[10px] block mb-0.5" style={{ color: 'var(--text-3)' }}>{txt}</label>

function ConnectionsTab() {
  const [conns, setConns] = useState([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState(null)
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState({ platform: 'proxmox', label: '', host: '', port: 8006, auth_type: 'token', credentials: {} })
  const [formError, setFormError] = useState('')
  const [testing, setTesting] = useState({})

  const updateForm = (key, val) => setForm(f => ({ ...f, [key]: val }))
  const updateCred = (key, val) => setForm(f => ({ ...f, credentials: { ...f.credentials, [key]: val } }))
  const resetForm = () => {
    setForm({ platform: 'proxmox', label: '', host: '', port: 8006, auth_type: 'token', credentials: {} })
    setEditingId(null)
    setShowForm(false)
    setFormError('')
  }
  const setPlatform = (p) => {
    const pa = PLATFORM_AUTH[p] || { auth_type: 'apikey', fields: [{ key: 'api_key', label: 'API Key', type: 'password' }] }
    setForm(f => ({ ...f, platform: p, port: pa.defaultPort || 443, auth_type: pa.auth_type, credentials: {} }))
    setFormError('')
  }
  const startEdit = (c) => {
    const pa = PLATFORM_AUTH[c.platform] || { auth_type: 'apikey', defaultPort: 443 }
    setForm({
      platform: c.platform,
      label: c.label || '',
      host: c.host || '',
      port: c.port || pa.defaultPort || 443,
      auth_type: c.auth_type || pa.auth_type || 'token',
      credentials: {},
    })
    setEditingId(c.id)
    setShowForm(true)
    setFormError('')
  }
  const startAdd = () => {
    resetForm()
    setShowForm(true)
  }

  const fetchConns = () => {
    fetch(`${BASE}/api/connections`, { headers: { ...authHeaders() } })
      .then(r => r.ok ? r.json() : { data: [] })
      .then(d => { setConns(d.data || []); setLoading(false) })
      .catch(() => setLoading(false))
  }

  useEffect(() => { fetchConns() }, [])

  const saveConn = async (e) => {
    e.stopPropagation()
    if (!form.host.trim()) { setFormError('Host is required'); return }
    setFormError('')
    setSaving(true)
    try {
      let savedId = editingId
      if (editingId) {
        // PUT — only send fields that changed; omit empty credential fields
        const body = { label: form.label, host: form.host, port: form.port, auth_type: form.auth_type }
        const creds = {}
        for (const [k, v] of Object.entries(form.credentials)) {
          if (v && v.trim()) creds[k] = v
        }
        if (Object.keys(creds).length > 0) body.credentials = creds
        const r = await fetch(`${BASE}/api/connections/${editingId}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json', ...authHeaders() },
          body: JSON.stringify(body),
        })
        if (r.ok) { resetForm(); fetchConns() }
        else { setFormError('Failed to update connection'); savedId = null }
      } else {
        // POST — full body
        const r = await fetch(`${BASE}/api/connections`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...authHeaders() },
          body: JSON.stringify(form),
        })
        if (r.ok) {
          const d = await r.json()
          savedId = d.id || null
          resetForm()
          fetchConns()
        } else { setFormError('Failed to save connection'); savedId = null }
      }
      // Auto-test the saved connection and show result
      if (savedId) {
        setTesting(t => ({ ...t, [savedId]: 'testing' }))
        try {
          const tr = await fetch(`${BASE}/api/connections/${savedId}/test`, { method: 'POST', headers: { ...authHeaders() } })
          const td = await tr.json()
          setTesting(t => ({ ...t, [savedId]: td.status === 'ok' ? 'ok' : 'fail' }))
          setTimeout(() => { setTesting(t => ({ ...t, [savedId]: null })); fetchConns() }, 3000)
        } catch (_) {
          setTesting(t => ({ ...t, [savedId]: 'fail' }))
          setTimeout(() => setTesting(t => ({ ...t, [savedId]: null })), 3000)
        }
      }
    } finally {
      setSaving(false)
    }
  }

  const deleteConn = async (id) => {
    await fetch(`${BASE}/api/connections/${id}`, { method: 'DELETE', headers: { ...authHeaders() } })
    if (editingId === id) resetForm()
    fetchConns()
  }

  const testConn = async (id) => {
    setTesting(t => ({ ...t, [id]: 'testing' }))
    const r = await fetch(`${BASE}/api/connections/${id}/test`, { method: 'POST', headers: { ...authHeaders() } })
    const d = await r.json()
    setTesting(t => ({ ...t, [id]: d.status === 'ok' ? 'ok' : 'fail' }))
    setTimeout(() => setTesting(t => ({ ...t, [id]: null })), 3000)
    fetchConns()
  }

  if (loading) return <div style={{ color: 'var(--text-3)', fontSize: '12px', padding: '16px' }}>Loading connections...</div>

  const grouped = {}
  conns.forEach(c => { (grouped[c.platform] = grouped[c.platform] || []).push(c) })
  const platAuth = PLATFORM_AUTH[form.platform] || { auth_type: 'apikey', fields: [{ key: 'api_key', label: 'API Key', type: 'password' }] }

  return (
    <div className="space-y-3" onClick={e => e.stopPropagation()}>
      <div className="flex justify-between items-center">
        <span className="text-xs" style={{ color: 'var(--text-3)' }}>{conns.length} connection(s)</span>
        <button className="btn btn-primary text-[10px] px-2 py-1"
                onClick={e => { e.stopPropagation(); showForm ? resetForm() : startAdd() }}>
          {showForm ? '✕ Cancel' : '+ Add Connection'}
        </button>
      </div>

      {showForm && (
        <div className="card p-3 space-y-2" onClick={e => e.stopPropagation()}>
          <div className="text-[10px] font-semibold mb-1" style={{ color: 'var(--text-2)' }}>
            {editingId ? 'Edit Connection' : 'New Connection'}
          </div>
          <div>
            {_FL('Platform')}
            <select className="input text-[10px]" value={form.platform}
                    onChange={e => setPlatform(e.target.value)} disabled={!!editingId}>
              {PLATFORMS.map(p => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>
          <div>
            {_FL('Label')}
            <input className="input text-[10px]" placeholder="e.g. Pmox1, Main FortiGate"
                   value={form.label} onChange={e => updateForm('label', e.target.value)} />
          </div>
          <div className="flex gap-2">
            <div className="flex-1">
              {_FL('Host')}
              <input className="input text-[10px]" placeholder="192.168.1.5 or hostname"
                     value={form.host} onChange={e => updateForm('host', e.target.value)} />
            </div>
            <div className="w-20">
              {_FL('Port')}
              <input className="input text-[10px]" type="number" placeholder="443"
                     value={form.port} onChange={e => updateForm('port', parseInt(e.target.value) || 443)} />
            </div>
          </div>
          {platAuth.fields.map(f => (
            <div key={f.key}>
              {_FL(f.label)}
              <input className="input text-[10px] w-full" type={f.type ?? 'text'}
                placeholder={editingId ? '••••••• (saved)' : (f.placeholder ?? '')}
                value={form.credentials[f.key] ?? ''}
                onChange={e => updateCred(f.key, e.target.value)} />
            </div>
          ))}
          {formError && <div className="text-[10px]" style={{ color: 'var(--red)' }}>{formError}</div>}
          <button className="btn btn-primary w-full text-[10px]" onClick={saveConn} disabled={saving}>
            {saving ? 'Saving…' : editingId ? 'Update Connection' : 'Save Connection'}
          </button>
        </div>
      )}

      {Object.entries(grouped).map(([platform, items]) => (
        <div key={platform} className="space-y-1">
          <div className="text-[10px] uppercase tracking-wider" style={{ color: 'var(--text-3)' }}>{platform}</div>
          {items.map(c => (
            <div key={c.id} className="card flex items-center justify-between px-2 py-1.5 text-[10px]">
              <div>
                <span className="font-medium" style={{ color: 'var(--text-1)' }}>{c.label || c.host}</span>
                <span className="mono ml-2" style={{ color: 'var(--text-3)' }}>{c.host}:{c.port} · {c.auth_type}</span>
                {c.verified && <span className="ml-2" style={{ color: 'var(--green)' }}>✓</span>}
                {c.verified === false && c.last_seen && <span className="ml-2" style={{ color: 'var(--red)' }}>✕</span>}
              </div>
              <div className="flex gap-1">
                <button className="btn text-[9px] px-1.5 py-0.5"
                        onClick={() => startEdit(c)}>Edit</button>
                <button className={`btn text-[9px] px-1.5 py-0.5 ${
                  testing[c.id] === 'ok' ? 'pill-green' :
                  testing[c.id] === 'fail' ? 'pill-red' :
                  testing[c.id] === 'testing' ? 'pill-amber' : ''}`}
                  onClick={() => testConn(c.id)} disabled={testing[c.id] === 'testing'}>
                  {testing[c.id] === 'testing' ? '…' : testing[c.id] === 'ok' ? '✓' : testing[c.id] === 'fail' ? '✕' : 'Test'}
                </button>
                <button className="btn text-[9px] px-1.5 py-0.5 text-red-400"
                        onClick={() => deleteConn(c.id)}>✕</button>
              </div>
            </div>
          ))}
        </div>
      ))}

      {conns.length === 0 && !showForm && (
        <div className="text-[10px] text-center py-4" style={{ color: 'var(--text-3)' }}>
          No connections configured. Click "+ Add Connection" to connect to your infrastructure.
        </div>
      )}
    </div>
  )
}

// ── Update status display ────────────────────────────────────────────────────

function UpdateStatus() {
  const [info, setInfo] = useState(null)

  useEffect(() => {
    let cancelled = false
    fetch(`${BASE}/api/dashboard/update-status`, { headers: { ...authHeaders() } })
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (!cancelled && d) setInfo(d) })
      .catch(() => {})
    return () => { cancelled = true }
  }, [])

  if (!info) return null

  return (
    <div className="mt-1.5 text-[10px] text-gray-500 space-y-0.5">
      <div>Current: <span className="text-gray-400 font-mono">{info.current_version || '—'}</span>
        {info.update_available && (
          <span className="ml-2 px-1.5 py-px rounded bg-[#2a1e05] text-amber-400 border border-[#3d2d0a]">
            update available
          </span>
        )}
      </div>
      {info.latest_available && (
        <div>Latest: <span className="text-gray-400 font-mono">{info.latest_available}</span></div>
      )}
      {info.last_checked && (
        <div>Last checked: <span className="text-gray-400">{new Date(info.last_checked).toLocaleString()}</span></div>
      )}
      {info.auto_update && !info.update_available && info.last_checked && (
        <div className="text-green-600">Auto-update enabled — checking every 5 min</div>
      )}
    </div>
  )
}

// ── Root modal ─────────────────────────────────────────────────────────────────

export default function OptionsModal() {
  const options  = useOptions()
  const { serverLoaded } = options
  const [open,     setOpen]    = useState(false)
  const [tab,      setTab]     = useState('General')
  const [draft,    setDraft]   = useState(null)
  const [snapshot, setSnapshot] = useState(null)
  const [saving,    setSaving]   = useState(false)
  const [saveError, setSaveError] = useState(null)

  const LIVE_KEYS = ['cardMinHeight', 'cardMaxHeight', 'cardMinWidth', 'cardMaxWidth']

  const openModal = () => {
    const snap = { ...options }
    setSnapshot(snap)
    setDraft(snap)
    setTab('General')
    setOpen(true)
  }

  const closeModal = () => {
    // Revert live-applied dimension changes back to last saved values
    if (snapshot) {
      LIVE_KEYS.forEach(k => options.setOption(k, snapshot[k]))
    }
    setOpen(false)
    setDraft(null)
    setSnapshot(null)
  }

  const update = (key, value) => {
    setDraft(prev => ({ ...prev, [key]: value }))
    // Apply dimension controls live so cards update as user types
    if (LIVE_KEYS.includes(key)) {
      options.setOption(key, value)
    }
  }

  const save = async () => {
    setSaving(true)
    setSaveError(null)
    try {
      await options.saveOptions(draft)
      // Close directly — do NOT call closeModal() which reverts LIVE_KEYS to snapshot
      setOpen(false)
      setDraft(null)
      setSnapshot(null)
    } catch (e) {
      setSaveError(e.message || 'Failed to save settings')
    } finally {
      setSaving(false)
    }
  }

  if (!open) {
    return (
      <button
        onClick={openModal}
        className="sidebar-link w-full"
        title="Options"
      >
        <span className="text-sm w-5 text-center shrink-0">⚙</span>
        <span>Options</span>
      </button>
    )
  }

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/60 z-40" />

      {/* Modal — click on backdrop area (outside card) closes */}
      <div className="fixed inset-0 flex items-center justify-center z-50"
           onClick={e => { if (e.target === e.currentTarget) closeModal() }}>
        <div
          className="bg-[color:var(--bg-1)] border border-[color:var(--border)] rounded-xl shadow-2xl w-[600px] max-h-[85vh] flex flex-col"
          onClick={e => e.stopPropagation()}
        >
          {/* Header */}
          <div className="flex items-center justify-between px-5 py-4 border-b border-[color:var(--border)] shrink-0">
            <div className="flex items-center gap-2">
              <Settings size={16} className="text-[color:var(--text-2)]" />
              <span className="text-sm font-semibold text-[color:var(--text-1)]">Options</span>
            </div>
            <button onClick={closeModal} className="text-[color:var(--text-3)] hover:text-[color:var(--text-1)] transition-colors">
              <X size={16} />
            </button>
          </div>

          {/* Tab bar */}
          <div className="flex border-b border-[color:var(--border)] shrink-0">
            {TABS.map(t => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`px-4 py-2.5 text-xs font-medium transition-colors border-b-2 ${
                  tab === t
                    ? 'border-blue-500 text-blue-400'
                    : 'border-transparent text-[color:var(--text-3)] hover:text-[color:var(--text-1)]'
                }`}
              >
                {t}
              </button>
            ))}
          </div>

          {/* Tab content */}
          <div className="flex-1 overflow-y-auto px-5 py-4">
            {!serverLoaded && (tab === 'Infrastructure' || tab === 'AI Services') && (
              <p className="text-xs text-[color:var(--text-3)] animate-pulse mb-3">Loading from server…</p>
            )}
            {draft && (
              <>
                {tab === 'General'        && <GeneralTab        draft={draft} update={update} />}
                {tab === 'Infrastructure' && <InfrastructureTab draft={draft} update={update} />}
                {tab === 'AI Services'    && <AIServicesTab     draft={draft} update={update} />}
                {tab === 'Connections'    && <ConnectionsTab />}
                {tab === 'Display'        && <DisplayTab        draft={draft} update={update} />}
              </>
            )}
          </div>

          {/* Footer */}
          <div className="flex items-center justify-end gap-3 px-5 py-3 border-t border-[color:var(--border)] shrink-0">
            {saveError && (
              <span className="text-xs text-red-400 mr-auto">{saveError}</span>
            )}
            <button
              onClick={closeModal}
              className="px-4 py-1.5 text-xs text-[color:var(--text-2)] hover:text-[color:var(--text-1)] transition-colors"
            >
              Cancel
            </button>
            {tab !== 'Connections' && (
              <button
                onClick={save}
                disabled={saving}
                className="px-4 py-1.5 bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold rounded transition-colors disabled:opacity-50"
              >
                {saving ? 'Saving…' : 'Save'}
              </button>
            )}
          </div>
        </div>
      </div>
    </>
  )
}

// Named exports for SettingsPage
export { GeneralTab, InfrastructureTab, AIServicesTab, ConnectionsTab, DisplayTab, UpdateStatus }
