import React, { useState, useEffect, useRef, lazy, Suspense, useCallback } from 'react'
import { Terminal } from 'lucide-react'
import CommandPanel   from './components/CommandPanel'
import OutputPanel    from './components/OutputPanel'
import StatusPanel    from './components/StatusPanel'
import NodeMap        from './components/NodeMap'
import AlertToast        from './components/AlertToast'
import PlanConfirmModal  from './components/PlanConfirmModal'
import MemoryPanel    from './components/MemoryPanel'
import LogsPanel      from './components/LogsPanel'
import TestsPanel     from './components/TestsPanel'
import DashboardCards from './components/DashboardCards'
import SettingsPage   from './components/SettingsPage'
import EntityDrawer   from './components/EntityDrawer'
import ComparePanel, { SLOT_COLORS } from './components/ComparePanel'
import { OptionsProvider, useOptions } from './context/OptionsContext'
import { CommandPanelProvider, useCommandPanel } from './context/CommandPanelContext'
import { AgentProvider } from './context/AgentContext'
import { AgentOutputProvider, useAgentOutput } from './context/AgentOutputContext'
import { TaskProvider } from './context/TaskContext'
import { fetchHealth, fetchStats, fetchStatus, fetchMemoryHealth, fetchDashboardContainers, fetchDashboardSwarm, fetchDashboardVMs, fetchDashboardExternal, authHeaders } from './api'
import { AuthProvider, useAuth } from './context/AuthContext'
import LoginScreen from './components/LoginScreen'
import LockBadge from './components/LockBadge'
import IngestPanel from './components/IngestPanel'
import DocsTab from './components/DocsTab'
import SkillsPanel from './components/SkillsPanel'
import ServiceCards from './components/ServiceCards'
import Sidebar from './components/Sidebar'
import CardFilterBar, { ALL_CARD_KEYS } from './components/CardFilterBar'

const FILTER_KEY = 'hp1_cardFilter'

class ServiceCardsErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false }
  }
  static getDerivedStateFromError() {
    return { hasError: true }
  }
  render() {
    if (this.state.hasError) {
      return (
        <div className="px-5 py-8 text-center text-[#888] text-sm">
          Dashboard sections unavailable — check browser console for details.
        </div>
      )
    }
    return this.props.children
  }
}

// Dev-only layout test harness — renders as overlay at ?test=layout
const _showLayoutTest = import.meta.env.DEV &&
  new URLSearchParams(window.location.search).get('test') === 'layout'
const LayoutTest = _showLayoutTest ? lazy(() => import('./dev/LayoutTest.jsx')) : null

const MAIN_TABS = ['Dashboard', 'Cluster', 'Commands', 'Skills', 'Logs', 'Memory', 'Output']
const TOOLS_TABS = ['Tests', 'Ingest', 'Docs']

// ── Row 1: Header — logo + tabs + settings gear only ──────────────────────────

