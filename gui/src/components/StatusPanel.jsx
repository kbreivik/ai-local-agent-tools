/**
 * StatusPanel — live infrastructure status dashboard.
 * Reads from /api/status (backed by DB snapshots from background collectors).
 * Polls every 15s. Collapsible sections per component.
 */
import { useEffect, useState, useCallback } from 'react'
import { fetchStatus } from '../api'
import SparkLine from './SparkLine'
import ElasticStatus from './ElasticStatus'

const POLL_MS = 15_000

// ── Health indicator ──────────────────────────────────────────────────────────

const HEALTH_DOT = {
  healthy:      'bg-green-500',
  ok:           'bg-green-500',
  green:        'bg-green-500',
  active:       'bg-green-500',
  degraded:     'bg-yellow-400',
  yellow:       'bg-yellow-400 animate-pulse',
  critical:     'bg-red-500 animate-pulse',
  red:          'bg-red-500 animate-pulse',
  error:        'bg-red-600 animate-pulse',
  unconfigured: 'bg-slate-600',
  unknown:      'bg-slate-700',
}

const HEALTH_TEXT = {
  healthy:      'text-green-400',
  ok:           'text-green-400',
  green:        'text-green-400',
  active:       'text-green-400',
  degraded:     'text-yellow-400',
  yellow:       'text-yellow-400',
  critical:     'text-red-400',
  red:          'text-red-400',
  error:        'text-red-400',
  unconfigured: 'text-slate-500',
  unknown:      'text-slate-600',
}

// Severity order — higher index = worse
const SEV = ['healthy', 'ok', 'green', 'active', 'degraded', 'yellow', 'error', 'critical', 'red']
const sev = (h) => {
  const i = SEV.indexOf(h)
  return i === -1 ? 4 : i   // unknown lands between degraded and error
}
function worstHealth(...healths) {
  return healths.flat().reduce((worst, h) => sev(h) > sev(worst) ? h : worst, 'healthy')
}

function Dot({ health }) {
  return (
    <span className={`inline-block w-2.5 h-2.5 rounded-full shrink-0 ${HEALTH_DOT[health] ?? 'bg-slate-600'}`} />
  )
}

function HealthBadge({ health }) {
  return (
    <span className={`text-xs font-mono uppercase font-semibold ${HEALTH_TEXT[health] ?? 'text-slate-500'}`}>
      {health ?? 'unknown'}
    </span>
  )
}

// ── Collapsible section ───────────────────────────────────────────────────────

function Section({ title, health, sparkComponent, children, defaultOpen = true }) {
  const [open, setOpen] = useState(defaultOpen)

  return (
    <div className="border-b border-slate-800 last:border-0">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-2 px-3 py-2 hover:bg-slate-800 transition-colors"
      >
        <Dot health={health} />
        <span className="flex-1 text-left text-xs font-semibold text-slate-300 uppercase tracking-wide">
          {title}
        </span>
        <HealthBadge health={health} />
        <span className="text-slate-600 text-xs ml-1">{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div className="px-3 pb-2">
          {sparkComponent && (
            <div className="mb-2">
              <SparkLine component={sparkComponent} hours={24} buckets={24} />
            </div>
          )}
          {children}
        </div>
      )}
    </div>
  )
}

// ── Swarm section ─────────────────────────────────────────────────────────────

