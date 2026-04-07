/**
 * Sidebar — left navigation with grouped sections.
 * Replaces the horizontal header nav bar from the old design.
 */
import { useState, useEffect } from 'react'
import { useAgentOutput } from '../context/AgentOutputContext'
import { fetchHealth } from '../api'
import LockBadge from './LockBadge'

const NAV = [
  { section: 'Monitor', items: [
    { key: 'Dashboard', icon: '◫' },
    { key: 'Cluster',   icon: '⬡' },
    { key: 'Logs',      icon: '☰' },
    { key: 'Memory',    icon: '◉' },
  ]},
  { section: 'Operate', items: [
    { key: 'Commands',  icon: '▶' },
    { key: 'Skills',    icon: '⚙' },
    { key: 'Output',    icon: '◧' },
  ]},
  { section: 'Tools', items: [
    { key: 'Tests',     icon: '✓' },
    { key: 'Ingest',    icon: '↓' },
    { key: 'Docs',      icon: '◪' },
  ]},
  { section: 'Settings', items: [
    { key: 'Settings',  icon: '⚙' },
  ]},
]

export default function Sidebar({ activeTab, onTab }) {
  const { isRunning, wsState } = useAgentOutput()
  const [health, setHealth] = useState(null)

  useEffect(() => {
    fetchHealth().then(setHealth).catch(() => {})
    const id = setInterval(() => fetchHealth().then(setHealth).catch(() => {}), 30000)
    return () => clearInterval(id)
  }, [])

  return (
    <div className="sidebar">
      {/* Brand */}
      <div className="flex items-center gap-2 px-4 py-4 border-b" style={{ borderColor: 'var(--border)' }}>
        <span className="font-bold text-base tracking-tight" style={{ color: 'var(--accent)', fontFamily: 'var(--font-mono)' }}>HP1</span>
        <span className="text-xs" style={{ color: 'var(--text-3)' }}>AI Agent</span>
      </div>

      {/* Navigation */}
      <nav className="flex-1 py-2 overflow-y-auto">
        {NAV.map(group => (
          <div key={group.section}>
            <div className="sidebar-section">{group.section}</div>
            {group.items.map(item => (
              <button
                key={item.key}
                onClick={() => onTab(item.key)}
                className={`sidebar-link ${activeTab === item.key ? 'sidebar-link-active' : ''}`}
              >
                <span className="text-sm w-5 text-center shrink-0">{item.icon}</span>
                <span>{item.key}</span>
                {item.key === 'Output' && isRunning && (
                  <span className="dot dot-amber dot-pulse ml-auto" />
                )}
              </button>
            ))}
          </div>
        ))}
      </nav>

      {/* Footer — status indicators */}
      <div className="border-t px-3 py-2 space-y-1.5" style={{ borderColor: 'var(--border)' }}>
        <div className="flex items-center justify-between text-[10px]" style={{ color: 'var(--text-3)' }}>
          <div className="flex items-center gap-1.5">
            <span className={`dot ${health?.status === 'ok' ? 'dot-green' : 'dot-gray'}`} />
            <span>API</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className={`dot ${wsState === 'connected' ? 'dot-green' : wsState === 'connecting' ? 'dot-amber' : 'dot-gray'}`} />
            <span>WS</span>
          </div>
          <LockBadge />
          {health?.version && (
            <span className="mono" style={{ color: 'var(--text-3)' }}>v{health.version}</span>
          )}
        </div>
      </div>
    </div>
  )
}
