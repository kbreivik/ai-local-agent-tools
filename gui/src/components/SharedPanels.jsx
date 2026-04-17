/**
 * SharedPanels — small V3a Imperial presentational helpers reused across
 * GatesView, SkillsTab (Metrics subtab), and future dashboard panels.
 *
 * Keep props intentionally minimal — composition over configuration.
 */

export function Panel({ title, children }) {
  return (
    <div style={{ border: '1px solid var(--border)', borderRadius: 2, background: 'var(--bg-1)' }}>
      <div style={{
        padding: '6px 10px', borderBottom: '1px solid var(--border)',
        fontSize: 9, color: 'var(--text-3)', fontFamily: 'var(--font-mono)', letterSpacing: 1.5,
      }}>
        {title}
      </div>
      <div style={{ padding: 10 }}>{children}</div>
    </div>
  )
}

export function Stat({ label, value, color, tooltip }) {
  return (
    <div title={tooltip} style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 72 }}>
      <span style={{
        fontSize: 16, color: color || 'var(--text-1)',
        fontFamily: 'var(--font-mono)', lineHeight: 1,
      }}>
        {value ?? '—'}
      </span>
      <span style={{
        fontSize: 8, color: 'var(--text-3)',
        letterSpacing: 0.5, textTransform: 'uppercase',
      }}>
        {label}
      </span>
    </div>
  )
}

export function Empty({ label = 'none' }) {
  return <div style={{ fontSize: 10, color: 'var(--text-3)', padding: '4px 0' }}>{label}</div>
}

export default { Panel, Stat, Empty }
