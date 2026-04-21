/**
 * OptionsModal — 4-tab settings modal.
 * Reads/writes via OptionsContext → localStorage + POST /api/settings.
 */
import { useState, useEffect } from 'react'
import { Settings, X } from 'lucide-react'
import { useOptions } from '../context/OptionsContext'
import { authHeaders } from '../api'
import RotationTestModal from './RotationTestModal'
import CardTemplateEditor from './CardTemplateEditor'
import { CONTAINER_SCHEMA, SWARM_SERVICE_SCHEMA, DEFAULT_TEMPLATES } from '../schemas/cardSchemas'
import CollapsibleSection from './CollapsibleSection'

const BASE = import.meta.env.VITE_API_BASE ?? ''

export const TABS = ['General', 'Infrastructure', 'AI Services', 'Connections', 'Allowlist', 'Permissions', 'Facts Permissions', 'Access', 'Naming', 'Appearance', 'Notifications', 'Layouts']

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

      {/* ── Rotation Test Settings ─────────────────────────────────────────── */}
      <div className="mb-5 pb-4" style={{ borderBottom: '1px solid var(--border)' }}>
        <div style={{ fontSize: 10, fontFamily: 'var(--font-mono)', fontWeight: 700,
          color: 'var(--text-2)', letterSpacing: 1, marginBottom: 8 }}>
          CREDENTIAL ROTATION TESTING
        </div>
        <p style={{ fontSize: 9, color: 'var(--text-3)', marginBottom: 10 }}>
          Controls how credential rotation tests run against linked connections.
          Use sequential mode or higher delays for Windows accounts to prevent domain lockouts.
        </p>

        <Field label="Test mode"
          hint="Adaptive: sequential for Windows profiles (lockout risk), parallel for SSH/API.">
          <Select
            value={draft.rotationTestMode || 'adaptive'}
            onChange={v => update('rotationTestMode', v)}
            options={[
              ['adaptive',   'Adaptive (recommended — auto per auth type)'],
              ['parallel',   'Parallel (fastest — all connections at once)'],
              ['sequential', 'Sequential (safest — one at a time with delay)'],
            ]}
          />
        </Field>

        <Field label="Sequential delay (ms)"
          hint="Time between tests in sequential mode or between Windows tests. Default: 500ms.">
          <input
            type="number" min="0" max="30000" step="100"
            value={draft.rotationTestDelayMs ?? 500}
            onChange={e => update('rotationTestDelayMs', e.target.value)}
            style={{ width: 100, background: 'var(--bg-2)', border: '1px solid var(--border)',
              borderRadius: 2, padding: '3px 8px', fontSize: 10, color: 'var(--text-1)', outline: 'none' }}
          />
          <span style={{ fontSize: 9, color: 'var(--text-3)', marginLeft: 6 }}>ms</span>
        </Field>

        <Field label="Windows profile delay (ms)"
          hint="Additional delay between tests for Windows profiles. Prevents AD lockout. Default: 2000ms.">
          <input
            type="number" min="0" max="60000" step="500"
            value={draft.rotationWindowsDelayMs ?? 2000}
            onChange={e => update('rotationWindowsDelayMs', e.target.value)}
            style={{ width: 100, background: 'var(--bg-2)', border: '1px solid var(--border)',
              borderRadius: 2, padding: '3px 8px', fontSize: 10, color: 'var(--text-1)', outline: 'none' }}
          />
          <span style={{ fontSize: 9, color: 'var(--text-3)', marginLeft: 6 }}>ms</span>
        </Field>

        <Field label="Max parallel tests"
          hint="Maximum concurrent SSH/API connections during parallel rotation tests. Default: 10.">
          <input
            type="number" min="1" max="100"
            value={draft.rotationMaxParallel ?? 10}
            onChange={e => update('rotationMaxParallel', e.target.value)}
            style={{ width: 80, background: 'var(--bg-2)', border: '1px solid var(--border)',
              borderRadius: 2, padding: '3px 8px', fontSize: 10, color: 'var(--text-1)', outline: 'none' }}
          />
        </Field>

        <div style={{ fontSize: 9, color: 'var(--text-3)', padding: '6px 8px', borderRadius: 2,
          background: 'rgba(204,136,0,0.06)', border: '1px solid rgba(204,136,0,0.2)', marginTop: 4 }}>
          ⚠ Windows/domain accounts: use sequential mode with ≥2000ms delay. Most AD environments
          lock accounts after 5–10 failed attempts within a window. Test on one connection manually first.
        </div>
      </div>
      {/* ── end Rotation Test Settings ─────────────────────────────────────── */}
    </div>
  )
}

// ── Tab: Infrastructure ───────────────────────────────────────────────────────

/**
 * DiscoveryScopeList — editable list of CIDR/subnet strings with validation.
 * value: JSON string or array of scope strings
 * onChange: called with new JSON string
 */
