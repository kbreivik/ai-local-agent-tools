import { useCallback, useState } from 'react'

/**
 * CopyableId — v2.38.5 shared click-to-copy ID pill.
 *
 * Extracted verbatim from v2.38.1's LogTable::copyId pattern so every
 * UUID field in the Logs sub-pages has the same UX:
 *   - 8-char truncated display (configurable)
 *   - hover title showing full UUID + "Click to copy"
 *   - click → clipboard.writeText with execCommand fallback
 *   - green ✓ flash for 1.5s on success
 *   - renders "—" in a muted style when value is null/empty
 *
 * Props:
 *   value:     string | number | null — the full ID to copy
 *   prefixLen: number — characters to display (default 8)
 *   label:     optional string shown inside the pill instead of the
 *              truncated value (e.g. "sess: a1b2c3d4"). If set,
 *              it's ALWAYS rendered — it does NOT fall back to showing
 *              the truncated value when label is truthy.
 *   dim:       boolean — render in muted colour (e.g. secondary IDs
 *              in a row where another ID is primary)
 *
 * Styling uses Tailwind classes that already exist in the bundle; no
 * new CSS. Matches the v2.38.1 pattern exactly so Operations view is
 * visually consistent.
 */
export default function CopyableId({
  value, prefixLen = 8, label = '', dim = false,
}) {
  const [copied, setCopied] = useState(false)

  const onClick = useCallback(async (e) => {
    if (e) e.stopPropagation()
    if (value == null || value === '') return
    const full = String(value)
    try {
      await navigator.clipboard.writeText(full)
    } catch {
      // Fallback for non-HTTPS / old browsers (copied from v2.38.1)
      const ta = document.createElement('textarea')
      ta.value = full
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      document.body.appendChild(ta)
      ta.select()
      try { document.execCommand('copy') } catch {}
      document.body.removeChild(ta)
    }
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }, [value])

  if (value == null || value === '') {
    return <span className="text-slate-700">—</span>
  }

  const full = String(value)
  const display = label || full.slice(0, prefixLen)
  const colour = dim ? 'text-slate-500 hover:text-slate-400'
                     : 'text-blue-300 hover:text-blue-200'

  return (
    <button
      onClick={onClick}
      title={copied ? 'Copied!' : `Click to copy: ${full}`}
      className={`font-mono text-xs ${colour}`}
      style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer' }}
    >
      {display}
      {copied && <span className="ml-1 text-green-400">✓</span>}
    </button>
  )
}
