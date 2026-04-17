import { useState } from 'react'

/**
 * SubAgentPanel — renders in-band sub-agent activity inside the parent's
 * OutputPanel. Introduced in v2.34.0 alongside the harness in-band spawn
 * of propose_subtask. Each panel corresponds to one subagent_spawned event
 * and updates on subagent_done.
 */
const STATUS_STYLE = {
  running:   { label: 'RUNNING',   cls: 'bg-blue-900 text-blue-300' },
  done:      { label: 'DONE',      cls: 'bg-green-900 text-green-300' },
  failed:    { label: 'FAILED',    cls: 'bg-red-900 text-red-300' },
  timeout:   { label: 'TIMEOUT',   cls: 'bg-orange-900 text-orange-300' },
  cancelled: { label: 'CANCELLED', cls: 'bg-slate-800 text-slate-400' },
  cap_hit:   { label: 'CAPPED',    cls: 'bg-yellow-900 text-yellow-300' },
  escalated: { label: 'ESCALATED', cls: 'bg-orange-900 text-orange-300' },
}

export default function SubAgentPanel({ sub }) {
  const [expanded, setExpanded] = useState(sub.status === 'running')
  const badge = STATUS_STYLE[sub.status] || STATUS_STYLE.running
  const indent = { marginLeft: `${Math.min((sub.depth || 1) * 12, 48)}px` }

  return (
    <div
      className="mt-2 border-l-2 border-l-red-700 bg-slate-900/40 rounded-sm"
      style={indent}
    >
      <div
        className="flex items-center gap-2 px-2 py-1 cursor-pointer hover:bg-slate-800/40"
        onClick={() => setExpanded(v => !v)}
      >
        <span className="text-red-500 font-mono text-xs shrink-0">
          ↳ SUB-AGENT
        </span>
        <span className="text-xs uppercase tracking-wider text-slate-400">
          {sub.agent_type}
        </span>
        {sub.scope_entity && (
          <span className="text-xs font-mono text-slate-500">
            {sub.scope_entity}
          </span>
        )}
        <span className={`text-xs font-bold px-1.5 py-0.5 rounded ${badge.cls}`}>
          {badge.label}
        </span>
        {sub.tools_used !== undefined && sub.status !== 'running' && (
          <span className="text-xs text-slate-500">
            tools={sub.tools_used}/{sub.budget_tools}
          </span>
        )}
        <span className="ml-auto text-xs text-slate-500">
          {expanded ? '▾' : '▸'}
        </span>
      </div>

      {expanded && (
        <div className="px-3 py-2 font-mono text-xs text-slate-300 space-y-1">
          <div>
            <span className="text-slate-500">objective: </span>
            {sub.objective}
          </div>
          <div>
            <span className="text-slate-500">depth: </span>{sub.depth}
            <span className="ml-3 text-slate-500">budget: </span>{sub.budget_tools}
          </div>
          {sub.final_answer && (
            <div className="mt-2 whitespace-pre-wrap break-words text-slate-200">
              <span className="text-slate-500">final_answer:</span>
              {'\n'}{sub.final_answer}
            </div>
          )}
          {sub.status === 'running' && (
            <div className="text-blue-400 italic">
              sub-agent in progress — parent is blocked until it returns
            </div>
          )}
        </div>
      )}
    </div>
  )
}
