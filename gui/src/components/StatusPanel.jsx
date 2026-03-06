import { useEffect, useState } from 'react'
import { fetchStatus } from '../api'

const POLL_MS = 10_000

function Indicator({ status }) {
  const map = {
    ok:      'bg-green-500',
    degraded:'bg-yellow-400',
    failed:  'bg-red-500',
    error:   'bg-red-500',
    unknown: 'bg-slate-500',
  }
  return (
    <span className={`inline-block w-2.5 h-2.5 rounded-full ${map[status] ?? 'bg-slate-500'} mr-2`} />
  )
}

function Row({ label, data }) {
  const status = data?.status ?? 'unknown'
  const msg    = data?.message ?? ''
  return (
    <div className="flex items-start gap-2 py-1.5 border-b border-slate-700 last:border-0">
      <Indicator status={status} />
      <div className="flex-1 min-w-0">
        <div className="flex justify-between">
          <span className="text-slate-200 font-semibold text-sm">{label}</span>
          <span className={`text-xs uppercase font-mono ${
            status === 'ok' ? 'text-green-400' :
            status === 'degraded' ? 'text-yellow-400' :
            status === 'unknown' ? 'text-slate-500' : 'text-red-400'
          }`}>{status}</span>
        </div>
        {msg && <p className="text-xs text-slate-400 mt-0.5 truncate">{msg}</p>}
        {status === 'ok' && data?.data?.nodes && (
          <p className="text-xs text-slate-500">{data.data.nodes.length} node(s)</p>
        )}
        {status === 'ok' && data?.data?.count !== undefined && (
          <p className="text-xs text-slate-500">{data.data.count} broker(s)</p>
        )}
      </div>
    </div>
  )
}

export default function StatusPanel() {
  const [snap, setSnap]     = useState(null)
  const [ts, setTs]         = useState(null)
  const [loading, setLoading] = useState(true)

  const refresh = () => {
    fetchStatus()
      .then(d => { setSnap(d); setTs(new Date().toLocaleTimeString()) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, POLL_MS)
    return () => clearInterval(id)
  }, [])

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-3 py-2 border-b border-slate-700">
        <span className="text-xs font-bold uppercase tracking-wider text-slate-400">Status</span>
        <button
          onClick={refresh}
          className="text-xs text-slate-500 hover:text-slate-300 transition-colors"
        >↺</button>
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-2">
        {loading ? (
          <p className="text-xs text-slate-500 animate-pulse">Loading…</p>
        ) : snap ? (
          <>
            <Row label="Docker Swarm"   data={snap.swarm} />
            <Row label="Services"       data={snap.services} />
            <Row label="Kafka"          data={snap.kafka} />
            <Row label="Elasticsearch"  data={snap.elasticsearch} />

            {/* Service list */}
            {snap.services?.data?.services?.length > 0 && (
              <div className="mt-3">
                <p className="text-xs text-slate-500 uppercase font-bold mb-1">Services</p>
                {snap.services.data.services.map(s => (
                  <div key={s.name} className="flex justify-between text-xs py-1 border-b border-slate-800">
                    <span className="text-slate-300 truncate max-w-[120px]" title={s.name}>
                      {s.name.replace(/^\w+-stack_/, '')}
                    </span>
                    <span className={`${
                      s.running_replicas === s.desired_replicas ? 'text-green-400' : 'text-yellow-400'
                    }`}>
                      {s.running_replicas}/{s.desired_replicas}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </>
        ) : (
          <p className="text-xs text-red-400">Failed to load status</p>
        )}
      </div>

      {ts && (
        <div className="px-3 py-1.5 border-t border-slate-700">
          <p className="text-xs text-slate-600">Updated {ts}</p>
        </div>
      )}
    </div>
  )
}
