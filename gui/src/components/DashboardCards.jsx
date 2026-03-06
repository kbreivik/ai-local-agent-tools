/**
 * DashboardCards — 6 infrastructure status cards for the Dashboard tab.
 * Light theme. Content-driven heights. Dots 14px with ring contrast.
 */
import { useState, useEffect, useCallback } from 'react'
import { fetchStatus, fetchMemoryHealth, fetchHealth } from '../api'
import { useOptions } from '../context/OptionsContext'
import VersionBadge from '../utils/VersionBadge'

// ── Health colour maps (light-theme palette) ──────────────────────────────────

// bg + ring classes for the large card-header dot
const DOT_CLS = {
  healthy:      'bg-green-500  ring-green-300',
  ok:           'bg-green-500  ring-green-300',
  green:        'bg-green-500  ring-green-300',
  active:       'bg-green-500  ring-green-300',
  degraded:     'bg-yellow-500 ring-yellow-300 animate-pulse',
  yellow:       'bg-yellow-500 ring-yellow-300 animate-pulse',
  critical:     'bg-red-500    ring-red-300    animate-pulse',
  red:          'bg-red-500    ring-red-300    animate-pulse',
  error:        'bg-red-500    ring-red-300    animate-pulse',
  unconfigured: 'bg-gray-300',
  unknown:      'bg-gray-300',
}

// text colour for the status label beside the dot / in summary lines
const STATUS_TEXT = {
  healthy:      'text-green-700',
  ok:           'text-green-700',
  green:        'text-green-700',
  active:       'text-green-700',
  degraded:     'text-yellow-700',
  yellow:       'text-yellow-700',
  critical:     'text-red-700',
  red:          'text-red-700',
  error:        'text-red-700',
  unconfigured: 'text-gray-400',
  unknown:      'text-gray-400',
}

// Large dot used in card headers (14 px + ring)
function Dot({ health }) {
  const cls     = DOT_CLS[health] ?? 'bg-gray-300'
  const hasRing = !['unconfigured', 'unknown', null, undefined].includes(health)
  return (
    <span
      className={`inline-block w-3.5 h-3.5 rounded-full shrink-0 ${cls}
        ${hasRing ? 'ring-2 ring-offset-2 ring-offset-white' : ''}`}
    />
  )
}

// Small dot used inside list rows
function RowDot({ ok, degraded }) {
  const cls = ok        ? 'bg-green-500'
            : degraded  ? 'bg-yellow-500'
            :             'bg-red-500'
  return <span className={`inline-block w-2 h-2 rounded-full shrink-0 ${cls}`} />
}

// ── Card shell ────────────────────────────────────────────────────────────────

function Card({ title, health, lastUpdated, onRefresh, loading, maxHeight, children }) {
  return (
    <div className="bg-white border border-gray-200 shadow-sm rounded-lg overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 bg-gray-50 border-b border-gray-200 shrink-0">
        <div className="flex items-center gap-2">
          <Dot health={health} />
          <span className="text-sm font-semibold text-gray-900">{title}</span>
        </div>
        <div className="flex items-center gap-2">
          {lastUpdated && (
            <span className="text-xs text-gray-400">{lastUpdated}</span>
          )}
          <button
            onClick={onRefresh}
            disabled={loading}
            className="text-gray-400 hover:text-gray-700 transition-colors text-sm disabled:opacity-40"
            title="Refresh"
          >
            ↺
          </button>
        </div>
      </div>

      {/* Body — content-driven height, scrolls if content overflows maxHeight */}
      <div
        className="px-3 py-2 overflow-y-auto"
        style={maxHeight ? { maxHeight: `${maxHeight}px` } : undefined}
      >
        {loading && !children ? (
          <p className="text-xs text-gray-400 animate-pulse py-2">Loading…</p>
        ) : children}
      </div>
    </div>
  )
}

// ── Card: Swarm Nodes ──────────────────────────────────────────────────────────

