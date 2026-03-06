import { useEffect, useState } from 'react'
import { fetchStats } from '../api'

function Stat({ label, value, accent = false }) {
  return (
    <div className="flex flex-col items-center px-4 py-1 border-r border-slate-700 last:border-r-0">
      <span className={`text-sm font-mono font-bold ${accent ? 'text-orange-400' : 'text-slate-200'}`}>
        {value ?? '—'}
      </span>
      <span className="text-xs text-slate-500 uppercase tracking-wide">{label}</span>
    </div>
  )
}

export default function StatsBar() {
  const [stats, setStats] = useState(null)

  useEffect(() => {
    const load = () => fetchStats().then(setStats).catch(() => {})
    load()
    const id = setInterval(load, 30_000)
    return () => clearInterval(id)
  }, [])

  if (!stats) return null

  const topTool = stats.most_used_tools?.[0]

  return (
    <div className="flex items-center justify-center bg-slate-900 border-b border-slate-700 shrink-0 overflow-x-auto">
      <Stat label="Runs" value={stats.total_operations} />
      <Stat label="Tool Calls" value={stats.total_tool_calls} />
      <Stat label="Success" value={`${stats.success_rate}%`} />
      <Stat label="Avg Duration" value={stats.avg_duration_ms ? `${stats.avg_duration_ms}ms` : '—'} />
      <Stat label="Top Tool" value={topTool ? `${topTool.tool.split('_').slice(0,2).join('_')} ×${topTool.count}` : '—'} />
      {stats.escalations_unresolved > 0 && (
        <Stat label="Escalations" value={`⚠ ${stats.escalations_unresolved}`} accent />
      )}
    </div>
  )
}
