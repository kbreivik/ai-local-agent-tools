/**
 * OptionsModal — 4-tab settings modal.
 * Reads/writes via OptionsContext → localStorage + POST /api/settings.
 */
import { useState, useEffect } from 'react'
import { Settings, X } from 'lucide-react'
import { useOptions } from '../context/OptionsContext'
import { authHeaders } from '../api'

const BASE = import.meta.env.VITE_API_BASE ?? ''

export const TABS = ['General', 'Infrastructure', 'AI Services', 'Connections', 'Allowlist', 'Permissions', 'Access', 'Naming', 'Display', 'Notifications', 'Layouts']

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

      <div className="mb-2 mt-5">
        <h3 className="text-xs font-bold text-[color:var(--text-2)] uppercase tracking-wider mb-3 border-b border-[color:var(--border)] pb-1">
          Data Retention
        </h3>
        <Field label="Session log retention" hint="Days to keep raw agent output logs (operation_log table). Cleanup runs hourly.">
          <div className="flex items-center gap-2">
            <input
              type="number"
              min={1} max={365}
              value={draft.opLogRetentionDays ?? 30}
              onChange={e => update('opLogRetentionDays', Number(e.target.value))}
              className="w-20 bg-[color:var(--bg-2)] border border-[color:var(--border)] rounded px-2 py-1.5 text-xs text-[color:var(--text-1)] focus:outline-none"
            />
            <span className="text-xs text-[color:var(--text-3)]">days</span>
          </div>
        </Field>
        <Field label="Max lines per session" hint="Trim oldest lines when a session exceeds this count. Applied when session ends.">
          <div className="flex items-center gap-2">
            <input
              type="number"
              min={100} max={5000} step={100}
              value={draft.opLogMaxLinesPerSession ?? 500}
              onChange={e => update('opLogMaxLinesPerSession', Number(e.target.value))}
              className="w-24 bg-[color:var(--bg-2)] border border-[color:var(--border)] rounded px-2 py-1.5 text-xs text-[color:var(--text-1)] focus:outline-none"
            />
            <span className="text-xs text-[color:var(--text-3)]">lines</span>
          </div>
        </Field>
      </div>
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
        <Field label="Agent Host IP" hint="LAN IP of the agent-01 VM — used for clickable container endpoint links (e.g. 192.168.199.10)">
          <TextInput value={draft.agentHostIp} onChange={v => update('agentHostIp', v)} placeholder="192.168.199.10" />
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

      {/* Elasticsearch health thresholds */}
      <div className="mb-5">
        <SectionHeader label="Elasticsearch" />
        <Field
          label="Single-node cluster"
          hint="Yellow status is expected on a single-node cluster (replicas can't be placed). Enable to treat yellow as healthy."
        >
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={draft.elasticsearchSingleNode === true || draft.elasticsearchSingleNode === 'true'}
              onChange={e => update('elasticsearchSingleNode', e.target.checked)}
              className="accent-blue-500"
            />
            <span className="text-xs text-gray-300">Single-node mode (yellow → healthy)</span>
          </label>
        </Field>
        <Field
          label="Expected replica count"
          hint="Number of replicas per shard. Use 0 for single-node, 1+ for multi-node clusters."
        >
          <div className="flex items-center gap-2">
            <input
              type="number"
              min={0} max={5}
              value={draft.elasticsearchExpectedReplicas ?? 1}
              onChange={e => update('elasticsearchExpectedReplicas', Number(e.target.value))}
              className="w-20 bg-[color:var(--bg-2)] border border-[color:var(--border)] rounded px-2 py-1.5 text-xs text-[color:var(--text-1)] focus:outline-none"
            />
            <span className="text-xs text-[color:var(--text-3)]">replicas per shard</span>
          </div>
        </Field>
      </div>

      {/* Kafka health thresholds */}
      <div className="mb-5">
        <SectionHeader label="Kafka" />
        <Field
          label="Expected broker count"
          hint="Alert when fewer brokers are in the cluster than expected."
        >
          <div className="flex items-center gap-2">
            <input
              type="number"
              min={1} max={9}
              value={draft.kafkaExpectedBrokers ?? 3}
              onChange={e => update('kafkaExpectedBrokers', Number(e.target.value))}
              className="w-20 bg-[color:var(--bg-2)] border border-[color:var(--border)] rounded px-2 py-1.5 text-xs text-[color:var(--text-1)] focus:outline-none"
            />
            <span className="text-xs text-[color:var(--text-3)]">brokers</span>
          </div>
        </Field>
        <Field
          label="Under-replicated partition threshold"
          hint="Report DEGRADED when under-replicated partition count exceeds this value. Use 0 to require all partitions fully replicated."
        >
          <div className="flex items-center gap-2">
            <input
              type="number"
              min={0} max={100}
              value={draft.kafkaUnderReplicatedThreshold ?? 1}
              onChange={e => update('kafkaUnderReplicatedThreshold', Number(e.target.value))}
              className="w-20 bg-[color:var(--bg-2)] border border-[color:var(--border)] rounded px-2 py-1.5 text-xs text-[color:var(--text-1)] focus:outline-none"
            />
            <span className="text-xs text-[color:var(--text-3)]">partitions</span>
          </div>
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
  'cisco', 'juniper', 'aruba',
  'docker_host', 'vm_host', 'elasticsearch', 'logstash',
]

const PLATFORM_AUTH = {
  proxmox:         { auth_type: 'token',  defaultPort: 8006, fields: [{ key: 'user', label: 'PVE User', placeholder: 'terraform@pve' }, { key: 'token_name', label: 'Token Name', placeholder: 'terraform-token' }, { key: 'secret', label: 'Token Secret', type: 'password' }] },
  fortigate:       { auth_type: 'apikey', fields: [{ key: 'api_key', label: 'API Key', type: 'password' }] },
  fortiswitch:     { auth_type: 'ssh', defaultPort: 22, fields: [{ key: 'username', label: 'Username', placeholder: 'admin' }, { key: 'password', label: 'Password', type: 'password' }, { key: 'device_type', label: 'Device Type', placeholder: 'fortinet' }, { key: 'api_key', label: 'API Key', type: 'password', placeholder: 'FortiSwitch API key (optional — future use)' }] },
  truenas:         { auth_type: 'apikey', fields: [{ key: 'api_key', label: 'API Key', type: 'password' }] },
  pbs:             { auth_type: 'token',  defaultPort: 8007, fields: [{ key: 'user', label: 'PBS User', placeholder: 'root@pam' }, { key: 'token_name', label: 'Token Name', placeholder: 'automation-token' }, { key: 'secret', label: 'Token Secret', type: 'password' }] },
  unifi:           { auth_type: 'apikey', defaultPort: 443, fields: [{ key: 'api_key', label: 'API Key (recommended)', type: 'password', placeholder: 'Network → Settings → Control Plane → Integrations (UniFi OS only)' }, { key: 'username', label: 'Username (classic only)', placeholder: 'local admin account only' }, { key: 'password', label: 'Password (classic only)', type: 'password' }] },
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
  cisco:           { auth_type: 'ssh', defaultPort: 22, fields: [{ key: 'username', label: 'Username', placeholder: 'admin' }, { key: 'password', label: 'Password', type: 'password' }, { key: 'device_type', label: 'Device Type', placeholder: 'cisco_ios' }, { key: 'api_key', label: 'API Key', type: 'password', placeholder: 'RESTCONF key (optional — future use)' }] },
  juniper:         { auth_type: 'ssh', defaultPort: 22, fields: [{ key: 'username', label: 'Username', placeholder: 'admin' }, { key: 'password', label: 'Password', type: 'password' }, { key: 'device_type', label: 'Device Type', placeholder: 'juniper_junos' }, { key: 'api_key', label: 'API Key', type: 'password', placeholder: 'Junos REST API key (optional — future use)' }] },
  aruba:           { auth_type: 'ssh', defaultPort: 22, fields: [{ key: 'username', label: 'Username', placeholder: 'admin' }, { key: 'password', label: 'Password', type: 'password' }, { key: 'device_type', label: 'Device Type', placeholder: 'aruba_os' }, { key: 'api_key', label: 'API Key', type: 'password', placeholder: 'AOS-CX API key (optional — future use)' }] },
  docker_host:     { auth_type: 'tcp', defaultPort: 2375, fields: [], _dockerHost: true },
  vm_host:         {
    auth_type: 'ssh', defaultPort: 22,
    fields: [
      { key: 'username', label: 'SSH User', placeholder: 'ubuntu' },
      { key: 'password', label: 'Password', type: 'password' },
      { key: 'private_key', label: 'Private Key', type: 'textarea', hint: 'PEM format — paste full key including -----BEGIN/END----- lines. Encrypted at rest. Leave blank to use password.' },
    ],
    configFields: [
      { key: 'role', label: 'VM Role', type: 'select', options: [{ value: 'swarm_manager', label: 'Swarm Manager' }, { value: 'swarm_worker', label: 'Swarm Worker' }, { value: 'storage', label: 'Storage' }, { value: 'monitoring', label: 'Monitoring' }, { value: 'general', label: 'General' }] },
      { key: 'os_type', label: 'OS', type: 'select', hint: 'Auto-detected on first poll if left as Unknown', options: [{ value: '', label: 'Unknown (auto-detect)' }, { value: 'debian', label: 'Ubuntu / Debian' }, { value: 'rhel', label: 'RHEL / CentOS / Fedora' }, { value: 'alpine', label: 'Alpine' }, { value: 'windows', label: 'Windows Server' }, { value: 'coreos', label: 'CoreOS / Flatcar' }] },
    ],
    advancedConfigFields: [
      { key: 'shared_credentials', label: 'Shared credentials', type: 'toggle', hint: 'Try these credentials on VMs with no key or password of their own. Tried last, never overwrites machine-specific credentials.' },
      { key: 'is_jump_host', label: 'This is a jump host / bastion', type: 'toggle', hint: 'Marks this machine as a relay. Not polled as a compute node.' },
      { key: 'jump_via', label: 'Connect via jump host', type: 'jump_select', hint: 'Route SSH through a bastion. Cannot be set if this connection is itself a jump host.' },
    ],
  },
  elasticsearch:   { auth_type: 'basic', defaultPort: 9200, fields: [{ key: 'username', label: 'Username', placeholder: 'elastic' }, { key: 'password', label: 'Password', type: 'password' }] },
  logstash:        { auth_type: 'none', defaultPort: 9600, fields: [] },
}
const _FL = (/** @type {string} */ txt) => <label className="text-[10px] block mb-0.5" style={{ color: 'var(--text-3)' }}>{txt}</label>

