import { useEffect, useState } from 'react'
import { fetchTools, invokeTool, runAgent, fetchSkills, executeSkill } from '../api'
import { useAgent } from '../context/AgentContext'
import { useTask } from '../context/TaskContext'
import ChoiceBar from './ChoiceBar'
import ClarificationWidget from './ClarificationWidget'
import AgentFeed from './AgentFeed'
import { useAgentOutput } from '../context/AgentOutputContext'

// ── Tool name humanization ────────────────────────────────────────────────────

function humanizeTool(name) {
  if (!name) return ''
  return name.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')
}

function humanizeCategory(cat) {
  if (!cat) return ''
  return cat.charAt(0).toUpperCase() + cat.slice(1)
}

// ── Category badge colors ─────────────────────────────────────────────────────

const CATEGORY_COLOR = {
  // built-in tool categories
  swarm:         'bg-blue-900 text-blue-300',
  kafka:         'bg-purple-900 text-purple-300',
  orchestration: 'bg-amber-900 text-amber-300',
  elastic:       'bg-teal-900 text-teal-300',
  network:       'bg-green-900 text-green-300',
  docker:        'bg-sky-800 text-sky-200',
  // skill categories
  compute:       'bg-sky-900 text-sky-300',
  monitoring:    'bg-cyan-900 text-cyan-300',
  storage:       'bg-violet-900 text-violet-300',
  general:       'bg-slate-700 text-slate-300',
  // common service names from generated skills
  proxmox:       'bg-orange-900 text-orange-300',
  fortigate:     'bg-red-900 text-red-300',
  truenas:       'bg-indigo-900 text-indigo-300',
}

// ── Skill normalisation ───────────────────────────────────────────────────────

function normaliseSkillParams(parameters) {
  const props    = parameters?.properties ?? {}
  const required = parameters?.required   ?? []
  return Object.entries(props).map(([name, schema]) => ({
    name,
    type:        schema.type        ?? 'string',
    description: schema.description ?? '',
    required:    required.includes(name),
    default:     schema.default     ?? (schema.type === 'boolean' ? false : ''),
  }))
}

function deriveTags(item) {
  if (item.source === 'skill') {
    const parts = [item.compat?.service, item.category].filter(Boolean)
    return parts.length ? [...new Set(parts)] : ['general']
  }
  return [item.category || 'general']
}

// ── Traffic light run button ──────────────────────────────────────────────────

function TrafficLightButton({ runState, onRun, taskEmpty }) {
  if (runState === 'running') {
    return (
      <button
        disabled
        className="mt-1 w-full py-1.5 rounded text-xs font-bold bg-amber-500 text-white cursor-not-allowed"
        style={{ pointerEvents: 'none' }}
      >
        <span className="inline-block animate-spin mr-1" style={{ display: 'inline-block' }}>⏳</span>
        {' '}Running…
      </button>
    )
  }
  if (runState === 'stopping') {
    return (
      <button
        disabled
        className="mt-1 w-full py-1.5 rounded text-xs font-bold bg-red-600 text-white cursor-not-allowed"
        style={{ pointerEvents: 'none' }}
      >
        ⏹ Stop
      </button>
    )
  }
  // idle
  return (
    <button
      onClick={onRun}
      disabled={taskEmpty}
      className={`mt-1 w-full py-1.5 rounded text-xs font-bold transition-colors ${
        taskEmpty
          ? 'bg-slate-700 text-slate-500 cursor-not-allowed'
          : 'bg-green-600 hover:bg-green-700 text-white'
      }`}
    >
      ⚡ Run Agent
    </button>
  )
}

// ── Tool param field ──────────────────────────────────────────────────────────

function ParamField({ param, value, onChange }) {
  const type = param.type === 'boolean' ? 'checkbox' : 'text'
  return (
    <div className="mb-2">
      <label className="block text-xs text-slate-400 mb-0.5">
        {param.name}
        {param.required && <span className="text-red-400 ml-1">*</span>}
        <span className="ml-1 text-slate-600 font-mono">{param.type}</span>
      </label>
      {type === 'checkbox' ? (
        <input
          type="checkbox"
          checked={!!value}
          onChange={e => onChange(e.target.checked)}
          className="accent-blue-500"
        />
      ) : (
        <input
          type="text"
          value={value ?? param.default ?? ''}
          onChange={e => onChange(e.target.value)}
          placeholder={param.default ?? ''}
          className="w-full bg-slate-800 border border-slate-600 rounded px-2 py-1 text-xs text-slate-200 focus:outline-none focus:border-blue-500"
        />
      )}
    </div>
  )
}

// ── Tool card ─────────────────────────────────────────────────────────────────

