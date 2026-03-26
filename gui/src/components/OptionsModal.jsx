/**
 * OptionsModal — 4-tab settings modal.
 * Reads/writes via OptionsContext → localStorage + POST /api/settings.
 */
import { useState } from 'react'
import { Settings, X } from 'lucide-react'
import { useOptions } from '../context/OptionsContext'

const BASE = import.meta.env.VITE_API_BASE ?? ''

const TABS = ['General', 'Infrastructure', 'AI Services', 'Display']

// ── Shared form helpers ────────────────────────────────────────────────────────

function Field({ label, hint, children }) {
  return (
    <div className="mb-4">
      <label className="block text-xs font-semibold text-slate-300 mb-1">{label}</label>
      {hint && <p className="text-xs text-slate-500 mb-1">{hint}</p>}
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
      className="w-full bg-slate-800 border border-slate-600 rounded px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-blue-500"
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
      className="w-full bg-slate-800 border border-slate-600 rounded px-3 py-1.5 text-xs text-slate-200 resize-none focus:outline-none focus:border-blue-500"
    />
  )
}

function Radio({ name, value, current, onChange, label }) {
  return (
    <label className="flex items-center gap-2 cursor-pointer text-xs text-slate-300 hover:text-slate-100">
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
          value ? 'bg-blue-600' : 'bg-slate-600'
        }`}
      >
        <div className={`w-4 h-4 rounded-full bg-white shadow transition-transform ${value ? 'translate-x-4' : ''}`} />
      </div>
      <span className="text-xs text-slate-300">{label}</span>
    </label>
  )
}

function Select({ value, onChange, options }) {
  return (
    <select
      value={value}
      onChange={e => onChange(e.target.value)}
      className="w-full bg-slate-800 border border-slate-600 rounded px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-blue-500"
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
    <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-3 border-b border-slate-700 pb-1">
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
        <Field label="Agent Docker Host">
          <TextInput value={draft.agentDockerHost} onChange={v => update('agentDockerHost', v)} placeholder="unix:///var/run/docker.sock" />
        </Field>
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

      {/* Proxmox */}
      <div className="mb-5">
        <SectionHeader label="Proxmox" />
        <Field label="Host" hint="IP or hostname only — https:// and port 8006 are added automatically. e.g. 192.168.1.5 or proxmox.local">
          <TextInput value={draft.proxmoxHost} onChange={v => update('proxmoxHost', v)} placeholder="192.168.1.5" />
        </Field>
        <Field label="Token ID" hint="Format: user@realm!tokenname — e.g. terraform@pve!terraform-token">
          <TextInput value={draft.proxmoxTokenId} onChange={v => update('proxmoxTokenId', v)} placeholder="terraform@pve!terraform-token" />
        </Field>
        <Field label="Token Secret" hint="UUID from Proxmox → Datacenter → API Tokens">
          <TextInput type="password" value={draft.proxmoxTokenSecret} onChange={v => update('proxmoxTokenSecret', v)} placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" />
        </Field>
        <Field label="User">
          <TextInput value={draft.proxmoxUser} onChange={v => update('proxmoxUser', v)} placeholder="root@pam" />
        </Field>
        <Field label="Nodes" hint="Comma-separated node hostnames">
          <TextInput value={draft.proxmoxNodes} onChange={v => update('proxmoxNodes', v)} placeholder="pve,pve2,pve3" />
        </Field>
      </div>

      {/* FortiGate */}
      <div className="mb-5">
        <SectionHeader label="FortiGate" />
        <Field label="Host" hint="IP or hostname only — https:// is added automatically. e.g. 192.168.1.1 or fortigate.local">
          <TextInput value={draft.fortigateHost} onChange={v => update('fortigateHost', v)} placeholder="192.168.1.1" />
        </Field>
        <Field label="API Key" hint="REST API key from FortiGate → System → Administrators → REST API Admin">
          <TextInput type="password" value={draft.fortigateApiKey} onChange={v => update('fortigateApiKey', v)} placeholder="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" />
        </Field>
      </div>

      {/* TrueNAS */}
      <div className="mb-5">
        <SectionHeader label="TrueNAS" />
        <Field label="Host" hint="IP or hostname only — https:// is added automatically. e.g. 192.168.1.10 or truenas.local">
          <TextInput value={draft.truenasHost} onChange={v => update('truenasHost', v)} placeholder="192.168.1.10" />
        </Field>
        <Field label="API Key" hint="API key from TrueNAS → Credentials → API Keys">
          <TextInput type="password" value={draft.truenasApiKey} onChange={v => update('truenasApiKey', v)} placeholder="1-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" />
        </Field>
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
        <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-3 border-b border-slate-700 pb-1">
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
          className="px-3 py-1.5 bg-slate-700 hover:bg-slate-600 text-xs text-slate-200 rounded transition-colors disabled:opacity-50"
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
        <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-3 border-b border-slate-700 pb-1">
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
          className="px-3 py-1.5 bg-slate-700 hover:bg-slate-600 text-xs text-slate-200 rounded transition-colors disabled:opacity-50"
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
        <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-3 border-b border-slate-700 pb-1">
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
        <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-3 border-b border-slate-700 pb-1">
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
        className="flex items-center gap-1.5 text-slate-400 hover:text-slate-200 transition-colors"
        title="Options"
      >
        <Settings size={16} />
      </button>
    )
  }

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/60 z-40" onClick={closeModal} />

      {/* Modal */}
      <div className="fixed inset-0 flex items-center justify-center z-50 pointer-events-none">
        <div
          className="bg-slate-900 border border-slate-700 rounded-xl shadow-2xl w-[600px] max-h-[85vh] flex flex-col pointer-events-auto"
          onClick={e => e.stopPropagation()}
        >
          {/* Header */}
          <div className="flex items-center justify-between px-5 py-4 border-b border-slate-700 shrink-0">
            <div className="flex items-center gap-2">
              <Settings size={16} className="text-slate-400" />
              <span className="text-sm font-semibold text-slate-200">Options</span>
            </div>
            <button onClick={closeModal} className="text-slate-500 hover:text-slate-300 transition-colors">
              <X size={16} />
            </button>
          </div>

          {/* Tab bar */}
          <div className="flex border-b border-slate-700 shrink-0">
            {TABS.map(t => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`px-4 py-2.5 text-xs font-medium transition-colors border-b-2 ${
                  tab === t
                    ? 'border-blue-500 text-blue-400'
                    : 'border-transparent text-slate-500 hover:text-slate-300'
                }`}
              >
                {t}
              </button>
            ))}
          </div>

          {/* Tab content */}
          <div className="flex-1 overflow-y-auto px-5 py-4">
            {!serverLoaded && (tab === 'Infrastructure' || tab === 'AI Services') && (
              <p className="text-xs text-slate-500 animate-pulse mb-3">Loading from server…</p>
            )}
            {draft && (
              <>
                {tab === 'General'        && <GeneralTab        draft={draft} update={update} />}
                {tab === 'Infrastructure' && <InfrastructureTab draft={draft} update={update} />}
                {tab === 'AI Services'    && <AIServicesTab     draft={draft} update={update} />}
                {tab === 'Display'        && <DisplayTab        draft={draft} update={update} />}
              </>
            )}
          </div>

          {/* Footer */}
          <div className="flex items-center justify-end gap-3 px-5 py-3 border-t border-slate-700 shrink-0">
            {saveError && (
              <span className="text-xs text-red-400 mr-auto">{saveError}</span>
            )}
            <button
              onClick={closeModal}
              className="px-4 py-1.5 text-xs text-slate-400 hover:text-slate-200 transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={save}
              disabled={saving}
              className="px-4 py-1.5 bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold rounded transition-colors disabled:opacity-50"
            >
              {saving ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      </div>
    </>
  )
}
