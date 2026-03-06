import { useEffect, useState } from 'react'
import { fetchTools, invokeTool, runAgent } from '../api'

const CATEGORY_COLOR = {
  swarm:         'bg-blue-900 text-blue-300',
  kafka:         'bg-purple-900 text-purple-300',
  orchestration: 'bg-amber-900 text-amber-300',
}

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
      const r = await invokeTool(tool.name, params)
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
          {tool.category}
        </span>
        <span className="text-sm text-slate-200 font-mono flex-1">{tool.name}</span>
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

export default function CommandPanel({ onResult }) {
  const [tools, setTools]       = useState([])
  const [loading, setLoading]   = useState(true)
  const [category, setCategory] = useState('all')
  const [task, setTask]         = useState('')
  const [agentBusy, setAgentBusy] = useState(false)
  const [agentMsg, setAgentMsg]   = useState('')

  useEffect(() => {
    fetchTools()
      .then(setTools)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const categories = ['all', ...new Set(tools.map(t => t.category))]
  const visible = category === 'all' ? tools : tools.filter(t => t.category === category)

  const runAgentTask = async () => {
    if (!task.trim()) return
    setAgentBusy(true)
    setAgentMsg('')
    try {
      const r = await runAgent(task)
      setAgentMsg(`Started — session ${r.session_id?.slice(0, 8)}`)
      onResult?.()
    } catch (e) {
      setAgentMsg(`Error: ${e.message}`)
    } finally {
      setAgentBusy(false)
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="px-3 py-2 border-b border-slate-700">
        <span className="text-xs font-bold uppercase tracking-wider text-slate-400">Commands</span>
      </div>

      {/* Agent task input */}
      <div className="px-3 py-2 border-b border-slate-700 bg-slate-900">
        <p className="text-xs text-slate-500 mb-1 font-bold uppercase">Agent Task</p>
        <textarea
          value={task}
          onChange={e => setTask(e.target.value)}
          placeholder="Describe a task for the agent…"
          rows={2}
          className="w-full bg-slate-800 border border-slate-600 rounded px-2 py-1 text-xs text-slate-200 resize-none focus:outline-none focus:border-blue-500"
        />
        <button
          onClick={runAgentTask}
          disabled={agentBusy || !task.trim()}
          className={`mt-1 w-full py-1.5 rounded text-xs font-bold transition-colors ${
            agentBusy || !task.trim()
              ? 'bg-slate-700 text-slate-500 cursor-not-allowed'
              : 'bg-green-700 hover:bg-green-600 text-white'
          }`}
        >
          {agentBusy ? '⏳ Agent running…' : '⚡ Run Agent'}
        </button>
        {agentMsg && <p className="text-xs text-slate-400 mt-1">{agentMsg}</p>}
      </div>

      {/* Category filter */}
      <div className="flex gap-1 px-3 py-2 border-b border-slate-700 flex-wrap">
        {categories.map(c => (
          <button
            key={c}
            onClick={() => setCategory(c)}
            className={`text-xs px-2 py-0.5 rounded capitalize transition-colors ${
              category === c
                ? 'bg-blue-600 text-white'
                : 'bg-slate-700 text-slate-400 hover:bg-slate-600'
            }`}
          >
            {c}
          </button>
        ))}
      </div>

      {/* Tool list */}
      <div className="flex-1 overflow-y-auto px-3 py-2">
        {loading && <p className="text-xs text-slate-500 animate-pulse">Loading tools…</p>}
        {!loading && visible.length === 0 && (
          <p className="text-xs text-slate-600">No tools found.</p>
        )}
        {visible.map(tool => (
          <ToolCard key={tool.name} tool={tool} onResult={onResult} />
        ))}
      </div>
    </div>
  )
}