function DiscoveryScopeList({ value, onChange }) {
  // Parse existing scopes from JSON string or array
  const _parse = (v) => {
    if (!v) return []
    if (Array.isArray(v)) return v
    try { return JSON.parse(v) } catch { return [] }
  }
  const scopes = _parse(value)

  const [input, setInput] = useState('')
  const [inputError, setInputError] = useState('')

  // Client-side CIDR/subnet validation
  const _validate = (raw) => {
    const s = raw.trim()
    if (!s) return { ok: false, error: 'Empty input' }
    // Reject any characters that could be SQL/injection attempts
    if (/['";\\\n\r\x00-\x1f]/.test(s)) return { ok: false, error: 'Invalid characters' }
    if (s.length > 50) return { ok: false, error: 'Too long' }
    // CIDR notation: x.x.x.x/n
    const cidrMatch = s.match(/^(\d{1,3}\.){3}\d{1,3}\/(\d{1,2})$/)
    if (cidrMatch) {
      const parts = s.split('/')[0].split('.').map(Number)
      const prefix = parseInt(s.split('/')[1])
      if (parts.every(p => p >= 0 && p <= 255) && prefix >= 0 && prefix <= 32) {
        return { ok: true, canonical: s }
      }
      return { ok: false, error: 'Invalid CIDR range' }
    }
    // Subnet mask: x.x.x.x y.y.y.y
    const maskMatch = s.match(/^(\d{1,3}\.){3}\d{1,3}\s+(\d{1,3}\.){3}\d{1,3}$/)
    if (maskMatch) {
      const [ipPart, maskPart] = s.split(/\s+/)
      const ipOctets = ipPart.split('.').map(Number)
      const maskOctets = maskPart.split('.').map(Number)
      if (ipOctets.every(p => p >= 0 && p <= 255) && maskOctets.every(p => p >= 0 && p <= 255)) {
        // Convert to CIDR notation
        const maskBits = maskOctets.map(o => o.toString(2).padStart(8, '0')).join('')
        const prefixLen = maskBits.split('').filter(b => b === '1').length
        return { ok: true, canonical: `${ipPart}/${prefixLen}` }
      }
      return { ok: false, error: 'Invalid subnet mask' }
    }
    return { ok: false, error: 'Format must be CIDR (192.168.0.0/24) or subnet mask (192.168.0.0 255.255.255.0)' }
  }

  const add = () => {
    const { ok, canonical, error } = _validate(input)
    if (!ok) { setInputError(error); return }
    if (scopes.includes(canonical)) { setInputError('Already in list'); return }
    setInputError('')
    const updated = [...scopes, canonical]
    onChange(JSON.stringify(updated))
    setInput('')
  }

  const remove = (scope) => {
    onChange(JSON.stringify(scopes.filter(s => s !== scope)))
  }

  return (
    <div>
      {/* Existing scopes */}
      <div style={{ marginBottom: 6 }}>
        {scopes.length === 0 ? (
          <div style={{ fontSize: 9, color: 'var(--text-3)', fontStyle: 'italic' }}>
            No scope restrictions — all discovered IPs will be shown
          </div>
        ) : (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {scopes.map((s, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '2px 8px',
                borderRadius: 2, background: 'var(--bg-3)', border: '1px solid var(--border)' }}>
                <span style={{ fontSize: 9, color: 'var(--cyan)', fontFamily: 'var(--font-mono)' }}>{s}</span>
                <button onClick={() => remove(s)}
                  style={{ background: 'none', border: 'none', color: 'var(--red)', cursor: 'pointer',
                    fontSize: 9, padding: 0, lineHeight: 1 }}>✕</button>
              </div>
            ))}
          </div>
        )}
      </div>
      {/* Add input */}
      <div style={{ display: 'flex', gap: 6, alignItems: 'flex-start' }}>
        <div style={{ flex: 1 }}>
          <input
            value={input}
            onChange={e => { setInput(e.target.value); setInputError('') }}
            onKeyDown={e => e.key === 'Enter' && add()}
            placeholder="192.168.199.0/24  or  10.0.0.0 255.0.0.0"
            style={{ width: '100%', background: 'var(--bg-2)', border: `1px solid ${inputError ? 'var(--red)' : 'var(--border)'}`,
              borderRadius: 2, padding: '3px 8px', fontSize: 9, color: 'var(--text-1)',
              fontFamily: 'var(--font-mono)', outline: 'none' }}
          />
          {inputError && (
            <div style={{ fontSize: 8, color: 'var(--red)', marginTop: 2 }}>{inputError}</div>
          )}
        </div>
        <button onClick={add}
          style={{ fontSize: 9, padding: '3px 10px', borderRadius: 2, cursor: 'pointer', flexShrink: 0,
            background: 'var(--bg-3)', border: '1px solid var(--border)', color: 'var(--text-2)' }}>
          + Add
        </button>
      </div>
    </div>
  )
}

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
      {/* ── Discovery Settings ─────────────────────────────────────────────── */}
      <div className="mb-5 pb-4" style={{ borderBottom: '1px solid var(--border)' }}>
        <div style={{ fontSize: 10, fontFamily: 'var(--font-mono)', fontWeight: 700,
          color: 'var(--text-2)', letterSpacing: 1, marginBottom: 8 }}>
          DEVICE DISCOVERY
        </div>
        <p style={{ fontSize: 9, color: 'var(--text-3)', marginBottom: 10 }}>
          Passive harvest from Proxmox, UniFi, and Swarm. Scope limits which IPs appear in the Discovered view.
          Active network scanning is not performed — only devices already visible from integrated sources are harvested.
        </p>

        <Field label="Enable Discovery">
          <Toggle
            value={draft.discoveryEnabled === 'true' || draft.discoveryEnabled === true}
            onChange={v => update('discoveryEnabled', String(v))}
            label="Allow harvest from Proxmox / UniFi / Swarm"
          />
        </Field>

        <Field label="Discovery Scopes"
          hint="Only IPs within these ranges will appear in Discovered. Leave empty to show all. Accepts CIDR (192.168.0.0/24) or subnet mask (192.168.0.0 255.255.255.0).">
          <DiscoveryScopeList
            value={draft.discoveryScopes}
            onChange={v => update('discoveryScopes', v)}
          />
        </Field>
      </div>
      {/* ── end Discovery Settings ─────────────────────────────────────────── */}

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
        <Field label="Auto-Update" hint="Auto-pull + restart when a newer version is available">
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
        <Field label="Auto-Update Interval (s)" hint="How often the auto-update task checks GHCR. Default: 300 (5 min).">
          <TextInput
            type="number"
            value={draft.autoUpdateInterval ?? 300}
            onChange={v => update('autoUpdateInterval', v === '' ? '' : Number(v))}
            placeholder="300"
          />
        </Field>
        <Field label="Version-Check Cache TTL (s)" hint="How long GHCR tag results are cached in memory. Lower = faster pickup of new pushes, more API calls. Default: 600 (10 min).">
          <TextInput
            type="number"
            value={draft.ghcrTagCacheTTL ?? 600}
            onChange={v => update('ghcrTagCacheTTL', v === '' ? '' : Number(v))}
            placeholder="600"
          />
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
      const r = await fetch(`${BASE}/api/settings/test-external-ai`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({
          provider: draft.externalProvider,
          // Send the typed key only if user typed a new one; backend falls back
          // to the saved DB value when this is empty or masked (contains '***').
          api_key:  draft.externalApiKey || '',
          model:    draft.externalModel  || '',
        }),
      })
      const d = await r.json()
      if (d.ok) {
        const toks = (d.input_tokens != null && d.output_tokens != null)
          ? ` · ${d.input_tokens}/${d.output_tokens} tok`
          : ''
        setExtTest({ ok: true, msg: `OK (${d.latency_ms}ms) — ${d.model}${toks}` })
      } else {
        const stage = d.stage ? `[${d.stage}] ` : ''
        setExtTest({ ok: false, msg: `${stage}${d.error || 'Failed'}` })
      }
    } catch (e) {
      setExtTest({ ok: false, msg: e.message })
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
      <CollapsibleSection title="Local AI (LM Studio)" storageKey="ai.local">
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
      </CollapsibleSection>

      <CollapsibleSection title="External AI — Provider" storageKey="ai.external.provider">
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
            {extTest.msg}
          </p>
        )}
      </CollapsibleSection>

      <CollapsibleSection title="External AI — Routing Mode" storageKey="ai.external.routing">
        <label className="block text-xs uppercase text-gray-400 mb-1">Mode</label>
        <div className="flex gap-4 mb-3">
          {['off', 'manual', 'auto'].map(m => (
            <label key={m} className="flex items-center gap-2 text-sm">
              <input
                type="radio"
                name="externalRoutingMode"
                checked={draft.externalRoutingMode === m}
                onChange={() => update('externalRoutingMode', m)}
              />
              {m}
            </label>
          ))}
        </div>
        <p className="text-xs text-gray-500 mb-3">
          <b>off</b>: no routing, no external calls.{' '}
          <b>manual</b>: operator-only via UI button (not implemented in v2.36.x).{' '}
          <b>auto</b>: router fires on rules below.
        </p>

        <label className="block text-xs uppercase text-gray-400 mt-3 mb-1">Output Mode</label>
        <div className="flex gap-4">
          {['replace'].map(m => (
            <label key={m} className="flex items-center gap-2 text-sm">
              <input
                type="radio"
                name="externalRoutingOutputMode"
                checked={draft.externalRoutingOutputMode === m}
                onChange={() => update('externalRoutingOutputMode', m)}
                disabled={m !== 'replace'}
              />
              {m}
            </label>
          ))}
        </div>
        <p className="text-xs text-gray-500 mt-1">
          REPLACE: external AI synthesises final_answer from local evidence, local
          agent does not continue. Other modes (ADVISE / TAKEOVER) deferred to
          v2.36.5+.
        </p>
      </CollapsibleSection>

      <CollapsibleSection title="External AI — Routing Triggers"
                          storageKey="ai.external.triggers"
                          defaultOpen={false}>
        <p className="text-xs text-gray-500 mb-3">
          Rules OR'd; first match wins in priority order. Set a numeric threshold
          to 0 to disable that rule.
        </p>

        <label className="flex items-center gap-2 text-sm mb-2">
          <input type="checkbox"
                 checked={!!draft.routeOnGateFailure}
                 onChange={e => update('routeOnGateFailure', e.target.checked)} />
          <span><b>gate_failure</b> — escalate on hallucination guard exhausted or
            fabrication detected ≥ 2x</span>
        </label>

        <label className="flex items-center gap-2 text-sm mb-2">
          <input type="checkbox"
                 checked={!!draft.routeOnBudgetExhaustion}
                 onChange={e => update('routeOnBudgetExhaustion', e.target.checked)} />
          <span><b>budget_exhaustion</b> — escalate if tool budget hit with no
            DIAGNOSIS: emitted</span>
        </label>

        <div className="flex items-center gap-2 text-sm mb-2">
          <span className="min-w-[200px]"><b>consecutive_failures</b> threshold:</span>
          <input type="number" min="0" max="20" value={draft.routeOnConsecutiveFailures ?? 0}
                 onChange={e => update('routeOnConsecutiveFailures', parseInt(e.target.value)||0)}
                 className="w-16 bg-[var(--bg-1)] border border-white/10 px-2 py-1 text-sm" />
          <span className="text-xs text-gray-500">(0 = disabled)</span>
        </div>

        <div className="flex items-center gap-2 text-sm mb-2">
          <span className="min-w-[200px]"><b>prior_attempts</b> threshold (7d):</span>
          <input type="number" min="0" max="20" value={draft.routeOnPriorAttemptsGte ?? 0}
                 onChange={e => update('routeOnPriorAttemptsGte', parseInt(e.target.value)||0)}
                 className="w-16 bg-[var(--bg-1)] border border-white/10 px-2 py-1 text-sm" />
          <span className="text-xs text-gray-500">(0 = disabled)</span>
        </div>

        <div className="mt-3">
          <label className="block text-xs uppercase text-gray-400 mb-1">
            complexity_prefilter keywords (comma-separated)
          </label>
          <input type="text"
                 value={draft.routeOnComplexityKeywords || ''}
                 onChange={e => update('routeOnComplexityKeywords', e.target.value)}
                 placeholder="correlate, root cause, why"
                 className="w-full bg-[var(--bg-1)] border border-white/10 px-2 py-1 text-sm" />
          <div className="flex items-center gap-2 text-sm mt-2">
            <span className="min-w-[200px]">min prior attempts:</span>
            <input type="number" min="0" max="20"
                   value={draft.routeOnComplexityMinPriorAttempts ?? 2}
                   onChange={e => update('routeOnComplexityMinPriorAttempts', parseInt(e.target.value)||0)}
                   className="w-16 bg-[var(--bg-1)] border border-white/10 px-2 py-1 text-sm" />
          </div>
        </div>
      </CollapsibleSection>

      <CollapsibleSection title="External AI — Limits"
                          storageKey="ai.external.limits"
                          defaultOpen={false}>
        <label className="flex items-center gap-2 text-sm mb-3">
          <input type="checkbox"
                 checked={!!draft.requireConfirmation}
                 onChange={e => update('requireConfirmation', e.target.checked)} />
          <span>Require operator confirmation before each external AI call</span>
        </label>

        <div className="flex items-center gap-2 text-sm mb-2">
          <span className="min-w-[220px]">Max external calls per operation:</span>
          <input type="number" min="1" max="20" value={draft.routeMaxExternalCallsPerOp ?? 3}
                 onChange={e => update('routeMaxExternalCallsPerOp', parseInt(e.target.value)||3)}
                 className="w-16 bg-[var(--bg-1)] border border-white/10 px-2 py-1 text-sm" />
        </div>

        <div className="flex items-center gap-2 text-sm mb-2">
          <span className="min-w-[220px]">Confirmation timeout (seconds):</span>
          <input type="number" min="30" max="3600"
                 value={draft.externalConfirmTimeoutSeconds ?? 300}
                 onChange={e => update('externalConfirmTimeoutSeconds', parseInt(e.target.value)||300)}
                 className="w-20 bg-[var(--bg-1)] border border-white/10 px-2 py-1 text-sm" />
        </div>

        <div className="flex items-center gap-2 text-sm">
          <span className="min-w-[220px]">Context handoff: last N tool results:</span>
          <input type="number" min="0" max="20"
                 value={draft.externalContextLastNToolResults ?? 5}
                 onChange={e => update('externalContextLastNToolResults', parseInt(e.target.value)||5)}
                 className="w-16 bg-[var(--bg-1)] border border-white/10 px-2 py-1 text-sm" />
        </div>
      </CollapsibleSection>

      <CollapsibleSection title="Escalation Policy" storageKey="ai.escalation" defaultOpen={false}>
        <Field label="Auto-escalate on">
          <div className="flex gap-4">
            {[['failure', 'Failure'], ['degraded', 'Degraded'], ['both', 'Both']].map(([v, l]) => (
              <Radio key={v} name="autoEscalate" value={v} current={draft.autoEscalate} onChange={v => update('autoEscalate', v)} label={l} />
            ))}
          </div>
        </Field>
      </CollapsibleSection>

      <CollapsibleSection title="Coordinator" storageKey="ai.coordinator" defaultOpen={false}>
        <Field label="Inject prior attempts context"
          hint="When a task scopes an entity, show the agent up to 3 prior attempts on that entity from the last 7 days. Helps avoid repeating failed tool chains.">
          <Toggle
            value={draft.coordinatorPriorAttemptsEnabled !== false}
            onChange={v => update('coordinatorPriorAttemptsEnabled', v)}
            label="Enabled"
          />
        </Field>
      </CollapsibleSection>

      <CollapsibleSection title="Elasticsearch" storageKey="ai.elastic" defaultOpen={false}>
        <Field label="Schema discovery on filter miss"
          hint="When elastic_search_logs returns 0 hits but the time window has data, sample 2-3 real docs and attach available fields + suggested filters to the response. Helps the agent discover correct field names (service.name vs container.name, etc.) instead of narrowing further.">
          <Toggle
            value={draft.elasticSchemaDiscoveryOnMiss !== false}
            onChange={v => update('elasticSchemaDiscoveryOnMiss', v)}
            label="Enabled"
          />
        </Field>
      </CollapsibleSection>

      {/* Agent Budgets (v2.36.5) */}
      <div className="mt-6 pt-4 border-t border-white/10">
        <h3 className="text-sm font-mono uppercase tracking-wider text-[var(--accent)] mb-1">
          Agent Budgets
        </h3>
        <p className="text-xs text-gray-500 mb-3">
          Tool call budget per agent type. When reached, the loop forces
          synthesis and status becomes 'capped'. Raising a value lets the
          agent gather more evidence before synthesising. Safe range 4..100.
          Changes take effect on the next task — no restart needed.
        </p>
        <div className="grid grid-cols-2 gap-3">
          {[
            ['agentToolBudget_observe',     'Observe',     'status checks, read-only'],
            ['agentToolBudget_investigate', 'Investigate', 'why/diagnose/logs'],
            ['agentToolBudget_execute',     'Execute',     'fix/restart/deploy'],
            ['agentToolBudget_build',       'Build',       'skill management'],
          ].map(([key, label, hint]) => (
            <div key={key}>
              <label className="block text-xs uppercase text-gray-400 mb-1">
                {label}
                <span className="ml-2 normal-case text-gray-500">— {hint}</span>
              </label>
              <input
                type="number"
                min="4"
                max="100"
                value={draft[key] ?? ''}
                onChange={e => update(key, parseInt(e.target.value) || 0)}
                className="w-24 bg-[var(--bg-1)] border border-white/10 px-2 py-1 text-sm"
              />
            </div>
          ))}
        </div>

        {/* v2.36.8 — LARGE-LIST RENDERING prompt toggle (dark launch) */}
        <div className="mt-4 pt-3 border-t border-white/5">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={!!draft.renderToolPromptEnabled}
              onChange={e => update('renderToolPromptEnabled', e.target.checked)}
            />
            <span>
              Enable LARGE-LIST RENDERING prompt (v2.36.8 — dark launch)
            </span>
          </label>
          <div className="text-xs text-gray-500 ml-6 mt-1">
            Teaches the agent to call result_render_table for lists over
            ~15 items instead of enumerating rows in prose.
          </div>
        </div>
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

