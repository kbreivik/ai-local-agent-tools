// TraceView — v2.34.16 — per-step viewer for agent LLM traces.
// Pulls /api/logs/operations/{op_id}/trace, renders a two-pane layout:
//   left: step list + gates-fired summary + prompt actions
//   right: selected step detail (assistant + tool calls + tool results + harness msgs)
//
// Gate detection uses gui/src/utils/gateDetection.js which mirrors the server-
// side detector in api/agents/gate_detection.py.

import { useEffect, useMemo, useState } from 'react'
import { detectGates } from '../utils/gateDetection'
import { authHeaders } from '../api'

const _BASE = import.meta.env.VITE_API_BASE ?? ''

function stepsHaveGate(step) {
  const g = detectGates([step])
  return Object.values(g).some((v) => v.count > 0)
}

function OperationPicker({ selected, onChange }) {
  const [opsList, setOpsList] = useState([])
  const [filter, setFilter] = useState('')

  useEffect(() => {
    fetch(`${_BASE}/api/logs/operations?limit=100`, {
      headers: authHeaders(),
      credentials: 'include',
    })
      .then((r) => (r.ok ? r.json() : { operations: [] }))
      .then((d) => setOpsList(d.operations || []))
      .catch(() => setOpsList([]))
  }, [])

  const visible = useMemo(() => {
    const f = filter.trim().toLowerCase()
    if (!f) return opsList.slice(0, 50)
    return opsList
      .filter((o) =>
        [o.id, o.task, o.agent_type, o.status]
          .filter(Boolean)
          .join(' ')
          .toLowerCase()
          .includes(f),
      )
      .slice(0, 50)
  }, [opsList, filter])

  return (
    <div className="flex items-center gap-2 px-3 py-2 border-b border-slate-700 bg-slate-900">
      <label className="text-xs text-slate-400">Operation:</label>
      <input
        type="text"
        placeholder="filter by id / task / status"
        className="text-xs bg-slate-800 border border-slate-700 rounded px-2 py-1 text-slate-200 w-48"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
      />
      <select
        className="text-xs bg-slate-800 border border-slate-700 rounded px-2 py-1 text-slate-200 flex-1"
        value={selected || ''}
        onChange={(e) => onChange(e.target.value || null)}
      >
        <option value="">— choose operation —</option>
        {visible.map((o) => (
          <option key={o.id} value={o.id}>
            {(o.id || '').slice(0, 8)} · {o.agent_type || '?'} · {o.status || '?'} ·{' '}
            {(o.task || '').slice(0, 60)}
          </option>
        ))}
      </select>
    </div>
  )
}

function StepList({ steps, selected, onSelect }) {
  return (
    <div className="border-b border-slate-800">
      <div className="px-2 py-1 text-[10px] uppercase tracking-wider text-slate-500">
        Steps
      </div>
      <div className="max-h-96 overflow-y-auto">
        {steps.map((s, i) => {
          const flagged = stepsHaveGate(s)
          const active = i === selected
          return (
            <button
              key={i}
              onClick={() => onSelect(i)}
              className={`w-full text-left px-2 py-1 text-xs flex items-center gap-2 ${
                active ? 'bg-blue-900 text-blue-200' : 'hover:bg-slate-800 text-slate-300'
              }`}
            >
              <span className="font-mono text-slate-500 w-6">#{s.step_index ?? i}</span>
              <span className="font-mono text-slate-400 w-10">
                {s.tool_calls_count ?? 0} tc
              </span>
              <span className="font-mono text-slate-500 truncate">
                {s.finish_reason || '-'}
              </span>
              {flagged && <span className="ml-auto text-amber-400">🚩</span>}
            </button>
          )
        })}
      </div>
    </div>
  )
}

