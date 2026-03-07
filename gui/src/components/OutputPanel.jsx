import { useEffect, useRef } from 'react'
import { useAgentOutput } from '../context/AgentOutputContext'
import { useTask } from '../context/TaskContext'
import ChoiceBar from './ChoiceBar'
import ClarificationWidget from './ClarificationWidget'

const TYPE_STYLE = {
  step:      { line: 'text-slate-400',  icon: '──' },
  reasoning: { line: 'text-slate-300',  icon: '💭' },
  tool:      { line: 'text-blue-300',   icon: '⚙' },
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

export default function OutputPanel() {
  const { outputLines, isRunning, wsState, clearOutput, pendingChoices, clearChoices, agentType, lastAgentType } = useAgentOutput()
  const { setTask } = useTask()
  const bottomRef = useRef(null)

  const pickChoice = (text) => {
    setTask(text)
    clearChoices()
  }

  // Auto-scroll to bottom when new lines arrive
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
          {isRunning && agentType && AGENT_BADGE[agentType] && (
            <span className={`text-xs font-bold px-1.5 py-0.5 rounded ${AGENT_BADGE[agentType].cls}`}>
              {AGENT_BADGE[agentType].label}
            </span>
          )}
          {isRunning && (
            <span className="text-yellow-400 animate-pulse text-xs">⚡ Running…</span>
          )}
          {!isRunning && lastAgentType && AGENT_BADGE[lastAgentType] && (
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
          <button onClick={clearOutput} className="text-xs text-slate-500 hover:text-slate-300">
            clear
          </button>
        </div>
      </div>

      <ClarificationWidget dark />

      {/* Output stream */}
      <div className="flex-1 overflow-y-auto px-3 py-2 bg-slate-950">
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
      </div>
      <ChoiceBar choices={pendingChoices} onPick={pickChoice} dark />
    </div>
  )
}
