/**
 * Sidebar — V3a Imperial Ops navigation.
 * Collapsible, with command panel toggle and user menu.
 */
import { useState, useEffect, useRef } from 'react'
import { useAgentOutput } from '../context/AgentOutputContext'
import { fetchHealth } from '../api'
import LockBadge from './LockBadge'

const NAV = [
  { section: 'MONITOR', items: [
    { key: 'Dashboard',   icon: '⬡' },
    { key: 'Cluster',     icon: '◈' },
    { key: 'Logs',        icon: '≡' },
    { key: 'Memory',      icon: '◎' },
    { key: 'Discovered',  icon: '⊕' },
  ]},
  { section: 'OPERATE', items: [
    { key: 'Commands',  icon: '▶' },
    { key: 'Skills',    icon: '⚙' },
    { key: 'Runbooks',  icon: '◫' },
    { key: 'Output',    icon: '□' },
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
    { key: 'Settings',  icon: '⊞', label: 'Appearance', settingsTab: 'Appearance' },
    { key: 'Settings',  icon: '◈', label: 'Notifications', settingsTab: 'Notifications' },
    { key: 'Settings',  icon: '◎', label: 'General', settingsTab: 'General' },
  ]},
]

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

export default function Sidebar({
  activeTab, onTab, onSettingsTab, activeSettingsTab,
  onToggleCommandPanel, commandPanelOpen,
  username, userRole, onLogout, onLayoutsTab, onNotificationsTab,
}) {
  const { isRunning } = useAgentOutput()
  const [health, setHealth] = useState(null)
  const [collapsed, setCollapsed] = useState(false)
  const [userMenuOpen, setUserMenuOpen] = useState(false)
  const userMenuRef = useRef(null)

  useEffect(() => {
    fetchHealth().then(setHealth).catch(() => {})
    const id = setInterval(() => fetchHealth().then(setHealth).catch(() => {}), 30000)
    return () => clearInterval(id)
  }, [])

  // Close user menu on outside click
  useEffect(() => {
    const handler = (e) => {
      if (userMenuRef.current && !userMenuRef.current.contains(e.target))
        setUserMenuOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
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
        display: 'flex',
        flexDirection: collapsed ? 'column' : 'row',
        alignItems: 'center',
        gap: collapsed ? 4 : 8,
        padding: collapsed ? '8px 0' : '12px 12px',
        borderBottom: '1px solid var(--border)',
      }}>
        <div style={orbStyle}>
          <div style={orbBandStyle}>
            <span style={{ fontSize: 7, color: '#fff', fontFamily: 'var(--font-mono)', lineHeight: 1, letterSpacing: 1 }}>DS</span>
          </div>
        </div>
        {!collapsed && (
          <>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: 13, letterSpacing: 1.5, color: 'var(--text-1)', lineHeight: 1 }}>DEATHSTAR</div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 7, color: 'var(--accent)', letterSpacing: 1, marginTop: 2 }}>IMPERIAL OPS</div>
            </div>
            <button onClick={() => setCollapsed(true)} style={{
              background: 'none', border: 'none', color: 'var(--text-3)', cursor: 'pointer',
              fontSize: 14, padding: 0, lineHeight: 1,
            }} title="Collapse sidebar">‹</button>
          </>
        )}
        {collapsed && (
          <button onClick={() => setCollapsed(false)} style={{
            background: 'none', border: 'none', color: 'var(--text-3)', cursor: 'pointer',
            fontSize: 14, padding: 0, lineHeight: 1, width: '100%', textAlign: 'center',
          }} title="Expand sidebar">›</button>
        )}
      </div>

      {/* Navigation */}
      <nav style={{ flex: 1, paddingTop: 8, overflowY: 'auto' }}>
        {NAV.map(group => (
          <div key={group.section}>
            {/* Section label row */}
            <div style={{
              display: 'flex', alignItems: 'center',
              padding: collapsed ? '10px 4px 4px' : '10px 12px 4px',
            }}>
              <div style={{
                fontFamily: 'var(--font-mono)', fontSize: 7, letterSpacing: 2, color: 'var(--text-3)',
                textTransform: 'uppercase', flex: 1,
                opacity: collapsed ? 0 : 1, transition: 'opacity 0.1s ease',
                whiteSpace: 'nowrap', overflow: 'hidden',
              }}>{group.section}</div>
              {group.section === 'OPERATE' && !collapsed && onToggleCommandPanel && (
                <button onClick={onToggleCommandPanel} title="Toggle command panel (Ctrl+Shift+C)"
                  style={{
                    background: commandPanelOpen ? 'var(--accent-dim)' : 'none',
                    border: `1px solid ${commandPanelOpen ? 'var(--accent)' : 'transparent'}`,
                    color: commandPanelOpen ? 'var(--accent)' : 'var(--text-3)',
                    borderRadius: 2, padding: '1px 4px', cursor: 'pointer',
                    fontSize: 9, fontFamily: 'var(--font-mono)', lineHeight: 1,
                    transition: 'all 0.1s',
                  }}>⌨</button>
              )}
            </div>

            {group.items.map((item) => {
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

      {/* Footer — user menu */}
      <div ref={userMenuRef} style={{ borderTop: '1px solid var(--border)', position: 'relative' }}>
        {/* User menu popup */}
        {userMenuOpen && !collapsed && (
          <div style={{
            position: 'absolute', bottom: '100%', left: 0, right: 0,
            background: 'var(--bg-2)', border: '1px solid var(--border)',
            borderRadius: 2, marginBottom: 2, zIndex: 100,
            fontFamily: 'var(--font-mono)', fontSize: 9,
          }}>
            <div style={{ padding: '8px 12px', borderBottom: '1px solid var(--border)' }}>
              <div style={{ color: 'var(--text-1)', fontWeight: 600 }}>{username || 'admin'}</div>
              <div style={{
                fontSize: 8, marginTop: 2, padding: '1px 5px', display: 'inline-block',
                borderRadius: 2, letterSpacing: 0.5,
                background: userRole === 'sith_lord' ? 'rgba(160,24,40,0.2)' : userRole === 'imperial_officer' ? 'rgba(204,136,0,0.15)' : 'var(--bg-3)',
                color: userRole === 'sith_lord' ? 'var(--accent)' : userRole === 'imperial_officer' ? 'var(--amber)' : 'var(--text-3)',
              }}>
                {userRole === 'sith_lord' ? 'SITH LORD' : userRole === 'imperial_officer' ? 'IMPERIAL OFFICER' : userRole === 'stormtrooper' ? 'STORMTROOPER' : (userRole || 'DROID').toUpperCase()}
              </div>
            </div>
            {[
              { icon: '⏻', label: 'Log out', action: () => { onLogout?.(); setUserMenuOpen(false) }, style: { color: 'var(--red)' } },
            ].map((item, i) => (
              <button key={i} onClick={item.action} style={{
                display: 'flex', alignItems: 'center', gap: 8, width: '100%',
                padding: '6px 12px', background: 'none', border: 'none',
                color: item.style?.color || 'var(--text-2)', cursor: 'pointer',
                fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: 0.5, textAlign: 'left',
              }}
              onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-3)'}
              onMouseLeave={e => e.currentTarget.style.background = 'none'}
              >
                <span style={{ width: 14, textAlign: 'center' }}>{item.icon}</span>
                {item.label}
              </button>
            ))}
          </div>
        )}

        {/* Footer trigger */}
        <button onClick={() => !collapsed && setUserMenuOpen(o => !o)} style={{
          width: '100%', display: 'flex', alignItems: 'center',
          gap: 6, padding: collapsed ? '10px 0' : '10px 12px',
          justifyContent: collapsed ? 'center' : 'flex-start',
          background: userMenuOpen
            ? 'var(--accent-dim)'
            : 'rgba(160,24,40,0.06)',
          borderTop: '1px solid var(--border)',
          border: 'none', cursor: collapsed ? 'default' : 'pointer',
          transition: 'background 0.1s',
        }}>
          <span style={{
            width: 7, height: 7, borderRadius: '50%', flexShrink: 0,
            background: health?.status === 'ok' ? 'var(--green)' : 'var(--red)',
            boxShadow: health?.status === 'ok' ? '0 0 4px var(--green)' : '0 0 4px var(--red)',
          }} />
          {!collapsed && (
            <>
              <span style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 10,
                color: 'var(--text-2)',
                whiteSpace: 'nowrap', flex: 1,
                letterSpacing: 0.3,
              }}>
                {username || 'admin'} · <span style={{ color: 'var(--accent)' }}>v{health?.version || '—'}</span>
              </span>
              <span style={{ fontSize: 9, color: 'var(--text-3)' }}>{userMenuOpen ? '▾' : '▴'}</span>
            </>
          )}
        </button>
      </div>
    </div>
  )
}