function SwarmNodesCard({ data, loading, lastUpdated, onRefresh, maxHeight }) {
  const nodes  = data?.nodes ?? []
  const health = data?.health ?? 'unknown'

  return (
    <Card title="Swarm Nodes" health={health} lastUpdated={lastUpdated}
          onRefresh={onRefresh} loading={loading} maxHeight={maxHeight}>
      {data ? (
        <>
          <div className="flex items-baseline gap-2 mb-2">
            <span className="text-2xl font-bold text-gray-900">{nodes.length}</span>
            <span className="text-sm text-gray-500">nodes</span>
            <span className={`ml-auto text-xs font-mono uppercase font-semibold ${STATUS_TEXT[health] ?? 'text-gray-400'}`}>
              {health}
            </span>
          </div>
          <div className="divide-y divide-gray-100">
            {nodes.map(n => (
              <div key={n.id} className="flex items-center justify-between py-1 text-xs">
                <div className="flex items-center gap-2">
                  <RowDot ok={n.state === 'ready'} />
                  <span className="text-gray-700 font-mono truncate max-w-[140px]" title={n.hostname}>
                    {n.hostname}
                  </span>
                  {n.leader && <span className="text-yellow-600" title="Swarm leader">★</span>}
                </div>
                <span className={`font-mono shrink-0 text-xs ${n.role === 'manager' ? 'text-blue-600' : 'text-gray-400'}`}>
                  {n.role === 'manager' ? 'MGR' : 'WRK'}
                </span>
              </div>
            ))}
          </div>
          {data.message && (
            <p className="text-xs text-gray-500 mt-1 leading-tight">{data.message}</p>
          )}
        </>
      ) : (
        <p className="text-xs text-gray-400 italic py-1">No data</p>
      )}
    </Card>
  )
}

// ── Card: Kafka Brokers ────────────────────────────────────────────────────────

function KafkaBrokersCard({ data, loading, lastUpdated, onRefresh, maxHeight }) {
  const brokers = data?.brokers ?? []
  const health  = data?.health ?? 'unknown'

  return (
    <Card title="Kafka Brokers" health={health} lastUpdated={lastUpdated}
          onRefresh={onRefresh} loading={loading} maxHeight={maxHeight}>
      {data ? (
        <>
          <div className="flex items-baseline gap-2 mb-2">
            <span className="text-2xl font-bold text-gray-900">{brokers.length}</span>
            <span className="text-sm text-gray-500">/ {data.expected_brokers ?? brokers.length} brokers</span>
            <span className={`ml-auto text-xs font-mono uppercase font-semibold ${STATUS_TEXT[health] ?? 'text-gray-400'}`}>
              {health}
            </span>
          </div>
          <div className="divide-y divide-gray-100">
            {brokers.map(b => (
              <div key={b.id} className="flex items-center justify-between py-1 text-xs">
                <div className="flex items-center gap-2">
                  <RowDot ok />
                  <span className="text-gray-700 font-mono">{b.host}</span>
                  {b.is_controller && <span className="text-yellow-600" title="Controller">★</span>}
                  {b.version && <VersionBadge image="apache/kafka" currentTag={b.version} />}
                </div>
                <span className="text-gray-400 font-mono shrink-0">id:{b.id}</span>
              </div>
            ))}
          </div>
          {data.under_replicated_partitions > 0 && (
            <div className="mt-1 text-xs bg-red-50 text-red-700 border border-red-200 px-2 py-1 rounded">
              {data.under_replicated_partitions} under-replicated partitions
            </div>
          )}
          {data.message && (
            <p className="text-xs text-gray-500 mt-1 leading-tight">{data.message}</p>
          )}
        </>
      ) : (
        <p className="text-xs text-gray-400 italic py-1">No data</p>
      )}
    </Card>
  )
}

// ── Card: Swarm Services ───────────────────────────────────────────────────────