function Header({ activeTab, onTab }) {
  const { isRunning, outputLines } = useAgentOutput()
  const [lastSeenCount,    setLastSeenCount]    = useState(0)
  const [lastRunToolCount, setLastRunToolCount] = useState(0)
  const [lastRunHadError,  setLastRunHadError]  = useState(false)
  const [outputBadge,      setOutputBadge]      = useState(false)
  const [toolsOpen,        setToolsOpen]        = useState(false)
  const toolsRef = useRef(null)
  const prevIsRunning = useRef(false)

  const unread = outputLines.length - lastSeenCount

  // When a run completes, capture tool call count + error state from that run
  useEffect(() => {
    if (prevIsRunning.current && !isRunning) {
      const toolCalls = outputLines.filter(m => m.type === 'tool').length
      const hasError  = outputLines.some(m => m.type === 'halt' || m.type === 'error')
      setLastRunToolCount(toolCalls)
      setLastRunHadError(hasError)
    }
    prevIsRunning.current = isRunning
  }, [isRunning, outputLines])

  // Listen for agent-done custom event from AgentOutputContext
  useEffect(() => {
    const handler = () => {
      if (activeTab !== 'Output') setOutputBadge(true)
    }
    window.addEventListener('agent-done', handler)
    return () => window.removeEventListener('agent-done', handler)
  }, [activeTab])

  // Close Tools dropdown on outside click
  useEffect(() => {
    const handler = (e) => {
      if (toolsRef.current && !toolsRef.current.contains(e.target)) {
        setToolsOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const handleTab = (tab) => {
    if (tab === 'Output') {
      setLastSeenCount(outputLines.length)
      setOutputBadge(false)
    }
    setToolsOpen(false)
    onTab(tab)
  }

  // Keep lastSeenCount in sync when Output tab is already active
  useEffect(() => {
    if (activeTab === 'Output') {
      setLastSeenCount(outputLines.length)
      setOutputBadge(false)
    }
  }, [activeTab, outputLines.length])

  return (
    <header className="flex items-center justify-between px-4 py-0 bg-white border-b border-gray-300 shrink-0">
      <div className="flex items-center gap-3">
        <span className="text-blue-600 font-bold text-lg tracking-tight font-mono py-2">HP1</span>
        <span className="text-gray-600 text-sm">AI Agent</span>
        <div className="flex ml-4">
          {MAIN_TABS.map(tab => (
            <button
              key={tab}
              onClick={() => handleTab(tab)}
              className={`text-xs px-3 py-3 border-b-2 transition-colors ${
                activeTab === tab
                  ? 'border-blue-500 text-blue-600'
                  : 'border-transparent text-gray-500 hover:text-gray-900'
              }`}
            >
              {tab === 'Output' ? (
                <span className="flex items-center gap-1">
                  Output
                  {isRunning && (
                    <span data-testid="output-badge" className="text-yellow-500 animate-pulse text-xs">⚡</span>
                  )}
                  {!isRunning && outputBadge && activeTab !== 'Output' && (
                    <span data-testid="output-badge" className="w-1.5 h-1.5 rounded-full bg-green-500 inline-block" />
                  )}
                  {!isRunning && !outputBadge && unread > 0 && activeTab !== 'Output' && (
                    <span className="text-gray-400 text-xs font-normal">({unread})</span>
                  )}
                </span>
              ) : tab === 'Logs' ? (
                <span className="flex items-center gap-1">
                  Logs
                  {lastRunHadError && activeTab !== 'Logs' && (
                    <span className="w-1.5 h-1.5 rounded-full bg-red-500 inline-block animate-pulse" />
                  )}
                  {!lastRunHadError && lastRunToolCount > 0 && activeTab !== 'Logs' && (
                    <span className="text-gray-400 text-xs font-normal">({lastRunToolCount})</span>
                  )}
                </span>
              ) : tab}
            </button>
          ))}

          {/* Tools dropdown */}
          <div className="relative" ref={toolsRef}>
            <button
              onClick={() => setToolsOpen(o => !o)}
              className={`text-xs px-3 py-3 border-b-2 transition-colors flex items-center gap-1 ${
                toolsOpen || TOOLS_TABS.includes(activeTab)
                  ? 'border-blue-500 text-blue-600'
                  : 'border-transparent text-gray-500 hover:text-gray-900'
              }`}
            >
              Tools
              <span className="text-[9px] leading-none">▾</span>
            </button>
            {toolsOpen && (
              <div className="absolute top-full left-0 mt-0 bg-white border border-gray-200 shadow-md rounded-b z-50 min-w-[100px]">
                {TOOLS_TABS.map(tab => (
                  <button
                    key={tab}
                    onClick={() => handleTab(tab)}
                    className={`w-full text-left text-xs px-3 py-2 transition-colors ${
                      activeTab === tab
                        ? 'text-blue-600 bg-blue-50'
                        : 'text-gray-600 hover:text-gray-900 hover:bg-gray-50'
                    }`}
                  >
                    {tab}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="flex items-center gap-2 h-full">
        <UserBadge />
      </div>
    </header>
  )
}

// ── Row 2: Sub bar — Commands toggle + stats + API status ─────────────────────

function StatItem({ label, value, accent }) {
  return (
    <div className="flex items-center px-2 border-r border-gray-200 h-full min-w-0">
      <span className="text-gray-400 text-xs mr-1 shrink-0">{label}:</span>
      <span className={`text-xs font-medium truncate ${accent ? 'text-orange-600' : 'text-gray-800'}`}>{value ?? '—'}</span>
    </div>
  )
}

const SUBBAR_BADGE = {
  status:   { label: 'Status',   color: '#93c5fd' },
  action:   { label: 'Action',   color: '#fdba74' },
  research: { label: 'Research', color: '#d8b4fe' },
}

const SEV = { red: 0, amber: 1, grey: 2, green: 3 }

function SubBar({ onTab, onAlertNavigate }) {
  const { panelOpen, togglePanel } = useCommandPanel()
  const { wsState, agentType, lastAgentType } = useAgentOutput()
  const [stats,  setStats]  = useState(null)
  const [health, setHealth] = useState(null)
  const [alerts, setAlerts] = useState([])
  const [rawContainers, setRawContainers] = useState(null)
  const [rawSwarm,      setRawSwarm]      = useState(null)
  const [rawVms,        setRawVms]        = useState(null)
  const [rawExternal,   setRawExternal]   = useState(null)
  const [alertTrayOpen, setAlertTrayOpen] = useState(false)
  const trayRef = useRef(null)

  useEffect(() => {
    const refreshStats = () => fetchStats().then(setStats).catch(() => setStats(null))

    const refreshAlerts = () => {
      Promise.allSettled([
        fetchDashboardContainers(),
        fetchDashboardSwarm(),
        fetchDashboardVMs(),
        fetchDashboardExternal(),
      ]).then(([c, s, v, e]) => {
        if (c.status === 'fulfilled') setRawContainers(c.value)
        if (s.status === 'fulfilled') setRawSwarm(s.value)
        if (v.status === 'fulfilled') setRawVms(v.value)
        if (e.status === 'fulfilled') setRawExternal(e.value)

        const issues = []
        let idx = 0
        if (c.status === 'fulfilled') for (const x of c.value?.containers || []) if (x.problem) issues.push({ sev: x.dot, text: `${x.name} ${x.problem}`, idx: idx++ })
        if (s.status === 'fulfilled') for (const x of s.value?.services   || []) if (x.problem) issues.push({ sev: x.dot, text: `${x.name} ${x.problem}`, idx: idx++ })
        if (v.status === 'fulfilled') for (const x of [...(v.value?.vms || []), ...(v.value?.lxc || [])]) if (x.problem) issues.push({ sev: x.dot, text: `${x.name} ${x.problem}`, idx: idx++ })
        if (e.status === 'fulfilled') for (const x of e.value?.services   || []) if (x.problem) issues.push({ sev: x.dot, text: `${x.name} ${x.problem}`, idx: idx++ })
        issues.sort((a, b) => (SEV[a.sev] ?? 2) - (SEV[b.sev] ?? 2) || a.idx - b.idx)
        setAlerts(issues)
        if (issues.length === 0) setAlertTrayOpen(false)
      }).catch(() => {})
    }

    const loadAll = () => {
      refreshStats()
      fetchHealth().then(setHealth).catch(() => setHealth(null))
      refreshAlerts()
    }
    loadAll()
    const id = setInterval(loadAll, 30_000)
    window.addEventListener('agent-done', refreshStats)
    return () => {
      clearInterval(id)
      window.removeEventListener('agent-done', refreshStats)
    }
  }, [])

  useEffect(() => {
    const handler = (e) => {
      if (trayRef.current && !trayRef.current.contains(e.target)) {
        setAlertTrayOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') setAlertTrayOpen(false) }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [])

  const topTool = stats?.most_used_tools?.[0]

  return (
    <div className="flex items-center h-8 bg-white border-b border-gray-200 shrink-0 overflow-hidden">

      <button
        onClick={togglePanel}
        title="Toggle Commands panel (Ctrl+Shift+C)"
        className={`flex items-center gap-1.5 px-3 h-full border-r border-gray-200 text-xs font-medium transition-colors shrink-0 ${
          panelOpen
            ? 'bg-blue-50 text-blue-700'
            : 'text-gray-600 hover:text-gray-900 hover:bg-gray-50'
        }`}
      >
        <Terminal size={13} />
        <span>Commands</span>
      </button>

      <div className="flex items-center min-w-0 overflow-hidden h-full">
        {stats ? (
          <>
            <StatItem label="Runs"       value={stats.total_operations} />
            <StatItem label="Tool Calls" value={stats.total_tool_calls} />
            <StatItem label="Success"    value={`${stats.success_rate}%`} />
            <StatItem label="Avg"        value={stats.avg_duration_ms ? `${stats.avg_duration_ms}ms` : '—'} />
            <StatItem label="Top Tool"
              value={topTool ? `${topTool.tool.split('_').slice(0, 2).join('_')} ×${topTool.count}` : '—'} />
            {stats.escalations_unresolved > 0 && (
              <StatItem label="Escalations" value={`⚠ ${stats.escalations_unresolved}`} accent />
            )}
          </>
        ) : (
          <div className="flex items-center px-2 border-r border-gray-200 h-full">
            <span className="text-xs text-gray-400">Loading…</span>
          </div>
        )}
      </div>

      {/* Alert strip — shows stopped/unhealthy infra items, click to open dropdown tray */}
      {alerts.length > 0 && (
        <div ref={trayRef} className="relative border-l border-orange-100 flex-1 min-w-0">
          <button
            onClick={() => setAlertTrayOpen(o => !o)}
            title={`${alerts.length} infrastructure alert${alerts.length !== 1 ? 's' : ''} — click for details`}
            className="flex items-center gap-1.5 px-2 h-8 w-full bg-orange-50/60 hover:bg-orange-50 transition-colors overflow-hidden"
          >
            <span className="text-orange-500 text-[12px] shrink-0">⚠</span>
            <span className="text-[11px] text-orange-700/80 truncate">
              {alerts.slice(0, 3).map(i => i.text).join(' · ')}
              {alerts.length > 3 ? ` · +${alerts.length - 3} more` : ''}
            </span>
            <span className="text-[10px] bg-orange-400 text-white rounded-full px-1.5 py-px shrink-0 ml-0.5">{alerts.length}</span>
          </button>

          {alertTrayOpen && (
            <div className="absolute top-full left-0 z-50 min-w-full bg-[#1e293b] border border-[#334155] rounded-b shadow-xl"
                 style={{ maxHeight: 400, overflowY: 'auto' }}>
              <div className="px-3 py-2 border-b border-[#334155] flex items-center gap-2">
                <span className="text-orange-400 text-[11px]">⚠</span>
                <span className="text-[11px] font-semibold text-slate-200">{alerts.length} Infrastructure Issue{alerts.length !== 1 ? 's' : ''}</span>
              </div>

              {[
                {
                  key: 'containers_local',
                  label: 'CONTAINERS · agent-01',
                  items: (rawContainers?.containers || []).filter(x => x.problem).map(x => ({ name: x.name, problem: x.problem })),
                },
                {
                  key: 'containers_swarm',
                  label: 'SWARM SERVICES',
                  items: (rawSwarm?.services || []).filter(x => x.problem).map(x => ({ name: x.name, problem: x.problem })),
                },
                {
                  key: 'vms',
                  label: 'PROXMOX VMs / LXC',
                  items: [...(rawVms?.vms || []), ...(rawVms?.lxc || [])].filter(x => x.problem).map(x => ({ name: x.name, problem: x.problem })),
                },
                {
                  key: 'external',
                  label: 'EXTERNAL SERVICES',
                  items: (rawExternal?.services || []).filter(x => x.problem).map(x => ({ name: x.name, problem: x.problem })),
                },
              ].map(({ key, label, items }) => {
                const shown = items.slice(0, 5)
                const extra = items.length - shown.length
                const hasIssues = items.length > 0
                return (
                  <div
                    key={key}
                    className={`border-b border-[#1e293b] ${hasIssues ? 'cursor-pointer hover:bg-[#243447]' : 'opacity-50'} transition-colors`}
                    onClick={hasIssues ? () => { onAlertNavigate(key); setAlertTrayOpen(false) } : undefined}
                  >
                    <div className="flex items-center justify-between px-3 py-1.5">
                      <div>
                        <span className="text-[9px] text-slate-400 uppercase tracking-wider font-semibold">{label}</span>
                        {hasIssues
                          ? <span className="ml-2 text-[10px] text-orange-400">{items.length} issue{items.length !== 1 ? 's' : ''}</span>
                          : <span className="ml-2 text-[10px] text-slate-600">0 issues</span>
                        }
                      </div>
                      <span className="text-[10px] text-slate-500 shrink-0 ml-2">→</span>
                    </div>
                    {shown.length > 0 && (
                      <div className="px-3 pb-1.5 flex flex-col gap-0.5">
                        {shown.map((item, i) => (
                          <div key={i} className="flex justify-between text-[10px]">
                            <span className="text-amber-300 truncate">{item.name}</span>
                            <span className="text-slate-500 ml-2 shrink-0">{item.problem}</span>
                          </div>
                        ))}
                        {extra > 0 && (
                          <div className="text-[9px] text-slate-600 mt-0.5">+ {extra} more</div>
                        )}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}

      <div className="flex items-center ml-auto">
        {/* Agent type indicator */}
        {(agentType || lastAgentType) && (() => {
          const type = agentType || lastAgentType
          const badge = SUBBAR_BADGE[type]
          return badge ? (
            <div className="flex items-center px-3 border-l border-gray-200 h-8 gap-1">
              <span className="text-gray-400 text-xs">Agent:</span>
              <span className="text-xs font-medium" style={{ color: badge.color }}>
                {badge.label}
              </span>
              {agentType && <span className="text-yellow-500 animate-pulse text-xs">&#9889;</span>}
            </div>
          ) : null
        })()}
        <LockBadge />
        <div className="flex items-center px-3 border-l border-gray-200 h-8">
          <span className="text-gray-400 text-xs mr-1">API</span>
          <span className="text-gray-800 text-xs font-medium">:8000</span>
          <span className={`w-1.5 h-1.5 rounded-full ml-1.5 ${
            health?.status === 'ok' ? 'bg-green-500' : 'bg-gray-400'
          }`} />
        </div>
        <div className="flex items-center px-3 border-l border-gray-200 h-8 gap-1">
          <span className="text-gray-400 text-xs">WS</span>
          <span style={{ color: wsState === 'connected' ? '#22c55e' : wsState === 'connecting' ? '#eab308' : '#9ca3af', fontSize: '0.6rem', lineHeight: 1 }}>●</span>
        </div>
        {health?.version && (
          <div className="relative flex items-center px-3 border-l border-gray-200 h-8 group">
            <span className="text-gray-400 text-xs font-mono cursor-default select-none">
              v{health.version}
            </span>
            {health?.build_info && (
              <div className="absolute right-0 top-full mt-1.5 z-50 hidden group-hover:block">
                <div className="bg-slate-800 border border-slate-700 rounded px-2.5 py-2 w-[210px] shadow-lg">
                  <div className="grid gap-x-3 gap-y-0.5" style={{ gridTemplateColumns: 'auto 1fr' }}>
                    <span className="text-slate-500 text-xs">commit</span>
                    <span className="font-mono text-indigo-300 text-xs">{health.build_info.commit}</span>
                    <span className="text-slate-500 text-xs">branch</span>
                    <span className="font-mono text-emerald-400 text-xs">{health.build_info.branch}</span>
                    <span className="text-slate-500 text-xs">built</span>
                    <span className="font-mono text-slate-200 text-xs">
                      {health.build_info.built_at !== 'unknown'
                        ? health.build_info.built_at.replace('T', ' ').replace('Z', ' UTC')
                        : 'unknown'}
                    </span>
                    <span className="text-slate-500 text-xs">build</span>
                    <span className="font-mono text-slate-200 text-xs">
                      {health.build_info.build_number === 'local'
                        ? 'local'
                        : `#${health.build_info.build_number}`}
                    </span>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Commands side panel ────────────────────────────────────────────────────────
// Width is controlled entirely by the CSS grid column — this div fills 100% of it.

function CommandSidePanel() {
  const { closePanel } = useCommandPanel()

  return (
    <div className="w-full h-full flex flex-col overflow-hidden" style={{ background: 'var(--bg-1)' }}>
      <div className="flex items-center justify-between px-4 py-2 border-b shrink-0" style={{ borderColor: 'var(--border)' }}>
        <div className="flex items-center gap-2">
          <Terminal size={13} style={{ color: 'var(--text-3)' }} />
          <span className="text-xs font-bold uppercase tracking-wider" style={{ color: 'var(--text-2)' }}>Commands</span>
        </div>
        <button
          onClick={closePanel}
          className="transition-colors text-sm leading-none"
          style={{ color: 'var(--text-3)' }}
          title="Close panel"
        >
          ✕
        </button>
      </div>
      <div className="flex-1 overflow-hidden">
        {/* mode="panel" — narrow dark-themed panel */}
        <CommandPanel mode="panel" />
      </div>
    </div>
  )
}


// ── Alerts panel ──────────────────────────────────────────────────────────────

function AlertsPanel() {
  const [alerts, setAlerts] = React.useState([])

  const fetchAlerts = React.useCallback(() => {
    fetch('/api/alerts/recent?limit=20&include_dismissed=false')
      .then(r => r.json())
      .then(d => setAlerts(d.alerts || []))
      .catch(() => {})
  }, [])

  React.useEffect(() => {
    fetchAlerts()
    const t = setInterval(fetchAlerts, 30000)
    return () => clearInterval(t)
  }, [fetchAlerts])

  const dismiss = (id) => {
    fetch(`/api/alerts/${id}/dismiss`, { method: 'POST' }).then(fetchAlerts)
  }

  const dismissAll = () => {
    fetch('/api/alerts/dismiss-all', { method: 'POST' }).then(fetchAlerts)
  }

  const sevStyle = (s) => {
    if (s === 'error' || s === 'critical') return { dot: 'var(--red)', bg: 'var(--red-dim)', color: 'var(--red)' }
    if (s === 'warning') return { dot: 'var(--amber)', bg: 'var(--amber-dim)', color: 'var(--amber)' }
    return { dot: 'var(--accent)', bg: 'var(--accent-dim)', color: 'var(--accent)' }
  }

  if (alerts.length === 0) {
    return (
      <div className="flex items-center gap-1.5 px-4 py-2">
        <span className="dot dot-green" />
        <span className="text-[11px]" style={{ color: 'var(--text-3)' }}>No active alerts</span>
      </div>
    )
  }

  return (
    <div className="px-4 py-2 space-y-1.5">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: 'var(--text-3)' }}>
          Alerts — {alerts.length} active
        </span>
        <button onClick={dismissAll} className="btn text-[9px] px-1.5 py-0.5">Dismiss all</button>
      </div>
      {alerts.map(a => {
        const sv = sevStyle(a.severity)
        return (
          <div key={a.id} className="flex items-center gap-2 rounded-md px-3 py-2"
               style={{ background: 'var(--bg-2)', border: '1px solid var(--border)' }}>
            <span className="dot dot-pulse shrink-0" style={{ background: sv.dot }} />
            <div className="flex-1 min-w-0">
              <span className="text-[11px]" style={{ color: 'var(--text-1)' }}>
                {a.connection_label || a.component}{a.message ? ` — ${a.message}` : ''}
              </span>
            </div>
            <span className="pill shrink-0" style={{ background: sv.bg, color: sv.color }}>
              {a.severity}
            </span>
            <button onClick={() => dismiss(a.id)} className="text-[10px] shrink-0"
                    style={{ color: 'var(--text-3)', cursor: 'pointer', background: 'none', border: 'none' }}>✕</button>
          </div>
        )
      })}
    </div>
  )
}

// ── Dashboard view ────────────────────────────────────────────────────────────

function DrillDownBar({ search, setSearch, showFilter, setShowFilter, typeFilter, setTypeFilter, globalMaint, setGlobalMaint, stats, compareMode, compareSet, onToggleCompare }) {
  const showFilters = ['ALL', 'ERRORS', 'DEGRADED', 'IN MAINT']
  const typeFilters = ['ALL', 'PLATFORM', 'COMPUTE', 'NETWORK', 'STORAGE', 'SECURITY']
  const _btn = (active) => ({
    padding: '2px 6px', fontSize: 9, fontFamily: 'var(--font-mono)',
    background: active ? 'var(--accent-dim)' : 'transparent',
    color: active ? 'var(--accent)' : 'var(--text-3)',
    border: `1px solid ${active ? 'var(--accent)' : 'var(--border)'}`,
    borderRadius: 2, cursor: 'pointer', letterSpacing: 0.5,
  })
  return (
    <div className="flex items-center gap-2 px-3 shrink-0" style={{
      height: 38, background: 'var(--bg-1)', borderBottom: '1px solid var(--border)',
      fontFamily: 'var(--font-mono)', fontSize: 10, overflowX: 'auto',
    }}>
      <span style={{ fontSize: 7, color: 'var(--text-3)', letterSpacing: 1, flexShrink: 0 }}>DRILL:</span>
      <input
        value={search} onChange={e => setSearch(e.target.value)}
        placeholder="search name / host / IP..."
        style={{
          width: 160, padding: '3px 8px', background: 'var(--bg-2)', border: '1px solid var(--border)',
          borderRadius: 2, color: 'var(--text-1)', fontSize: 10, fontFamily: 'var(--font-mono)',
          outline: 'none', flexShrink: 0,
        }}
      />
      <div style={{ width: 1, height: 20, background: 'var(--border)', flexShrink: 0 }} />
      <span style={{ fontSize: 7, color: 'var(--text-3)', letterSpacing: 1, flexShrink: 0 }}>SHOW:</span>
      {showFilters.map(f => (
        <button key={f} onClick={() => setShowFilter(f)} style={_btn(showFilter === f)}>{f}</button>
      ))}
      <div style={{ width: 1, height: 20, background: 'var(--border)', flexShrink: 0 }} />
      <span style={{ fontSize: 7, color: 'var(--text-3)', letterSpacing: 1, flexShrink: 0 }}>TYPE:</span>
      {typeFilters.map(f => (
        <button key={f} onClick={() => setTypeFilter(f)} style={_btn(typeFilter === f)}>{f}</button>
      ))}
      <div style={{ width: 1, height: 20, background: 'var(--border)', flexShrink: 0 }} />
      <button onClick={() => setGlobalMaint(!globalMaint)} title="Order 66"
        style={{
          padding: '2px 8px', fontSize: 9, fontFamily: 'var(--font-mono)', flexShrink: 0,
          background: globalMaint ? 'var(--amber-dim)' : 'transparent',
          color: globalMaint ? 'var(--amber)' : 'var(--text-3)',
          border: `1px solid ${globalMaint ? 'var(--amber)' : 'var(--border)'}`,
          borderRadius: 2, cursor: 'pointer',
        }}>⚑ GLOBAL MAINT</button>
      {/* Compare toggle */}
      <div onClick={onToggleCompare} style={{
        display: 'flex', alignItems: 'center', gap: 5,
        padding: '3px 10px 3px 8px',
        border: `1px solid ${compareMode ? 'var(--cyan)' : 'var(--border)'}`,
        borderRadius: 2, cursor: 'pointer',
        background: compareMode ? 'rgba(0,200,238,0.06)' : 'transparent',
        transition: 'all 0.15s', userSelect: 'none', flexShrink: 0,
      }}>
        <span style={{ fontSize: 13, color: compareMode ? 'var(--cyan)' : 'var(--text-3)' }}>⊞</span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: '0.06em',
                       color: compareMode ? 'var(--cyan)' : 'var(--text-3)', whiteSpace: 'nowrap' }}>
          {(compareSet || []).length > 0 ? `${compareSet.length} selected` : 'compare'}
        </span>
        <div style={{ display: 'flex', gap: 2, alignItems: 'center', marginLeft: 2 }}>
          {[0,1,2,3].map(i => (
            <div key={i} style={{
              width: 9, height: 9, borderRadius: 1,
              border: `1px solid ${i < (compareSet || []).length ? SLOT_COLORS[i] : 'rgba(255,255,255,0.15)'}`,
              background: i < (compareSet || []).length ? SLOT_COLORS[i] : 'transparent',
              boxShadow: i < (compareSet || []).length ? `0 0 4px ${SLOT_COLORS[i]}` : 'none',
              transition: 'all 0.15s',
            }} />
          ))}
        </div>
      </div>
      <div style={{ flex: 1 }} />
      <div className="flex gap-3" style={{ fontSize: 8, color: 'var(--text-3)', flexShrink: 0 }}>
        <span>RUNS <span style={{ color: 'var(--text-2)' }}>{stats?.total_operations ?? '—'}</span></span>
        <span>CALLS <span style={{ color: 'var(--text-2)' }}>{stats?.total_tool_calls ?? '—'}</span></span>
        <span>SUCCESS <span style={{ color: 'var(--text-2)' }}>{stats?.success_rate != null ? `${stats.success_rate}%` : '—'}</span></span>
      </div>
    </div>
  )
}


function PlatformCoreCards() {
  const [health, setHealth] = useState(null)
  const [statusData, setStatusData] = useState(null)
  const [memHealth, setMemHealth] = useState(null)
  const [containers, setContainers] = useState([])
  useEffect(() => {
    const load = () => {
      fetchHealth().then(setHealth).catch(() => {})
      fetchStatus().then(setStatusData).catch(() => {})
      fetchMemoryHealth().then(setMemHealth).catch(() => {})
      fetchDashboardContainers().then(d => setContainers(d?.containers || [])).catch(() => {})
    }
    load()
    const id = setInterval(load, 30000)
    return () => clearInterval(id)
  }, [])

  const collectors = statusData?.collectors ?? {}
  const sortedCollectors = Object.entries(collectors).sort(([a], [b]) => a.localeCompare(b))
  const apiOk = health?.status === 'ok'

  const _healthDot = (h) => {
    if (h === 'healthy' || h === 'ok' || h === 'green') return 'var(--green)'
    if (h === 'degraded' || h === 'yellow') return 'var(--amber)'
    if (h === 'critical' || h === 'error' || h === 'red') return 'var(--red)'
    return 'var(--text-3)'
  }
  const _healthTag = (h) => {
    if (h === 'healthy' || h === 'ok' || h === 'green') return 'green'
    if (h === 'degraded' || h === 'yellow') return 'amber'
    if (h === 'critical' || h === 'error' || h === 'red') return 'red'
    return 'grey'
  }
  const _tagBg = (c) => c === 'green' ? 'var(--green-dim)' : c === 'amber' ? 'var(--amber-dim)' : c === 'red' ? 'var(--red-dim)' : 'var(--bg-3)'
  const _tagFg = (c) => c === 'green' ? 'var(--green)' : c === 'amber' ? 'var(--amber)' : c === 'red' ? 'var(--red)' : 'var(--text-3)'

  const _row = (dot, label, tag, tagColor, value) => (
    <div style={{ display: 'flex', alignItems: 'center', padding: '4px 0', borderTop: '1px solid var(--bg-3)', fontSize: 10, gap: 6 }}>
      <span style={{ width: 6, height: 6, borderRadius: '50%', background: dot, flexShrink: 0 }} />
      <span style={{ flex: 1, color: 'var(--text-2)', fontFamily: 'var(--font-mono)' }}>{label}</span>
      {tag && <span style={{ fontSize: 7, fontFamily: 'var(--font-mono)', padding: '1px 4px', background: _tagBg(tagColor), color: _tagFg(tagColor), borderRadius: 2 }}>{tag}</span>}
      {value && <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-3)', fontSize: 9 }}>{value}</span>}
    </div>
  )

  // Extract data for right-side values
  const kafkaHealth = statusData?.kafka?.health || 'unknown'
  const kafkaBrokers = statusData?.kafka?.data?.brokers?.length ?? statusData?.kafka?.data?.count ?? ''
  const esHealth = statusData?.elasticsearch?.health || 'unknown'
  const esNodes = statusData?.elasticsearch?.data?.node_count ?? statusData?.elasticsearch?.data?.nodes ?? ''
  // MuninnDB: use dedicated memory health endpoint
  const muninnOk = memHealth?.status === 'ok' || memHealth?.healthy === true
  const muninnHealth = muninnOk ? 'healthy' : memHealth ? 'error' : 'unknown'
  const muninnEngrams = memHealth?.engram_count ?? memHealth?.count ?? memHealth?.data?.count ?? ''

  // Find postgres container dynamically — matches hp1-postgres, hp1_postgres, DS-postgres, etc.
  const pgContainer = containers.find(c =>
    c.name?.toLowerCase().includes('postgres') && !c.name?.toLowerCase().includes('pgadmin')
  )
  const pgDot    = pgContainer ? pgContainer.dot : 'grey'
  const pgHealth = pgContainer
    ? (pgContainer.dot === 'green' ? 'HEALTHY' : pgContainer.dot === 'amber' ? 'DEGRADED' : 'ERROR')
    : 'UNKNOWN'
  const pgLabel  = pgContainer?.name || 'postgres'
  const pgVersion = pgContainer?.image?.match(/pg(\d+)/i)?.[1]
    ? `pg${pgContainer.image.match(/pg(\d+)/i)[1]}`
    : pgContainer ? 'running' : ''

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
      {/* PLATFORM CORE */}
      <div style={{ background: 'var(--bg-2)', border: '1px solid var(--border)', borderLeft: `3px solid ${apiOk ? 'var(--green)' : 'var(--red)'}`, borderRadius: 2, padding: '8px 10px' }}>
        <div style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: 11, color: 'var(--text-1)', marginBottom: 4, letterSpacing: 0.5 }}>PLATFORM CORE</div>
        {_row(apiOk ? 'var(--green)' : 'var(--red)', 'DS-agent-01', apiOk ? 'ONLINE' : 'ERROR', apiOk ? 'green' : 'red', `v${health?.version || '—'}`)}
        {_row(_healthDot(pgDot === 'green' ? 'healthy' : pgDot === 'amber' ? 'degraded' : pgDot === 'red' ? 'error' : 'unknown'), pgLabel, pgHealth, pgDot === 'green' ? 'green' : pgDot === 'amber' ? 'amber' : pgDot === 'red' ? 'red' : 'grey', pgVersion)}
        {_row(_healthDot(muninnHealth), 'DS-muninndb', muninnHealth.toUpperCase(), _healthTag(muninnHealth), muninnEngrams ? `${Number(muninnEngrams).toLocaleString()} engrams` : '')}
        {_row(_healthDot(kafkaHealth), 'Kafka', kafkaHealth.toUpperCase(), _healthTag(kafkaHealth), kafkaBrokers ? `${kafkaBrokers} brokers` : '')}
        {_row(_healthDot(esHealth), 'Elasticsearch', esHealth.toUpperCase(), _healthTag(esHealth), esNodes ? `${esNodes} node${esNodes !== 1 ? 's' : ''}` : '')}
      </div>

      {/* COLLECTORS */}
      <div style={{ background: 'var(--bg-2)', border: '1px solid var(--border)', borderLeft: '3px solid var(--green)', borderRadius: 2, padding: '8px 10px' }}>
        <div style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: 11, color: 'var(--text-1)', marginBottom: 4, letterSpacing: 0.5 }}>COLLECTORS</div>
        {sortedCollectors.map(([name, c]) => {
          const h = c.last_health || 'unknown'
          return _row(_healthDot(h), name, h.toUpperCase(), _healthTag(h), c.running ? '' : 'stopped')
        })}
        {sortedCollectors.length === 0 && (
          <div style={{ fontSize: 9, color: 'var(--text-3)', padding: '4px 0' }}>Loading collectors...</div>
        )}
      </div>
    </div>
  )
}

function SectionAccordion({ icon, title, badge, statusText, statusColor, defaultOpen, children }) {
  const [open, setOpen] = useState(defaultOpen ?? true)
  return (
    <div>
      <div onClick={() => setOpen(!open)} style={{
        display: 'flex', alignItems: 'center', padding: '8px 12px', cursor: 'pointer',
        background: 'var(--bg-1)', borderBottom: '1px solid var(--border)',
        userSelect: 'none',
      }}>
        <span style={{ fontSize: 10, color: 'var(--text-3)', marginRight: 6, transition: 'transform 0.1s', transform: open ? 'rotate(90deg)' : 'none' }}>▶</span>
        <span style={{ fontSize: 11, marginRight: 6 }}>{icon}</span>
        <span style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: 12, color: 'var(--text-1)', letterSpacing: 0.5 }}>{title}</span>
        {badge && <span style={{ marginLeft: 8, fontSize: 7, fontFamily: 'var(--font-mono)', padding: '1px 4px', background: 'var(--bg-3)', color: 'var(--text-3)', borderRadius: 2, letterSpacing: 1 }}>{badge}</span>}
        <span style={{ marginLeft: 'auto', fontSize: 9, fontFamily: 'var(--font-mono)', color: statusColor || 'var(--text-3)' }}>{statusText}</span>
      </div>
      {open && <div style={{ padding: '8px 12px' }}>{children}</div>}
    </div>
  )
}

// Platform groupings for dashboard sections
const SECTION_PLATFORMS = {
  NETWORK:  ['fortigate', 'fortiswitch', 'opnsense', 'cisco', 'juniper', 'aruba', 'pihole', 'technitium', 'nginx', 'caddy', 'traefik'],
  STORAGE:  ['truenas', 'synology', 'syncthing'],
  SECURITY: ['security_onion', 'wazuh', 'grafana', 'kibana'],
}

// ── Helpers for connection card dot color ─────────────────────────────────────
function connDotColor(ext, c) {
  if (ext?.dot === 'green') return 'var(--green)'
  if (ext?.dot === 'amber') return 'var(--amber)'
  if (ext?.dot === 'red')   return 'var(--red)'
  if (c.verified)           return 'var(--green)'
  if (c.verified === false) return 'var(--red)'
  return 'var(--text-3)'
}

function connDotName(ext, c) {
  if (ext?.dot) return ext.dot
  if (c.verified) return 'green'
  if (c.verified === false) return 'red'
  return 'grey'
}

function ConnectionSectionCards({ platforms, externalData, onEntityClick, compareMode, compareSet, onCompareAdd, sectionName, showFilter }) {
  const [conns, setConns] = useState([])
  useEffect(() => {
    const load = () => {
      fetch(`${import.meta.env.VITE_API_BASE ?? ''}/api/connections`, { headers: { ...authHeaders() } })
        .then(r => r.ok ? r.json() : { data: [] })
        .then(d => setConns((d.data || []).filter(c => platforms.includes(c.platform) && c.host)))
        .catch(() => {})
    }
    load()
    const id = setInterval(load, 30000)
    return () => clearInterval(id)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const [expanded, setExpanded] = useState({})
  const [hoveredId, setHoveredId] = useState(null)

  if (conns.length === 0) {
    return (
      <div style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--text-3)', padding: 12 }}>
        No connections configured — add one in Settings → Connections
      </div>
    )
  }

  const isPinned = (id) => (compareSet || []).some(e => e.id === id)
  const visibleConns = showFilter && showFilter !== 'ALL' ? conns.filter(c => {
    const cid = `connection:${c.id}`
    if (isPinned(cid)) return true
    const ext = (externalData || []).find(e => e.slug === c.platform)
    const dot = connDotName(ext, c)
    if (showFilter === 'ERRORS') return dot === 'red'
    if (showFilter === 'DEGRADED') return dot === 'amber'
    if (showFilter === 'IN MAINT') return dot === 'grey'
    return true
  }) : conns

  const authLabel = (t) => t === 'ssh' ? 'SSH' : 'API'

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 8 }}>
      {visibleConns.map(c => {
        const ext = (externalData || []).find(e => e.slug === c.platform)
        const dotColor = connDotColor(ext, c)
        const isExpanded = expanded[c.id]
        const compareId = `connection:${c.id}`
        const slotIdx = (compareSet || []).findIndex(e => e.id === compareId)
        const isCompareSelected = slotIdx >= 0
        return (
          <div key={c.id}
            onMouseEnter={() => setHoveredId(c.id)}
            onMouseLeave={() => setHoveredId(null)}
            onClick={(e) => {
              if ((e.ctrlKey || e.metaKey) && compareMode && onCompareAdd) {
                e.stopPropagation()
                onCompareAdd({
                  id: compareId, label: c.label || c.host, platform: c.platform,
                  section: sectionName || 'NETWORK',
                  metadata: { host: `${c.host}:${c.port || 443}`, status: ext?.dot, latency_ms: ext?.latency_ms, verified: c.verified }
                })
                return
              }
              if (onEntityClick) onEntityClick(`external_services:${c.platform}`)
            }}
            style={{
              background: isCompareSelected ? `${SLOT_COLORS[slotIdx]}0d` : 'var(--bg-2)',
              border: '1px solid var(--border)',
              borderLeft: `3px solid ${dotColor}`, borderRadius: 2, padding: '8px 10px',
              cursor: onEntityClick || compareMode ? 'pointer' : 'default',
              position: 'relative',
              outline: isCompareSelected ? `1px solid ${SLOT_COLORS[slotIdx]}` : undefined,
              outlineOffset: isCompareSelected ? -1 : undefined,
          }}>
            {isCompareSelected && (
              <div style={{
                position: 'absolute', top: 5, right: 5, width: 15, height: 15, borderRadius: 2,
                background: SLOT_COLORS[slotIdx], color: '#05060a',
                fontFamily: 'var(--font-mono)', fontSize: 8, fontWeight: 'bold',
                display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 2,
              }}>{slotIdx + 1}</div>
            )}
            {compareMode && !isCompareSelected && hoveredId === c.id && (
              <span style={{
                position: 'absolute', bottom: 3, right: 6,
                fontFamily: 'var(--font-mono)', fontSize: 7,
                color: 'var(--text-3)', letterSpacing: '0.04em', pointerEvents: 'none',
              }}>ctrl+click</span>
            )}
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
              <span style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: 11, color: 'var(--text-1)', flex: 1, letterSpacing: 0.5 }}>{c.label || c.host}</span>
              <span style={{ fontSize: 7, fontFamily: 'var(--font-mono)', padding: '1px 4px', background: 'var(--bg-3)', color: 'var(--text-3)', borderRadius: 2, letterSpacing: 1 }}>{c.platform?.toUpperCase()}</span>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: dotColor, flexShrink: 0 }} />
              {ext?.latency_ms != null && <span style={{ fontSize: 8, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>↑ {ext.latency_ms}ms</span>}
              <span style={{ fontSize: 8, fontFamily: 'var(--font-mono)', color: c.auth_type === 'ssh' ? 'var(--cyan)' : c.verified ? 'var(--green)' : 'var(--red)' }}>{authLabel(c.auth_type)}</span>
              <button onClick={(e) => { e.stopPropagation(); setExpanded(prev => ({ ...prev, [c.id]: !prev[c.id] })) }} style={{
                background: 'none', border: 'none', color: 'var(--text-3)', cursor: 'pointer', fontSize: 10, padding: 0,
              }}>{isExpanded ? '−' : '+'}</button>
            </div>
            <div style={{ fontSize: 9, fontFamily: 'var(--font-mono)' }}>
              <div style={{ display: 'flex', gap: 4 }}>
                <span style={{ width: 36, color: 'var(--text-3)', fontSize: 7, letterSpacing: 1 }}>AUTH</span>
                <span style={{ color: 'var(--cyan)' }}>{authLabel(c.auth_type)}</span>
              </div>
              <div style={{ display: 'flex', gap: 4 }}>
                <span style={{ width: 36, color: 'var(--text-3)', fontSize: 7, letterSpacing: 1 }}>HOST</span>
                <span style={{ color: 'var(--cyan)' }}>{c.host}:{c.port || 443}</span>
              </div>
            </div>
            {isExpanded && (
              <div style={{ marginTop: 6, paddingTop: 6, borderTop: '1px solid var(--bg-3)', fontSize: 9, color: 'var(--text-3)' }}>
                <div>Verified: {c.verified ? 'yes' : 'no'}{c.last_seen ? ` · ${c.last_seen}` : ''}</div>
                <div>ID: {(c.id || '').slice(0, 8)}…</div>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

function DashboardView({ activeFilters, onToggleFilter, onToggleAll, onTab, onEntityClick, compareMode, compareSet, onCompareAdd, onToggleCompare }) {
  const [stats, setStats] = useState(null)
  const [search, setSearch] = useState('')
  const [showFilter, setShowFilter] = useState('ALL')
  const [typeFilter, setTypeFilter] = useState('ALL')
  const [globalMaint, setGlobalMaint] = useState(false)
  const [externalData, setExternalData] = useState([])
  useEffect(() => {
    fetchStats().then(setStats).catch(() => {})
    const id = setInterval(() => fetchStats().then(setStats).catch(() => {}), 30000)
    return () => clearInterval(id)
  }, [])
  useEffect(() => {
    const load = () => fetchDashboardExternal()
      .then(d => setExternalData(d?.services || []))
      .catch(() => {})
    load()
    const id = setInterval(load, 30000)
    return () => clearInterval(id)
  }, [])

  const showSection = (type) => typeFilter === 'ALL' || typeFilter === type

  return (
    <div className="flex flex-col flex-1 overflow-hidden min-h-0">
      <DrillDownBar
        search={search} setSearch={setSearch}
        showFilter={showFilter} setShowFilter={setShowFilter}
        typeFilter={typeFilter} setTypeFilter={setTypeFilter}
        globalMaint={globalMaint} setGlobalMaint={setGlobalMaint}
        stats={stats}
        compareMode={compareMode} compareSet={compareSet} onToggleCompare={onToggleCompare}
      />

      {globalMaint && (
        <div style={{ padding: '6px 12px', background: 'var(--amber-dim)', borderBottom: '1px solid var(--amber)', fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--amber)' }}>
          ⚑ GLOBAL MAINTENANCE MODE — ALL ALERTS SUPPRESSED
        </div>
      )}

      <div className="flex-1 overflow-auto min-h-0">
        <AlertsPanel />

        {showSection('PLATFORM') && (
          <SectionAccordion icon="⬡" title="DEATHSTAR PLATFORM" badge="INTERNAL" statusText="" defaultOpen={true}>
            <PlatformCoreCards />
          </SectionAccordion>
        )}

        {showSection('COMPUTE') && (
          <SectionAccordion icon="◈" title="COMPUTE" badge="HYPERVISORS" statusText="" defaultOpen={true}>
            <ServiceCardsErrorBoundary>
              <ServiceCards activeFilters={['vms']} onTab={onTab} onEntityDetail={onEntityClick} compareMode={compareMode} compareSet={compareSet} onCompareAdd={onCompareAdd} showFilter={showFilter} />
            </ServiceCardsErrorBoundary>
          </SectionAccordion>
        )}

        {showSection('COMPUTE') && (
          <SectionAccordion icon="⊟" title="CONTAINERS" badge="DOCKER" statusText="" defaultOpen={true}>
            <ServiceCardsErrorBoundary>
              <ServiceCards activeFilters={['containers_local', 'containers_swarm']} onTab={onTab} onEntityDetail={onEntityClick} compareMode={compareMode} compareSet={compareSet} onCompareAdd={onCompareAdd} showFilter={showFilter} />
            </ServiceCardsErrorBoundary>
          </SectionAccordion>
        )}

        {showSection('NETWORK') && (
          <SectionAccordion icon="◉" title="NETWORK" badge="INFRA" statusText="" defaultOpen={true}>
            <ServiceCardsErrorBoundary>
              <ServiceCards activeFilters={['unifi', 'fortigate']} onTab={onTab} onEntityDetail={onEntityClick} compareMode={compareMode} compareSet={compareSet} onCompareAdd={onCompareAdd} showFilter={showFilter} />
            </ServiceCardsErrorBoundary>
            <ConnectionSectionCards platforms={SECTION_PLATFORMS.NETWORK} externalData={externalData} onEntityClick={onEntityClick} compareMode={compareMode} compareSet={compareSet} onCompareAdd={onCompareAdd} sectionName="NETWORK" showFilter={showFilter} />
          </SectionAccordion>
        )}

        {showSection('STORAGE') && (
          <SectionAccordion icon="⊠" title="STORAGE" badge="DATA" statusText="" defaultOpen={true}>
            <ServiceCardsErrorBoundary>
              <ServiceCards activeFilters={['pbs', 'truenas']} onTab={onTab} onEntityDetail={onEntityClick} compareMode={compareMode} compareSet={compareSet} onCompareAdd={onCompareAdd} showFilter={showFilter} />
            </ServiceCardsErrorBoundary>
            <ConnectionSectionCards platforms={SECTION_PLATFORMS.STORAGE} externalData={externalData} onEntityClick={onEntityClick} compareMode={compareMode} compareSet={compareSet} onCompareAdd={onCompareAdd} sectionName="STORAGE" showFilter={showFilter} />
          </SectionAccordion>
        )}

        {showSection('SECURITY') && (
          <SectionAccordion icon="⊛" title="SECURITY" badge="SOC" statusText="" defaultOpen={true}>
            <ConnectionSectionCards platforms={SECTION_PLATFORMS.SECURITY} externalData={externalData} onEntityClick={onEntityClick} compareMode={compareMode} compareSet={compareSet} onCompareAdd={onCompareAdd} sectionName="SECURITY" showFilter={showFilter} />
          </SectionAccordion>
        )}
      </div>
    </div>
  )
}

// ── Cluster view ──────────────────────────────────────────────────────────────

function ClusterView() {
  return (
    <div className="flex flex-1 overflow-auto p-4 gap-4 min-h-0" style={{ background: 'var(--bg-0)' }}>
      <div className="flex-1 card overflow-auto">
        <div className="px-4 py-3 border-b" style={{ borderColor: 'var(--border)' }}>
          <h2 className="text-sm font-semibold" style={{ color: 'var(--text-1)' }}>Cluster Node Map</h2>
          <p className="text-xs mt-0.5" style={{ color: 'var(--text-3)' }}>
            Click a node to see details. ★ = leader/controller. Brokers shown on worker nodes.
          </p>
        </div>
        <NodeMap compact={false} />
      </div>

      <div className="w-72 shrink-0 flex flex-col gap-3">
        <div className="card overflow-hidden">
          <div className="px-3 py-2 border-b" style={{ borderColor: 'var(--border)' }}>
            <h3 className="text-xs font-semibold uppercase" style={{ color: 'var(--text-2)' }}>Live Status</h3>
          </div>
          <div className="max-h-[calc(100vh-12rem)] overflow-y-auto">
            <StatusPanel />
          </div>
        </div>
      </div>
    </div>
  )
}

// ── App shell ─────────────────────────────────────────────────────────────────

function AppShell() {
  const [activeTab, setActiveTab] = useState('Dashboard')
  const [settingsTab, setSettingsTab] = useState('Connections')
  const [drawerEntityId, setDrawerEntityId] = useState(null)
  const [compareMode, setCompareMode]     = useState(false)
  const [compareSet, setCompareSet]       = useState([])
  const [compareChats, setCompareChats]   = useState({})
  const [bcTargets, setBcTargets]         = useState({})
  const { panelOpen } = useCommandPanel()

  const addToCompare = (entity) => {
    setCompareSet(prev => {
      if (prev.find(e => e.id === entity.id)) return prev
      if (prev.length >= 4) return prev
      return [...prev, entity]
    })
    setCompareChats(prev => prev[entity.id] ? prev : {...prev, [entity.id]: []})
    setBcTargets(prev => ({...prev, [entity.id]: true}))
    setCompareMode(true)
  }

  const removeFromCompare = (id) => {
    setCompareSet(prev => prev.filter(e => e.id !== id))
    setCompareChats(prev => { const n={...prev}; delete n[id]; return n })
    setBcTargets(prev => { const n={...prev}; delete n[id]; return n })
  }

  const toggleCompareMode = () => {
    if (compareMode) {
      setCompareMode(false)
      setCompareSet([])
      setCompareChats({})
      setBcTargets({})
    } else {
      setCompareMode(true)
    }
  }

  // Filter state (lifted here so SubBar can set it via onAlertNavigate)
  const [activeFilters, setActiveFilters] = useState(() => {
    try {
      const saved = localStorage.getItem(FILTER_KEY)
      if (!saved) return ALL_CARD_KEYS.map(c => c.key)
      const loaded = JSON.parse(saved)
      const newKeys = ALL_CARD_KEYS.map(c => c.key).filter(k => !loaded.includes(k))
      return [...loaded, ...newKeys]
    } catch {
      return ALL_CARD_KEYS.map(c => c.key)
    }
  })

  const toggleFilter = (key) => {
    setActiveFilters(prev => {
      const next = prev.includes(key) ? prev.filter(k => k !== key) : [...prev, key]
      localStorage.setItem(FILTER_KEY, JSON.stringify(next))
      return next
    })
  }

  const toggleAll = () => {
    setActiveFilters(prev => {
      const allKeys = ALL_CARD_KEYS.map(c => c.key)
      const allActive = allKeys.every(k => prev.includes(k))
      const next = allActive ? [] : allKeys
      localStorage.setItem(FILTER_KEY, JSON.stringify(next))
      return next
    })
  }

  // Called by SubBar tray — navigates to Dashboard and isolates one section.
  // localStorage is NOT updated (transient navigation; user restores with filter bar).
  const onAlertNavigate = useCallback((sectionKey) => {
    setActiveTab('Dashboard')
    setActiveFilters([sectionKey])
  }, [])

  // "Full log →" link in AgentFeed navigates to Output tab
  useEffect(() => {
    const handler = () => setActiveTab('Output')
    window.addEventListener('navigate-to-output', handler)
    return () => window.removeEventListener('navigate-to-output', handler)
  }, [])

  // CSS grid column widths:
  //   Commands tab active → full width (0px panel col + 1fr main)
  //   Panel open          → 360px panel col + 1fr main
  //   Panel closed        → 0px panel col + 1fr main (0px collapses the panel)
  const gridCols = (panelOpen && activeTab !== 'Commands')
    ? '360px 1fr'
    : '0px 1fr'

  return (
    <div className="flex h-screen overflow-hidden" style={{ background: 'var(--bg-0)' }}>
      {/* Sidebar navigation */}
      <Sidebar activeTab={activeTab} onTab={setActiveTab} onSettingsTab={setSettingsTab} activeSettingsTab={settingsTab} />

      {/* Main content area */}
      <div className="flex-1 flex overflow-hidden min-w-0 min-h-0">
        {/* Commands side panel (when open and not on Commands tab) */}
        {panelOpen && activeTab !== 'Commands' && (
          <div className="w-[360px] shrink-0 overflow-hidden" style={{ borderRight: '1px solid var(--border)' }}>
            <CommandSidePanel />
          </div>
        )}

        {/* Page content */}
        <div
          className="flex flex-col flex-1 overflow-hidden min-w-0 min-h-0"
          data-testid="main-content"
        >
          {activeTab === 'Dashboard' && (
            <DashboardView
              activeFilters={activeFilters}
              onToggleFilter={toggleFilter}
              onToggleAll={toggleAll}
              onTab={setActiveTab}
              onEntityClick={setDrawerEntityId}
              compareMode={compareMode}
              compareSet={compareSet}
              onCompareAdd={addToCompare}
              onToggleCompare={toggleCompareMode}
            />
          )}

          {activeTab === 'Cluster' && <ClusterView />}

          {activeTab === 'Commands' && (
            // Single CommandPanel instance at full width — mode="tab"
            <div className="flex flex-col flex-1 overflow-hidden min-h-0">
              <CommandPanel mode="tab" />
            </div>
          )}

          {activeTab === 'Skills' && (
            <div className="flex-1 overflow-hidden">
              <SkillsPanel />
            </div>
          )}

          {activeTab === 'Logs' && (
            <div className="flex flex-1 overflow-hidden min-h-0">
              <div className="flex-1 overflow-hidden">
                <LogsPanel />
              </div>
            </div>
          )}

          {activeTab === 'Memory' && (
            <div className="flex flex-1 overflow-hidden min-h-0">
              <div className="flex-1 overflow-hidden" style={{ background: "var(--bg-0)" }}>
                <MemoryPanel />
              </div>
            </div>
          )}

          {activeTab === 'Ingest' && (
            <div className="flex flex-1 overflow-hidden min-h-0">
              <div className="flex-1 overflow-hidden" style={{ background: "var(--bg-0)" }}>
                <IngestPanel />
              </div>
            </div>
          )}

          {activeTab === 'Docs' && (
            <div className="flex flex-1 overflow-hidden min-h-0">
              <div className="flex-1 overflow-hidden" style={{ background: "var(--bg-0)" }}>
                <DocsTab />
              </div>
            </div>
          )}

          {activeTab === 'Output' && (
            <div className="flex flex-1 overflow-hidden min-h-0">
              <div className="flex-1 overflow-hidden">
                <OutputPanel />
              </div>
            </div>
          )}

          {activeTab === 'Tests' && (
            <div className="flex flex-1 overflow-hidden min-h-0">
              <div className="flex-1 overflow-hidden">
                <TestsPanel />
              </div>
            </div>
          )}

          {activeTab === 'Settings' && (
            <div className="flex flex-1 overflow-hidden min-h-0">
              <div className="flex-1 overflow-hidden" style={{ background: 'var(--bg-0)' }}>
                <SettingsPage initialTab={settingsTab} />
              </div>
            </div>
          )}
        </div>

        {/* Compare panel — right side */}
        {compareSet.length > 0 && (
          <ComparePanel
            compareSet={compareSet}
            chats={compareChats}
            setChats={setCompareChats}
            bcTargets={bcTargets}
            setBcTargets={setBcTargets}
            onRemove={removeFromCompare}
            onClose={toggleCompareMode}
          />
        )}
      </div>

      <AlertToast />
      <PlanConfirmModal />
      {drawerEntityId && (
        <EntityDrawer entityId={drawerEntityId} onClose={() => setDrawerEntityId(null)} />
      )}

      {_showLayoutTest && LayoutTest && (
        <Suspense fallback={null}>
          <LayoutTest />
        </Suspense>
      )}
    </div>
  )
}

// ── Auth components ────────────────────────────────────────────────────────────

function UserBadge() {
  const { user, logout } = useAuth()
  if (!user) return null
  return (
    <div className="flex items-center gap-2 px-3 border-l border-gray-200 h-full">
      <span className="text-xs text-gray-500">{user}</span>
      <button
        onClick={logout}
        className="text-xs text-gray-400 hover:text-red-500 transition-colors"
        title="Sign out"
      >
        Sign out
      </button>
    </div>
  )
}

function AuthGate({ children }) {
  const { isAuthed, loading } = useAuth()
  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-950">
        <div className="text-gray-500 text-sm font-mono">Loading\u2026</div>
      </div>
    )
  }
  if (!isAuthed) return <LoginScreen />
  return children
}

// ── Root with providers ────────────────────────────────────────────────────────

function AppWithPanelProvider() {
  const { commandsPanelDefault } = useOptions()
  return (
    <CommandPanelProvider defaultOpen={commandsPanelDefault === 'visible'}>
      <AgentProvider>
        <AppShell />
      </AgentProvider>
    </CommandPanelProvider>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <AuthGate>
        <OptionsProvider>
          <AgentOutputProvider>
            <TaskProvider>
              <AppWithPanelProvider />
            </TaskProvider>
          </AgentOutputProvider>
        </OptionsProvider>
      </AuthGate>
    </AuthProvider>
  )
}
