import { useState, useEffect, lazy, Suspense } from 'react'
import { Terminal } from 'lucide-react'
import CommandPanel   from './components/CommandPanel'
import OutputPanel    from './components/OutputPanel'
import StatusPanel    from './components/StatusPanel'
import LogTable       from './components/LogTable'
import NodeMap        from './components/NodeMap'
import AlertToast     from './components/AlertToast'
import MemoryPanel    from './components/MemoryPanel'
import LogsPanel      from './components/LogsPanel'
import DashboardCards from './components/DashboardCards'
import OptionsModal   from './components/OptionsModal'
import { OptionsProvider, useOptions } from './context/OptionsContext'
import { CommandPanelProvider, useCommandPanel } from './context/CommandPanelContext'
import { AgentProvider, useAgent } from './context/AgentContext'
import { fetchHealth, fetchStats, runAgent } from './api'
// Dev-only layout test harness — renders as overlay at ?test=layout
const _showLayoutTest = import.meta.env.DEV &&
  new URLSearchParams(window.location.search).get('test') === 'layout'
const LayoutTest = _showLayoutTest ? lazy(() => import('./dev/LayoutTest.jsx')) : null

const MAIN_TABS = ['Dashboard', 'Cluster', 'Commands', 'Logs', 'Memory', 'Output']

// ── Row 1: Header — logo + tabs + settings gear only ──────────────────────────

function Header({ activeTab, onTab }) {
  const { agentState, clearState } = useAgent()

  const handleTab = (tab) => {
    if (tab === 'Output' && agentState && agentState !== 'running') clearState()
    onTab(tab)
  }

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
                  {agentState === 'running' && (
                    <span data-testid="output-badge" className="text-yellow-500 animate-pulse text-xs">⚡</span>
                  )}
                  {agentState === 'success' && (
                    <span data-testid="output-badge" className="w-1.5 h-1.5 rounded-full bg-green-500 inline-block" />
                  )}
                  {agentState === 'failed' && (
                    <span data-testid="output-badge" className="w-1.5 h-1.5 rounded-full bg-red-500 inline-block" />
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
    <div className="flex items-center px-3 border-r border-gray-200 h-full shrink-0">
      <span className="text-gray-400 text-xs mr-1">{label}:</span>
      <span className={`text-xs font-medium ${accent ? 'text-orange-600' : 'text-gray-800'}`}>{value ?? '—'}</span>
    </div>
  )
}

function SubBar() {
  const { panelOpen, togglePanel } = useCommandPanel()
  const [stats,  setStats]  = useState(null)
  const [health, setHealth] = useState(null)

  useEffect(() => {
    const loadAll = () => {
      fetchStats().then(setStats).catch(() => {})
      fetchHealth().then(setHealth).catch(() => {})
    }
    loadAll()
    const id = setInterval(loadAll, 30_000)
    return () => clearInterval(id)
  }, [])

  const topTool = stats?.most_used_tools?.[0]

  return (
    <div className="flex items-center h-8 bg-white border-b border-gray-200 shrink-0 overflow-x-auto">

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
        <div className="flex items-center px-3 border-r border-gray-200 h-full">
          <span className="text-xs text-gray-400">Loading…</span>
        </div>
      )}

      <div className="flex items-center ml-auto">
        <div className="flex items-center px-3 border-l border-gray-200 h-8">
          <span className="text-gray-400 text-xs mr-1">API</span>
          <span className="text-gray-800 text-xs font-medium">:8000</span>
          <span className={`w-1.5 h-1.5 rounded-full ml-1.5 ${
            health?.status === 'ok' ? 'bg-green-500' : 'bg-gray-400'
          }`} />
        </div>
        {health?.ws_clients !== undefined && (
          <div className="flex items-center px-3 border-l border-gray-200 h-8">
            <span className="text-gray-400 text-xs">WS:</span>
            <span className="text-gray-800 text-xs font-medium ml-1">{health.ws_clients}</span>
          </div>
        )}
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

// ── Agent task bar (bottom of Dashboard only) ─────────────────────────────────

function AgentTaskBar({ onRun }) {
  const { markRunning, markDone } = useAgent()
  const [task, setTask] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg,  setMsg]  = useState('')

  const submit = async () => {
    if (!task.trim()) return
    setBusy(true)
    setMsg('')
    markRunning()
    try {
      const r = await runAgent(task)
      setMsg(`Started — session ${r.session_id?.slice(0, 8)}`)
      onRun?.()
    } catch (e) {
      setMsg(`Error: ${e.message}`)
      markDone(false)
    } finally {
      setBusy(false)
    }
  }

  const onKey = (e) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) submit()
  }

  return (
    <div className="shrink-0 border-t border-gray-200 bg-gray-50 px-4 py-3">
      <div className="flex items-start gap-3 max-w-4xl mx-auto">
        <div className="flex-1">
          <textarea
            value={task}
            onChange={e => setTask(e.target.value)}
            onKeyDown={onKey}
            placeholder="Describe a task for the agent… (Ctrl+Enter to run)"
            rows={2}
            className="w-full bg-white border border-gray-300 rounded px-3 py-2 text-xs text-gray-900 resize-none focus:outline-none focus:border-blue-500"
          />
          {msg && <p className="text-xs text-gray-500 mt-1">{msg}</p>}
        </div>
        <button
          onClick={submit}
          disabled={busy || !task.trim()}
          className={`mt-0.5 px-4 py-2 rounded text-xs font-bold transition-colors shrink-0 ${
            busy || !task.trim()
              ? 'bg-gray-200 text-gray-400 cursor-not-allowed'
              : 'bg-green-600 hover:bg-green-700 text-white'
          }`}
        >
          {busy ? '⏳ Running…' : 'Run Agent'}
        </button>
      </div>
    </div>
  )
}

// ── Dashboard view ────────────────────────────────────────────────────────────

function DashboardView({ logRefresh, onLogRefresh }) {
  return (
    <div className="flex flex-col flex-1 overflow-hidden min-h-0">
      <div className="flex-1 overflow-hidden min-h-0">
        <DashboardCards />
      </div>
      <div className="h-48 shrink-0 border-t border-gray-200 flex flex-col overflow-hidden bg-white">
        <LogTable refreshTick={logRefresh} />
      </div>
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
  const [logRefresh, setLogRefresh] = useState(0)
  const [activeTab,  setActiveTab]  = useState('Dashboard')
  const { panelOpen } = useCommandPanel()

  const triggerLogRefresh = () => setLogRefresh(n => n + 1)

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
            <DashboardView logRefresh={logRefresh} onLogRefresh={triggerLogRefresh} />
          )}

          {activeTab === 'Cluster' && <ClusterView />}

          {activeTab === 'Commands' && (
            // Single CommandPanel instance at full width — mode="tab"
            <div className="flex flex-col flex-1 overflow-hidden min-h-0">
              <CommandPanel mode="tab" onResult={triggerLogRefresh} />
            </div>
          )}

          {activeTab === 'Logs' && (
            <div className="flex flex-1 overflow-hidden min-h-0">
              <div className="flex-1 bg-white overflow-hidden">
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
        </div>
      </div>

      {activeTab === 'Dashboard' && <AgentTaskBar onRun={triggerLogRefresh} />}

      <AlertToast />

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
      <AppWithPanelProvider />
    </OptionsProvider>
  )
}
