import { useState, useEffect } from 'react'
import CommandPanel from './components/CommandPanel'
import OutputPanel  from './components/OutputPanel'
import StatusPanel  from './components/StatusPanel'
import LogTable     from './components/LogTable'
import { fetchHealth } from './api'

function Header() {
  const [health, setHealth] = useState(null)

  useEffect(() => {
    fetchHealth().then(setHealth).catch(() => {})
    const id = setInterval(() => fetchHealth().then(setHealth).catch(() => {}), 15_000)
    return () => clearInterval(id)
  }, [])

  return (
    <header className="flex items-center justify-between px-4 py-2 bg-slate-900 border-b border-slate-700 shrink-0">
      <div className="flex items-center gap-3">
        <span className="text-blue-400 font-bold text-lg tracking-tight font-mono">HP1</span>
        <span className="text-slate-300 text-sm">AI Agent</span>
        {health && (
          <span className="text-xs text-slate-500 font-mono">v{health.version}</span>
        )}
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

export default function App() {
  const [logRefresh, setLogRefresh] = useState(0)

  const triggerLogRefresh = () => setLogRefresh(n => n + 1)

  return (
    <div className="flex flex-col h-screen bg-slate-950 overflow-hidden">
      <Header />

      {/* 3-panel main area */}
      <div className="flex flex-1 overflow-hidden min-h-0">

        {/* Left — Commands (fixed width) */}
        <div className="w-72 shrink-0 border-r border-slate-700 flex flex-col overflow-hidden">
          <CommandPanel onResult={triggerLogRefresh} />
        </div>

        {/* Centre — Live Output (fills space) */}
        <div className="flex-1 flex flex-col overflow-hidden border-r border-slate-700">
          <OutputPanel />
        </div>

        {/* Right — Status (fixed width) */}
        <div className="w-56 shrink-0 flex flex-col overflow-hidden">
          <StatusPanel />
        </div>
      </div>

      {/* Bottom — Log table */}
      <div className="h-52 shrink-0 border-t border-slate-700 flex flex-col overflow-hidden">
        <LogTable refreshTick={logRefresh} />
      </div>
    </div>
  )
}