function ToolCard({ tool, onResult }) {
  const [open, setOpen]     = useState(false)
  const [params, setParams] = useState({})
  const [busy, setBusy]     = useState(false)
  const [result, setResult] = useState(null)

  const setParam = (name, val) => setParams(p => ({ ...p, [name]: val }))

  const execute = async () => {
    setBusy(true)
    setResult(null)
    try {
      const r = tool.source === 'skill'
        ? await executeSkill(tool.name, params)
        : await invokeTool(tool.name, params)
      setResult(r)
      onResult?.()
    } catch (e) {
      setResult({ status: 'error', message: String(e) })
    } finally {
      setBusy(false)
    }
  }

  const badge = CATEGORY_COLOR[tool.category] ?? 'bg-slate-700 text-slate-300'
  const statusColor = result
    ? result.status === 'ok'        ? 'border-green-600'
    : result.status === 'degraded'  ? 'border-yellow-600'
    : result.status === 'escalated' ? 'border-orange-600'
    : 'border-red-600'
    : 'border-slate-700'

  return (
    <div className={`border rounded ${statusColor} mb-1.5 overflow-hidden transition-colors`}>
      <button
        className="w-full text-left px-3 py-2 flex items-center gap-2 hover:bg-slate-800 transition-colors"
        onClick={() => setOpen(o => !o)}
      >
        <span className={`text-xs px-1.5 py-0.5 rounded font-mono shrink-0 ${badge}`}>
          {humanizeCategory(tool.category)}
        </span>
        {tool.source === 'skill' && (
          <span className="text-xs px-1.5 py-0.5 rounded bg-amber-900 text-amber-300 shrink-0">
            generated
          </span>
        )}
        <span className="text-sm text-slate-200 flex-1">{humanizeTool(tool.name)}</span>
        <span className="text-slate-600 text-xs">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="px-3 pb-3 bg-slate-900 border-t border-slate-700">
          {tool.description && (
            <p className="text-xs text-slate-400 mt-2 mb-3">{tool.description}</p>
          )}

          {tool.params.map(p => (
            <ParamField
              key={p.name}
              param={p}
              value={params[p.name]}
              onChange={v => setParam(p.name, v)}
            />
          ))}

          <button
            onClick={execute}
            disabled={busy}
            className={`mt-2 w-full py-1.5 rounded text-xs font-bold transition-colors ${
              busy
                ? 'bg-slate-700 text-slate-500 cursor-not-allowed'
                : 'bg-blue-600 hover:bg-blue-500 text-white'
            }`}
          >
            {busy ? '⏳ Running…' : '▶ Execute'}
          </button>

          {result && (
            <div className={`mt-2 p-2 rounded text-xs font-mono ${
              result.status === 'ok'       ? 'bg-green-950 text-green-300' :
              result.status === 'degraded' ? 'bg-yellow-950 text-yellow-300' :
              'bg-red-950 text-red-300'
            }`}>
              <div className="font-bold mb-1">{result.status} — {result.message}</div>
              <pre className="whitespace-pre-wrap max-h-32 overflow-y-auto text-slate-400">
                {JSON.stringify(result.data, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── CommandPanel ──────────────────────────────────────────────────────────────
// mode="panel" — narrow, inside the slide-in side panel (360px)
// mode="tab"   — full width, rendered when Commands tab is active

export default function CommandPanel({ onResult, mode = 'panel' }) {
  const { markRunning, markDone } = useAgent()
  const { task, setTask }         = useTask()
  const { pendingChoices, clearChoices, runState, setRunState, stopAgent } = useAgentOutput()
  const [items,    setItems]   = useState([])
  const [loading,  setLoading] = useState(true)
  const [selectedTags, setSelectedTags] = useState(new Set())
  const [andMode,  setAndMode] = useState(false)
  const [agentMsg, setAgentMsg] = useState('')

  const isTab = mode === 'tab'

  useEffect(() => {
    Promise.all([
      fetchTools().catch(() => []),
      fetchSkills().catch(() => []),
    ]).then(([tools, skills]) => {
      const normTools = tools.map(t => ({
        ...t,
        source: 'tool',
        tags: [(t.category || 'general').toLowerCase()],
      }))
      const normSkills = skills.map(s => ({
        name:        s.name,
        description: s.description ?? '',
        category:    s.category ?? 'general',
        params:      normaliseSkillParams(s.parameters),
        source:      'skill',
        compat:      s.compat ?? null,
        tags:        [],
      })).map(s => ({ ...s, tags: deriveTags(s) }))

      const sorted = [
        ...normTools.sort((a, b) => a.name.localeCompare(b.name)),
        ...normSkills.sort((a, b) => a.name.localeCompare(b.name)),
      ]
      setItems(sorted)
    }).finally(() => setLoading(false))
  }, [])

  const toolTags  = new Set(items.filter(i => i.source === 'tool').flatMap(i => i.tags))
  const skillTags = new Set(items.filter(i => i.source === 'skill').flatMap(i => i.tags))
  const allTags   = [
    ...[...toolTags].sort(),
    ...[...skillTags].filter(t => !toolTags.has(t)).sort(),
  ]

  const visible = selectedTags.size === 0
    ? items
    : items.filter(item =>
        andMode
          ? [...selectedTags].every(t => item.tags.includes(t))
          : [...selectedTags].some(t => item.tags.includes(t))
      )

  const runAgentTask = async () => {
    if (!task.trim() || runState !== 'idle') return
    // Immediately go amber — don't wait for API
    setRunState('running')
    setAgentMsg('')
    clearChoices()
    markRunning()
    try {
      const r = await runAgent(task)
      setAgentMsg(`Session ${r.session_id?.slice(0, 8)}`)
      onResult?.()
    } catch (e) {
      setAgentMsg(`Error: ${e.message}`)
      setRunState('idle')
      markDone(false)
    }
  }

  const pickChoice = (text) => {
    setTask(text)
    clearChoices()
  }

  const inner = (
    <div className="flex flex-col h-full" data-component="CommandPanel">
      {/* Agent task input */}
      <div className={`border-b border-slate-700 bg-slate-900 shrink-0 ${isTab ? 'px-4 py-3' : 'px-3 py-2'}`}>
        {isTab && (
          <p className="text-sm font-semibold text-slate-300 mb-2">Agent Task</p>
        )}
        {!isTab && (
          <p className="text-xs text-slate-500 mb-1 font-bold uppercase">Agent Task</p>
        )}
        <textarea
          value={task}
          onChange={e => setTask(e.target.value)}
          placeholder="Describe a task for the agent…"
          rows={isTab ? 6 : 4}
          className="w-full bg-slate-800 border border-slate-600 rounded px-2 py-1 text-xs text-slate-200 resize-vertical focus:outline-none focus:border-blue-500"
          style={{ minHeight: isTab ? 120 : 80 }}
        />
        <TrafficLightButton
          runState={runState}
          onRun={runAgentTask}
          taskEmpty={!task.trim()}
        />
        {agentMsg && <p className="text-xs text-slate-400 mt-1">{agentMsg}</p>}
      </div>
      {/* Inline agent feed — below Run button, above tool list */}
      <AgentFeed />
      <ChoiceBar choices={pendingChoices} onPick={pickChoice} dark />
      <ClarificationWidget dark />

      {/* Tag filter bar */}
      <div className={`flex gap-1 border-b border-slate-700 flex-wrap items-center shrink-0 ${isTab ? 'px-4 py-2' : 'px-3 py-2'}`}>
        {allTags.map(tag => (
          <button
            key={tag}
            onClick={() => setSelectedTags(prev => {
              const next = new Set(prev)
              next.has(tag) ? next.delete(tag) : next.add(tag)
              return next
            })}
            className={`text-xs px-2 py-0.5 rounded transition-colors ${
              selectedTags.has(tag)
                ? 'bg-blue-600 text-white'
                : 'bg-slate-700 text-slate-400 hover:bg-slate-600'
            }`}
          >
            {humanizeCategory(tag)}
          </button>
        ))}
        {selectedTags.size > 0 && (
          <button
            onClick={() => setSelectedTags(new Set())}
            className="text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-500 hover:text-slate-300 ml-1"
          >
            ✕ clear
          </button>
        )}
        {allTags.length > 0 && (
          <div className="ml-auto flex items-center gap-0 border border-slate-600 rounded overflow-hidden text-xs shrink-0">
            <button
              onClick={() => setAndMode(false)}
              className={`px-2 py-0.5 transition-colors ${!andMode ? 'bg-blue-600 text-white' : 'bg-slate-800 text-slate-400 hover:bg-slate-700'}`}
            >
              OR
            </button>
            <button
              onClick={() => setAndMode(true)}
              className={`px-2 py-0.5 transition-colors ${andMode ? 'bg-blue-600 text-white' : 'bg-slate-800 text-slate-400 hover:bg-slate-700'}`}
            >
              AND
            </button>
          </div>
        )}
      </div>

      {/* Tool list — 2-column grid in tab mode, single column in panel mode */}
      <div className={`flex-1 overflow-y-auto ${isTab ? 'px-4 py-3' : 'px-3 py-2'}`}>
        {loading && <p className="text-xs text-slate-500 animate-pulse">Loading…</p>}
        {!loading && visible.length === 0 && (
          <p className="text-xs text-slate-600">No items match the selected tags.</p>
        )}
        <div className={isTab ? 'grid grid-cols-2 gap-x-4' : ''}>
          {visible.map(item => (
            <ToolCard key={item.name} tool={item} onResult={onResult} />
          ))}
        </div>
      </div>
    </div>
  )

  if (isTab) {
    return (
      <div className="flex flex-col h-full w-full bg-slate-950">
        <div className="px-4 py-2 border-b border-slate-700 bg-slate-900 shrink-0 flex items-center gap-2">
          <span className="text-xs font-bold uppercase tracking-wider text-slate-400">Commands</span>
          <span className="text-slate-600 text-xs">— execute tools or run agent tasks</span>
        </div>
        <div className="flex-1 overflow-hidden max-w-5xl w-full mx-auto">
          {inner}
        </div>
      </div>
    )
  }

  return inner
}