function BulkForm({ bulk, setBulk, profiles, jumpHosts, onSave, onCancel }) {
  const [preview, setPreview] = useState([])

  const update = (k, v) => setBulk(b => ({ ...b, [k]: v }))

  const expandIpRange = (ipStart, ipEnd) => {
    const parse = ip => ip.split('.').map(Number)
    const toNum = p => p[0]*16777216 + p[1]*65536 + p[2]*256 + p[3]
    const fromNum = n => [(n>>24)&255,(n>>16)&255,(n>>8)&255,n&255].join('.')
    try {
      const s = toNum(parse(ipStart)), e = toNum(parse(ipEnd))
      if (e < s || e - s > 255) return []
      return Array.from({ length: e - s + 1 }, (_, i) => fromNum(s + i))
    } catch { return [] }
  }

  const buildPreview = () => {
    const ips = expandIpRange(bulk.ipStart, bulk.ipEnd)
    return ips.map((ip, i) => {
      const n = bulk.startN + i
      const nStr = String(n).padStart(bulk.padWidth, '0')
      return { label: bulk.namePattern.replace('%N%', nStr), host: ip, port: bulk.port }
    })
  }

  useEffect(() => { setPreview(buildPreview()) }, [bulk])

  const ROLES = [
    ['swarm_manager', 'Swarm Manager'],
    ['swarm_worker', 'Swarm Worker'],
    ['storage', 'Storage'],
    ['monitoring', 'Monitoring'],
    ['general', 'General'],
  ]

  return (
    <div className="border rounded p-4 mb-4" style={{ borderColor: 'var(--border)', background: 'var(--bg-2)' }}>
      <h3 className="text-xs font-semibold mb-3" style={{ color: 'var(--text-1)' }}>Bulk add connections</h3>

      <Field label="Platform">
        <select value={bulk.platform} onChange={e => update('platform', e.target.value)}
          className="w-full bg-[color:var(--bg-3)] border border-[color:var(--border)] rounded px-3 py-1.5 text-xs">
          <option value="vm_host">VM Host (SSH)</option>
          <option value="docker_host">Docker Host</option>
        </select>
      </Field>

      <div className="grid grid-cols-2 gap-3">
        <Field label="Name pattern">
          <TextInput value={bulk.namePattern} onChange={v => update('namePattern', v)} placeholder="ds-docker-worker-%N%" />
          <p className="text-[10px] mt-0.5" style={{ color: 'var(--text-3)' }}>%N% = counter</p>
        </Field>
        <Field label="Start number">
          <div className="flex gap-2">
            <TextInput value={bulk.startN} onChange={v => update('startN', Number(v))} placeholder="1" />
            <select value={bulk.padWidth} onChange={e => update('padWidth', Number(e.target.value))}
              className="bg-[color:var(--bg-3)] border border-[color:var(--border)] rounded px-2 py-1.5 text-xs">
              <option value={1}>1 (1,2,3…)</option>
              <option value={2}>2 (01,02…)</option>
              <option value={3}>3 (001…)</option>
            </select>
          </div>
        </Field>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Field label="IP start">
          <TextInput value={bulk.ipStart} onChange={v => update('ipStart', v)} placeholder="192.168.199.31" />
        </Field>
        <Field label="IP end">
          <TextInput value={bulk.ipEnd} onChange={v => update('ipEnd', v)} placeholder="192.168.199.33" />
        </Field>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Field label="Port">
          <TextInput value={bulk.port} onChange={v => update('port', Number(v))} placeholder="22" />
        </Field>
        <Field label="Role">
          <select value={bulk.role} onChange={e => update('role', e.target.value)}
            className="w-full bg-[color:var(--bg-3)] border border-[color:var(--border)] rounded px-3 py-1.5 text-xs">
            {ROLES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </Field>
      </div>

      <Field label="Credential profile">
        <select value={bulk.credential_profile_id} onChange={e => update('credential_profile_id', e.target.value)}
          className="w-full bg-[color:var(--bg-3)] border border-[color:var(--border)] rounded px-3 py-1.5 text-xs">
          <option value="">— none —</option>
          {profiles.map(p => <option key={p.id} value={p.id}>{p.name} ({p.auth_type})</option>)}
        </select>
      </Field>

      <Field label="Jump host">
        <select value={bulk.jump_via} onChange={e => update('jump_via', e.target.value)}
          className="w-full bg-[color:var(--bg-3)] border border-[color:var(--border)] rounded px-3 py-1.5 text-xs">
          <option value="">— direct connection —</option>
          {jumpHosts.map(jh => <option key={jh.id} value={jh.id}>{jh.label} ({jh.host})</option>)}
        </select>
      </Field>

      {preview.length > 0 && (
        <div className="mt-3">
          <p className="text-[10px] font-semibold mb-1" style={{ color: 'var(--text-2)' }}>
            Preview — {preview.length} connection{preview.length !== 1 ? 's' : ''} will be created:
          </p>
          <div className="border rounded overflow-hidden" style={{ borderColor: 'var(--border)' }}>
            {preview.map((row, i) => (
              <div key={i} className="flex gap-4 px-3 py-1.5 border-b text-[11px]"
                style={{ borderColor: 'var(--border)', background: i % 2 ? 'var(--bg-2)' : 'var(--bg-1)', color: 'var(--text-1)' }}>
                <span className="font-mono w-52 truncate">{row.label}</span>
                <span className="font-mono text-[color:var(--text-3)]">{row.host}:{row.port}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {preview.length === 0 && (bulk.ipStart && bulk.ipEnd) && (
        <p className="text-xs mt-2" style={{ color: 'var(--red)' }}>
          Invalid IP range — check start/end addresses (max 256 IPs)
        </p>
      )}

      <div className="flex gap-2 mt-4">
        <button onClick={() => onSave(preview)} disabled={preview.length === 0}
          className="px-3 py-1 text-xs rounded bg-blue-600 text-white disabled:opacity-40">
          Create {preview.length} connection{preview.length !== 1 ? 's' : ''}
        </button>
        <button onClick={onCancel} className="px-3 py-1 text-xs rounded"
          style={{ background: 'var(--bg-3)', color: 'var(--text-2)' }}>Cancel</button>
      </div>
    </div>
  )
}

function ProfileForm({ form, setForm, onSave, onCancel }) {
  const AUTH_TYPES = [
    ['ssh_key', 'SSH Key'],
    ['password', 'Password'],
    ['api_key', 'API Key'],
    ['token', 'Token'],
  ]
  const update = (k, v) => setForm(f => ({ ...f, [k]: v }))
  const updateCred = (k, v) => setForm(f => ({ ...f, credentials: { ...f.credentials, [k]: v } }))

  return (
    <div className="mt-3 p-3 border rounded" style={{ borderColor: 'var(--border)', background: 'var(--bg-2)' }}>
      <Field label="Profile name">
        <TextInput value={form.name} onChange={v => update('name', v)} placeholder="ubuntu-ssh-key" />
      </Field>
      <Field label="Auth type">
        <Select value={form.auth_type} onChange={v => update('auth_type', v)}
          options={AUTH_TYPES} />
      </Field>
      {(form.auth_type === 'ssh_key' || form.auth_type === 'password') && (
        <>
          <Field label="Username">
            <TextInput value={form.credentials.username || ''} onChange={v => updateCred('username', v)} placeholder="ubuntu" />
          </Field>
          {form.auth_type === 'ssh_key' && (
            <Field label="Private key (PEM)">
              <Textarea value={form.credentials.private_key || ''} onChange={v => updateCred('private_key', v)}
                placeholder="-----BEGIN OPENSSH PRIVATE KEY-----" rows={5} />
            </Field>
          )}
          {form.auth_type === 'password' && (
            <Field label="Password">
              <TextInput type="password" value={form.credentials.password || ''} onChange={v => updateCred('password', v)} />
            </Field>
          )}
        </>
      )}
      {form.auth_type === 'api_key' && (
        <Field label="API Key">
          <TextInput type="password" value={form.credentials.api_key || ''} onChange={v => updateCred('api_key', v)} />
        </Field>
      )}
      <div className="flex gap-2 mt-3">
        <button onClick={onSave} className="px-3 py-1 text-xs rounded bg-blue-600 text-white">Save</button>
        <button onClick={onCancel} className="px-3 py-1 text-xs rounded" style={{ background: 'var(--bg-3)', color: 'var(--text-2)' }}>Cancel</button>
      </div>
    </div>
  )
}

function ConnectionsTab() {
  const [conns, setConns] = useState([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState(null)
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState({ platform: 'proxmox', label: '', host: '', port: 8006, auth_type: 'token', credentials: {}, config: {} })
  const [formError, setFormError] = useState('')
  const [testing, setTesting] = useState({})
  const [pausing, setPausing] = useState({})
  const [advancedOpen, setAdvancedOpen] = useState(() => localStorage.getItem('ds_conn_advanced_open') === 'true')
  const [jumpHosts, setJumpHosts] = useState([])
  const [vmHostConns, setVmHostConns] = useState([])
  const [profiles, setProfiles] = useState([])
  const [showProfileForm, setShowProfileForm] = useState(false)
  const [profileForm, setProfileForm] = useState({ name: '', auth_type: 'ssh_key', credentials: {} })
  const [profilesOpen, setProfilesOpen] = useState(false)
  const [showBulk, setShowBulk] = useState(false)
  const [bulk, setBulk] = useState({
    platform: 'vm_host',
    namePattern: 'ds-docker-worker-%N%',
    startN: 1,
    padWidth: 2,
    ipStart: '192.168.199.31',
    ipEnd: '192.168.199.33',
    port: 22,
    role: 'swarm_worker',
    credential_profile_id: '',
    jump_via: '',
  })
  const [bulkSaving, setBulkSaving] = useState(false)
  const [bulkResult, setBulkResult] = useState(null)

  const DOCKER_AUTH_MODES = [
    { value: 'tcp', label: 'TCP (plain)', port: 2375, hint: 'Unauthenticated — Docker daemon on port 2375. Private LAN only.', warning: '⚠ No authentication. Use only on trusted private networks.', warningColor: 'var(--amber)', fields: [] },
    { value: 'tls', label: 'TLS (mutual)', port: 2376, hint: 'Docker daemon with --tlsverify. Client presents a signed certificate.', fields: [
      { key: 'ca_cert', label: 'CA Certificate', type: 'textarea', placeholder: '-----BEGIN CERTIFICATE-----', hint: 'ca.pem — the CA that signed both server and client certs' },
      { key: 'client_cert', label: 'Client Certificate', type: 'textarea', placeholder: '-----BEGIN CERTIFICATE-----', hint: 'cert.pem — your client certificate' },
      { key: 'client_key', label: 'Client Key', type: 'textarea', placeholder: '-----BEGIN RSA PRIVATE KEY-----', hint: 'key.pem — your client private key. Stored encrypted at rest.' },
    ]},
    { value: 'ssh', label: 'SSH tunnel', port: 22, hint: 'Connects via SSH and forwards the remote Docker socket. No daemon reconfiguration needed.', fields: [
      { key: '_ssh_source', label: 'Credentials from', type: 'ssh_source_select', hint: 'Pick an existing vm_host connection or enter creds below' },
      { key: 'username', label: 'SSH User', placeholder: 'ubuntu', hint: 'Leave blank to inherit from vm_host' },
      { key: 'private_key', label: 'Private Key', type: 'textarea', placeholder: '-----BEGIN RSA PRIVATE KEY-----', hint: 'PEM key. Leave blank to inherit from vm_host.' },
      { key: 'password', label: 'Password', type: 'password', hint: 'Note: Docker SDK SSH transport does not support password auth — key preferred.' },
    ]},
  ]

  const updateForm = (key, val) => setForm(f => ({ ...f, [key]: val }))
  const updateCred = (key, val) => setForm(f => ({ ...f, credentials: { ...f.credentials, [key]: val } }))
  const updateConfig = (key, val) => {
    setForm(f => {
      const cfg = { ...f.config, [key]: val }
      // Mutual exclusion: jump host ↔ jump via
      if (key === 'is_jump_host' && val) cfg.jump_via = ''
      if (key === 'jump_via' && val) cfg.is_jump_host = false
      return { ...f, config: cfg }
    })
  }
  const resetForm = () => {
    setForm({ platform: 'proxmox', label: '', host: '', port: 8006, auth_type: 'token', credentials: {}, config: {} })
    setEditingId(null)
    setShowForm(false)
    setFormError('')
  }
  const setPlatform = (p) => {
    const pa = PLATFORM_AUTH[p] || { auth_type: 'apikey', fields: [{ key: 'api_key', label: 'API Key', type: 'password' }] }
    setForm(f => ({ ...f, platform: p, port: pa.defaultPort || 443, auth_type: pa.auth_type, credentials: {}, config: {} }))
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
      config: c.config || {},
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
      .then(d => {
        const all = (d.data || []).sort((a, b) =>
          (a.label || a.host || '').localeCompare(b.label || b.host || '')
        )
        setConns(all)
        setJumpHosts(all.filter(c => c.platform === 'vm_host' && c.config?.is_jump_host).map(c => ({ id: c.id, label: c.label, host: c.host })))
        setVmHostConns(all.filter(c => c.platform === 'vm_host'))
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }

  const fetchProfiles = () => {
    fetch(`${BASE}/api/credential-profiles`, { headers: { ...authHeaders() } })
      .then(r => r.json())
      .then(d => setProfiles(d.profiles || []))
      .catch(() => {})
  }

  useEffect(() => { fetchConns(); fetchProfiles() }, [])

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
          if (v && String(v).trim()) creds[k] = v
        }
        if (Object.keys(creds).length > 0) body.credentials = creds
        if (form.config && Object.keys(form.config).length > 0) body.config = form.config
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

  const duplicateConn = (c) => {
    const pa = PLATFORM_AUTH[c.platform] || { auth_type: 'apikey', defaultPort: 443 }
    setForm({
      platform: c.platform,
      label: `${c.label} (copy)`,
      host: c.host || '',
      port: c.port || pa.defaultPort || 443,
      auth_type: c.auth_type || pa.auth_type || 'token',
      credentials: {},
      config: { ...(c.config || {}), credential_profile_id: c.config?.credential_profile_id },
    })
    setEditingId(null)
    setShowForm(true)
    setShowBulk(false)
    setFormError('')
    setTimeout(() => document.getElementById('conn-form-top')?.scrollIntoView({ behavior: 'smooth' }), 100)
  }

  const saveBulk = async (preview) => {
    setBulkSaving(true)
    setBulkResult(null)
    const results = []
    for (const row of preview) {
      const body = {
        platform: bulk.platform,
        label: row.label,
        host: row.host,
        port: row.port,
        auth_type: 'ssh',
        credentials: {},
        config: {
          role: bulk.role,
          ...(bulk.credential_profile_id ? { credential_profile_id: bulk.credential_profile_id } : {}),
          ...(bulk.jump_via ? { jump_via: bulk.jump_via } : {}),
        }
      }
      try {
        const r = await fetch(`${BASE}/api/connections`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...authHeaders() },
          body: JSON.stringify(body),
        })
        const d = await r.json()
        results.push({ label: row.label, ok: d.status === 'ok', msg: d.message })
      } catch (e) {
        results.push({ label: row.label, ok: false, msg: e.message })
      }
    }
    setBulkSaving(false)
    setBulkResult(results)
    const allOk = results.every(r => r.ok)
    if (allOk) {
      setTimeout(() => { setShowBulk(false); setBulkResult(null); fetchConns() }, 1500)
    } else {
      fetchConns()
    }
  }

  if (loading) return <div style={{ color: 'var(--text-3)', fontSize: '12px', padding: '16px' }}>Loading connections...</div>

  const grouped = {}
  conns.forEach(c => { (grouped[c.platform] = grouped[c.platform] || []).push(c) })
  const platAuth = PLATFORM_AUTH[form.platform] || { auth_type: 'apikey', fields: [{ key: 'api_key', label: 'API Key', type: 'password' }] }

  return (
    <div className="space-y-3" onClick={e => e.stopPropagation()}>
      <div className="mb-4 border rounded" style={{ borderColor: 'var(--border)' }}>
        <button
          onClick={() => setProfilesOpen(o => !o)}
          className="w-full flex items-center justify-between px-3 py-2 text-xs font-semibold"
          style={{ color: 'var(--text-1)', background: 'none', border: 'none', cursor: 'pointer' }}
        >
          <span>CREDENTIAL PROFILES ({profiles.length})</span>
          <span>{profilesOpen ? '\u25B2' : '\u25BC'}</span>
        </button>
        {profilesOpen && (
          <div className="px-3 pb-3">
            <p className="text-[10px] mb-2" style={{ color: 'var(--text-3)' }}>
              Named auth sets shared across multiple connections. Select a profile when adding vm_host or docker_host connections instead of re-entering credentials each time.
            </p>
            {profiles.map(p => (
              <div key={p.id} className="flex items-center justify-between py-1 border-b" style={{ borderColor: 'var(--border)' }}>
                <span className="text-xs" style={{ color: 'var(--text-1)' }}>{p.name}</span>
                <span className="text-[10px] px-2 py-0.5 rounded" style={{ background: 'var(--bg-3)', color: 'var(--text-3)' }}>{p.auth_type}</span>
              </div>
            ))}
            <button
              onClick={() => setShowProfileForm(true)}
              className="mt-2 text-xs px-3 py-1 rounded"
              style={{ background: 'var(--accent-dim)', color: 'var(--accent)' }}
            >+ New profile</button>
            {showProfileForm && <ProfileForm
              form={profileForm}
              setForm={setProfileForm}
              onSave={async () => {
                await fetch(`${BASE}/api/credential-profiles`, {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json', ...authHeaders() },
                  body: JSON.stringify(profileForm),
                })
                setShowProfileForm(false)
                setProfileForm({ name: '', auth_type: 'ssh_key', credentials: {} })
                fetchProfiles()
              }}
              onCancel={() => setShowProfileForm(false)}
            />}
          </div>
        )}
      </div>

      <div className="flex justify-between items-center">
        <span className="text-xs" style={{ color: 'var(--text-3)' }}>{conns.length} connection(s)</span>
        <div className="flex gap-2">
          <button className="btn btn-primary text-[10px] px-2 py-1"
                  onClick={e => { e.stopPropagation(); setShowBulk(false); showForm ? resetForm() : startAdd() }}>
            {showForm ? '✕ Cancel' : '+ Add Connection'}
          </button>
          <button className="btn text-[10px] px-2 py-1"
                  onClick={e => { e.stopPropagation(); resetForm(); setShowBulk(b => !b) }}
                  style={{ background: 'var(--bg-3)', color: 'var(--text-2)' }}>
            {showBulk ? '✕ Cancel' : '\u229E Bulk add'}
          </button>
        </div>
      </div>

      {showBulk && (
        <BulkForm bulk={bulk} setBulk={setBulk} profiles={profiles} jumpHosts={jumpHosts}
          onSave={saveBulk}
          onCancel={() => { setShowBulk(false); setBulkResult(null) }} />
      )}
      {showBulk && bulkSaving && (
        <div className="text-xs py-2" style={{ color: 'var(--text-3)' }}>Creating connections…</div>
      )}
      {showBulk && bulkResult && (
        <div className="border rounded p-3 mb-3" style={{ borderColor: 'var(--border)' }}>
          {bulkResult.map((r, i) => (
            <div key={i} className="flex gap-2 text-[10px] py-0.5" style={{ color: r.ok ? 'var(--green)' : 'var(--red)' }}>
              <span>{r.ok ? '✓' : '✕'}</span>
              <span>{r.label}</span>
              {!r.ok && <span style={{ color: 'var(--text-3)' }}>{r.msg}</span>}
            </div>
          ))}
        </div>
      )}

      {showForm && (
        <div id="conn-form-top" className="card p-3 space-y-2" onClick={e => e.stopPropagation()}>
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
          {/* Docker host — custom 3-mode form */}
          {form.platform === 'docker_host' && (() => {
            const mode = DOCKER_AUTH_MODES.find(m => m.value === form.auth_type) || DOCKER_AUTH_MODES[0]
            return (<>
              <div>
                {_FL('Connection Mode')}
                <div style={{ display: 'flex', gap: 4 }}>
                  {DOCKER_AUTH_MODES.map(m => (
                    <button key={m.value} onClick={() => setForm(f => ({ ...f, auth_type: m.value, port: m.port, credentials: {} }))}
                      style={{ flex: 1, fontSize: 9, padding: '4px 0', fontFamily: 'var(--font-mono)', letterSpacing: '0.05em', borderRadius: 2, cursor: 'pointer', border: '1px solid',
                        background: form.auth_type === m.value ? 'var(--accent-dim)' : 'var(--bg-2)', color: form.auth_type === m.value ? 'var(--accent)' : 'var(--text-3)', borderColor: form.auth_type === m.value ? 'var(--accent)' : 'var(--border)' }}>
                      {m.label}
                    </button>
                  ))}
                </div>
                <div style={{ fontSize: 9, color: 'var(--text-3)', marginTop: 4 }}>{mode.hint}</div>
                {mode.warning && <div style={{ fontSize: 9, marginTop: 3, padding: '3px 6px', borderRadius: 2, border: `1px solid ${mode.warningColor}`, color: mode.warningColor, background: 'var(--bg-3)' }}>{mode.warning}</div>}
              </div>
              <div>
                {_FL('Swarm Role')}
                <select className="input text-[10px]" value={form.config?.role || 'swarm_manager'} onChange={e => updateConfig('role', e.target.value)}>
                  <option value="swarm_manager">Swarm Manager</option>
                  <option value="swarm_worker">Swarm Worker</option>
                  <option value="standalone">Standalone</option>
                </select>
              </div>
              {mode.fields.map(f => f.type === 'ssh_source_select' ? (
                <div key={f.key}>
                  {_FL(f.label)}
                  {f.hint && <div style={{ fontSize: 9, color: 'var(--text-3)', marginBottom: 3 }}>{f.hint}</div>}
                  <select className="input text-[10px] w-full" value={form.config?._ssh_source || ''} onChange={e => { updateConfig('_ssh_source', e.target.value); const vmc = vmHostConns.find(c => c.id === e.target.value); if (vmc && !form.host) updateForm('host', vmc.host) }}>
                    <option value="">— enter credentials directly —</option>
                    {vmHostConns.map(vmc => <option key={vmc.id} value={vmc.id}>{vmc.label} ({vmc.host})</option>)}
                  </select>
                  {vmHostConns.length === 0 && <div style={{ fontSize: 9, color: 'var(--text-3)', marginTop: 2 }}>No vm_host connections found — add one first or enter SSH credentials directly</div>}
                </div>
              ) : f.type === 'textarea' ? (
                <div key={f.key}>
                  {_FL(f.label)}
                  {f.hint && <div style={{ fontSize: 9, color: 'var(--text-3)', marginBottom: 3 }}>{f.hint}</div>}
                  <textarea className="input text-[10px] w-full" style={{ minHeight: 70, fontFamily: 'var(--font-mono)', fontSize: 9, resize: 'vertical', whiteSpace: 'pre' }}
                    placeholder={editingId ? '••• (saved)' : (f.placeholder || '')} value={form.credentials[f.key] ?? ''} onChange={e => updateCred(f.key, e.target.value)} />
                </div>
              ) : (
                <div key={f.key}>
                  {_FL(f.label)}
                  {f.hint && <div style={{ fontSize: 9, color: 'var(--text-3)', marginBottom: 3 }}>{f.hint}</div>}
                  <input className="input text-[10px] w-full" type={f.type || 'text'}
                    placeholder={editingId ? '••• (saved)' : (f.placeholder || '')} value={form.credentials[f.key] ?? ''} onChange={e => updateCred(f.key, e.target.value)} />
                </div>
              ))}
            </>)
          })()}
          {/* Credential profile picker for vm_host */}
          {form.platform === 'vm_host' && (
            <div>
              {_FL('Credential profile')}
              <div style={{ fontSize: 9, color: 'var(--text-3)', marginBottom: 3 }}>Pick a saved profile or enter credentials below</div>
              <select
                value={form.config?.credential_profile_id || ''}
                onChange={e => updateConfig('credential_profile_id', e.target.value || null)}
                className="input text-[10px] w-full"
              >
                <option value="">— none (use credentials below) —</option>
                {profiles.map(p => (
                  <option key={p.id} value={p.id}>{p.name} ({p.auth_type})</option>
                ))}
              </select>
              {form.config?.credential_profile_id && (
                <div style={{ fontSize: 9, color: 'var(--accent)', marginTop: 3 }}>Credentials from profile — leave blank below to inherit</div>
              )}
            </div>
          )}
          {/* Standard platform fields */}
          {form.platform !== 'docker_host' && platAuth.fields.map(f => (
            <div key={f.key}>
              {_FL(f.label + (f.hint ? ' ↓' : ''))}
              {f.hint && <div style={{ fontSize: 9, color: 'var(--text-3)', marginBottom: 3 }}>{f.hint}</div>}
              {f.type === 'select' ? (
                <select className="input text-[10px] w-full"
                  value={form.credentials[f.key] ?? (f.options?.[0]?.value ?? '')}
                  onChange={e => updateCred(f.key, e.target.value)}>
                  {(f.options || []).map(opt =>
                    typeof opt === 'string'
                      ? <option key={opt} value={opt}>{opt}</option>
                      : <option key={opt.value} value={opt.value}>{opt.label}</option>
                  )}
                </select>
              ) : f.type === 'textarea' ? (
                <textarea className="input text-[10px] w-full"
                  style={{ minHeight: 80, fontFamily: 'var(--font-mono)', fontSize: 9, resize: 'vertical', whiteSpace: 'pre' }}
                  placeholder={editingId ? '••• (saved — leave blank to keep)' : (f.placeholder ?? '')}
                  value={form.credentials[f.key] ?? ''}
                  onChange={e => updateCred(f.key, e.target.value)} />
              ) : (
                <input className="input text-[10px] w-full" type={f.type ?? 'text'}
                  placeholder={editingId ? '••••••• (saved)' : (f.placeholder ?? '')}
                  value={form.credentials[f.key] ?? ''}
                  onChange={e => updateCred(f.key, e.target.value)} />
              )}
            </div>
          ))}
          {/* Config fields (role, os_type, etc.) */}
          {(platAuth.configFields || []).map(f => (
            <div key={f.key}>
              {_FL(f.label)}
              {f.hint && <div style={{ fontSize: 9, color: 'var(--text-3)', marginBottom: 3 }}>{f.hint}</div>}
              {f.type === 'select' ? (
                <select className="input text-[10px] w-full"
                  value={form.config[f.key] ?? (f.options?.[0]?.value ?? '')}
                  onChange={e => updateConfig(f.key, e.target.value)}>
                  {(f.options || []).map(opt => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
                </select>
              ) : (
                <input className="input text-[10px] w-full" type={f.type ?? 'text'}
                  value={form.config[f.key] ?? ''} onChange={e => updateConfig(f.key, e.target.value)} />
              )}
            </div>
          ))}
          {/* Advanced config accordion */}
          {(platAuth.advancedConfigFields || []).length > 0 && (
            <>
              <button onClick={() => { const next = !advancedOpen; setAdvancedOpen(next); localStorage.setItem('ds_conn_advanced_open', String(next)) }}
                style={{ width: '100%', textAlign: 'left', fontSize: 9, color: 'var(--text-3)', background: 'none', border: 'none', borderTop: '1px solid var(--border)', padding: '5px 0', cursor: 'pointer', fontFamily: 'var(--font-mono)', letterSpacing: '0.05em', display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ transform: advancedOpen ? 'rotate(90deg)' : 'none', display: 'inline-block', transition: 'transform 0.15s' }}>▶</span>
                ADVANCED
              </button>
              {advancedOpen && platAuth.advancedConfigFields.map(f => (
                <div key={f.key} style={{ marginBottom: 6 }}>
                  {_FL(f.label)}
                  {f.hint && <div style={{ fontSize: 9, color: 'var(--text-3)', marginBottom: 3 }}>{f.hint}</div>}
                  {f.type === 'toggle' ? (
                    <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
                      <div onClick={() => updateConfig(f.key, !form.config[f.key])}
                        style={{ width: 32, height: 18, borderRadius: 9, flexShrink: 0, background: form.config[f.key] ? 'var(--green)' : 'var(--bg-3)', border: '1px solid var(--border)', cursor: 'pointer', position: 'relative', transition: 'background 0.15s' }}>
                        <div style={{ position: 'absolute', top: 2, left: form.config[f.key] ? 14 : 2, width: 12, height: 12, borderRadius: '50%', background: 'var(--text-1)', transition: 'left 0.15s' }} />
                      </div>
                      <span style={{ fontSize: 10, color: 'var(--text-2)' }}>{form.config[f.key] ? 'Enabled' : 'Disabled'}</span>
                    </label>
                  ) : f.type === 'jump_select' ? (
                    !form.config.is_jump_host && (
                      <>
                        <select className="input text-[10px] w-full" value={form.config[f.key] || ''} onChange={e => updateConfig(f.key, e.target.value)}>
                          <option value="">— direct connection —</option>
                          {jumpHosts.filter(jh => jh.id !== editingId).map(jh => <option key={jh.id} value={jh.id}>{jh.label} ({jh.host})</option>)}
                        </select>
                        {jumpHosts.length === 0 && <div style={{ fontSize: 9, color: 'var(--text-3)', marginTop: 2 }}>No jump hosts configured — mark another vm_host as a jump host first</div>}
                      </>
                    )
                  ) : f.type === 'select' ? (
                    <select className="input text-[10px] w-full" value={form.config[f.key] ?? ''} onChange={e => updateConfig(f.key, e.target.value)}>
                      {(f.options || []).map(opt => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
                    </select>
                  ) : (
                    <input className="input text-[10px] w-full" type="text" value={form.config[f.key] ?? ''} onChange={e => updateConfig(f.key, e.target.value)} />
                  )}
                </div>
              ))}
            </>
          )}
          {formError && <div className="text-[10px]" style={{ color: 'var(--red)' }}>{formError}</div>}
          <button className="btn btn-primary w-full text-[10px]" onClick={saveConn} disabled={saving}>
            {saving ? 'Saving…' : editingId ? 'Update Connection' : 'Save Connection'}
          </button>
        </div>
      )}

      {Object.entries(grouped).map(([platform, items]) => (
        <div key={platform} className="space-y-1">
          <div className="text-[10px] uppercase tracking-wider" style={{ color: 'var(--text-3)' }}>{platform}</div>
          {items.map(c => {
            const isPaused = c.config?.paused === true
            const pauseConn = async (id, paused) => {
              const action = paused ? 'resume' : 'pause'
              setPausing(p => ({ ...p, [id]: true }))
              const r = await fetch(`${BASE}/api/connections/${id}/${action}`, { method: 'POST', headers: { ...authHeaders() } })
              if (!r.ok) { setTesting(t => ({ ...t, [id]: 'fail' })); setTimeout(() => setTesting(t => ({ ...t, [id]: null })), 3000) }
              setPausing(p => ({ ...p, [id]: false }))
              fetchConns()
            }
            return (
            <div key={c.id} className="card flex items-center justify-between px-2 py-1.5 text-[10px]" style={{ opacity: isPaused ? 0.6 : 1, transition: 'opacity 0.2s' }}>
              <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 4 }}>
                <span className="font-medium" style={{ color: 'var(--text-1)' }}>{c.label || c.host}</span>
                <span className="mono" style={{ color: 'var(--text-3)' }}>{c.host}:{c.port} · {c.platform === 'docker_host' ? ({ tcp: '⊘ plain TCP', tls: '⚿ TLS', ssh: '⇢ SSH' }[c.auth_type] || c.auth_type) : c.auth_type}</span>
                {c.verified && <span style={{ color: 'var(--green)' }}>✓</span>}
                {c.verified === false && c.last_seen && <span style={{ color: 'var(--red)' }}>✕</span>}
                {c.config?.is_jump_host && <span style={{ fontSize: 8, padding: '1px 4px', borderRadius: 2, background: 'var(--amber-dim)', color: 'var(--amber)' }}>⇢ BASTION</span>}
                {c.config?.shared_credentials && <span style={{ fontSize: 8, padding: '1px 4px', borderRadius: 2, background: 'var(--cyan-dim)', color: 'var(--cyan)' }}>⊕ SHARED</span>}
                {c.config?.os_type && <span style={{ fontSize: 8, padding: '1px 4px', borderRadius: 2, background: 'var(--bg-3)', color: 'var(--text-3)' }}>{c.config.os_type}</span>}
                {isPaused && <span style={{ fontSize: 8, padding: '1px 5px', borderRadius: 2, background: 'rgba(100,100,120,0.2)', color: 'var(--text-3)', border: '1px solid var(--border)', fontFamily: 'var(--font-mono)', letterSpacing: '0.04em' }}>⏸ PAUSED{c.config.paused_by ? ` · ${c.config.paused_by}` : ''}</span>}
              </div>
              <div className="flex gap-1" style={{ flexShrink: 0 }}>
                <button className="btn text-[9px] px-1.5 py-0.5" onClick={() => startEdit(c)}>Edit</button>
                <button onClick={() => duplicateConn(c)} title="Duplicate connection" className="btn text-[9px] px-1.5 py-0.5" style={{ color: 'var(--text-3)' }}>Copy</button>
                <button className={`btn text-[9px] px-1.5 py-0.5 ${testing[c.id] === 'ok' ? 'pill-green' : testing[c.id] === 'fail' ? 'pill-red' : testing[c.id] === 'testing' ? 'pill-amber' : ''}`}
                  onClick={() => testConn(c.id)} disabled={testing[c.id] === 'testing' || isPaused}
                  title={isPaused ? 'Resume before testing' : 'Test connection'}>
                  {testing[c.id] === 'testing' ? '…' : testing[c.id] === 'ok' ? '✓' : testing[c.id] === 'fail' ? '✕' : 'Test'}
                </button>
                <button className="btn text-[9px] px-1.5 py-0.5" onClick={() => pauseConn(c.id, isPaused)} disabled={!!pausing[c.id]}
                  title={isPaused ? 'Resume — collectors will poll again' : 'Pause — stop polling'}
                  style={{ color: isPaused ? 'var(--green)' : 'var(--text-3)', opacity: pausing[c.id] ? 0.5 : 1 }}>
                  {pausing[c.id] ? '…' : isPaused ? '▶' : '⏸'}
                </button>
                <button className="btn text-[9px] px-1.5 py-0.5 text-red-400" onClick={() => deleteConn(c.id)}>✕</button>
              </div>
            </div>
          )})}
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

// ── Tab: Permissions (placeholder) ───────────────────────────────────────────

function PermissionsTab() {
  const _th = { fontSize: 8, fontFamily: 'var(--font-mono)', color: 'var(--text-3)', padding: '6px 12px', textAlign: 'left', borderBottom: '1px solid var(--border)', letterSpacing: 1 }
  return (
    <div>
      <div style={{ fontSize: 11, color: 'var(--text-2)', marginBottom: 12 }}>Permissions management coming soon</div>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            <th style={_th}>PERMISSION</th>
            <th style={_th}>SITH LORD</th>
            <th style={_th}>IMPERIAL OFFICER</th>
            <th style={_th}>STORMTROOPER</th>
            <th style={_th}>DROID</th>
          </tr>
        </thead>
        <tbody>
          {[
            //                                     SITH  OFFICER  TROOPER  DROID
            ['Execute tasks',          [true,  true,  true,   false]],
            ['Run agent commands',     [true,  true,  false,  false]],
            ['View logs',              [true,  true,  true,   true ]],
            ['Manage connections',     [true,  true,  false,  false]],
            ['Manage skills',          [true,  true,  false,  false]],
            ['Toggle maintenance',     [true,  true,  true,   false]],
            ['Global maintenance',     [true,  true,  false,  false]],
            ['Change AI model config', [true,  false, false,  false]],
            ['Manage users / roles',   [true,  false, false,  false]],
            ['System admin',           [true,  false, false,  false]],
            ['Read-only API token',    [true,  true,  true,   true ]],
          ].map(([p, perms]) => (
            <tr key={p}>
              <td style={{ fontSize: 10, padding: '4px 12px', color: 'var(--text-2)', borderBottom: '1px solid var(--bg-3)' }}>{p}</td>
              {perms.map((v, i) => (
                <td key={i} style={{ fontSize: 10, padding: '4px 12px', textAlign: 'center', borderBottom: '1px solid var(--bg-3)', color: v ? 'var(--green)' : 'var(--text-3)' }}>{v ? '✓' : '—'}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Tab: Access (placeholder) ────────────────────────────────────────────────

function AccessTab() {
  const [subTab, setSubTab] = useState('users')
  const [users, setUsers] = useState([])
  const [tokens, setTokens] = useState([])
  const [showAddUser, setShowAddUser] = useState(false)
  const [showAddToken, setShowAddToken] = useState(false)
  const [newUser, setNewUser] = useState({ username: '', password: '', confirm: '', role: 'stormtrooper' })
  const [newToken, setNewToken] = useState({ name: '', role: 'droid', expires_at: '' })
  const [generatedToken, setGeneratedToken] = useState(null)
  const [saving, setSaving] = useState(false)

  const ROLE_COLORS = { sith_lord: 'var(--red)', imperial_officer: 'var(--amber)', stormtrooper: 'var(--cyan)', droid: 'var(--text-3)' }
  const ROLE_LABELS = { sith_lord: 'SITH LORD', imperial_officer: 'IMPERIAL OFFICER', stormtrooper: 'STORMTROOPER', droid: 'DROID' }

  const fetchUsers = () => fetch(`${BASE}/api/users`, { headers: { ...authHeaders() } }).then(r => r.json()).then(d => setUsers(d.data || [])).catch(() => {})
  const fetchTokens = () => fetch(`${BASE}/api/tokens`, { headers: { ...authHeaders() } }).then(r => r.json()).then(d => setTokens(d.data || [])).catch(() => {})
  useEffect(() => { fetchUsers(); fetchTokens() }, [])

  const addUser = async () => {
    if (newUser.password !== newUser.confirm) return
    setSaving(true)
    const r = await fetch(`${BASE}/api/users`, { method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeaders() }, body: JSON.stringify({ username: newUser.username, password: newUser.password, role: newUser.role }) })
    setSaving(false)
    if (r.ok) { setShowAddUser(false); setNewUser({ username: '', password: '', confirm: '', role: 'stormtrooper' }); fetchUsers() }
  }

  const deleteUser = async (id) => {
    await fetch(`${BASE}/api/users/${id}`, { method: 'DELETE', headers: { ...authHeaders() } })
    fetchUsers()
  }

  const addToken = async () => {
    setSaving(true)
    const r = await fetch(`${BASE}/api/tokens`, { method: 'POST', headers: { 'Content-Type': 'application/json', ...authHeaders() }, body: JSON.stringify({ name: newToken.name, role: newToken.role, expires_at: newToken.expires_at || null }) })
    setSaving(false)
    if (r.ok) {
      const d = await r.json()
      setGeneratedToken(d.token)
      setShowAddToken(false)
      setNewToken({ name: '', role: 'droid', expires_at: '' })
      fetchTokens()
    }
  }

  const revokeToken = async (id) => {
    await fetch(`${BASE}/api/tokens/${id}`, { method: 'DELETE', headers: { ...authHeaders() } })
    fetchTokens()
  }

  const _relTime = (iso) => {
    if (!iso) return 'never'
    const d = new Date(iso)
    const s = Math.floor((Date.now() - d.getTime()) / 1000)
    if (s < 60) return 'just now'
    if (s < 3600) return `${Math.floor(s / 60)}m ago`
    if (s < 86400) return `${Math.floor(s / 3600)}h ago`
    return `${Math.floor(s / 86400)}d ago`
  }

  const _td = { fontSize: 10, padding: '5px 8px', borderBottom: '1px solid var(--bg-3)', fontFamily: 'var(--font-mono)' }
  const _th = { fontSize: 8, padding: '5px 8px', borderBottom: '1px solid var(--border)', color: 'var(--text-3)', letterSpacing: 1, textAlign: 'left', fontFamily: 'var(--font-mono)' }

  return (
    <div onClick={e => e.stopPropagation()}>
      {/* Header: sub-tab buttons + action button in one row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
        {['users', 'tokens', 'ssh'].map(t => (
          <button key={t} onClick={() => { setSubTab(t); setGeneratedToken(null); setShowAddUser(false); setShowAddToken(false) }} style={{
            fontSize: 9, fontFamily: 'var(--font-mono)', padding: '3px 10px',
            background: subTab === t ? 'var(--accent-dim)' : 'transparent',
            color: subTab === t ? 'var(--accent)' : 'var(--text-3)',
            border: `1px solid ${subTab === t ? 'var(--accent)' : 'var(--border)'}`,
            borderRadius: 2, cursor: 'pointer', letterSpacing: 1,
          }}>{t === 'users' ? 'USERS' : t === 'tokens' ? 'API TOKENS' : 'SSH ACCESS'}</button>
        ))}
        {subTab === 'users' && (
          <button className="btn btn-primary text-[9px] px-2 py-1" style={{ marginLeft: 'auto' }} onClick={() => setShowAddUser(!showAddUser)}>
            {showAddUser ? '✕ Cancel' : '+ ADD USER'}
          </button>
        )}
        {subTab === 'tokens' && (
          <button className="btn btn-primary text-[9px] px-2 py-1" style={{ marginLeft: 'auto' }} onClick={() => setShowAddToken(!showAddToken)}>
            {showAddToken ? '✕ Cancel' : '+ GENERATE TOKEN'}
          </button>
        )}
      </div>

      {subTab === 'users' && (
        <>
          {showAddUser && (
            <div className="card p-3 space-y-2 mb-3" onClick={e => e.stopPropagation()}>
              <input className="input text-[10px]" placeholder="Username" value={newUser.username} onChange={e => setNewUser(u => ({ ...u, username: e.target.value }))} />
              <input className="input text-[10px]" type="password" placeholder="Password" value={newUser.password} onChange={e => setNewUser(u => ({ ...u, password: e.target.value }))} />
              <input className="input text-[10px]" type="password" placeholder="Confirm password" value={newUser.confirm} onChange={e => setNewUser(u => ({ ...u, confirm: e.target.value }))} />
              {newUser.password && newUser.confirm && newUser.password !== newUser.confirm && <div style={{ fontSize: 9, color: 'var(--red)' }}>Passwords don't match</div>}
              <select className="input text-[10px]" value={newUser.role} onChange={e => setNewUser(u => ({ ...u, role: e.target.value }))}>
                <option value="imperial_officer">Imperial Officer</option>
                <option value="stormtrooper">Stormtrooper</option>
                <option value="droid">Droid</option>
              </select>
              <button className="btn btn-primary w-full text-[10px]" onClick={addUser} disabled={saving || !newUser.username || !newUser.password || newUser.password !== newUser.confirm}>
                {saving ? 'Creating…' : 'Create User'}
              </button>
            </div>
          )}
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr>
              <th style={_th}>USERNAME</th><th style={_th}>ROLE</th><th style={_th}>STATUS</th><th style={_th}>LAST LOGIN</th><th style={_th}>ACTIONS</th>
            </tr></thead>
            <tbody>
              {users.map(u => {
                const changeRole = async (newRole) => {
                  await fetch(`${BASE}/api/users/${u.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json', ...authHeaders() }, body: JSON.stringify({ role: newRole }) })
                  fetchUsers()
                }
                const toggleEnabled = async () => {
                  await fetch(`${BASE}/api/users/${u.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json', ...authHeaders() }, body: JSON.stringify({ enabled: !u.enabled }) })
                  fetchUsers()
                }
                return (
                  <tr key={u.id}>
                    <td style={{ ..._td, color: 'var(--text-1)' }}>{u.username}</td>
                    <td style={_td}><span style={{ fontSize: 8, padding: '1px 4px', borderRadius: 2, background: 'var(--bg-3)', color: ROLE_COLORS[u.role] || 'var(--text-3)', letterSpacing: 0.5 }}>{ROLE_LABELS[u.role] || u.role}</span></td>
                    <td style={_td}><span style={{ color: u.enabled ? 'var(--green)' : 'var(--text-3)' }}>{u.enabled ? '● ACTIVE' : '○ DISABLED'}</span></td>
                    <td style={{ ..._td, color: 'var(--text-3)' }}>{_relTime(u.last_login)}</td>
                    <td style={{ ..._td, whiteSpace: 'nowrap' }}>
                      <select style={{ fontSize: 8, background: 'var(--bg-2)', color: 'var(--text-2)', border: '1px solid var(--border)', borderRadius: 2, padding: '1px 4px', marginRight: 4, fontFamily: 'var(--font-mono)' }}
                              value={u.role} onChange={e => changeRole(e.target.value)}>
                        <option value="sith_lord">Sith Lord</option>
                        <option value="imperial_officer">Officer</option>
                        <option value="stormtrooper">Trooper</option>
                        <option value="droid">Droid</option>
                      </select>
                      <button style={{ fontSize: 8, color: u.enabled ? 'var(--amber)' : 'var(--green)', background: 'none', border: 'none', cursor: 'pointer', marginRight: 4 }}
                              onClick={toggleEnabled}>{u.enabled ? 'Disable' : 'Enable'}</button>
                      <button style={{ fontSize: 8, color: 'var(--red)', background: 'none', border: 'none', cursor: 'pointer' }}
                              onClick={() => deleteUser(u.id)}>Delete</button>
                    </td>
                  </tr>
                )
              })}
              {users.length === 0 && <tr><td colSpan={5} style={{ ..._td, color: 'var(--text-3)', textAlign: 'center' }}>No users — the Force is strong but the team is small</td></tr>}
            </tbody>
          </table>
        </>
      )}

      {subTab === 'tokens' && (
        <>
          {generatedToken && (
            <div style={{ padding: '8px 12px', background: 'var(--amber-dim)', border: '1px solid var(--amber)', borderRadius: 2, marginBottom: 8, fontSize: 10 }}>
              <div style={{ color: 'var(--amber)', marginBottom: 4, fontWeight: 600 }}>⚠ This token will not be shown again</div>
              <div style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-1)', wordBreak: 'break-all', cursor: 'pointer' }} onClick={() => { navigator.clipboard.writeText(generatedToken); setGeneratedToken(null) }} title="Click to copy">{generatedToken}</div>
            </div>
          )}
          {showAddToken && (
            <div className="card p-3 space-y-2 mb-3" onClick={e => e.stopPropagation()}>
              <input className="input text-[10px]" placeholder="Token name (e.g. ansible-deploy)" value={newToken.name} onChange={e => setNewToken(t => ({ ...t, name: e.target.value }))} />
              <select className="input text-[10px]" value={newToken.role} onChange={e => setNewToken(t => ({ ...t, role: e.target.value }))}>
                <option value="imperial_officer">Imperial Officer</option>
                <option value="stormtrooper">Stormtrooper</option>
                <option value="droid">Droid</option>
              </select>
              <input className="input text-[10px]" type="date" placeholder="Expires (optional)" value={newToken.expires_at} onChange={e => setNewToken(t => ({ ...t, expires_at: e.target.value }))} />
              <button className="btn btn-primary w-full text-[10px]" onClick={addToken} disabled={saving || !newToken.name}>
                {saving ? 'Generating…' : 'Generate Token'}
              </button>
            </div>
          )}
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr>
              <th style={_th}>NAME</th><th style={_th}>ROLE</th><th style={_th}>CREATED</th><th style={_th}>EXPIRES</th><th style={_th}>LAST USED</th><th style={_th}>ACTIONS</th>
            </tr></thead>
            <tbody>
              {tokens.map(t => (
                <tr key={t.id}>
                  <td style={{ ..._td, color: 'var(--text-1)' }}>{t.name}</td>
                  <td style={_td}><span style={{ fontSize: 8, padding: '1px 4px', borderRadius: 2, background: 'var(--bg-3)', color: ROLE_COLORS[t.role] || 'var(--text-3)' }}>{ROLE_LABELS[t.role] || t.role}</span></td>
                  <td style={{ ..._td, color: 'var(--text-3)' }}>{_relTime(t.created_at)}</td>
                  <td style={{ ..._td, color: 'var(--text-3)' }}>{t.expires_at ? new Date(t.expires_at).toLocaleDateString() : 'never'}</td>
                  <td style={{ ..._td, color: 'var(--text-3)' }}>{_relTime(t.last_used)}</td>
                  <td style={_td}><button style={{ fontSize: 9, color: 'var(--red)', background: 'none', border: 'none', cursor: 'pointer' }} onClick={() => revokeToken(t.id)}>Revoke</button></td>
                </tr>
              ))}
              {tokens.length === 0 && <tr><td colSpan={6} style={{ ..._td, color: 'var(--text-3)', textAlign: 'center' }}>No API tokens generated</td></tr>}
            </tbody>
          </table>
        </>
      )}
      {subTab === 'ssh' && <SSHAccessSubTab _td={_td} _th={_th} _relTime={_relTime} />}
    </div>
  )
}

function SSHAccessSubTab({ _td, _th, _relTime }) {
  const [summary, setSummary] = useState(null)
  const [capabilities, setCapabilities] = useState([])
  const [sshLogs, setSshLogs] = useState([])
  const [showLogs, setShowLogs] = useState(false)

  const fetchAll = () => {
    fetch(`${BASE}/api/logs/ssh/capabilities/summary`, { headers: { ...authHeaders() } })
      .then(r => r.ok ? r.json() : null).then(d => { if (d) setSummary(d.summary) }).catch(() => {})
    fetch(`${BASE}/api/logs/ssh/capabilities`, { headers: { ...authHeaders() } })
      .then(r => r.ok ? r.json() : null).then(d => { if (d) setCapabilities(d.capabilities || d.data || []) }).catch(() => {})
  }

  useEffect(() => { fetchAll() }, [])

  const markReviewed = (connId, host) => {
    fetch(`${BASE}/api/logs/ssh/capabilities/alerts/${connId}/reviewed?target_host=${encodeURIComponent(host)}`, {
      method: 'POST', headers: { ...authHeaders() },
    }).then(() => fetchAll()).catch(() => {})
  }

  const loadLogs = () => {
    setShowLogs(true)
    fetch(`${BASE}/api/logs/ssh?limit=50`, { headers: { ...authHeaders() } })
      .then(r => r.ok ? r.json() : null).then(d => { if (d) setSshLogs(d.entries || d.data || []) }).catch(() => {})
  }

  const OUTCOME_STYLE = {
    success:   { bg: 'rgba(0,170,68,0.12)', color: 'var(--green)', label: 'OK' },
    auth_fail: { bg: 'rgba(204,40,40,0.15)', color: 'var(--red)', label: 'AUTH FAIL' },
    timeout:   { bg: 'rgba(204,136,0,0.12)', color: 'var(--amber)', label: 'TIMEOUT' },
    refused:   { bg: 'rgba(204,40,40,0.15)', color: 'var(--red)', label: 'REFUSED' },
    error:     { bg: 'rgba(204,40,40,0.15)', color: 'var(--red)', label: 'ERROR' },
  }

  return (
    <>
      {/* Summary bar */}
      {summary && (
        <div style={{ display: 'flex', gap: 16, marginBottom: 12, fontSize: 10, fontFamily: 'var(--font-mono)' }}>
          <span style={{ color: 'var(--text-3)' }}>Verified pairs: <span style={{ color: 'var(--text-1)' }}>{summary.total_pairs ?? 0}</span></span>
          <span style={{ color: 'var(--text-3)' }}>Active 24h: <span style={{ color: 'var(--green)' }}>{summary.active_24h ?? 0}</span></span>
          {(summary.stale ?? 0) > 0 && <span style={{ color: 'var(--amber)' }}>Stale: {summary.stale}</span>}
          {(summary.new_host_alerts ?? 0) > 0 && <span style={{ color: 'var(--red)' }}>New host alerts: {summary.new_host_alerts}</span>}
        </div>
      )}

      {/* New host alert banner */}
      {summary && (summary.new_host_alerts ?? 0) > 0 && (
        <div style={{
          padding: '8px 12px', marginBottom: 12,
          background: 'rgba(204,40,40,0.1)', border: '1px solid var(--red)',
          borderRadius: 2, fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--red)',
        }}>
          ⚠ {summary.new_host_alerts} credential(s) gained access to new host(s). Review below.
        </div>
      )}

      {/* Capability table */}
      <table style={{ width: '100%', borderCollapse: 'collapse', marginBottom: 12 }}>
        <thead><tr>
          <th style={_th}>CREDENTIAL</th><th style={_th}>HOST</th><th style={_th}>USER</th>
          <th style={_th}>LAST SUCCESS</th><th style={_th}>RATE</th><th style={_th}>LATENCY</th><th style={_th}>ALERT</th>
        </tr></thead>
        <tbody>
          {capabilities.map((c, i) => {
            const rate = c.success_rate ?? c.success_pct ?? 0
            const rateColor = rate < 50 ? 'var(--red)' : rate < 80 ? 'var(--amber)' : 'var(--green)'
            return (
              <tr key={i} style={c.new_host_alert ? { background: 'rgba(204,40,40,0.05)' } : undefined}>
                <td style={{ ..._td, color: 'var(--text-1)' }}>{c.connection_label || c.credential_label || '?'}</td>
                <td style={{ ..._td, fontFamily: 'var(--font-mono)' }}>{c.target_host || c.host}</td>
                <td style={_td}>{c.username || '?'}</td>
                <td style={{ ..._td, color: 'var(--text-3)' }}>{_relTime(c.last_success)}</td>
                <td style={{ ..._td, color: rateColor }}>{rate}%</td>
                <td style={{ ..._td, color: 'var(--text-3)' }}>{c.avg_latency_ms ? `${c.avg_latency_ms}ms` : '—'}</td>
                <td style={_td}>
                  {c.new_host_alert ? (
                    <button onClick={() => markReviewed(c.connection_id, c.target_host || c.host)}
                      style={{ fontSize: 8, padding: '1px 5px', borderRadius: 2, background: 'rgba(204,40,40,0.15)', color: 'var(--red)', border: '1px solid var(--red)', cursor: 'pointer', fontFamily: 'var(--font-mono)' }}>
                      🆕 NEW — Mark reviewed
                    </button>
                  ) : '—'}
                </td>
              </tr>
            )
          })}
          {capabilities.length === 0 && <tr><td colSpan={7} style={{ ..._td, color: 'var(--text-3)', textAlign: 'center' }}>No SSH capabilities recorded</td></tr>}
        </tbody>
      </table>

      {/* SSH log viewer */}
      {!showLogs ? (
        <button onClick={loadLogs} style={{ fontSize: 9, fontFamily: 'var(--font-mono)', color: 'var(--accent)', background: 'none', border: '1px solid var(--border)', padding: '3px 10px', borderRadius: 2, cursor: 'pointer' }}>
          Show recent SSH attempts
        </button>
      ) : (
        <>
          <div style={{ fontSize: 8, fontFamily: 'var(--font-mono)', color: 'var(--text-3)', letterSpacing: 1, marginBottom: 6 }}>RECENT SSH ATTEMPTS</div>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead><tr>
              <th style={_th}>TIME</th><th style={_th}>HOST</th><th style={_th}>USER</th>
              <th style={_th}>OUTCOME</th><th style={_th}>DURATION</th><th style={_th}>TRIGGERED BY</th>
            </tr></thead>
            <tbody>
              {sshLogs.map((l, i) => {
                const os = OUTCOME_STYLE[l.outcome] || OUTCOME_STYLE.error
                return (
                  <tr key={i}>
                    <td style={{ ..._td, color: 'var(--text-3)' }}>{_relTime(l.timestamp || l.attempted_at)}</td>
                    <td style={{ ..._td, fontFamily: 'var(--font-mono)' }}>{l.host || l.target_host}</td>
                    <td style={_td}>{l.username || '?'}</td>
                    <td style={_td}><span style={{ fontSize: 8, padding: '1px 5px', borderRadius: 2, background: os.bg, color: os.color }}>{os.label}</span></td>
                    <td style={{ ..._td, color: 'var(--text-3)' }}>{l.duration_ms ? `${l.duration_ms}ms` : '—'}</td>
                    <td style={{ ..._td, color: 'var(--text-3)' }}>{l.triggered_by || '—'}</td>
                  </tr>
                )
              })}
              {sshLogs.length === 0 && <tr><td colSpan={6} style={{ ..._td, color: 'var(--text-3)', textAlign: 'center' }}>No SSH attempts logged</td></tr>}
            </tbody>
          </table>
        </>
      )}
    </>
  )
}

// ── Tab: Naming ─────────────────────────────────────────────────────────────

function NamingTab({ draft, update }) {
  const name = draft?.namingPlatform || 'DEATHSTAR'
  const short = draft?.namingShort || 'DS'
  const agentPat = draft?.namingAgentPattern || '{short}-agent-{n:02d}'
  const dbName = draft?.namingDatabase || '{short}-postgres'
  const memName = draft?.namingMemory || '{short}-muninndb'
  const tagline = draft?.namingTagline || 'IMPERIAL OPS'

  const resolve = (pat) => pat.replace(/\{short\}/g, short).replace(/\{n:02d\}/g, '01')

  return (
    <div>
      <Field label="Platform Name">
        <TextInput value={name} onChange={v => update('namingPlatform', v)} placeholder="DEATHSTAR" />
      </Field>
      <Field label="Short Code">
        <TextInput value={short} onChange={v => update('namingShort', v)} placeholder="DS" />
      </Field>
      <Field label="Agent Pattern">
        <TextInput value={agentPat} onChange={v => update('namingAgentPattern', v)} placeholder="{short}-agent-{n:02d}" />
      </Field>
      <Field label="Database Name">
        <TextInput value={dbName} onChange={v => update('namingDatabase', v)} placeholder="{short}-postgres" />
      </Field>
      <Field label="Memory Store Name">
        <TextInput value={memName} onChange={v => update('namingMemory', v)} placeholder="{short}-muninndb" />
      </Field>
      <Field label="Tagline">
        <TextInput value={tagline} onChange={v => update('namingTagline', v)} placeholder="IMPERIAL OPS" />
      </Field>

      {/* Live preview */}
      <div style={{ marginTop: 12, padding: '10px 12px', background: 'var(--bg-2)', border: '1px solid var(--border)', borderRadius: 2 }}>
        <div style={{ fontSize: 8, fontFamily: 'var(--font-mono)', color: 'var(--text-3)', letterSpacing: 1, marginBottom: 6 }}>LIVE PREVIEW</div>
        {[
          ['Platform name', name],
          ['Agent #1', resolve(agentPat)],
          ['Agent #2', resolve(agentPat).replace('01', '02')],
          ['Database', resolve(dbName)],
          ['Memory store', resolve(memName)],
          ['Tagline', tagline],
        ].map(([label, val]) => (
          <div key={label} style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0', fontSize: 10 }}>
            <span style={{ color: 'var(--text-3)' }}>{label}</span>
            <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--cyan)' }}>{val || '—'}</span>
          </div>
        ))}
      </div>
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

// ── Tab: Allowlist ────────────────────────────────────────────────────────────

function AllowlistTab() {
  const [patterns, setPatterns] = useState([])
  const [loading, setLoading] = useState(true)
  const [addOpen, setAddOpen] = useState(false)
  const [form, setForm] = useState({ pattern: '', description: '', scope: 'permanent' })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const fetchPatterns = () => {
    setLoading(true)
    fetch(`${BASE}/api/vm-exec-allowlist`, { headers: { ...authHeaders() } })
      .then(r => r.ok ? r.json() : { patterns: [] })
      .then(d => { setPatterns(d.patterns || []); setLoading(false) })
      .catch(() => setLoading(false))
  }

  useEffect(() => { fetchPatterns() }, [])

  const save = async () => {
    if (!form.pattern.trim() || !form.description.trim()) {
      setError('Pattern and description are required'); return
    }
    setSaving(true); setError('')
    try {
      const r = await fetch(`${BASE}/api/vm-exec-allowlist`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify(form),
      })
      if (r.ok) {
        setForm({ pattern: '', description: '', scope: 'permanent' })
        setAddOpen(false)
        fetchPatterns()
      } else {
        const d = await r.json()
        setError(d.detail || 'Failed to add pattern')
      }
    } catch (e) { setError(e.message) }
    setSaving(false)
  }

  const remove = async (id) => {
    if (!window.confirm('Remove this pattern?')) return
    await fetch(`${BASE}/api/vm-exec-allowlist/${id}`, {
      method: 'DELETE', headers: { ...authHeaders() }
    })
    fetchPatterns()
  }

  const base = patterns.filter(p => p.is_base)
  const custom = patterns.filter(p => !p.is_base)
  const session = custom.filter(p => p.scope === 'session')
  const permanent = custom.filter(p => p.scope === 'permanent')

  const _scopeBadge = (p) => {
    if (p.is_base) return { label: 'base', bg: 'var(--bg-3)', color: 'var(--text-3)' }
    if (p.scope === 'session') return { label: 'session', bg: 'rgba(0,200,238,0.12)', color: 'var(--cyan)' }
    return { label: 'permanent', bg: 'rgba(0,170,68,0.12)', color: 'var(--green)' }
  }

  return (
    <div>
      <p className="text-xs mb-3" style={{ color: 'var(--text-3)' }}>
        Commands the agent can run via <code className="text-xs">vm_exec</code>. Base patterns are built-in.
        Custom patterns can be added permanently or per-session (auto-deleted when agent session ends).
        The agent can also request approval via <code className="text-xs">vm_exec_allowlist_request()</code>.
      </p>

      {/* Summary */}
      <div className="flex gap-4 mb-4 text-xs" style={{ color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>
        <span><span style={{ color: 'var(--text-1)' }}>{base.length}</span> base</span>
        <span><span style={{ color: 'var(--green)' }}>{permanent.length}</span> custom permanent</span>
        <span><span style={{ color: 'var(--cyan)' }}>{session.length}</span> session</span>
      </div>

      {/* Add button */}
      <div className="flex justify-between items-center mb-3">
        <span className="text-[10px] uppercase tracking-wider" style={{ color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>
          CUSTOM PATTERNS
        </span>
        <button
          onClick={() => setAddOpen(o => !o)}
          className="text-[10px] px-2 py-1 rounded"
          style={{ background: 'var(--accent-dim)', color: 'var(--accent)', border: '1px solid var(--accent)' }}
        >
          {addOpen ? 'Cancel' : '+ Add Pattern'}
        </button>
      </div>

      {/* Add form */}
      {addOpen && (
        <div className="mb-4 p-3 rounded" style={{ background: 'var(--bg-2)', border: '1px solid var(--border)' }}>
          <div className="mb-2">
            <label className="text-[10px] block mb-1" style={{ color: 'var(--text-3)' }}>Regex pattern</label>
            <input
              className="w-full text-[10px] px-2 py-1 rounded"
              style={{ background: 'var(--bg-3)', border: '1px solid var(--border)', color: 'var(--text-1)', fontFamily: 'var(--font-mono)' }}
              placeholder={String.raw`^ss\b`}
              value={form.pattern}
              onChange={e => setForm(f => ({ ...f, pattern: e.target.value }))}
            />
          </div>
          <div className="mb-2">
            <label className="text-[10px] block mb-1" style={{ color: 'var(--text-3)' }}>Description</label>
            <input
              className="w-full text-[10px] px-2 py-1 rounded"
              style={{ background: 'var(--bg-3)', border: '1px solid var(--border)', color: 'var(--text-1)' }}
              placeholder="Socket statistics (ss -tlnp)"
              value={form.description}
              onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
            />
          </div>
          <div className="mb-3">
            <label className="text-[10px] block mb-1" style={{ color: 'var(--text-3)' }}>Scope</label>
            <div className="flex gap-3">
              {[['permanent', 'Permanent'], ['session', 'Session only']].map(([v, l]) => (
                <label key={v} className="flex items-center gap-1.5 cursor-pointer text-[10px]" style={{ color: 'var(--text-1)' }}>
                  <input type="radio" value={v} checked={form.scope === v} onChange={() => setForm(f => ({ ...f, scope: v }))} />
                  {l}
                </label>
              ))}
            </div>
          </div>
          {error && <div className="text-[10px] mb-2" style={{ color: 'var(--red)' }}>{error}</div>}
          <button
            onClick={save} disabled={saving}
            className="text-[10px] px-3 py-1 rounded"
            style={{ background: 'var(--accent)', color: '#fff', opacity: saving ? 0.5 : 1 }}
          >
            {saving ? 'Adding...' : 'Add Pattern'}
          </button>
        </div>
      )}

      {/* Custom patterns */}
      {custom.length === 0 && !addOpen && (
        <div className="text-[10px] mb-4" style={{ color: 'var(--text-3)' }}>
          No custom patterns. The agent can request additions via <code>vm_exec_allowlist_request()</code>.
        </div>
      )}
      {custom.map(p => {
        const badge = _scopeBadge(p)
        return (
          <div key={p.id} className="flex items-start justify-between mb-2 p-2 rounded"
               style={{ background: 'var(--bg-2)', border: '1px solid var(--border)' }}>
            <div className="min-w-0">
              <div className="flex items-center gap-2 mb-0.5">
                <span className="text-[10px]" style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-1)' }}>{p.pattern}</span>
                <span className="text-[8px] px-1.5 py-px rounded" style={{ background: badge.bg, color: badge.color }}>{badge.label}</span>
              </div>
              <div className="text-[9px]" style={{ color: 'var(--text-3)' }}>
                {p.description}
                {p.added_by && p.added_by !== 'system' && ` · added by ${p.added_by}`}
                {p.approved_by && ` · approved by ${p.approved_by}`}
              </div>
            </div>
            <button
              onClick={() => remove(p.id)}
              className="text-[9px] ml-2 flex-shrink-0"
              style={{ color: 'var(--red)', background: 'none', border: 'none', cursor: 'pointer' }}
            >X</button>
          </div>
        )
      })}

      {/* Base patterns (collapsible) */}
      <details className="mt-4">
        <summary className="text-[10px] cursor-pointer" style={{ color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>
          BASE PATTERNS ({base.length}) — built-in, read-only
        </summary>
        <div className="mt-2 space-y-1">
          {base.map(p => (
            <div key={p.pattern} className="flex items-center gap-2 px-2 py-1 rounded"
                 style={{ background: 'var(--bg-2)' }}>
              <span className="text-[9px] flex-1" style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-3)' }}>{p.pattern}</span>
              <span className="text-[9px]" style={{ color: 'var(--text-3)' }}>{p.description}</span>
            </div>
          ))}
        </div>
      </details>

      {loading && <div className="text-[10px] mt-2" style={{ color: 'var(--text-3)' }}>Loading...</div>}
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
                {tab === 'Allowlist'      && <AllowlistTab />}
                {tab === 'Permissions'    && <PermissionsTab />}
                {tab === 'Access'        && <AccessTab />}
                {tab === 'Naming'        && <NamingTab         draft={draft} update={update} />}
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

export function NotificationsTab({ draft, update }) {
  const [testResult, setTestResult] = useState(null)
  const [testing, setTesting]       = useState(false)

  const testWebhook = async () => {
    setTesting(true)
    setTestResult(null)
    try {
      const r = await fetch(`${BASE}/api/alerts/test-webhook`, {
        method: 'POST',
        headers: authHeaders(),
      })
      const d = await r.json()
      setTestResult(d)
    } catch (e) {
      setTestResult({ ok: false, message: e.message })
    } finally {
      setTesting(false)
    }
  }

  return (
    <div>
      <Field label="Webhook URL" hint="Receives a JSON POST on every warning or critical alert. Compatible with Slack, Discord, ntfy, Gotify, and custom endpoints.">
        <input
          className="input text-[10px]"
          type="url"
          placeholder="https://hooks.slack.com/... or https://ntfy.sh/your-topic"
          value={draft.notificationWebhookUrl ?? ''}
          onChange={e => update('notificationWebhookUrl', e.target.value)}
        />
      </Field>

      <Field label="Notify on Recovery" hint="Also send a notification when a service recovers to healthy.">
        <Toggle
          value={!!draft.notifyOnRecovery}
          onChange={v => update('notifyOnRecovery', v)}
          label="Send recovery notifications"
        />
      </Field>

      <div className="mt-6 flex items-center gap-3">
        <button
          onClick={testWebhook}
          disabled={testing || !draft.notificationWebhookUrl}
          className="btn-secondary text-sm"
        >
          {testing ? 'Sending…' : 'Send test notification'}
        </button>

        {testResult && (
          <span className={`text-sm ${testResult.ok ? 'text-green-400' : 'text-red-400'}`}>
            {testResult.ok ? '✓' : '✗'} {testResult.message}
          </span>
        )}
      </div>

      <p className="mt-6 text-xs opacity-40">
        Payload schema: platform, severity, component, message, timestamp, connection_label, connection_id
      </p>
    </div>
  )
}

// Named exports for SettingsPage
export { GeneralTab, InfrastructureTab, AIServicesTab, ConnectionsTab, AllowlistTab, PermissionsTab, AccessTab, NamingTab, DisplayTab, UpdateStatus }
