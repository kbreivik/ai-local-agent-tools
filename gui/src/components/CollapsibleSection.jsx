import React from 'react'

/**
 * CollapsibleSection — v2.36.4.
 *
 * Reusable collapsible wrapper with localStorage-persisted open/closed state.
 * Used across AI Services settings subsections, Sidebar groups, and any other
 * page section that benefits from an operator-togglable chevron.
 *
 * Props:
 *   title        — header label (required)
 *   defaultOpen  — initial state when nothing is persisted (default true)
 *   storageKey   — localStorage key suffix; key = `collapse:${storageKey}`
 *                  If omitted, state is not persisted.
 */
export default function CollapsibleSection({ title, defaultOpen = true, storageKey, children }) {
  const [open, setOpen] = React.useState(() => {
    if (!storageKey) return defaultOpen
    try {
      const raw = localStorage.getItem(`collapse:${storageKey}`)
      return raw === null ? defaultOpen : raw === 'true'
    } catch { return defaultOpen }
  })
  React.useEffect(() => {
    if (!storageKey) return
    try { localStorage.setItem(`collapse:${storageKey}`, String(open)) } catch {}
  }, [open, storageKey])
  return (
    <div className="mb-4 border border-white/5 rounded">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-3 py-2
                   text-sm font-mono uppercase tracking-wider
                   bg-[var(--bg-2)] hover:bg-white/5 text-[var(--accent)]"
        style={{ borderRadius: 0 }}
      >
        <span>{title}</span>
        <span style={{ transform: open ? 'rotate(90deg)' : 'rotate(0deg)',
                        transition: 'transform 0.15s' }}>›</span>
      </button>
      {open && <div className="p-3">{children}</div>}
    </div>
  )
}
