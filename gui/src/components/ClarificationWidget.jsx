/**
 * ClarificationWidget — appears when the agent calls clarifying_question().
 * Shown above the output stream in OutputPanel and CommandPanel.
 *
 * Props: dark (bool) — use dark palette (Output panel) or light (Commands panel)
 */
import { useState } from 'react'
import { useAgentOutput } from '../context/AgentOutputContext'
import { sendClarification } from '../api'

export default function ClarificationWidget({ dark = false }) {
  const { pendingClarification, clearClarification } = useAgentOutput()
  const [custom, setCustom] = useState('')
  const [sending, setSending] = useState(false)

  if (!pendingClarification) return null

  const { question, options, sessionId } = pendingClarification

  const answer = async (text) => {
    if (!text.trim() || sending) return
    setSending(true)
    try {
      await sendClarification(sessionId, text.trim())
      clearClarification()
      setCustom('')
    } catch (e) {
      console.error('[ClarificationWidget] send failed:', e)
    } finally {
      setSending(false)
    }
  }

  const bg     = dark ? 'bg-slate-800 border-slate-600'   : 'bg-blue-50 border-blue-200'
  const header = dark ? 'text-blue-300'                   : 'text-blue-700'
  const text   = dark ? 'text-slate-200'                  : 'text-gray-800'
  const btnOpt = dark
    ? 'bg-slate-700 hover:bg-blue-700 text-slate-200 border border-slate-500'
    : 'bg-white hover:bg-blue-100 text-gray-700 border border-blue-300'
  const input  = dark
    ? 'bg-slate-700 border-slate-500 text-slate-200 placeholder-slate-400 focus:border-blue-400'
    : 'bg-white border-blue-300 text-gray-900 placeholder-gray-400 focus:border-blue-500'
  const btnSend = sending
    ? 'bg-gray-400 cursor-not-allowed text-white'
    : (dark ? 'bg-blue-600 hover:bg-blue-500 text-white' : 'bg-blue-600 hover:bg-blue-700 text-white')

  return (
    <div className={`border rounded-lg mx-3 my-2 p-3 ${bg}`}>
      <p className={`text-xs font-semibold mb-2 flex items-center gap-1.5 ${header}`}>
        <span>❓</span> Agent needs clarification
      </p>
      <p className={`text-sm mb-3 ${text}`}>{question}</p>

      {options.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-3">
          {options.map((opt, i) => (
            <button
              key={i}
              onClick={() => answer(opt)}
              disabled={sending}
              className={`text-xs px-3 py-1.5 rounded transition-colors ${btnOpt}`}
            >
              {opt}
            </button>
          ))}
        </div>
      )}

      <div className="flex gap-2">
        <input
          type="text"
          value={custom}
          onChange={e => setCustom(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && answer(custom)}
          placeholder="Or type your answer…"
          disabled={sending}
          className={`flex-1 text-xs px-2 py-1.5 rounded border outline-none transition-colors ${input}`}
        />
        <button
          onClick={() => answer(custom)}
          disabled={sending || !custom.trim()}
          className={`text-xs px-3 py-1.5 rounded font-medium transition-colors ${btnSend}`}
        >
          {sending ? 'Sending…' : 'Answer'}
        </button>
      </div>
    </div>
  )
}
