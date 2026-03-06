import { useState, useEffect } from 'react'
import CommandPanel  from './components/CommandPanel'
import OutputPanel   from './components/OutputPanel'
import StatusPanel   from './components/StatusPanel'
import LogTable      from './components/LogTable'
import StatsBar      from './components/StatsBar'
import NodeMap       from './components/NodeMap'
import AlertToast    from './components/AlertToast'
import MemoryPanel   from './components/MemoryPanel'
import LogsPanel     from './components/LogsPanel'
import { fetchHealth } from './api'

const MAIN_TABS = ['Dashboard', 'Cluster', 'Logs', 'Memory']

function Header({ activeTab, onTab }) {
  const [health, setHealth] = useState(null)

  useEffect(() => {
    fetchHealth().then(setHealth).catch(() => {})
    const id = setInterval(() => fetchHealth().then(setHealth).catch(() => {}), 15_000)
    return () => clearInterval(id)
  }, [])

  return (
    <header className="flex items-center justify-between px-4 py-0 bg-slate-900 border-b border-slate-700 shrink-0">
      <div className="flex items-center gap-3">
        <span className="text-blue-400 font-bold text-lg tracking-tight font-mono py-2">HP1</span>
        <span className="text-slate-300 text-sm">AI Agent</span>
        {health && (
          <span className="text-xs text-slate-500 font-mono">v{health.version}</span>
        )}
        {/* Main nav tabs */}
        <div className="flex ml-4">
          {MAIN_TABS.map(tab => (
            <button
              key={tab}
              onClick={() => onTab(tab)}
              className={`text-xs px-3 py-3 border-b-2 transition-colors ${
                activeTab === tab
                  ? 'border-blue-500 text-blue-400'
                  : 'border-transparent text-slate-500 hover:text-slate-300'
              }`}
            >
              {tab}
            </button>
          ))}
        </div>
      </div>
      <div className="flex items-center gap-4 text-xs text-slate-400">
        <span className="flex items-center gap-1.5">
          <span className={`w-2 h-2 rounded-full ${health?.status === 'ok' ? 'bg-green-500 animate-pulse' : 'bg-slate-600'}`} />
          API :8000
        </span>
        {health?.ws_clients !== undefined && (
          <span className="text-slate-600 font-mono">{health.ws_clients} ws</span>
        )}
      </div>
    </header>
  )
}

// ── Dashboard view (original 3-panel layout) ──────────────────────────────────

function DashboardView({ logRefresh, onLogRefresh }) {
  return (
    <>
      <div className="flex flex-1 overflow-hidden min-h-0">
        {/* Left — Commands */}
        <div className="w-72 shrink-0 border-r border-slate-700 flex flex-col overflow-hidden">
          <CommandPanel onResult={onLogRefresh} />
        </div>

        {/* Centre — Live Output */}
        <div className="flex-1 flex flex-col overflow-hidden border-r border-slate-700">
          <OutputPanel />
        </div>

        {/* Right — Status */}
        <div className="w-80 shrink-0 flex flex-col overflow-hidden">
          <StatusPanel />
        </div>
      </div>

      <StatsBar />

      <div className="h-64 shrink-0 border-t border-slate-700 flex flex-col overflow-hidden">
        <LogTable refreshTick={logRefresh} />
      </div>
    </>
  )
}

// ── Cluster view (full-width NodeMap) ─────────────────────────────────────────

function ClusterView() {
  return (
    <div className="flex flex-1 overflow-auto p-4 gap-4 min-h-0">
      {/* Node map — main area */}
      <div className="flex-1 bg-slate-900 rounded-lg border border-slate-700 overflow-auto">
        <div className="px-4 py-3 border-b border-slate-700">
          <h2 className="text-sm font-semibold text-slate-300">Cluster Node Map</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Click a node to see details. ★ = leader/controller. Brokers shown on worker nodes.
          </p>
        </div>
        <NodeMap compact={false} />
      </div>

      {/* Right sidebar — infrastructure details */}
      <div className="w-72 shrink-0 flex flex-col gap-4">
        <div className="bg-slate-900 rounded-lg border border-slate-700 overflow-hidden">
          <div className="px-3 py-2 border-b border-slate-700">
            <h3 className="text-xs font-semibold text-slate-400 uppercase">Live Status</h3>
          </div>
          <div className="max-h-96 overflow-y-auto">
            <StatusPanel />
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Root ──────────────────────────────────────────────────────────────────────

export default function App() {
  const [logRefresh, setLogRefresh] = useState(0)
  const [activeTab, setActiveTab]   = useState('Dashboard')

  const triggerLogRefresh = () => setLogRefresh(n => n + 1)

  return (
    <div className="flex flex-col h-screen bg-slate-950 overflow-hidden">
      <Header activeTab={activeTab} onTab={setActiveTab} />

      {activeTab === 'Dashboard' && (
        <DashboardView logRefresh={logRefresh} onLogRefresh={triggerLogRefresh} />
      )}

      {activeTab === 'Cluster' && (
        <ClusterView />
      )}

      {activeTab === 'Logs' && (
        <div className="flex flex-1 overflow-hidden min-h-0">
          <div className="flex-1 bg-slate-900 overflow-hidden">
            <LogsPanel />
          </div>
        </div>
      )}

      {activeTab === 'Memory' && (
        <div className="flex flex-1 overflow-hidden min-h-0">
          <div className="flex-1 bg-slate-900 overflow-hidden">
            <MemoryPanel />
          </div>
        </div>
      )}

      {/* Global alert toasts — always visible */}
      <AlertToast />
    </div>
  )
}