function SwarmServicesCard({ data, loading, lastUpdated, onRefresh, maxHeight, showVersionBadges }) {
  const services  = data?.services ?? []
  const allOk     = services.length > 0 && services.every(s => s.running_replicas === s.desired_replicas)
  const cardHealth = allOk ? 'ok' : (services.length === 0 ? 'unknown' : 'degraded')

  return (
    <Card title="Swarm Services" health={cardHealth} lastUpdated={lastUpdated}
          onRefresh={onRefresh} loading={loading} maxHeight={maxHeight}>
      {data ? (
        <>
          <div className="flex items-baseline gap-2 mb-2">
            <span className="text-2xl font-bold text-gray-900">{services.length}</span>
            <span className="text-sm text-gray-500">services</span>
            <span className={`ml-auto text-xs font-mono font-semibold ${allOk ? 'text-green-700' : 'text-yellow-700'}`}>
              {allOk ? 'all healthy' : 'degraded'}
            </span>
          </div>
          <div className="divide-y divide-gray-100">
            {services.map(s => {
              const ok        = s.running_replicas === s.desired_replicas
              const name      = s.name.replace(/^[\w-]+-stack_/, '')
              const imageBase = s.image ? s.image.split('@')[0] : ''
              const colonIdx  = imageBase.lastIndexOf(':')
              const imgRepo   = colonIdx >= 0 ? imageBase.slice(0, colonIdx) : imageBase
              const imgTag    = colonIdx >= 0 ? imageBase.slice(colonIdx + 1) : ''

              return (
                <div key={s.id} className="py-1 text-xs">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <RowDot ok={ok} degraded={!ok} />
                      <span className="text-gray-700 font-mono truncate max-w-[150px]" title={s.name}>{name}</span>
                    </div>
                    <span className={`font-mono shrink-0 px-1.5 text-xs ${ok ? 'text-green-700' : 'text-yellow-700'}`}>
                      {s.running_replicas}/{s.desired_replicas}
                    </span>
                  </div>
                  {imageBase && (
                    <div className="flex items-center gap-2 ml-4 mt-0.5">
                      <span className="text-gray-400 font-mono truncate max-w-[160px]" title={imageBase}>
                        {imageBase.split('/').pop()}
                      </span>
                      {showVersionBadges && imgTag && (
                        <VersionBadge image={imgRepo} currentTag={imgTag} />
                      )}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </>
      ) : (
        <p className="text-xs text-gray-400 italic py-1">No data</p>
      )}
    </Card>
  )
}

// ── Card: Elasticsearch ────────────────────────────────────────────────────────

function ElasticsearchCard({ data, loading, lastUpdated, onRefresh, maxHeight }) {
  const health = data?.health ?? 'unknown'
  const shards = data?.shards ?? {}

  return (
    <Card title="Elasticsearch" health={health} lastUpdated={lastUpdated}
          onRefresh={onRefresh} loading={loading} maxHeight={maxHeight}>
      {data ? (
        health === 'unconfigured' ? (
          <p className="text-xs text-gray-400 italic py-1">Not configured</p>
        ) : (
          <>
            <div className="flex items-baseline gap-2 mb-2">
              <span className="text-2xl font-bold text-gray-900">{data.nodes ?? 0}</span>
              <span className="text-sm text-gray-500">nodes</span>
              <span className={`ml-auto text-xs font-mono uppercase font-semibold ${STATUS_TEXT[health] ?? 'text-gray-400'}`}>
                {health}
              </span>
            </div>
            <div className="divide-y divide-gray-100 text-xs">
              {shards.active !== undefined && (
                <div className="flex justify-between py-1">
                  <span className="text-gray-600">Active shards</span>
                  <span className="text-gray-800 font-mono">{shards.active}</span>
                </div>
              )}
              {shards.unassigned > 0 && (
                <div className="flex justify-between py-1">
                  <span className="text-gray-600">Unassigned</span>
                  <span className="text-red-600 font-mono">{shards.unassigned}</span>
                </div>
              )}
              <div className="flex justify-between py-1">
                <span className="text-gray-600">Filebeat</span>
                <span className={data.filebeat?.status === 'active' ? 'text-green-700' : 'text-gray-400'}>
                  {data.filebeat?.status ?? 'unknown'}
                </span>
              </div>
              {data.docs_per_min !== undefined && data.docs_per_min > 0 && (
                <div className="flex justify-between py-1">
                  <span className="text-gray-600">Ingest rate</span>
                  <span className="text-gray-800 font-mono">{data.docs_per_min}/min</span>
                </div>
              )}
            </div>
            {data.message && (
              <p className="text-xs text-gray-500 mt-1 leading-tight">{data.message}</p>
            )}
          </>
        )
      ) : (
        <p className="text-xs text-gray-400 italic py-1">No data</p>
      )}
    </Card>
  )
}

// ── Card: MuninnDB ─────────────────────────────────────────────────────────────

function MuninnDBCard({ data, loading, lastUpdated, onRefresh, maxHeight }) {
  // unknown/error → grey dot; ok → green dot
  const health = !data                      ? 'unknown'
               : data.status === 'ok'       ? 'ok'
               : (data.status ?? 'unknown')

  return (
    <Card title="MuninnDB Memory" health={health} lastUpdated={lastUpdated}
          onRefresh={onRefresh} loading={loading} maxHeight={maxHeight}>
      {data ? (
        <>
          <div className="flex items-baseline gap-2 mb-2">
            <span className="text-2xl font-bold text-gray-900">{data.total_engrams ?? 0}</span>
            <span className="text-sm text-gray-500">engrams</span>
            <span className={`ml-auto text-xs font-mono uppercase font-semibold ${STATUS_TEXT[health] ?? 'text-gray-400'}`}>
              {health === 'unknown' ? 'unconfigured' : health}
            </span>
          </div>
          <div className="divide-y divide-gray-100 text-xs">
            {data.version && (
              <div className="flex justify-between py-1">
                <span className="text-gray-600">Version</span>
                <span className="text-gray-800 font-mono">{data.version}</span>
              </div>
            )}
            {data.memory_mb !== undefined && (
              <div className="flex justify-between py-1">
                <span className="text-gray-600">Memory</span>
                <span className="text-gray-800 font-mono">{data.memory_mb} MB</span>
              </div>
            )}
          </div>
          {data.message && (
            <p className="text-xs text-gray-500 mt-1 leading-tight">{data.message}</p>
          )}
        </>
      ) : (
        <p className="text-xs text-gray-400 italic py-1">No data</p>
      )}
    </Card>
  )
}

// ── Card: System Summary ───────────────────────────────────────────────────────

function SystemSummaryCard({ statusData, apiHealth, loading, lastUpdated, onRefresh, maxHeight }) {
  const collectors      = statusData?.collectors ?? {}
  const apiOk           = apiHealth?.status === 'ok'
  const allCollectorsOk = Object.values(collectors).every(c => c.running)
  const overallHealth   = !apiHealth ? 'unknown' : (apiOk && allCollectorsOk ? 'ok' : 'degraded')

  return (
    <Card title="System Summary" health={overallHealth} lastUpdated={lastUpdated}
          onRefresh={onRefresh} loading={loading} maxHeight={maxHeight}>
      {apiHealth ? (
        <>
          <div className="divide-y divide-gray-100 text-xs mb-2">
            <div className="flex justify-between py-1">
              <span className="text-gray-600">API</span>
              <div className="flex items-center gap-1.5">
                <RowDot ok={apiOk} />
                <span className={`font-mono ${apiOk ? 'text-green-700' : 'text-red-700'}`}>
                  {apiHealth.status} v{apiHealth.version}
                </span>
              </div>
            </div>
            {apiHealth.ws_clients !== undefined && (
              <div className="flex justify-between py-1">
                <span className="text-gray-600">WS clients</span>
                <span className="text-gray-800 font-mono">{apiHealth.ws_clients}</span>
              </div>
            )}
          </div>
          {Object.keys(collectors).length > 0 && (
            <>
              <p className="text-xs text-gray-500 font-semibold uppercase mb-1">Collectors</p>
              <div className="divide-y divide-gray-100">
                {Object.entries(collectors).map(([name, c]) => (
                  <div key={name} className="flex items-center justify-between py-0.5 text-xs">
                    <span className="text-gray-700 truncate">{name}</span>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <RowDot ok={c.running} />
                      <span className={`font-mono text-xs ${STATUS_TEXT[c.last_health] ?? 'text-gray-400'}`}>
                        {c.last_health}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </>
      ) : (
        <p className="text-xs text-gray-400 italic py-1">Loading…</p>
      )}
    </Card>
  )
}

// ── Root ───────────────────────────────────────────────────────────────────────

export default function DashboardCards() {
  const { dashboardRefreshInterval, cardMaxHeight, showVersionBadges } = useOptions()

  const [snap,        setSnap]        = useState(null)
  const [memHealth,   setMemHealth]   = useState(null)
  const [apiHealth,   setApiHealth]   = useState(null)
  const [loading,     setLoading]     = useState(true)
  const [lastUpdated, setLastUpdated] = useState(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const [status, mem, api] = await Promise.allSettled([
        fetchStatus(),
        fetchMemoryHealth(),
        fetchHealth(),
      ])
      if (status.status === 'fulfilled') setSnap(status.value)
      if (mem.status    === 'fulfilled') setMemHealth(mem.value)
      if (api.status    === 'fulfilled') setApiHealth(api.value)
      setLastUpdated(new Date().toLocaleTimeString())
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, dashboardRefreshInterval)
    return () => clearInterval(id)
  }, [refresh, dashboardRefreshInterval])

  const cardProps = { loading: loading && !snap, lastUpdated, onRefresh: refresh, maxHeight: cardMaxHeight }

  return (
    <div className="grid grid-cols-2 gap-3 p-3 overflow-auto flex-1 min-h-0 items-start content-start">
      <SwarmNodesCard     {...cardProps} data={snap?.swarm} />
      <KafkaBrokersCard   {...cardProps} data={snap?.kafka} />
      <SwarmServicesCard  {...cardProps} data={snap?.swarm} showVersionBadges={showVersionBadges} />
      <ElasticsearchCard  {...cardProps} data={snap?.elasticsearch} />
      <MuninnDBCard       {...cardProps} data={memHealth} loading={loading && !memHealth} />
      <SystemSummaryCard  {...cardProps} statusData={snap} apiHealth={apiHealth}
                          loading={loading && !apiHealth} />
    </div>
  )
}
