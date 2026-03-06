/**
 * ElasticStatus — compact Elasticsearch status widget.
 * Embedded in StatusPanel elastic section.
 * Shows: index count, total docs, last Filebeat ingest, cluster health.
 */
import { useEffect, useState, useCallback } from 'react'

const BASE = import.meta.env.VITE_API_BASE ?? ''

export default function ElasticStatus() {
  const [stats, setStats]   = useState(null)
  const [error, setError]   = useState(null)

  const refresh = useCallback(async () => {
    try {
      const r = await fetch(`${BASE}/api/elastic/stats`)
      const d = await r.json()
      setStats(d)
      setError(null)
    } catch (e) {
      setError(e.message)
    }
  }, [])

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, 30_000)
    return () => clearInterval(id)
  }, [refresh])

  if (!stats || stats.available === false) {
    return (
      <p className="text-xs text-slate-600 italic px-1">
        {stats?.message || 'Elasticsearch not configured'}
      </p>
    )
  }

  const stale = stats.stale
  const fmtTs = (ts) => {
    if (!ts) return 'N/A'
    const d = new Date(ts)
    return isNaN(d.getTime()) ? 'N/A' : d.toLocaleTimeString()
  }
  const lastIngest = fmtTs(stats.last_ingest)

  const kibanaUrl = import.meta.env.VITE_KIBANA_URL

  return (
    <div className="text-xs space-y-1">
      <div className="flex justify-between">
        <span className="text-slate-500">Indices</span>
        <span className="text-slate-300 font-mono">{stats.indices?.length ?? 0}</span>
      </div>
      <div className="flex justify-between">
        <span className="text-slate-500">Total docs</span>
        <span className="text-slate-300 font-mono">{(stats.total_docs ?? 0).toLocaleString()}</span>
      </div>
      <div className="flex justify-between">
        <span className="text-slate-500">Last ingest</span>
        <span className={`font-mono ${stale ? 'text-red-400 animate-pulse' : 'text-green-400'}`}>
          {lastIngest ?? 'never'}
          {stale && ' ⚠ stale'}
        </span>
      </div>
      <div className="flex justify-between">
        <span className="text-slate-500">Filebeat</span>
        <span className={stats.filebeat_active ? 'text-green-400' : 'text-red-400'}>
          {stats.filebeat_active ? 'active' : 'stale'}
        </span>
      </div>
      {kibanaUrl && (
        <div className="pt-1">
          <a
            href={kibanaUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-500 hover:text-blue-400 underline"
          >
            Open Kibana ↗
          </a>
        </div>
      )}
    </div>
  )
}
