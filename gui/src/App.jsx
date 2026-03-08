import { useState, useEffect, useRef, lazy, Suspense } from 'react'
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
import OptionsModal   from './components/OptionsModal'
import { OptionsProvider, useOptions } from './context/OptionsContext'
import { CommandPanelProvider, useCommandPanel } from './context/CommandPanelContext'
import { AgentProvider } from './context/AgentContext'
import { AgentOutputProvider, useAgentOutput } from './context/AgentOutputContext'
import { TaskProvider } from './context/TaskContext'
import { fetchHealth, fetchStats } from './api'
// Dev-only layout test harness — renders as overlay at ?test=layout
const _showLayoutTest = import.meta.env.DEV &&
  new URLSearchParams(window.location.search).get('test') === 'layout'
const LayoutTest = _showLayoutTest ? lazy(() => import('./dev/LayoutTest.jsx')) : null

const MAIN_TABS = ['Dashboard', 'Cluster', 'Commands', 'Logs', 'Memory', 'Output', 'Tests']

// ── Row 1: Header — logo + tabs + settings gear only ──────────────────────────

function Header({ activeTab, onTab }) {
  const { isRunning, outputLines } = useAgentOutput()
  const [lastSeenCount,    setLastSeenCount]    = useState(0)
  const [lastRunToolCount, setLastRunToolCount] = useState(0)
  const [lastRunHadError,  setLastRunHadError]  = useState(false)
  const [outputBadge,      setOutputBadge]      = useState(false)
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

  const handleTab = (tab) => {
    if (tab === 'Output') {
      setLastSeenCount(outputLines.length)
      setOutputBadge(false)
    }
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
        </div>
      </div>

      <div className="flex items-center gap-2">
        <OptionsModal />
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

function SubBar() {
  const { panelOpen, togglePanel } = useCommandPanel()
  const { wsState, agentType, lastAgentType } = useAgentOutput()
  const [stats,  setStats]  = useState(null)
  const [health, setHealth] = useState(null)

  useEffect(() => {
    const refreshStats = () => fetchStats().then(setStats).catch(() => setStats(null))
    const loadAll = () => {
      refreshStats()
      fetchHealth().then(setHealth).catch(() => setHealth(null))
    }
    loadAll()
    const id = setInterval(loadAll, 30_000)
    window.addEventListener('agent-done', refreshStats)
    return () => {
      clearInterval(id)
      window.removeEventListener('agent-done', refreshStats)
    }
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
              {agentType && <span className="text-yellow-500 animate-pulse text-xs">⚡</span>}
            </div>
          ) : null
        })()}
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
          <div className="flex items-center px-3 border-l border-gray-200 h-8">
            <span className="text-gray-400 text-xs font-mono">v{health.version}</span>
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
    <div className="w-full h-full flex flex-col bg-white border-r border-gray-200 overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2 border-b border-gray-200 bg-gray-50 shrink-0">
        <div className="flex items-center gap-2">
          <Terminal size={13} className="text-gray-500" />
          <span className="text-xs font-bold uppercase tracking-wider text-gray-600">Commands</span>
        </div>
        <button
          onClick={closePanel}
          className="text-gray-400 hover:text-gray-700 transition-colors text-sm leading-none"
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


// ── Dashboard view ────────────────────────────────────────────────────────────

function DashboardView() {
  return (
    <div className="flex flex-col flex-1 overflow-hidden min-h-0">
      <DashboardCards />
    </div>
  )
}

// ── Cluster view ──────────────────────────────────────────────────────────────

function ClusterView() {
  return (
    <div className="flex flex-1 overflow-auto p-4 gap-4 min-h-0 bg-gray-100">
      <div className="flex-1 bg-white border border-gray-200 shadow-sm rounded-lg overflow-auto">
        <div className="px-4 py-3 bg-gray-50 border-b border-gray-200">
          <h2 className="text-sm font-semibold text-gray-900">Cluster Node Map</h2>
          <p className="text-xs text-gray-500 mt-0.5">
            Click a node to see details. ★ = leader/controller. Brokers shown on worker nodes.
          </p>
        </div>
        <NodeMap compact={false} />
      </div>

      <div className="w-72 shrink-0 flex flex-col gap-3">
        <div className="bg-white border border-gray-200 shadow-sm rounded-lg overflow-hidden">
          <div className="px-3 py-2 bg-gray-50 border-b border-gray-200">
            <h3 className="text-xs font-semibold text-gray-600 uppercase">Live Status</h3>
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
  const { panelOpen } = useCommandPanel()

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
    <div className="flex flex-col h-screen bg-gray-100 overflow-hidden">
      {/* Row 1: logo + tabs + gear */}
      <Header activeTab={activeTab} onTab={setActiveTab} />

      {/* Row 2: commands toggle + stats + API status */}
      <SubBar />

      {/* Main content — CSS Grid controls panel vs content widths */}
      <div
        className="flex-1 overflow-hidden min-h-0"
        style={{
          display: 'grid',
          gridTemplateColumns: gridCols,
          transition: 'grid-template-columns 200ms ease-in-out',
        }}
      >
        {/* ── Column 1: Commands side panel (0px when closed or Commands tab) ── */}
        <div className="overflow-hidden" data-testid="commands-panel-col">
          {/* Unmount panel content when Commands tab is active to avoid duplicate render */}
          {activeTab !== 'Commands' && <CommandSidePanel />}
        </div>

        {/* ── Column 2: Main content ── */}
        <div
          className="flex flex-col overflow-hidden min-w-0 min-h-0"
          data-testid="main-content"
        >
          {activeTab === 'Dashboard' && (
            <DashboardView />
          )}

          {activeTab === 'Cluster' && <ClusterView />}

          {activeTab === 'Commands' && (
            // Single CommandPanel instance at full width — mode="tab"
            <div className="flex flex-col flex-1 overflow-hidden min-h-0">
              <CommandPanel mode="tab" />
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
              <div className="flex-1 bg-white overflow-hidden">
                <MemoryPanel />
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
        </div>
      </div>

      <AlertToast />
      <PlanConfirmModal />

      {_showLayoutTest && LayoutTest && (
        <Suspense fallback={null}>
          <LayoutTest />
        </Suspense>
      )}
    </div>
  )
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
    <OptionsProvider>
      <AgentOutputProvider>
        <TaskProvider>
          <AppWithPanelProvider />
        </TaskProvider>
      </AgentOutputProvider>
    </OptionsProvider>
  )
}
