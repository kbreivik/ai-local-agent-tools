/**
 * Sidebar — V3a Imperial Ops navigation.
 * Visual-only redesign — all routing/click handlers unchanged.
 */
import { useState, useEffect } from 'react'
import { useAgentOutput } from '../context/AgentOutputContext'
import { fetchHealth } from '../api'
import LockBadge from './LockBadge'

const NAV = [
  { section: 'MONITOR', items: [
    { key: 'Dashboard', icon: '⬡' },
    { key: 'Cluster',   icon: '◈' },
    { key: 'Logs',      icon: '≡' },
    { key: 'Memory',    icon: '◎' },
  ]},
  { section: 'OPERATE', items: [
    { key: 'Commands',  icon: '▶' },
    { key: 'Skills',    icon: '⚙' },
    { key: 'Output',    icon: '◫' },
  ]},
  { section: 'TOOLS', items: [
    { key: 'Tests',     icon: '✓' },
    { key: 'Ingest',    icon: '↓' },
    { key: 'Docs',      icon: '⊞' },
  ]},
  { section: 'SETTINGS', items: [
    { key: 'Settings',  icon: '⊕', label: 'Connections', settingsTab: 'Connections' },
    { key: 'Settings',  icon: '◈', label: 'AI Services', settingsTab: 'AI Services' },
    { key: 'Settings',  icon: '⚙', label: 'Infrastructure', settingsTab: 'Infrastructure' },
    { key: 'Settings',  icon: '⊞', label: 'Permissions', settingsTab: 'Permissions' },
    { key: 'Settings',  icon: '◎', label: 'Access', settingsTab: 'Access' },
    { key: 'Settings',  icon: '◉', label: 'Naming', settingsTab: 'Naming' },
    { key: 'Settings',  icon: '⊞', label: 'Display', settingsTab: 'Display' },
    { key: 'Settings',  icon: '◎', label: 'General', settingsTab: 'General' },
  ]},
]

// DS orb styles
const orbStyle = {
  width: 24, height: 24, borderRadius: '50%', flexShrink: 0,
  background: 'radial-gradient(circle at 40% 35%, #c44 0%, #700 50%, #100 100%)',
  display: 'flex', alignItems: 'center', justifyContent: 'center',
  position: 'relative', overflow: 'hidden',
}
const orbBandStyle = {
  position: 'absolute', left: 0, right: 0, top: '50%', transform: 'translateY(-50%)',
  height: 2, background: '#200', display: 'flex', alignItems: 'center', justifyContent: 'center',
}

