import { useEffect, useRef } from 'react'
import { useAgentOutput } from '../context/AgentOutputContext'
import { useTask } from '../context/TaskContext'
import ChoiceBar from './ChoiceBar'
import ClarificationWidget from './ClarificationWidget'
import SubtaskOfferCard from './SubtaskOfferCard'
import AgentDiagnostics from './AgentDiagnostics'

const TYPE_STYLE = {
  step:      { line: 'text-slate-400',  icon: '──' },
  reasoning: { line: 'text-slate-300',  icon: '💭' },
  tool:      { line: 'text-blue-300',   icon: '⚙' },
  memory:    { line: 'text-slate-500',  icon: '◈' },
  halt:      { line: 'text-orange-400', icon: '⚠' },
  done:      { line: 'text-green-400',  icon: '✓' },
  error:     { line: 'text-red-400',    icon: '✗' },
  pong:      { line: 'text-slate-600',  icon: '·' },
}

const STATUS_COLOR = {
  ok:        'text-green-400',
  degraded:  'text-yellow-400',
  failed:    'text-red-400',
  escalated: 'text-orange-400',
  error:     'text-red-400',
  '':        '',
}

function Line({ msg }) {
  const { line, icon } = TYPE_STYLE[msg.type] ?? TYPE_STYLE.step
  const statusColor = STATUS_COLOR[msg.status] ?? ''
  const ts = (() => {
    if (!msg.timestamp) return 'N/A'
    const d = new Date(msg.timestamp)
    return isNaN(d.getTime()) ? 'N/A' : d.toLocaleTimeString()
  })()

  return (
    <div className={`flex gap-2 py-0.5 font-mono text-xs leading-relaxed ${line}`}>
      <span className="text-slate-600 shrink-0 w-16">{ts}</span>
      <span className="shrink-0 w-4">{icon}</span>
      <span className={`flex-1 whitespace-pre-wrap break-all ${
        msg.type === 'tool' ? statusColor : ''
      }`}>
        {msg.content}
      </span>
    </div>
  )
}

const AGENT_BADGE = {
  status:   { label: 'Status',   cls: 'bg-blue-900 text-blue-300'   },
  action:   { label: 'Action',   cls: 'bg-orange-900 text-orange-300' },
  research: { label: 'Research', cls: 'bg-purple-900 text-purple-300' },
}

export default function OutputPanel({ onTab }) {
  const { outputLines, runState, wsState, clearOutput, pendingChoices, clearChoices, agentType, lastAgentType, stopAgent, pendingProposals, zeroPivot, contradictions, agentDiag } = useAgentOutput()
  const { setTask } = useTask()
  const bottomRef = useRef(null)

  const pickChoice = (text) => {
    setTask(text)
    clearChoices()
  }

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [outputLines])

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-slate-700">
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold uppercase tracking-wider text-slate-400">
            Live Output
          </span>
          {runState === 'running' && agentType && AGENT_BADGE[agentType] && (
            <span className={`text-xs font-bold px-1.5 py-0.5 rounded ${AGENT_BADGE[agentType].cls}`}>
              {AGENT_BADGE[agentType].label}
            </span>
          )}
          {runState === 'running' && (
            <span className="text-yellow-400 animate-pulse text-xs">⚡ Running…</span>
          )}
          {runState === 'idle' && lastAgentType && AGENT_BADGE[lastAgentType] && (
            <span className={`text-xs px-1.5 py-0.5 rounded opacity-50 ${AGENT_BADGE[lastAgentType].cls}`}>
              {AGENT_BADGE[lastAgentType].label}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <span className={`flex items-center gap-1 text-xs ${
            wsState === 'connected'  ? 'text-green-400' :
            wsState === 'connecting' ? 'text-yellow-400 animate-pulse' : 'text-red-400'
          }`}>
            <span className="w-1.5 h-1.5 rounded-full bg-current inline-block" />
            {wsState}
          </span>
          {runState === 'running' && (
            <button
              onClick={stopAgent}
              className="text-xs px-2 py-0.5 rounded border border-red-700 text-red-400 hover:bg-red-950 transition-colors"
            >
              ⏹ Stop
            </button>
          )}
          <button onClick={clearOutput} className="text-xs text-slate-500 hover:text-slate-300">
            clear
          </button>
        </div>
      </div>

      <ClarificationWidget dark />

      {/* Output stream */}
      <div className="flex-1 overflow-y-auto px-3 py-2 bg-slate-950">
        <AgentDiagnostics diag={agentDiag} />
        {zeroPivot && (
          <div className="mono" style={{
            margin: '6px 0', padding: '6px 10px',
            background: 'var(--amber-dim)', color: 'var(--amber)',
            border: '1px solid var(--amber)', borderRadius: 2,
            fontSize: 10, letterSpacing: '0.1em',
          }}>
            ⚠ PIVOT NUDGE — {zeroPivot.tool} returned 0 · {zeroPivot.consecutive_zeros}× in a row
            {zeroPivot.prior_nonzero > 0 && <> (earlier: {zeroPivot.prior_nonzero})</>}
          </div>
        )}
        {contradictions && contradictions.length > 0 && (
          <div className="mono" style={{
            margin: '8px 0', padding: '8px 10px',
            background: 'var(--red-dim)', color: 'var(--red)',
            border: '1px solid var(--red)', borderRadius: 2, fontSize: 10,
          }}>
            <div style={{ letterSpacing: '0.15em', marginBottom: 4 }}>
              ⚠ EVIDENCE CONTRADICTION — AGENT RECONCILING
            </div>
            {contradictions.map((c, i) => (
              <div key={i} style={{ opacity: 0.9 }}>
                Step {c.step}: {c.tool} → {c.nonzero_count} results (ignored in draft conclusion)
              </div>
            ))}
          </div>
        )}
        {outputLines.length === 0 && (
          <p className="text-xs text-slate-600 mt-4">
            Waiting for agent output…<br />
            Run a tool or agent task from the Commands panel or Dashboard.
          </p>
        )}
        {outputLines
          .filter(m => m && m.type !== 'pong' && m.content)
          .map((m, i) => <Line key={i} msg={m} />)
        }
        <div ref={bottomRef} />
        {/* View in logs — shown after run completes */}
        {runState !== 'running' && pendingProposals?.length > 0 && (
          <SubtaskOfferCard proposals={pendingProposals} />
        )}
        {runState !== 'running' && outputLines.some(m => m.type === 'done' || m.type === 'error') && (
          <button
            onClick={() => onTab && onTab('Logs')}
            style={{
              fontSize: 9, color: 'var(--text-3)', background: 'none',
              border: '1px solid var(--border)', borderRadius: 2,
              padding: '2px 8px', cursor: 'pointer', marginTop: 8,
              fontFamily: 'var(--font-mono)', letterSpacing: '0.04em',
            }}
          >
            ⊞ View full log →
          </button>
        )}
      </div>
      <ChoiceBar choices={pendingChoices} onPick={pickChoice} dark />
    </div>
  )
}
