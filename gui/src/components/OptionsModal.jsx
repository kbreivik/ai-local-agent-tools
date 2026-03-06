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

function InfrastructureTab({ draft, update }) {
  return (
    <div>
      <Field label="Docker Swarm Manager IPs" hint="One IP address per line">
        <Textarea value={draft.swarmManagerIPs} onChange={v => update('swarmManagerIPs', v)} placeholder="192.168.1.10" />
      </Field>
      <Field label="Docker Swarm Worker IPs" hint="One IP address per line">
        <Textarea value={draft.swarmWorkerIPs} onChange={v => update('swarmWorkerIPs', v)} placeholder="192.168.1.20" />
      </Field>
      <Field label="Docker Host">
        <TextInput value={draft.dockerHost} onChange={v => update('dockerHost', v)} placeholder="npipe:////./pipe/docker_engine" />
      </Field>
      <Field label="Kafka Bootstrap Servers" hint="Comma-separated host:port pairs">
        <TextInput value={draft.kafkaBootstrapServers} onChange={v => update('kafkaBootstrapServers', v)} placeholder="localhost:9092,localhost:9093" />
      </Field>
      <Field label="Elasticsearch URL">
        <TextInput value={draft.elasticsearchUrl} onChange={v => update('elasticsearchUrl', v)} placeholder="http://localhost:9200" />
      </Field>
      <Field label="Kibana URL">
        <TextInput value={draft.kibanaUrl} onChange={v => update('kibanaUrl', v)} placeholder="http://localhost:5601" />
      </Field>
      <Field label="MuninnDB URL">
        <TextInput value={draft.muninndbUrl} onChange={v => update('muninndbUrl', v)} placeholder="http://localhost:8475" />
      </Field>
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

function DisplayTab({ draft, update }) {
  return (
    <div>
      <Field label="Card Minimum Height (px)">
        <input
          type="number"
          min={60}
          max={400}
          value={draft.cardMinHeight}
          onChange={e => update('cardMinHeight', Number(e.target.value))}
          className="w-24 bg-slate-800 border border-slate-600 rounded px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-blue-500"
        />
      </Field>
      <Field label="Card Maximum Height (px)">
        <input
          type="number"
          min={80}
          max={800}
          value={draft.cardMaxHeight}
          onChange={e => update('cardMaxHeight', Number(e.target.value))}
          className="w-24 bg-slate-800 border border-slate-600 rounded px-3 py-1.5 text-xs text-slate-200 focus:outline-none focus:border-blue-500"
        />
      </Field>
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
  const options = useOptions()
  const [open,    setOpen]    = useState(false)
  const [tab,     setTab]     = useState('General')
  const [draft,   setDraft]   = useState(null)
  const [saving,  setSaving]  = useState(false)

  const openModal = () => {
    setDraft({ ...options })
    setTab('General')
    setOpen(true)
  }

  const closeModal = () => {
    setOpen(false)
    setDraft(null)
  }

  const update = (key, value) => {
    setDraft(prev => ({ ...prev, [key]: value }))
  }

  const save = async () => {
    setSaving(true)
    options.saveOptions(draft)

    // Non-critical POST to backend — ignore errors
    try {
      const infraKeys = ['dockerHost', 'kafkaBootstrapServers', 'elasticsearchUrl',
                         'kibanaUrl', 'muninndbUrl', 'swarmManagerIPs', 'swarmWorkerIPs']
      const infraSettings = Object.fromEntries(infraKeys.map(k => [k, draft[k]]))
      await fetch(`${BASE}/api/settings`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(infraSettings),
      })
    } catch { /* ignore */ }

    setSaving(false)
    closeModal()
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