export default function Sidebar({ activeTab, onTab, onSettingsTab, activeSettingsTab }) {
  const { isRunning, wsState } = useAgentOutput()
  const [health, setHealth] = useState(null)
  const [collapsed, setCollapsed] = useState(false)

  useEffect(() => {
    fetchHealth().then(setHealth).catch(() => {})
    const id = setInterval(() => fetchHealth().then(setHealth).catch(() => {}), 30000)
    return () => clearInterval(id)
  }, [])

  const w = collapsed ? 44 : 200

  return (
    <div style={{
      width: w, minWidth: w, background: 'var(--bg-1)', borderRight: '1px solid var(--border)',
      display: 'flex', flexDirection: 'column', transition: 'width 0.15s ease, min-width 0.15s ease',
      overflow: 'hidden', flexShrink: 0,
    }}>
      {/* Brand */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8, padding: collapsed ? '12px 10px' : '12px 12px',
        borderBottom: '1px solid var(--border)',
      }}>
        {/* DS Orb */}
        <div style={orbStyle}>
          <div style={orbBandStyle}>
            <span style={{ fontSize: 7, color: '#fff', fontFamily: 'var(--font-mono)', lineHeight: 1, letterSpacing: 1 }}>DS</span>
          </div>
        </div>
        {!collapsed && (
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: 13, letterSpacing: 1.5, color: 'var(--text-1)', lineHeight: 1 }}>DEATHSTAR</div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 7, color: 'var(--accent)', letterSpacing: 1, marginTop: 2 }}>IMPERIAL OPS</div>
          </div>
        )}
        {!collapsed && (
          <button onClick={() => setCollapsed(true)} style={{
            background: 'none', border: 'none', color: 'var(--text-3)', cursor: 'pointer',
            fontSize: 12, padding: 0, lineHeight: 1,
          }} title="Collapse sidebar">‹</button>
        )}
        {collapsed && (
          <button onClick={() => setCollapsed(false)} style={{
            background: 'none', border: 'none', color: 'var(--text-3)', cursor: 'pointer',
            fontSize: 12, padding: 0, lineHeight: 1, position: 'absolute', right: 4, top: 14,
          }} title="Expand sidebar">›</button>
        )}
      </div>

      {/* Navigation */}
      <nav style={{ flex: 1, paddingTop: 8, overflowY: 'auto' }}>
        {NAV.map(group => (
          <div key={group.section}>
            {/* Section label */}
            <div style={{
              fontFamily: 'var(--font-mono)', fontSize: 7, letterSpacing: 2, color: 'var(--text-3)',
              textTransform: 'uppercase', padding: collapsed ? '10px 4px 4px' : '10px 12px 4px',
              opacity: collapsed ? 0 : 1, transition: 'opacity 0.1s ease',
              whiteSpace: 'nowrap', overflow: 'hidden',
            }}>{group.section}</div>

            {group.items.map((item, idx) => {
              const isActive = item.key === activeTab && (!item.settingsTab || item.settingsTab === activeSettingsTab)
              const navKey = item.settingsTab ? `${item.key}-${item.settingsTab}` : item.key
              return (
                <button
                  key={navKey}
                  onClick={() => {
                    onTab(item.key)
                    if (item.settingsTab && onSettingsTab) onSettingsTab(item.settingsTab)
                  }}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 8, width: '100%',
                    padding: collapsed ? '6px 0' : '6px 12px',
                    justifyContent: collapsed ? 'center' : 'flex-start',
                    background: isActive ? 'var(--accent-dim)' : 'transparent',
                    borderLeft: `2px solid ${isActive ? 'var(--accent)' : 'transparent'}`,
                    color: isActive ? 'var(--accent)' : 'var(--text-2)',
                    fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: 0.5,
                    cursor: 'pointer', border: 'none', borderLeft: `2px solid ${isActive ? 'var(--accent)' : 'transparent'}`,
                    transition: 'all 0.1s ease', textAlign: 'left', whiteSpace: 'nowrap',
                  }}
                  onMouseEnter={e => { if (!isActive) e.currentTarget.style.color = 'var(--text-1)' }}
                  onMouseLeave={e => { if (!isActive) e.currentTarget.style.color = 'var(--text-2)' }}
                >
                  <span style={{ width: 16, textAlign: 'center', flexShrink: 0, fontSize: 11 }}>{item.icon}</span>
                  {!collapsed && <span>{item.label || item.key}</span>}
                  {!collapsed && item.key === 'Output' && isRunning && (
                    <span className="dot dot-amber dot-pulse" style={{ marginLeft: 'auto' }} />
                  )}
                </button>
              )
            })}
          </div>
        ))}
      </nav>

      {/* Footer */}
      <div style={{ borderTop: '1px solid var(--border)', padding: collapsed ? '8px 0' : '8px 12px', display: 'flex', alignItems: 'center', gap: 6, justifyContent: collapsed ? 'center' : 'flex-start' }}>
        <span style={{
          width: 5, height: 5, borderRadius: '50%', flexShrink: 0,
          background: health?.status === 'ok' ? 'var(--green)' : 'var(--red)',
          boxShadow: health?.status === 'ok' ? '0 0 3px var(--green)' : '0 0 3px var(--red)',
          animation: 'pulse 2s ease-in-out infinite',
        }} />
        {!collapsed && (
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 8, color: 'var(--text-3)', whiteSpace: 'nowrap' }}>
            DS-AGENT-01 · v{health?.version || '—'}
          </span>
        )}
      </div>
    </div>
  )
}