function CardTemplatesSection() {
  const [activeCardType, setActiveCardType] = useState(null)  // which editor is open
  const [saving, setSaving] = useState(false)
  const [savedMsg, setSavedMsg] = useState('')
  const [templates, setTemplates] = useState({})

  const CARD_TYPES = [
    { key: 'container',     label: 'Container (agent-01)',    schema: CONTAINER_SCHEMA },
    { key: 'swarm_service', label: 'Swarm Service',           schema: SWARM_SERVICE_SCHEMA },
  ]

  const fetchTemplates = async () => {
    try {
      const r = await fetch(`${BASE}/api/card-templates/defaults`, { headers: authHeaders() })
      if (r.ok) {
        const d = await r.json()
        setTemplates(d)
      }
    } catch { /* silent */ }
  }

  useEffect(() => { fetchTemplates() }, [])

  const saveTemplate = async (cardType, template) => {
    setSaving(true)
    setSavedMsg('')
    try {
      const r = await fetch(`${BASE}/api/card-templates/type/${cardType}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ template }),
      })
      if (r.ok) {
        setSavedMsg(`${cardType} template saved`)
        setActiveCardType(null)
        fetchTemplates()
        // Invalidate frontend cache
        const { invalidateCardTypeCache } = await import('../hooks/useCardTemplate')
        invalidateCardTypeCache(cardType)
      } else {
        const d = await r.json()
        setSavedMsg(d.detail || 'Save failed')
      }
    } catch (e) {
      setSavedMsg('Save failed: ' + e.message)
    }
    setSaving(false)
  }

  return (
    <div>
      {/* Card type selector */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
        {CARD_TYPES.map(({ key, label }) => (
          <button key={key}
            onClick={() => setActiveCardType(activeCardType === key ? null : key)}
            style={{ fontSize: 9, padding: '4px 12px', borderRadius: 2, cursor: 'pointer',
              fontFamily: 'var(--font-mono)', letterSpacing: 0.5,
              background: activeCardType === key ? 'var(--accent-dim)' : 'var(--bg-3)',
              color: activeCardType === key ? 'var(--accent)' : 'var(--text-3)',
              border: `1px solid ${activeCardType === key ? 'var(--accent)' : 'var(--border)'}` }}>
            {label.toUpperCase()}
          </button>
        ))}
      </div>

      {savedMsg && (
        <div style={{ fontSize: 9, color: savedMsg.includes('failed') ? 'var(--red)' : 'var(--green)',
          marginBottom: 8 }}>
          {savedMsg.includes('failed') ? '✕' : '✓'} {savedMsg}
        </div>
      )}

      {/* Editor panel */}
      {activeCardType && (() => {
        const ct = CARD_TYPES.find(c => c.key === activeCardType)
        if (!ct) return null
        return (
          <CardTemplateEditor
            key={activeCardType}
            cardType={activeCardType}
            schema={ct.schema}
            initialTemplate={templates[activeCardType] || {}}
            title={`${ct.label} — drag fields between sections`}
            onSave={(template) => saveTemplate(activeCardType, template)}
            onCancel={() => setActiveCardType(null)}
          />
        )
      })()}
    </div>
  )
}

const ACCENT_PRESETS = [
  { key: 'crimson', label: 'Imperial Crimson', color: '#a01828' },
  { key: 'blue',    label: 'Republic Blue',    color: '#1a56e8' },
  { key: 'purple',  label: 'Sith Purple',      color: '#7c3aed' },
  { key: 'teal',    label: 'Officer Teal',     color: '#0891b2' },
  { key: 'orange',  label: 'Droid Orange',     color: '#c2410c' },
  { key: 'green',   label: 'Jedi Green',       color: '#047857' },
]

function DisplayTab({ draft, update }) {
  const minH = draft.cardMinHeight ?? 70
  const maxH = draft.cardMaxHeight ?? 200
  const minW = draft.cardMinWidth  ?? 300
  const maxW = draft.cardMaxWidth

  const heightInvalid = minH != null && maxH != null && Number(minH) >= Number(maxH)
  const widthInvalid  = minW != null && maxW != null && Number(minW) >= Number(maxW)

  return (
    <div>

      {/* ── Theme & Accent ─────────────────────────────────────────────── */}
      <div style={{ marginBottom: 20 }}>
        <h3 className="text-xs font-bold text-[color:var(--text-2)] uppercase tracking-wider mb-3 border-b border-[color:var(--border)] pb-1">
          Theme
        </h3>

        <Field label="Color mode">
          <div className="flex gap-4">
            {[['dark', 'Dark'], ['light', 'Light'], ['system', 'System']].map(([v, l]) => (
              <Radio key={v} name="theme" value={v} current={draft.theme} onChange={v => update('theme', v)} label={l} />
            ))}
          </div>
        </Field>

        <Field label="Accent color">
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {ACCENT_PRESETS.map(({ key, label, color }) => {
              const active = (draft.accentColor || 'crimson') === key
              return (
                <button
                  key={key}
                  onClick={() => update('accentColor', key)}
                  title={label}
                  style={{
                    width: 26, height: 26, borderRadius: 'var(--radius-btn)',
                    background: color, border: `2px solid ${active ? 'var(--text-1)' : 'transparent'}`,
                    cursor: 'pointer', outline: active ? `2px solid ${color}` : 'none',
                    outlineOffset: 2, transition: 'all 0.1s',
                    boxShadow: active ? `0 0 8px ${color}80` : 'none',
                  }}
                />
              )
            })}
          </div>
          <div style={{ fontSize: 9, color: 'var(--text-3)', marginTop: 4 }}>
            {ACCENT_PRESETS.find(p => p.key === (draft.accentColor || 'crimson'))?.label}
          </div>
        </Field>
      </div>

      {/* ── Typography ─────────────────────────────────────────────────── */}
      <div style={{ marginBottom: 20 }}>
        <h3 className="text-xs font-bold text-[color:var(--text-2)] uppercase tracking-wider mb-3 border-b border-[color:var(--border)] pb-1">
          Typography
        </h3>

        <Field label="Font size">
          <div className="flex gap-4">
            {[['small', 'Small (11px)'], ['medium', 'Medium (13px)'], ['large', 'Large (15px)']].map(([v, l]) => (
              <Radio key={v} name="fontSize" value={v} current={draft.fontSize || 'medium'} onChange={v => update('fontSize', v)} label={l} />
            ))}
          </div>
        </Field>

        <Field label="Font style" hint="Controls UI labels, values, and section text.">
          <div className="flex gap-4">
            {[
              ['mono',  'Monospace (Share Tech Mono)'],
              ['mixed', 'Mixed (Rajdhani sans-serif)'],
              ['sans',  'Clean (Inter sans-serif)'],
            ].map(([v, l]) => (
              <Radio key={v} name="fontStyle" value={v} current={draft.fontStyle || 'mono'} onChange={v => update('fontStyle', v)} label={l} />
            ))}
          </div>
        </Field>
      </div>

      {/* ── Layout & Shape ─────────────────────────────────────────────── */}
      <div style={{ marginBottom: 20 }}>
        <h3 className="text-xs font-bold text-[color:var(--text-2)] uppercase tracking-wider mb-3 border-b border-[color:var(--border)] pb-1">
          Layout &amp; Shape
        </h3>

        <Field label="UI density">
          <div className="flex gap-4">
            {[['compact', 'Compact'], ['normal', 'Normal'], ['comfortable', 'Comfortable']].map(([v, l]) => (
              <Radio key={v} name="uiDensity" value={v} current={draft.uiDensity || 'normal'} onChange={v => update('uiDensity', v)} label={l} />
            ))}
          </div>
        </Field>

        <Field label="Border radius" hint="Applies to cards, buttons, and pills.">
          <div className="flex gap-4">
            {[['sharp', 'Sharp (2px)'], ['soft', 'Soft (4px)'], ['round', 'Round (8px)']].map(([v, l]) => (
              <Radio key={v} name="borderRadius" value={v} current={draft.borderRadius || 'sharp'} onChange={v => update('borderRadius', v)} label={l} />
            ))}
          </div>
        </Field>
      </div>

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

      <Field label="Recent tasks count"
        hint="Number of unique recent tasks shown in the RECENT section below templates (deduplicated by task text). Range 1–50. Default 10.">
        <div className="flex items-center gap-2">
          <input
            type="number"
            min={1} max={50}
            value={draft.recentTasksCount ?? 10}
            onChange={e => update('recentTasksCount',
              Math.max(1, Math.min(50, parseInt(e.target.value, 10) || 10)))}
            className="w-20 bg-[color:var(--bg-2)] border border-[color:var(--border)] rounded px-2 py-1.5 text-xs text-[color:var(--text-1)] focus:outline-none"
          />
          <span className="text-xs text-[color:var(--text-3)]">rows</span>
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
  'docker_host', 'vm_host', 'windows', 'elasticsearch', 'logstash',
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
  windows:         {
    auth_type: 'windows', defaultPort: 5985,
    fields: [
      {
        key: 'username', label: 'Username',
        placeholder: 'Administrator or DOMAIN\\user or user@domain.com',
        hint: 'Accepts local\\user, DOMAIN\\user, or user@domain.com — stored as-is, format detected automatically',
      },
      { key: 'password', label: 'Password', type: 'password' },
    ],
    configFields: [
      {
        key: 'winrm_auth_method', label: 'WinRM Auth Method', type: 'select',
        options: [
          { value: 'ntlm',        label: 'NTLM (recommended)' },
          { value: 'kerberos',    label: 'Kerberos (domain)' },
          { value: 'basic',       label: 'Basic (plaintext — HTTPS only)' },
          { value: 'certificate', label: 'Certificate' },
        ],
      },
      {
        key: 'account_type', label: 'Account Type', type: 'select',
        hint: 'Informational — affects lockout risk display and agent behaviour',
        options: [
          { value: 'local',           label: 'Local account' },
          { value: 'domain',          label: 'Domain account' },
          { value: 'service',         label: 'Service account' },
          { value: 'managed_service', label: 'Managed service account (gMSA)' },
        ],
      },
      {
        key: 'use_ssl', label: 'Use SSL (port 5986)', type: 'toggle',
        hint: 'Switches to HTTPS WinRM — strongly recommended for production',
      },
    ],
    advancedConfigFields: [
      { key: 'is_jump_host', label: 'This is a jump host / bastion', type: 'toggle', hint: 'Not polled as a compute node.' },
    ],
  },
  vm_host:         {
    auth_type: 'ssh', defaultPort: 22,
    fields: [
      { key: 'username',    label: 'SSH User',    placeholder: 'ubuntu' },
      { key: 'private_key', label: 'Private Key', type: 'textarea',
        hint: 'PEM format — paste full key including -----BEGIN/END----- lines. Encrypted at rest. Use passphrase-protected keys for security.' },
      { key: 'passphrase',  label: 'Key Passphrase', type: 'password',
        hint: 'Passphrase for the private key. Strongly recommended.' },
      { key: 'password',    label: 'Password', type: 'password',
        hint: 'Fallback if key auth fails. Prefer key-only authentication.' },
    ],
    configFields: [
      { key: 'role', label: 'VM Role', type: 'select', options: [
        { value: 'swarm_manager', label: 'Swarm Manager' },
        { value: 'swarm_worker',  label: 'Swarm Worker' },
        { value: 'storage',       label: 'Storage' },
        { value: 'monitoring',    label: 'Monitoring' },
        { value: 'general',       label: 'General' },
      ]},
      { key: 'os_type', label: 'OS', type: 'select', hint: 'Auto-detected on first poll if left as Unknown', options: [
        { value: '',        label: 'Unknown (auto-detect)' },
        { value: 'debian',  label: 'Ubuntu / Debian' },
        { value: 'rhel',    label: 'RHEL / CentOS / Fedora' },
        { value: 'alpine',  label: 'Alpine' },
        { value: 'windows', label: 'Windows Server' },
        { value: 'coreos',  label: 'CoreOS / Flatcar' },
      ]},
    ],
    advancedConfigFields: [
      { key: 'is_jump_host', label: 'This is a jump host / bastion', type: 'toggle',
        hint: 'Marks this machine as a relay. Not polled as a compute node.' },
      { key: 'jump_via', label: 'Connect via jump host', type: 'jump_select',
        hint: 'Route SSH through a bastion. Cannot be set if this connection is itself a jump host.' },
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

const PROFILE_AUTH_TYPES = [
  ['ssh',        'SSH (key / password)'],
  ['windows',    'Windows (WinRM)'],
  ['api',        'API Key'],
  ['token_pair', 'Token Pair (ID + Secret)'],
  ['basic',      'HTTP Basic'],
]

const WINRM_AUTH_METHODS = [
  ['ntlm',        'NTLM (recommended)'],
  ['kerberos',    'Kerberos (domain)'],
  ['basic',       'Basic (HTTPS only)'],
  ['certificate', 'Certificate'],
]

const ACCOUNT_TYPES = [
  ['local',           'Local account'],
  ['domain',          'Domain account'],
  ['service',         'Service account'],
  ['managed_service', 'Managed service account (gMSA)'],
]

function _detectWindowsFormat(raw) {
  if (!raw) return null
  if (raw.includes('@') && raw.includes('.')) return 'UPN (user@domain.com)'
  if (raw.startsWith('local\\') || raw.startsWith('LOCAL\\')) return 'Local (local\\user)'
  if (raw.includes('\\')) return 'NetBIOS (DOMAIN\\user)'
  return 'Local (no prefix — will use local\\)'
}

function ProfileForm({ form, setForm, onSave, onCancel, isEdit }) {
  const update = (k, v) => setForm(f => ({ ...f, [k]: v }))
  const updateCred = (k, v) => setForm(f => ({ ...f, credentials: { ...f.credentials, [k]: v } }))
  const winFmt = _detectWindowsFormat(form.credentials?.username)

  return (
    <div className="mt-3 p-3 border rounded" style={{ borderColor: 'var(--border)', background: 'var(--bg-2)' }}>
      <div className="text-[10px] font-semibold mb-3" style={{ color: 'var(--text-2)', fontFamily: 'var(--font-mono)', letterSpacing: 1 }}>
        {isEdit ? 'EDIT PROFILE' : 'NEW CREDENTIAL PROFILE'}
      </div>

      <Field label="Profile name">
        <TextInput value={form.name} onChange={v => update('name', v)} placeholder="ubuntu-ssh-key" />
      </Field>

      <Field label="Auth type">
        <Select value={form.auth_type} onChange={v => { update('auth_type', v); setForm(f => ({ ...f, credentials: {} })) }}
          options={PROFILE_AUTH_TYPES} />
      </Field>

      {/* SSH */}
      {form.auth_type === 'ssh' && (<>
        <Field label="Username">
          <TextInput value={form.credentials.username || ''} onChange={v => updateCred('username', v)} placeholder="ubuntu" />
        </Field>
        <Field label="Private Key (PEM)" hint={
          <span>
            PEM format — paste full key including BEGIN/END lines. Stored encrypted.
            <span style={{ color: 'var(--amber)', marginLeft: 4 }}>
              ⚠ Use passphrase-protected keys for security — unprotected keys are a risk if the server is compromised.
            </span>
          </span>
        }>
          <Textarea value={form.credentials.private_key || ''} onChange={v => updateCred('private_key', v)}
            placeholder="-----BEGIN OPENSSH PRIVATE KEY-----" rows={5} />
        </Field>
        <Field label="Key Passphrase" hint="Passphrase for the private key. Strongly recommended.">
          <TextInput type="password" value={form.credentials.passphrase || ''} onChange={v => updateCred('passphrase', v)} placeholder="passphrase (recommended)" />
        </Field>
        <Field label="Password" hint="Fallback if private key auth fails. Not recommended — prefer key-only.">
          <TextInput type="password" value={form.credentials.password || ''} onChange={v => updateCred('password', v)} placeholder="leave blank to require key auth" />
        </Field>
      </>)}

      {/* Windows */}
      {form.auth_type === 'windows' && (<>
        <Field label="Username" hint="Accepts: local\\user · DOMAIN\\user · user@domain.com">
          <TextInput value={form.credentials.username || ''} onChange={v => updateCred('username', v)}
            placeholder="Administrator or DOMAIN\\user or user@domain.com" />
          {winFmt && (
            <div style={{ fontSize: 9, color: 'var(--cyan)', marginTop: 3, fontFamily: 'var(--font-mono)' }}>
              Detected format: {winFmt}
            </div>
          )}
        </Field>
        <Field label="Password">
          <TextInput type="password" value={form.credentials.password || ''} onChange={v => updateCred('password', v)} />
        </Field>
        <Field label="WinRM Auth Method">
          <Select value={form.credentials.winrm_auth_method || 'ntlm'}
            onChange={v => updateCred('winrm_auth_method', v)} options={WINRM_AUTH_METHODS} />
        </Field>
        <Field label="Account Type" hint="Informational — affects lockout risk display and agent behaviour">
          <Select value={form.credentials.account_type || 'local'}
            onChange={v => updateCred('account_type', v)} options={ACCOUNT_TYPES} />
        </Field>
        {form.credentials.account_type === 'domain' || form.credentials.account_type === 'service' ? (
          <div style={{ fontSize: 9, padding: '4px 8px', borderRadius: 2, border: '1px solid var(--amber)', color: 'var(--amber)', marginBottom: 8 }}>
            ⚠ Domain/service accounts may lock out across all linked devices if credentials change — test rotation carefully.
          </div>
        ) : null}
      </>)}

      {/* API Key */}
      {form.auth_type === 'api' && (<>
        <Field label="API Key">
          <TextInput type="password" value={form.credentials.api_key || ''} onChange={v => updateCred('api_key', v)} placeholder="sk-..." />
        </Field>
        <Field label="Header Name" hint='Default: Authorization'>
          <TextInput value={form.credentials.header_name || ''} onChange={v => updateCred('header_name', v)} placeholder="Authorization" />
        </Field>
        <Field label="Prefix" hint='Default: Bearer (use X-Api-Key for header-key style)'>
          <TextInput value={form.credentials.prefix || ''} onChange={v => updateCred('prefix', v)} placeholder="Bearer" />
        </Field>
      </>)}

      {/* Token Pair */}
      {form.auth_type === 'token_pair' && (<>
        <Field label="Token ID">
          <TextInput value={form.credentials.token_id || ''} onChange={v => updateCred('token_id', v)} placeholder="terraform@pve!my-token" />
        </Field>
        <Field label="Token Secret">
          <TextInput type="password" value={form.credentials.secret || ''} onChange={v => updateCred('secret', v)} />
        </Field>
      </>)}

      {/* HTTP Basic */}
      {form.auth_type === 'basic' && (<>
        <Field label="Username">
          <TextInput value={form.credentials.username || ''} onChange={v => updateCred('username', v)} placeholder="admin" />
        </Field>
        <Field label="Password">
          <TextInput type="password" value={form.credentials.password || ''} onChange={v => updateCred('password', v)} />
        </Field>
      </>)}

      <Field label="">
        <Toggle value={!!form.discoverable} onChange={v => update('discoverable', v)}
          label="Available for discovery (use this profile when testing unlinked devices)" />
      </Field>

      <div className="flex gap-2 mt-3">
        <button onClick={onSave} className="px-3 py-1 text-xs rounded bg-blue-600 text-white">
          {isEdit ? 'Update Profile' : 'Save Profile'}
        </button>
        <button onClick={onCancel} className="px-3 py-1 text-xs rounded"
          style={{ background: 'var(--bg-3)', color: 'var(--text-2)' }}>Cancel</button>
      </div>
    </div>
  )
}

function ConnectionsTab({ userRole = 'stormtrooper' }) {
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
  const [usernameOverride, setUsernameOverride] = useState(false)
  const [importResult, setImportResult] = useState(null)
  const [importing, setImporting] = useState(false)
  const [rotationModal, setRotationModal] = useState(null)  // {profileId, profileName, newCreds}
  const [templateEditId, setTemplateEditId] = useState(null)       // connection id being edited
  const [connectionTemplates, setConnectionTemplates] = useState({}) // {conn_id: {has_override, template}}
  const [jumpHosts, setJumpHosts] = useState([])
  const [profiles, setProfiles] = useState([])
  const [showProfileForm, setShowProfileForm] = useState(false)
  const [editingProfileId, setEditingProfileId] = useState(null)
  const [profileForm, setProfileForm] = useState({ name: '', auth_type: 'ssh', credentials: {}, discoverable: false })
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
    { value: 'ssh', label: 'SSH tunnel', port: 22,
      hint: 'Connects via SSH and forwards the remote Docker socket. No daemon reconfiguration needed. Link a credential profile — do not enter creds inline.',
      fields: [
        { key: 'username',    label: 'SSH User',   placeholder: 'ubuntu',
          hint: 'Override only — normally comes from the linked credential profile.' },
        { key: 'private_key', label: 'Private Key', type: 'textarea',
          placeholder: '-----BEGIN RSA PRIVATE KEY-----',
          hint: 'Override only — normally comes from the linked credential profile.' },
        { key: 'password',    label: 'Password',    type: 'password',
          hint: 'Fallback only. Docker SDK SSH transport does not support password auth; key is required.' },
      ]
    },
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
      _credState: c.credential_state || null,   // non-secret display state from API
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
    return fetch(`${BASE}/api/connections`, { headers: { ...authHeaders() } })
      .then(r => r.ok ? r.json() : { data: [] })
      .then(d => {
        const all = (d.data || []).sort((a, b) =>
          (a.label || a.host || '').localeCompare(b.label || b.host || '')
        )
        setConns(all)
        setJumpHosts(all.filter(c => c.platform === 'vm_host' && c.config?.is_jump_host).map(c => ({ id: c.id, label: c.label, host: c.host })))
        setLoading(false)
        return all
      })
      .catch(() => setLoading(false))
  }

  const fetchProfiles = () => {
    fetch(`${BASE}/api/credential-profiles`, { headers: { ...authHeaders() } })
      .then(r => r.json())
      .then(d => setProfiles(d.profiles || []))
      .catch(() => {})
  }

  const fetchConnectionTemplates = async (connIds) => {
    const results = {}
    await Promise.allSettled(
      connIds.map(async id => {
        try {
          const r = await fetch(`${BASE}/api/card-templates/connection/${id}`, { headers: authHeaders() })
          if (r.ok) results[id] = await r.json()
        } catch { /* silent */ }
      })
    )
    setConnectionTemplates(results)
  }

  useEffect(() => {
    fetchConns().then?.(all => {
      if (all) {
        const templateTargets = all.filter(c => ['vm_host', 'docker_host', 'windows'].includes(c.platform)).map(c => c.id)
        fetchConnectionTemplates(templateTargets)
      }
    })
    fetchProfiles()
  }, [])

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
    <>
    {rotationModal && (
      <RotationTestModal
        profileId={rotationModal.profileId}
        profileName={rotationModal.profileName}
        newCredentials={rotationModal.newCreds}
        userRole={userRole}
        onConfirmed={() => {
          setRotationModal(null)
          setEditingProfileId(null)
          setProfileForm({ name: '', auth_type: 'ssh', credentials: {}, discoverable: false })
          fetchProfiles()
        }}
        onCancel={() => setRotationModal(null)}
      />
    )}
    <div className="space-y-3" onClick={e => e.stopPropagation()}>
      {/* ── Credential Profiles — prominent section ───────────────────────── */}
      <div className="mb-5">
        <div className="flex items-center justify-between mb-2">
          <div>
            <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', fontWeight: 700,
              color: 'var(--text-2)', letterSpacing: 1 }}>
              CREDENTIAL PROFILES
            </span>
            <span style={{ fontSize: 9, color: 'var(--text-3)', marginLeft: 8 }}>
              Shared auth sets — link to connections instead of storing credentials per-connection
            </span>
          </div>
          <button onClick={() => { setShowProfileForm(true); setEditingProfileId(null); setProfileForm({ name: '', auth_type: 'ssh', credentials: {}, discoverable: false }) }}
            style={{ fontSize: 9, padding: '3px 10px', borderRadius: 2, background: 'var(--accent-dim)',
              color: 'var(--accent)', border: '1px solid var(--accent)', cursor: 'pointer', fontFamily: 'var(--font-mono)' }}>
            + NEW PROFILE
          </button>
        </div>

        {showProfileForm && (
          <ProfileForm
            form={profileForm}
            setForm={setProfileForm}
            isEdit={!!editingProfileId}
            onSave={async () => {
              const hasCreds = profileForm.credentials && Object.keys(profileForm.credentials).length > 0
              if (editingProfileId && hasCreds) {
                // Has credential changes — trigger rotation test modal
                setRotationModal({
                  profileId:   editingProfileId,
                  profileName: profileForm.name,
                  newCreds:    profileForm.credentials,
                })
                setShowProfileForm(false)
                return
              }
              // New profile or metadata-only change — save directly
              const url = editingProfileId
                ? `${BASE}/api/credential-profiles/${editingProfileId}`
                : `${BASE}/api/credential-profiles`
              const method = editingProfileId ? 'PUT' : 'POST'
              await fetch(url, {
                method,
                headers: { 'Content-Type': 'application/json', ...authHeaders() },
                body: JSON.stringify(profileForm),
              })
              setShowProfileForm(false)
              setEditingProfileId(null)
              setProfileForm({ name: '', auth_type: 'ssh', credentials: {}, discoverable: false })
              fetchProfiles()
            }}
            onCancel={() => { setShowProfileForm(false); setEditingProfileId(null) }}
          />
        )}

        <div className="space-y-1 mt-2">
          {profiles.filter(p => p.name !== '__no_credential__').map(p => {
            const isLinked = (p.linked_connections_count || 0) > 0
            return (
              <div key={p.id} className="flex items-center justify-between px-2 py-1.5 rounded"
                style={{ background: 'var(--bg-2)', border: '1px solid var(--border)' }}>
                <div className="flex items-center gap-2 min-w-0">
                  {/* seq_id badge */}
                  <span style={{ fontSize: 8, padding: '1px 5px', borderRadius: 2, fontFamily: 'var(--font-mono)',
                    background: 'var(--bg-3)', color: 'var(--text-3)', flexShrink: 0 }}>
                    #{p.seq_id ?? '?'}
                  </span>
                  <span style={{ fontSize: 11, color: 'var(--text-1)', fontWeight: 600, truncate: true }}>
                    {p.name}
                  </span>
                  <span style={{ fontSize: 8, padding: '1px 5px', borderRadius: 2,
                    background: 'var(--bg-3)', color: 'var(--cyan)' }}>
                    {p.auth_type}
                  </span>
                  {p.username && (
                    <span style={{ fontSize: 9, color: 'var(--text-3)' }}>{p.username}</span>
                  )}
                  {p.has_private_key && (
                    <span style={{ fontSize: 8, padding: '1px 4px', borderRadius: 2,
                      background: 'rgba(0,200,238,0.1)', color: 'var(--cyan)' }}>⚿ KEY</span>
                  )}
                  {p.has_passphrase && (
                    <span style={{ fontSize: 8, padding: '1px 4px', borderRadius: 2,
                      background: 'rgba(0,170,68,0.1)', color: 'var(--green)' }}>🔒 PASS</span>
                  )}
                  {p.discoverable && (
                    <span style={{ fontSize: 8, padding: '1px 4px', borderRadius: 2,
                      background: 'rgba(204,136,0,0.12)', color: 'var(--amber)' }}>◎ DISCOVERABLE</span>
                  )}
                  {isLinked && (
                    <span style={{ fontSize: 8, color: 'var(--text-3)' }}>
                      {p.linked_connections_count} connection{p.linked_connections_count !== 1 ? 's' : ''}
                    </span>
                  )}
                </div>
                <div className="flex gap-1 flex-shrink-0">
                  <button
                    onClick={() => {
                      setEditingProfileId(p.id)
                      setProfileForm({ name: p.name, auth_type: p.auth_type, credentials: {}, discoverable: p.discoverable })
                      setShowProfileForm(true)
                    }}
                    style={{ fontSize: 9, color: 'var(--text-3)', background: 'none', border: '1px solid var(--border)',
                      borderRadius: 2, padding: '2px 6px', cursor: 'pointer' }}>
                    Edit
                  </button>
                  <button
                    onClick={async () => {
                      if (isLinked) {
                        if (!window.confirm(`This profile is used by ${p.linked_connections_count} connection(s). Deleting it will unlink them. Continue?`)) return
                      }
                      await fetch(`${BASE}/api/credential-profiles/${p.id}`, {
                        method: 'DELETE', headers: { ...authHeaders() }
                      })
                      fetchProfiles()
                    }}
                    style={{ fontSize: 9, color: 'var(--red)', background: 'none', border: 'none', cursor: 'pointer', padding: '2px 4px' }}>
                    ✕
                  </button>
                </div>
              </div>
            )
          })}
          {profiles.filter(p => p.name !== '__no_credential__').length === 0 && !showProfileForm && (
            <div style={{ fontSize: 10, color: 'var(--text-3)', padding: '8px 0' }}>
              No profiles yet — create one above, then link it to connections instead of entering credentials per-connection.
            </div>
          )}
        </div>
      </div>
      {/* ── end Credential Profiles ─────────────────────────────────────── */}

      <div className="flex justify-between items-center flex-wrap gap-2">
        <span className="text-xs" style={{ color: 'var(--text-3)' }}>{conns.length} connection(s)</span>
        <div className="flex gap-2 flex-wrap">
          {/* Export */}
          <button className="btn text-[10px] px-2 py-1"
            style={{ background: 'var(--bg-3)', color: 'var(--text-2)' }}
            onClick={async e => {
              e.stopPropagation()
              const r = await fetch(`${BASE}/api/connections/export`, { headers: { ...authHeaders() } })
              const blob = await r.blob()
              const url = URL.createObjectURL(blob)
              const a = document.createElement('a'); a.href = url
              a.download = 'connections_export.csv'; a.click()
              URL.revokeObjectURL(url)
            }}>
            ↓ Export CSV
          </button>
          {/* Import */}
          <button className="btn text-[10px] px-2 py-1"
            style={{ background: 'var(--bg-3)', color: 'var(--text-2)' }}
            onClick={e => {
              e.stopPropagation()
              const input = document.createElement('input')
              input.type = 'file'; input.accept = '.csv,text/csv'
              input.onchange = async ev => {
                const file = ev.target.files[0]
                if (!file) return
                setImporting(true); setImportResult(null)
                const text = await file.text()
                const b64 = btoa(unescape(encodeURIComponent(text)))
                try {
                  const r = await fetch(`${BASE}/api/connections/import`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', ...authHeaders() },
                    body: JSON.stringify({ csv_data: b64 }),
                  })
                  const d = await r.json()
                  setImportResult(d)
                  if (d.status === 'ok') fetchConns()
                } catch (e) {
                  setImportResult({ status: 'error', message: e.message })
                } finally { setImporting(false) }
              }
              input.click()
            }}>
            {importing ? '…' : '↑ Import CSV'}
          </button>
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

      {/* Import result display */}
      {importResult && (
        <div style={{ padding: '8px 10px', borderRadius: 2, border: `1px solid ${importResult.status === 'ok' ? 'var(--border)' : 'var(--red)'}`,
          background: 'var(--bg-2)', fontSize: 10, marginTop: 4 }}>
          {importResult.status === 'ok' ? (
            <>
              <div style={{ color: 'var(--text-1)', marginBottom: 4 }}>
                Import complete — created: {importResult.summary?.created ?? 0}, skipped: {importResult.summary?.skipped ?? 0}, errors: {importResult.summary?.errors ?? 0}
              </div>
              {(importResult.results || []).filter(r => r.status !== 'exists').map((r, i) => (
                <div key={i} style={{ color: r.status === 'created' ? 'var(--green)' : r.status === 'created_no_profile' ? 'var(--amber)' : 'var(--red)', marginBottom: 1 }}>
                  {r.status === 'created' ? '✓' : r.status === 'created_no_profile' ? '⚠' : '✕'} {r.label}
                  {r.profile_not_found && ' (profile not found — link manually)'}
                  {r.status === 'error' && ` — ${r.message}`}
                </div>
              ))}
            </>
          ) : (
            <span style={{ color: 'var(--red)' }}>{importResult.message || 'Import failed'}</span>
          )}
          <button onClick={() => setImportResult(null)}
            style={{ fontSize: 9, color: 'var(--text-3)', background: 'none', border: 'none', cursor: 'pointer', marginTop: 4, display: 'block' }}>
            Dismiss
          </button>
        </div>
      )}

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
              {!(form.config?.credential_profile_id && form.auth_type === 'ssh') && mode.fields.map(f => f.type === 'textarea' ? (
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
          {/* Credential profile picker for SSH-capable platforms */}
          {(
            ['vm_host', 'windows', 'fortiswitch', 'cisco', 'juniper', 'aruba'].includes(form.platform) ||
            (form.platform === 'docker_host' && form.auth_type === 'ssh')
          ) && (() => {
            const credState = form._credState || {}
            const activeProfileId = form.config?.credential_profile_id || ''
            const activeProfile = profiles.find(p => p.id === activeProfileId)

            const _ProfileField = ({ label, valueDisplay, fieldKey, disabled, overrideActive, onToggleOverride, children }) => (
              <div style={{ marginBottom: 6 }}>
                {_FL(label)}
                {disabled && !overrideActive ? (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <div style={{
                      flex: 1, padding: '4px 8px', borderRadius: 2, fontSize: 9,
                      background: 'var(--bg-3)', border: '1px solid var(--border)',
                      color: 'var(--cyan)', fontFamily: 'var(--font-mono)', opacity: 0.8,
                    }}>
                      {valueDisplay}
                    </div>
                    {fieldKey === 'username' && onToggleOverride && (
                      <button onClick={onToggleOverride} title="Override username for this connection only"
                        style={{ fontSize: 8, color: 'var(--amber)', background: 'none',
                          border: '1px solid var(--amber)', borderRadius: 2, padding: '2px 5px', cursor: 'pointer' }}>
                        Override
                      </button>
                    )}
                  </div>
                ) : children}
                {overrideActive && fieldKey === 'username' && (
                  <div style={{ fontSize: 9, marginTop: 3, color: 'var(--amber)', padding: '3px 6px',
                    background: 'rgba(204,136,0,0.08)', border: '1px solid var(--amber)', borderRadius: 2 }}>
                    ⚠ Overriding username for this connection only — not recommended. Consider creating a separate profile.
                  </div>
                )}
              </div>
            )

            return (
              <div>
                {_FL('Credential Profile')}
                <div style={{ fontSize: 9, color: 'var(--text-3)', marginBottom: 3 }}>
                  Select a profile — credentials are stored once and reused across connections
                </div>
                <select
                  value={activeProfileId}
                  onChange={e => {
                    updateConfig('credential_profile_id', e.target.value || null)
                    setUsernameOverride(false)
                  }}
                  className="input text-[10px] w-full"
                >
                  <option value="">— no profile (enter credentials below) —</option>
                  {profiles
                    .filter(p => p.name !== '__no_credential__')
                    .filter(p => form.platform !== 'docker_host' || p.auth_type === 'ssh')
                    .map(p => (
                      <option key={p.id} value={p.id}>
                        #{p.seq_id ?? '?'} — {p.name} ({p.auth_type})
                      </option>
                    ))}
                </select>

                {/* When a profile is active — show derived safe fields greyed out */}
                {activeProfile && (
                  <div style={{ marginTop: 8, padding: '8px', borderRadius: 2,
                    background: 'var(--bg-3)', border: '1px solid var(--border)' }}>
                    <div style={{ fontSize: 8, color: 'var(--text-3)', marginBottom: 6,
                      fontFamily: 'var(--font-mono)', letterSpacing: 0.5 }}>
                      FROM PROFILE: {activeProfile.name.toUpperCase()} (#{activeProfile.seq_id})
                    </div>

                    {/* Username — overrideable */}
                    <_ProfileField
                      label="SSH User"
                      fieldKey="username"
                      disabled={!usernameOverride}
                      overrideActive={usernameOverride}
                      valueDisplay={activeProfile.username ? `${activeProfile.username} (from profile)` : '(from profile)'}
                      onToggleOverride={() => setUsernameOverride(o => !o)}
                    >
                      <input className="input text-[10px] w-full"
                        placeholder={activeProfile.username || 'override username'}
                        value={form.credentials.username ?? ''}
                        onChange={e => updateCred('username', e.target.value)} />
                    </_ProfileField>

                    {/* Private key — not overrideable, just display */}
                    <_ProfileField
                      label="Private Key"
                      fieldKey="private_key"
                      disabled={true}
                      valueDisplay={activeProfile.has_private_key ? '⚿ Private key set in profile' : 'No private key in profile'}
                    />

                    {/* Passphrase — display only */}
                    {activeProfile.has_private_key && (
                      <_ProfileField
                        label="Passphrase"
                        fieldKey="passphrase"
                        disabled={true}
                        valueDisplay={activeProfile.has_passphrase ? '🔒 Passphrase set in profile' : '⚠ No passphrase — key unprotected'}
                      />
                    )}

                    {/* Password — display only */}
                    <_ProfileField
                      label="Password (fallback)"
                      fieldKey="password"
                      disabled={true}
                      valueDisplay={activeProfile.has_password ? '●●●● (from profile)' : 'No password in profile'}
                    />
                  </div>
                )}

                {/* Inline creds warning when no profile */}
                {!activeProfile && editingId && (
                  <div style={{ marginTop: 6, fontSize: 9, padding: '4px 8px', borderRadius: 2,
                    border: '1px solid var(--amber)', color: 'var(--amber)', background: 'rgba(204,136,0,0.08)' }}>
                    ⚠ Using inline credentials — consider linking a credential profile for better security and easier rotation.
                  </div>
                )}
              </div>
            )
          })()}
          {/* Standard platform fields — hidden for profile-linked SSH platforms when profile active */}
          {form.platform !== 'docker_host' &&
           !(form.config?.credential_profile_id && ['vm_host','windows','fortiswitch','cisco','juniper','aruba','docker_host'].includes(form.platform)) &&
           platAuth.fields.map(f => (
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
            return (<div key={c.id}>
            <div className="card flex items-center justify-between px-2 py-1.5 text-[10px]" style={{ opacity: isPaused ? 0.6 : 1, transition: 'opacity 0.2s' }}>
              <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 4 }}>
                <span className="font-medium" style={{ color: 'var(--text-1)' }}>{c.label || c.host}</span>
                <span className="mono" style={{ color: 'var(--text-3)' }}>{c.host}:{c.port} · {c.platform === 'docker_host' ? ({ tcp: '⊘ plain TCP', tls: '⚿ TLS', ssh: '⇢ SSH' }[c.auth_type] || c.auth_type) : c.auth_type}</span>
                {c.verified && <span style={{ color: 'var(--green)' }}>✓</span>}
                {c.verified === false && c.last_seen && <span style={{ color: 'var(--red)' }}>✕</span>}
                {c.config?.is_jump_host && <span style={{ fontSize: 8, padding: '1px 4px', borderRadius: 2, background: 'var(--amber-dim)', color: 'var(--amber)' }}>⇢ BASTION</span>}
                {c.credential_state?.source === 'profile' && (
                  <span style={{ fontSize: 8, padding: '1px 4px', borderRadius: 2, background: 'rgba(0,200,238,0.1)', color: 'var(--cyan)' }}>
                    ⊕ {c.credential_state.profile_name || 'PROFILE'}
                  </span>
                )}
                {c.credential_state?.source === 'profile_not_found' && (
                  <span style={{ fontSize: 8, padding: '1px 4px', borderRadius: 2, background: 'rgba(204,40,40,0.15)', color: 'var(--red)' }}>
                    ⚠ PROFILE MISSING
                  </span>
                )}
                {c.credential_state?.source === 'inline' && ['vm_host','windows'].includes(c.platform) && (
                  <span style={{ fontSize: 8, padding: '1px 4px', borderRadius: 2, background: 'rgba(204,136,0,0.12)', color: 'var(--amber)' }}>
                    ⚠ INLINE CREDS
                  </span>
                )}
                {c.credential_state?.source === 'needs_profile' && (
                  <span style={{ fontSize: 8, padding: '1px 4px', borderRadius: 2,
                    background: 'rgba(204,40,40,0.15)', color: 'var(--red)' }}>
                    ⚠ NEEDS PROFILE
                  </span>
                )}
                {c.config?.os_type && <span style={{ fontSize: 8, padding: '1px 4px', borderRadius: 2, background: 'var(--bg-3)', color: 'var(--text-3)' }}>{c.config.os_type}</span>}
                {connectionTemplates[c.id]?.has_override && (
                  <span style={{ fontSize: 8, padding: '1px 4px', borderRadius: 2,
                    background: 'rgba(0,200,238,0.1)', color: 'var(--cyan)' }}>◈ CUSTOM CARD</span>
                )}
                {isPaused && <span style={{ fontSize: 8, padding: '1px 5px', borderRadius: 2, background: 'rgba(100,100,120,0.2)', color: 'var(--text-3)', border: '1px solid var(--border)', fontFamily: 'var(--font-mono)', letterSpacing: '0.04em' }}>⏸ PAUSED{c.config.paused_by ? ` · ${c.config.paused_by}` : ''}</span>}
              </div>
              <div className="flex gap-1" style={{ flexShrink: 0 }}>
                <button className="btn text-[9px] px-1.5 py-0.5" onClick={() => startEdit(c)}>Edit</button>
                <button onClick={() => duplicateConn(c)} title="Duplicate connection" className="btn text-[9px] px-1.5 py-0.5" style={{ color: 'var(--text-3)' }}>Copy</button>
                {['vm_host', 'docker_host', 'windows'].includes(c.platform) && (
                  <button
                    onClick={() => setTemplateEditId(templateEditId === c.id ? null : c.id)}
                    title="Customize card template for this connection"
                    className="btn text-[9px] px-1.5 py-0.5"
                    style={{ color: connectionTemplates[c.id]?.has_override ? 'var(--cyan)' : 'var(--text-3)' }}>
                    ◈
                  </button>
                )}
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
            {/* Inline card template editor for this connection */}
            {templateEditId === c.id && (() => {
              const cardType = c.platform === 'docker_host' ? 'container' : 'vm_host'
              const schema = CONTAINER_SCHEMA
              const connTemplate = connectionTemplates[c.id]
              const initialTemplate = connTemplate?.template || DEFAULT_TEMPLATES['container'] || {}

              return (
                <div style={{ margin: '4px 0 8px 0', padding: '10px', background: 'var(--bg-2)',
                  border: '1px solid var(--cyan)', borderRadius: 2 }}>
                  <div style={{ fontSize: 9, fontFamily: 'var(--font-mono)', color: 'var(--cyan)',
                    marginBottom: 8, letterSpacing: 0.5 }}>
                    CUSTOM CARD TEMPLATE — {c.label || c.host}
                  </div>
                  <CardTemplateEditor
                    cardType="container"
                    schema={schema}
                    initialTemplate={initialTemplate}
                    onSave={async (template) => {
                      const r = await fetch(`${BASE}/api/card-templates/connection/${c.id}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json', ...authHeaders() },
                        body: JSON.stringify({ template }),
                      })
                      if (r.ok) {
                        setTemplateEditId(null)
                        fetchConnectionTemplates([c.id])
                        const { invalidateCardTemplateCache } = await import('../hooks/useCardTemplate')
                        invalidateCardTemplateCache(c.id)
                      }
                    }}
                    onCancel={() => setTemplateEditId(null)}
                  />
                  {connTemplate?.has_override && (
                    <button
                      onClick={async () => {
                        await fetch(`${BASE}/api/card-templates/connection/${c.id}`, {
                          method: 'DELETE', headers: authHeaders(),
                        })
                        setTemplateEditId(null)
                        fetchConnectionTemplates([c.id])
                        const { invalidateCardTemplateCache } = await import('../hooks/useCardTemplate')
                        invalidateCardTemplateCache(c.id)
                      }}
                      style={{ marginTop: 8, fontSize: 9, color: 'var(--red)', background: 'none',
                        border: '1px solid var(--red)', borderRadius: 2, padding: '3px 10px', cursor: 'pointer' }}>
                      ↺ Reset to type default
                    </button>
                  )}
                </div>
              )
            })()}
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
    </>
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