function GatesFired({ steps, onJumpToStep }) {
  const gates = useMemo(() => detectGates(steps), [steps])
  const any = Object.values(gates).some((v) => v.count > 0)

  return (
    <div className="border-b border-slate-800 px-2 py-2">
      <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">
        Gates Fired
      </div>
      {!any && <div className="text-xs text-slate-600 italic">none detected</div>}
      {any &&
        Object.entries(gates).map(([name, info]) =>
          info.count === 0 ? null : (
            <div key={name} className="text-xs text-slate-300 py-0.5">
              <span className="text-amber-400">✓</span>{' '}
              <span className="font-mono">{name}</span>{' '}
              <span className="text-slate-500">×{info.count}</span>
              {info.details.length > 0 && (
                <span className="ml-1 text-slate-600">
                  {info.details.slice(0, 5).map((d, i) => (
                    <button
                      key={i}
                      className="ml-1 text-blue-400 hover:underline"
                      onClick={() => onJumpToStep?.(d.step)}
                    >
                      #{d.step}
                    </button>
                  ))}
                </span>
              )}
            </div>
          ),
        )}
    </div>
  )
}

function TraceActions({ systemPrompt, operationId, trace }) {
  const [copied, setCopied] = useState(false)

  const onCopy = () => {
    if (!systemPrompt) return
    navigator.clipboard.writeText(systemPrompt).then(
      () => {
        setCopied(true)
        setTimeout(() => setCopied(false), 1500)
      },
      () => {},
    )
  }

  const onDownload = () => {
    if (!trace) return
    const blob = new Blob([JSON.stringify(trace, null, 2)], {
      type: 'application/json',
    })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `trace-${(operationId || 'op').slice(0, 8)}.json`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  return (
    <div className="px-2 py-2 flex flex-col gap-1">
      <button
        onClick={onCopy}
        disabled={!systemPrompt}
        className="text-xs bg-slate-800 hover:bg-slate-700 disabled:opacity-50 text-slate-300 rounded px-2 py-1 text-left"
      >
        {copied ? 'Copied!' : 'Copy system prompt'}
      </button>
      <button
        onClick={onDownload}
        disabled={!trace}
        className="text-xs bg-slate-800 hover:bg-slate-700 disabled:opacity-50 text-slate-300 rounded px-2 py-1 text-left"
      >
        Download full JSON
      </button>
    </div>
  )
}

function AssistantBlock({ step }) {
  const content = useMemo(() => {
    const choice = (step?.response_raw?.choices || [])[0] || {}
    return (choice.message && choice.message.content) || ''
  }, [step])
  if (!content) return null
  return (
    <div className="border border-slate-800 rounded p-2 bg-slate-900">
      <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">
        Assistant
      </div>
      <pre className="text-xs text-slate-300 whitespace-pre-wrap font-mono">{content}</pre>
    </div>
  )
}

function ToolCallsBlock({ step }) {
  const calls = useMemo(() => {
    const choice = (step?.response_raw?.choices || [])[0] || {}
    return (choice.message && choice.message.tool_calls) || []
  }, [step])
  if (!calls.length) return null
  return (
    <div className="border border-slate-800 rounded p-2 bg-slate-900">
      <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">
        Tool calls ({calls.length})
      </div>
      {calls.map((tc, i) => {
        const fn = (tc && tc.function) || {}
        let args = fn.arguments
        if (typeof args === 'string') {
          try {
            args = JSON.stringify(JSON.parse(args), null, 2)
          } catch (e) {
            // keep raw string
          }
        } else if (args != null) {
          args = JSON.stringify(args, null, 2)
        }
        return (
          <div key={i} className="mb-2 last:mb-0">
            <div className="text-xs font-mono text-cyan-400">
              {fn.name}(
            </div>
            <pre className="text-[11px] text-slate-400 font-mono whitespace-pre-wrap pl-4">
              {args || ''}
            </pre>
            <div className="text-xs font-mono text-cyan-400">)</div>
          </div>
        )
      })}
    </div>
  )
}

function ToolResultsBlock({ step }) {
  const results = useMemo(
    () => (step?.messages_delta || []).filter((m) => m && m.role === 'tool'),
    [step],
  )
  if (!results.length) return null
  return (
    <div className="border border-slate-800 rounded p-2 bg-slate-900">
      <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">
        Tool results ({results.length})
      </div>
      {results.map((m, i) => {
        let body = m.content || ''
        try {
          body = JSON.stringify(JSON.parse(body), null, 2)
        } catch (e) {
          // leave as string
        }
        return (
          <details key={i} className="mb-2 last:mb-0">
            <summary className="text-xs text-slate-400 cursor-pointer hover:text-slate-200">
              result #{i + 1}{' '}
              <span className="text-slate-600">
                ({String(body).length} chars)
              </span>
            </summary>
            <pre className="text-[11px] text-slate-500 font-mono whitespace-pre-wrap mt-1 max-h-64 overflow-auto">
              {body}
            </pre>
          </details>
        )
      })}
    </div>
  )
}

function HarnessInjectionsBlock({ step }) {
  const injections = useMemo(
    () =>
      (step?.messages_delta || []).filter(
        (m) => m && (m.role === 'system' || m.role === 'user'),
      ),
    [step],
  )
  if (!injections.length) return null
  return (
    <div className="border border-amber-900 rounded p-2 bg-amber-950/40">
      <div className="text-[10px] uppercase tracking-wider text-amber-400 mb-1">
        Harness injections ({injections.length})
      </div>
      {injections.map((m, i) => (
        <div key={i} className="mb-1 last:mb-0">
          <span className="text-[10px] font-mono text-amber-500 uppercase">
            {m.role}
          </span>
          <pre className="text-xs text-amber-100 whitespace-pre-wrap font-mono">
            {m.content || ''}
          </pre>
        </div>
      ))}
    </div>
  )
}

function StepDetail({ step }) {
  if (!step) return <div className="text-slate-600 p-3 text-sm">Select a step</div>
  return (
    <div className="p-3 space-y-3 overflow-y-auto h-full">
      <div className="text-xs text-slate-500 font-mono">
        Step {step.step_index} · finish={step.finish_reason || '-'} · tokens=
        {step.tokens_total ?? '?'} · tool_calls={step.tool_calls_count ?? 0}
      </div>
      <AssistantBlock step={step} />
      <ToolCallsBlock step={step} />
      <ToolResultsBlock step={step} />
      <HarnessInjectionsBlock step={step} />
    </div>
  )
}

export default function TraceView({ operationId: propOperationId }) {
  const [operationId, setOperationId] = useState(propOperationId || null)
  const [trace, setTrace] = useState(null)
  const [selectedStep, setSelectedStep] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [notFound, setNotFound] = useState(false)

  useEffect(() => {
    if (!operationId) {
      setTrace(null)
      return
    }
    setLoading(true)
    setError(null)
    setNotFound(false)
    fetch(`${_BASE}/api/logs/operations/${operationId}/trace`, {
      headers: authHeaders(),
      credentials: 'include',
    })
      .then(async (r) => {
        if (r.status === 404) {
          setNotFound(true)
          return null
        }
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
        return r.json()
      })
      .then((d) => {
        if (d) {
          setTrace(d)
          setSelectedStep(0)
        } else {
          setTrace(null)
        }
      })
      .catch((e) => setError(e.message || String(e)))
      .finally(() => setLoading(false))
  }, [operationId])

  return (
    <div className="flex flex-col h-full bg-slate-950">
      <OperationPicker selected={operationId} onChange={setOperationId} />
      <div className="flex-1 min-h-0 flex">
        {!operationId && (
          <div className="p-4 text-slate-500 text-sm">
            Select an operation to view its trace.
          </div>
        )}
        {operationId && loading && (
          <div className="p-4 text-slate-500 text-sm">Loading trace…</div>
        )}
        {operationId && notFound && (
          <div className="p-4 text-slate-500 text-sm italic">
            No trace data for this operation. Trace persistence was added in
            v2.34.14 (retention: 7 days).
          </div>
        )}
        {operationId && error && (
          <div className="p-4 text-red-400 text-sm">Failed to load trace: {error}</div>
        )}
        {operationId && !loading && !error && !notFound && trace && (
          <>
            <div className="w-64 border-r border-slate-800 flex flex-col overflow-y-auto">
              <StepList
                steps={trace.steps || []}
                selected={selectedStep}
                onSelect={setSelectedStep}
              />
              <GatesFired
                steps={trace.steps || []}
                onJumpToStep={(idx) => {
                  const pos = (trace.steps || []).findIndex(
                    (s) => s.step_index === idx,
                  )
                  if (pos >= 0) setSelectedStep(pos)
                }}
              />
              <TraceActions
                systemPrompt={trace.system_prompt}
                operationId={operationId}
                trace={trace}
              />
            </div>
            <div className="flex-1 min-w-0 overflow-hidden">
              <StepDetail step={(trace.steps || [])[selectedStep]} />
            </div>
          </>
        )}
      </div>
    </div>
  )
}
