/**
 * ChoiceBar — shows numbered choices extracted from the agent's final message.
 * Clicking a choice prefills the shared task and clears the choice list.
 *
 * Props:
 *   choices    string[]   — list of choice strings (already stripped of number prefix)
 *   onPick     (text) => void   — called with the chosen text
 *   dark       boolean    — use dark Tailwind classes (for OutputPanel / CommandPanel)
 */
export default function ChoiceBar({ choices, onPick, dark = false }) {
  if (!choices || choices.length === 0) return null

  const label   = dark ? 'text-slate-400' : 'text-gray-500'
  const btnBase = dark
    ? 'bg-slate-700 hover:bg-slate-600 text-slate-200 border border-slate-600'
    : 'bg-white hover:bg-blue-50 text-gray-700 border border-gray-300'

  return (
    <div className={`px-3 py-2 border-t ${dark ? 'border-slate-700 bg-slate-900' : 'border-gray-200 bg-gray-50'}`}>
      <p className={`text-xs mb-1.5 ${label}`}>Suggested next actions:</p>
      <div className="flex flex-col gap-1">
        {choices.map((c, i) => (
          <button
            key={i}
            onClick={() => onPick(c)}
            className={`text-left text-xs px-2 py-1 rounded transition-colors ${btnBase}`}
          >
            <span className={`font-mono mr-1.5 ${dark ? 'text-slate-500' : 'text-gray-400'}`}>{i + 1}.</span>
            {c}
          </button>
        ))}
      </div>
    </div>
  )
}