function EntityAliasEditor() {
  const [aliases, setAliases] = useState({})    // {entity_id: alias}
  const [origins, setOrigins] = useState({})    // {entity_id: origin}
  const [entities, setEntities] = useState([])  // [{entity_id, origin, type}]
  const [edits, setEdits] = useState({})        // {entity_id: draft alias value}
  const [saving, setSaving] = useState({})
  const [loading, setLoading] = useState(true)

  const fetchAliases = async () => {
    try {
      const r = await fetch(`${BASE}/api/display-aliases`, { headers: authHeaders() })
      const d = await r.json()
      const aliasMap = {}
      const originMap = {}
      for (const a of (d.aliases || [])) {
        aliasMap[a.entity_id] = a.alias
        originMap[a.entity_id] = a.origin
      }
      setAliases(aliasMap)
      setOrigins(originMap)
    } catch { /* silent */ }
  }

  const fetchEntities = async () => {
    setLoading(true)
    const collected = []
    try {
      // Docker containers from summary
      const r = await fetch(`${BASE}/api/dashboard/containers`, { headers: authHeaders() })
      if (r.ok) {
        const d = await r.json()
        for (const c of (d.containers || [])) {
          if (c.name) collected.push({
            entity_id: `docker:${c.name}`,
            origin: c.name,
            type: 'container',
            detail: c.image?.split('/').pop() || '',
          })
        }
      }
    } catch { /* silent */ }
    try {
      // Connections (vm_host, windows)
      const r = await fetch(`${BASE}/api/connections?platform=vm_host`, { headers: authHeaders() })
      if (r.ok) {
        const d = await r.json()
        for (const c of (d.data || [])) {
          collected.push({
            entity_id: `connection:${c.id}`,
            origin: c.label || c.host,
            type: 'vm_host',
            detail: c.host,
          })
        }
      }
    } catch { /* silent */ }
    setEntities(collected)
    setLoading(false)
  }

  useEffect(() => {
    fetchAliases()
    fetchEntities()
  }, [])

  const saveAlias = async (entityId, origin) => {
    const alias = (edits[entityId] ?? aliases[entityId] ?? '').trim()
    if (!alias) return clearAlias(entityId)
    if (alias === origin) return clearAlias(entityId)  // same as origin = no alias needed
    setSaving(s => ({ ...s, [entityId]: true }))
    try {
      await fetch(`${BASE}/api/display-aliases/${encodeURIComponent(entityId)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ alias, origin }),
      })
      await fetchAliases()
      setEdits(e => { const n = { ...e }; delete n[entityId]; return n })
    } catch { /* silent */ }
    setSaving(s => ({ ...s, [entityId]: false }))
  }

  const clearAlias = async (entityId) => {
    setSaving(s => ({ ...s, [entityId]: true }))
    try {
      await fetch(`${BASE}/api/display-aliases/${encodeURIComponent(entityId)}`, {
        method: 'DELETE', headers: authHeaders(),
      })
      await fetchAliases()
      setEdits(e => { const n = { ...e }; delete n[entityId]; return n })
    } catch { /* silent */ }
    setSaving(s => ({ ...s, [entityId]: false }))
  }

  if (loading) return <div style={{ fontSize: 9, color: 'var(--text-3)' }}>Loading entities…</div>
  if (entities.length === 0) return (
    <div style={{ fontSize: 9, color: 'var(--text-3)' }}>
      No entities discovered. Run a harvest in the Discovered view or check connections.
    </div>
  )

  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr auto auto', gap: '4px 8px',
        marginBottom: 4, fontSize: 8, fontFamily: 'var(--font-mono)', color: 'var(--text-3)',
        letterSpacing: 0.5, padding: '0 2px' }}>
        <span>ORIGINAL NAME</span><span>DISPLAY ALIAS</span><span></span><span></span>
      </div>
      {entities.map(({ entity_id, origin, type, detail }) => {
        const currentAlias = aliases[entity_id] || ''
        const draftAlias = edits[entity_id] ?? currentAlias
        const hasOverride = !!currentAlias && currentAlias !== origin
        const isDirty = draftAlias !== currentAlias
        return (
          <div key={entity_id} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr auto auto',
            gap: '0 8px', alignItems: 'center', marginBottom: 5 }}>
            <div>
              <div style={{ fontSize: 10, color: 'var(--text-1)', fontFamily: 'var(--font-mono)' }}>{origin}</div>
              {detail && <div style={{ fontSize: 8, color: 'var(--text-3)' }}>{type} · {detail}</div>}
            </div>
            <input
              value={draftAlias}
              onChange={e => setEdits(ed => ({ ...ed, [entity_id]: e.target.value }))}
              placeholder={origin}
              style={{ background: 'var(--bg-2)', border: `1px solid ${isDirty ? 'var(--amber)' : 'var(--border)'}`,
                borderRadius: 2, padding: '3px 8px', fontSize: 10, color: 'var(--text-1)',
                fontFamily: 'var(--font-mono)', outline: 'none' }}
            />
            <button
              onClick={() => saveAlias(entity_id, origin)}
              disabled={!isDirty || saving[entity_id]}
              style={{ fontSize: 9, padding: '3px 8px', borderRadius: 2, cursor: 'pointer',
                background: isDirty ? 'var(--accent-dim)' : 'var(--bg-3)',
                color: isDirty ? 'var(--accent)' : 'var(--text-3)',
                border: `1px solid ${isDirty ? 'var(--accent)' : 'var(--border)'}`,
                opacity: (!isDirty || saving[entity_id]) ? 0.5 : 1 }}>
              {saving[entity_id] ? '…' : 'Save'}
            </button>
            {hasOverride && (
              <button
                onClick={() => clearAlias(entity_id)}
                disabled={saving[entity_id]}
                title={`Reset to: ${origin}`}
                style={{ fontSize: 9, padding: '3px 6px', borderRadius: 2, cursor: 'pointer',
                  background: 'none', border: 'none', color: 'var(--red)', opacity: saving[entity_id] ? 0.5 : 1 }}>
                ↺
              </button>
            )}
            {!hasOverride && <span />}
          </div>
        )
      })}
    </div>
  )
}

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

      {/* ── Entity Display Aliases ─────────────────────────────────────────── */}
      <div style={{ marginTop: 20, paddingTop: 16, borderTop: '1px solid var(--border)' }}>
        <div style={{ fontSize: 10, fontFamily: 'var(--font-mono)', fontWeight: 700,
          color: 'var(--text-2)', letterSpacing: 1, marginBottom: 6 }}>
          ENTITY DISPLAY ALIASES
        </div>
        <p style={{ fontSize: 9, color: 'var(--text-3)', marginBottom: 10 }}>
          Set a custom display name for any container or connection. The alias is shown in
          Platform Core and card headers. If cleared, the original name is restored automatically.
        </p>
        <EntityAliasEditor />
      </div>
      {/* ── end Entity Display Aliases ─────────────────────────────────────── */}
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

export default function OptionsModal({ userRole = 'stormtrooper' }) {
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
                {tab === 'Connections'    && <ConnectionsTab userRole={userRole} />}
                {tab === 'Allowlist'      && <AllowlistTab />}
                {tab === 'Permissions'    && <PermissionsTab />}
                {tab === 'Access'        && <AccessTab />}
                {tab === 'Naming'        && <NamingTab         draft={draft} update={update} />}
                {tab === 'Appearance'     && <DisplayTab        draft={draft} update={update} />}
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
// Alias for SettingsPage import compatibility
export { DisplayTab as AppearanceTab }