function SwarmSection({ data }) {
  if (!data) return null
  const nodes = data.nodes ?? []
  const services = data.services ?? []

  return (
    <Section title="Docker Swarm" health={data.health} sparkComponent="swarm">
      {data.message && (
        <p className="text-xs text-slate-400 mb-2 leading-tight">{data.message}</p>
      )}

      {nodes.length > 0 && (
        <div className="mb-3">
          <p className="text-xs text-slate-500 font-semibold uppercase mb-1">
            Nodes ({nodes.length})
          </p>
          <table className="w-full text-xs">
            <thead>
              <tr className="text-slate-600 text-left">
                <th className="pb-1 font-normal">Host</th>
                <th className="pb-1 font-normal">Role</th>
                <th className="pb-1 font-normal">State</th>
              </tr>
            </thead>
            <tbody>
              {nodes.map(n => (
                <tr
                  key={n.id}
                  className={`border-t border-slate-800 ${n.state !== 'ready' ? 'text-red-400' : 'text-slate-300'}`}
                >
                  <td className="py-0.5 truncate max-w-[80px]" title={n.hostname}>
                    {n.hostname}
                    {n.leader && <span className="text-yellow-400 ml-1" title="Leader">★</span>}
                  </td>
                  <td className="py-0.5">
                    <span className={`text-xs px-1 rounded ${n.role === 'manager' ? 'bg-blue-900 text-blue-300' : 'bg-slate-800 text-slate-400'}`}>
                      {n.role === 'manager' ? 'M' : 'W'}
                    </span>
                  </td>
                  <td className={`py-0.5 ${n.state === 'ready' ? 'text-green-400' : 'text-red-400'}`}>
                    {n.state}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {services.length > 0 && (
        <div>
          <p className="text-xs text-slate-500 font-semibold uppercase mb-1">
            Services ({services.length})
          </p>
          {services.map(s => {
            const ok = s.running_replicas === s.desired_replicas
            const name = s.name.replace(/^[\w-]+-stack_/, '')
            return (
              <div key={s.id} className="flex items-center justify-between py-0.5 border-t border-slate-800 first:border-0">
                <span
                  className="text-slate-300 truncate max-w-[120px] text-xs"
                  title={s.name}
                >
                  {name}
                </span>
                <span className={`text-xs font-mono shrink-0 ${ok ? 'text-green-400' : 'text-yellow-400'}`}>
                  {s.running_replicas}/{s.desired_replicas}
                </span>
              </div>
            )
          })}
        </div>
      )}

      {nodes.length === 0 && services.length === 0 && (
        <p className="text-xs text-slate-600 italic">No data yet</p>
      )}
    </Section>
  )
}

// ── Kafka section ─────────────────────────────────────────────────────────────

function KafkaSection({ data }) {
  if (!data) return null
  const brokers = data.brokers ?? []
  const lagData = data.consumer_lag ?? {}
  const lagThreshold = 1000

  return (
    <Section title="Kafka Cluster" health={data.health} sparkComponent="kafka_cluster">
      {data.message && (
        <p className="text-xs text-slate-400 mb-2 leading-tight">{data.message}</p>
      )}

      {brokers.length > 0 && (
        <div className="mb-3">
          <div className="flex items-center justify-between mb-1">
            <p className="text-xs text-slate-500 font-semibold uppercase">
              Brokers ({brokers.length}/{data.expected_brokers ?? brokers.length})
            </p>
            {data.under_replicated_partitions > 0 && (
              <span className="text-xs bg-red-900 text-red-300 px-1.5 rounded font-mono">
                {data.under_replicated_partitions} under-rep
              </span>
            )}
          </div>
          <table className="w-full text-xs">
            <thead>
              <tr className="text-slate-600 text-left">
                <th className="pb-1 font-normal">ID</th>
                <th className="pb-1 font-normal">Host</th>
                <th className="pb-1 font-normal">Status</th>
              </tr>
            </thead>
            <tbody>
              {brokers.map(b => (
                <tr key={b.id} className="border-t border-slate-800 text-slate-300">
                  <td className="py-0.5 font-mono">
                    {b.id}
                    {b.is_controller && (
                      <span className="text-yellow-400 ml-1" title="Controller">★</span>
                    )}
                  </td>
                  <td className="py-0.5 truncate max-w-[80px]" title={b.host}>
                    {b.host}
                  </td>
                  <td className="py-0.5 text-green-400">{b.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {Object.keys(lagData).length > 0 && (
        <div>
          <p className="text-xs text-slate-500 font-semibold uppercase mb-1">
            Consumer Lag
          </p>
          {Object.entries(lagData).map(([group, info]) => (
            <div
              key={group}
              className={`flex justify-between text-xs py-0.5 border-t border-slate-800 ${
                info.total_lag > lagThreshold ? 'text-red-400' : 'text-slate-300'
              }`}
            >
              <span className="truncate max-w-[120px]" title={group}>{group}</span>
              <span className="font-mono shrink-0">{info.total_lag}</span>
            </div>
          ))}
        </div>
      )}

      {brokers.length === 0 && (
        <p className="text-xs text-slate-600 italic">No data yet</p>
      )}
    </Section>
  )
}

// ── Elasticsearch section ─────────────────────────────────────────────────────

function ElasticSection({ data }) {
  if (!data) return null
  const shards = data.shards ?? {}
  const filebeatHealth = data.filebeat?.status === 'active' ? 'healthy' : data.filebeat?.status === 'stale' ? 'degraded' : 'unknown'
  const sectionHealth = worstHealth(data.health, filebeatHealth)

  return (
    <Section title="Elasticsearch" health={sectionHealth} sparkComponent="elasticsearch" defaultOpen={false}>
      {data.message && (
        <p className="text-xs text-slate-400 mb-2 leading-tight">{data.message}</p>
      )}
      {data.health !== 'unconfigured' && data.nodes > 0 && (
        <div className="text-xs space-y-0.5">
          <div className="flex justify-between">
            <span className="text-slate-500">Nodes</span>
            <span className="text-slate-300">{data.nodes}</span>
          </div>
          {shards.active !== undefined && (
            <>
              <div className="flex justify-between">
                <span className="text-slate-500">Active shards</span>
                <span className="text-slate-300">{shards.active}</span>
              </div>
              {shards.unassigned > 0 && (
                <div className="flex justify-between">
                  <span className="text-slate-500">Unassigned</span>
                  <span className="text-red-400">{shards.unassigned}</span>
                </div>
              )}
            </>
          )}
          <div className="flex justify-between">
            <span className="text-slate-500">Filebeat</span>
            <span className={data.filebeat?.status === 'active' ? 'text-green-400' : 'text-slate-500'}>
              {data.filebeat?.status ?? 'unknown'}
            </span>
          </div>
          <div className="mt-2 border-t border-slate-800 pt-2">
            <ElasticStatus />
          </div>
        </div>
      )}
    </Section>
  )
}

// ── Collectors status ─────────────────────────────────────────────────────────

function CollectorsSection({ collectors }) {
  if (!collectors || Object.keys(collectors).length === 0) return null
  const sectionHealth = worstHealth(Object.values(collectors).map(c => c.last_health ?? 'unknown'))

  return (
    <Section title="Collectors" health={sectionHealth} defaultOpen={false}>
      <div className="text-xs space-y-1">
        {Object.entries(collectors).map(([name, c]) => (
          <div key={name} className="flex items-center justify-between">
            <span className="text-slate-400 truncate">{name}</span>
            <div className="flex items-center gap-2 shrink-0">
              <span className={c.running ? 'text-green-400' : 'text-red-400'}>
                {c.running ? '●' : '○'}
              </span>
              <span className={`${HEALTH_TEXT[c.last_health] ?? 'text-slate-500'} font-mono`}>
                {c.last_health}
              </span>
            </div>
          </div>
        ))}
      </div>
    </Section>
  )
}

// ── Root component ────────────────────────────────────────────────────────────

export default function StatusPanel() {
  const [snap, setSnap]         = useState(null)
  const [ts, setTs]             = useState(null)
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState(null)

  const refresh = useCallback(() => {
    fetchStatus()
      .then(d => {
        setSnap(d)
        setTs(new Date().toLocaleTimeString())
        setError(null)
      })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, POLL_MS)
    return () => clearInterval(id)
  }, [refresh])

  return (
    <div className="flex flex-col h-full text-sm">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-slate-700 shrink-0">
        <span className="text-xs font-bold uppercase tracking-wider text-slate-400">
          Infrastructure
        </span>
        <button
          onClick={refresh}
          className="text-xs text-slate-500 hover:text-slate-300 transition-colors"
          title="Refresh"
        >
          ↺
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        {loading && !snap && (
          <p className="text-xs text-slate-500 animate-pulse p-3">Connecting to infrastructure…</p>
        )}
        {error && !snap && (
          <p className="text-xs text-red-400 p-3">{error}</p>
        )}
        {snap && (
          <>
            <SwarmSection data={snap.swarm} />
            <KafkaSection data={snap.kafka} />
            <ElasticSection data={snap.elasticsearch} />
            <CollectorsSection collectors={snap.collectors} />
          </>
        )}
      </div>

      {/* Footer timestamp */}
      {ts && (
        <div className="px-3 py-1 border-t border-slate-800 shrink-0">
          <p className="text-xs text-slate-700">Updated {ts}</p>
        </div>
      )}
    </div>
  )
}
