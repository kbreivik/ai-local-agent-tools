/**
 * DashboardCards — 6 infrastructure status cards for the Dashboard tab.
 * Spacing is controlled entirely via inline styles to avoid Tailwind override issues.
 * Target card heights: Nodes~110, Brokers~120, Services~130, ES~90, Muninn~70, Summary~100
 */
import { useState, useEffect, useCallback } from 'react'
import { fetchStatus, fetchMemoryHealth, fetchHealth } from '../api'
import { useOptions } from '../context/OptionsContext'
import VersionBadge from '../utils/VersionBadge'

// ── Health colour maps ─────────────────────────────────────────────────────────

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

function Dot({ health }) {
  const cls     = DOT_CLS[health] ?? 'bg-gray-300'
  const hasRing = !['unconfigured', 'unknown', null, undefined].includes(health)
  return (
    <span className={`inline-block w-3.5 h-3.5 rounded-full shrink-0 ${cls} ${hasRing ? 'ring-2 ring-offset-2 ring-offset-white' : ''}`} />
  )
}

function RowDot({ ok, degraded }) {
  const cls = ok ? 'bg-green-500' : degraded ? 'bg-yellow-500' : 'bg-red-500'
  return <span className={`inline-block w-2 h-2 rounded-full shrink-0 ${cls}`} />
}

// ── Shared style constants ─────────────────────────────────────────────────────

const S = {
  header:      { padding: '6px 10px', lineHeight: 1 },
  headerTitle: { fontSize: '0.75rem', fontWeight: 600, color: '#111827', lineHeight: 1 },
  headerMeta:  { fontSize: '0.7rem',  color: '#9ca3af' },
  body:        { padding: '6px 10px' },
  countRow:    { display: 'flex', alignItems: 'baseline', gap: 6, marginBottom: 4 },
  bigNum:      { fontSize: '1rem', fontWeight: 700, color: '#111827', lineHeight: 1, margin: 0 },
  countLabel:  { fontSize: '0.75rem', color: '#6b7280' },
  countStatus: { marginLeft: 'auto', fontSize: '0.72rem', fontWeight: 600, fontFamily: 'monospace' },
  row:         { display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                 paddingTop: 2, paddingBottom: 2, borderTop: '1px solid #f9fafb',
                 fontSize: '0.75rem', lineHeight: 1.3 },
  rowInner:    { display: 'flex', alignItems: 'center', gap: 6 },
  rowMono:     { fontFamily: 'monospace', color: '#374151' },
  rowFaint:    { fontFamily: 'monospace', color: '#9ca3af', flexShrink: 0 },
  summary:     { fontSize: '0.7rem', color: '#6b7280', marginTop: 2,
                 paddingTop: 4, borderTop: '1px solid #f3f4f6', lineHeight: 1.3 },
  sectionLabel:{ fontSize: '0.68rem', fontWeight: 700, textTransform: 'uppercase',
                 color: '#9ca3af', letterSpacing: '0.04em', marginBottom: 2, marginTop: 2 },
  collectorRow:{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                 paddingTop: 2, paddingBottom: 2, fontSize: '0.72rem', lineHeight: 1.3,
                 borderTop: '1px solid #f9fafb' },
}

// ── Card shell ─────────────────────────────────────────────────────────────────

function Card({ title, health, lastUpdated, onRefresh, loading, maxHeight, children }) {
  return (
    <div className="bg-white border border-gray-200 shadow-sm rounded-lg overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between bg-gray-50 border-b border-gray-200 shrink-0" style={S.header}>
        <div className="flex items-center gap-2">
          <Dot health={health} />
          <span style={S.headerTitle}>{title}</span>
        </div>
        <div className="flex items-center gap-2">
          {lastUpdated && <span style={S.headerMeta}>{lastUpdated}</span>}
          <button
            onClick={onRefresh}
            disabled={loading}
            className="text-gray-400 hover:text-gray-700 transition-colors disabled:opacity-40"
            style={{ fontSize: '0.75rem' }}
            title="Refresh"
          >
            ↺
          </button>
        </div>
      </div>

      {/* Body */}
      <div
        className="overflow-y-auto"
        style={{ ...S.body, ...(maxHeight ? { maxHeight } : {}) }}
      >
        {loading && !children
          ? <p style={{ fontSize: '0.75rem', color: '#9ca3af', padding: '4px 0' }}>Loading…</p>
          : children}
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
          <div style={S.countRow}>
            <span style={S.bigNum}>{nodes.length}</span>
            <span style={S.countLabel}>nodes</span>
            <span className={STATUS_TEXT[health] ?? 'text-gray-400'} style={S.countStatus}>
              {health}
            </span>
          </div>
          <div>
            {nodes.map(n => (
              <div key={n.id} style={S.row}>
                <div style={S.rowInner}>
                  <RowDot ok={n.state === 'ready'} />
                  <span style={{ ...S.rowMono, maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={n.hostname}>
                    {n.hostname}
                  </span>
                  {n.leader && <span style={{ color: '#d97706', fontSize: '0.7rem' }} title="Swarm leader">★</span>}
                </div>
                <span style={{ fontFamily: 'monospace', fontSize: '0.72rem', flexShrink: 0, color: n.role === 'manager' ? '#2563eb' : '#9ca3af' }}>
                  {n.role === 'manager' ? 'MGR' : 'WRK'}
                </span>
              </div>
            ))}
          </div>
          {data.message && <p style={S.summary}>{data.message}</p>}
        </>
      ) : (
        <p style={{ fontSize: '0.75rem', color: '#9ca3af', fontStyle: 'italic', padding: '2px 0' }}>No data</p>
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
          <div style={S.countRow}>
            <span style={S.bigNum}>{brokers.length}</span>
            <span style={S.countLabel}>/ {data.expected_brokers ?? brokers.length} brokers</span>
            <span className={STATUS_TEXT[health] ?? 'text-gray-400'} style={S.countStatus}>
              {health}
            </span>
          </div>
          <div>
            {brokers.map(b => (
              <div key={b.id} style={S.row}>
                <div style={S.rowInner}>
                  <RowDot ok />
                  <span style={S.rowMono}>{b.host}</span>
                  {b.is_controller && <span style={{ color: '#d97706', fontSize: '0.7rem' }} title="Controller">★</span>}
                  {b.version && <VersionBadge image="apache/kafka" currentTag={b.version} />}
                </div>
                <span style={S.rowFaint}>id:{b.id}</span>
              </div>
            ))}
          </div>
          {data.under_replicated_partitions > 0 && (
            <div style={{ marginTop: 4, fontSize: '0.72rem', background: '#fef2f2', color: '#b91c1c', border: '1px solid #fecaca', padding: '2px 6px', borderRadius: 4 }}>
              {data.under_replicated_partitions} under-replicated partitions
            </div>
          )}
          {data.message && <p style={S.summary}>{data.message}</p>}
        </>
      ) : (
        <p style={{ fontSize: '0.75rem', color: '#9ca3af', fontStyle: 'italic', padding: '2px 0' }}>No data</p>
      )}
    </Card>
  )
}

// ── Card: Swarm Services ───────────────────────────────────────────────────────

function SwarmServicesCard({ data, loading, lastUpdated, onRefresh, maxHeight, showVersionBadges }) {
  const services   = data?.services ?? []
  const allOk      = services.length > 0 && services.every(s => s.running_replicas === s.desired_replicas)
  const cardHealth = allOk ? 'ok' : (services.length === 0 ? 'unknown' : 'degraded')

  return (
    <Card title="Swarm Services" health={cardHealth} lastUpdated={lastUpdated}
          onRefresh={onRefresh} loading={loading} maxHeight={maxHeight}>
      {data ? (
        <>
          <div style={S.countRow}>
            <span style={S.bigNum}>{services.length}</span>
            <span style={S.countLabel}>services</span>
            <span style={{ ...S.countStatus, color: allOk ? '#15803d' : '#a16207' }}>
              {allOk ? 'all healthy' : 'degraded'}
            </span>
          </div>
          <div>
            {services.map(s => {
              const ok        = s.running_replicas === s.desired_replicas
              const name      = s.name.replace(/^[\w-]+-stack_/, '')
              const imageBase = s.image ? s.image.split('@')[0] : ''
              const colonIdx  = imageBase.lastIndexOf(':')
              const imgRepo   = colonIdx >= 0 ? imageBase.slice(0, colonIdx) : imageBase
              const imgTag    = colonIdx >= 0 ? imageBase.slice(colonIdx + 1) : ''

              return (
                <div key={s.id} style={{ paddingTop: 2, paddingBottom: 2, borderTop: '1px solid #f9fafb' }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '0.75rem', lineHeight: 1.3 }}>
                    <div style={S.rowInner}>
                      <RowDot ok={ok} degraded={!ok} />
                      <span style={{ ...S.rowMono, maxWidth: 150, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={s.name}>{name}</span>
                    </div>
                    <span style={{ fontFamily: 'monospace', fontSize: '0.72rem', flexShrink: 0, color: ok ? '#15803d' : '#a16207' }}>
                      {s.running_replicas}/{s.desired_replicas}
                    </span>
                  </div>
                  {imageBase && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginLeft: 14, marginTop: 1 }}>
                      <span style={{ fontFamily: 'monospace', fontSize: '0.68rem', color: '#9ca3af', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 160 }} title={imageBase}>
                        {imageBase.split('/').pop()}
                      </span>
                      {showVersionBadges && imgTag && <VersionBadge image={imgRepo} currentTag={imgTag} />}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </>
      ) : (
        <p style={{ fontSize: '0.75rem', color: '#9ca3af', fontStyle: 'italic', padding: '2px 0' }}>No data</p>
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
          <p style={{ fontSize: '0.75rem', color: '#9ca3af', fontStyle: 'italic', padding: '2px 0' }}>Not configured</p>
        ) : (
          <>
            <div style={S.countRow}>
              <span style={S.bigNum}>{data.nodes ?? 0}</span>
              <span style={S.countLabel}>nodes</span>
              <span className={STATUS_TEXT[health] ?? 'text-gray-400'} style={S.countStatus}>
                {health}
              </span>
            </div>
            <div>
              {shards.active !== undefined && (
                <div style={S.row}>
                  <span style={{ color: '#4b5563', fontSize: '0.75rem' }}>Active shards</span>
                  <span style={S.rowMono}>{shards.active}</span>
                </div>
              )}
              {shards.unassigned > 0 && (
                <div style={S.row}>
                  <span style={{ color: '#4b5563', fontSize: '0.75rem' }}>Unassigned</span>
                  <span style={{ ...S.rowMono, color: '#dc2626' }}>{shards.unassigned}</span>
                </div>
              )}
              <div style={S.row}>
                <span style={{ color: '#4b5563', fontSize: '0.75rem' }}>Filebeat</span>
                <span style={{ fontSize: '0.75rem', color: data.filebeat?.status === 'active' ? '#15803d' : '#9ca3af' }}>
                  {data.filebeat?.status ?? 'unknown'}
                </span>
              </div>
              {data.docs_per_min !== undefined && data.docs_per_min > 0 && (
                <div style={S.row}>
                  <span style={{ color: '#4b5563', fontSize: '0.75rem' }}>Ingest rate</span>
                  <span style={S.rowMono}>{data.docs_per_min}/min</span>
                </div>
              )}
            </div>
            {data.message && <p style={S.summary}>{data.message}</p>}
          </>
        )
      ) : (
        <p style={{ fontSize: '0.75rem', color: '#9ca3af', fontStyle: 'italic', padding: '2px 0' }}>No data</p>
      )}
    </Card>
  )
}

// ── Card: MuninnDB ─────────────────────────────────────────────────────────────

function MuninnDBCard({ data, loading, lastUpdated, onRefresh, maxHeight }) {
  const health = !data                      ? 'unknown'
               : data.status === 'ok'       ? 'ok'
               : (data.status ?? 'unknown')

  return (
    <Card title="MuninnDB Memory" health={health} lastUpdated={lastUpdated}
          onRefresh={onRefresh} loading={loading} maxHeight={maxHeight}>
      {data ? (
        <>
          <div style={S.countRow}>
            <span style={S.bigNum}>{data.total_engrams ?? 0}</span>
            <span style={S.countLabel}>engrams</span>
            <span className={STATUS_TEXT[health] ?? 'text-gray-400'} style={S.countStatus}>
              {health === 'unknown' ? 'unconfigured' : health}
            </span>
          </div>
          <div>
            {data.version && (
              <div style={S.row}>
                <span style={{ color: '#4b5563', fontSize: '0.75rem' }}>Version</span>
                <span style={S.rowMono}>{data.version}</span>
              </div>
            )}
            {data.memory_mb !== undefined && (
              <div style={S.row}>
                <span style={{ color: '#4b5563', fontSize: '0.75rem' }}>Memory</span>
                <span style={S.rowMono}>{data.memory_mb} MB</span>
              </div>
            )}
          </div>
          {data.message && <p style={S.summary}>{data.message}</p>}
        </>
      ) : (
        <p style={{ fontSize: '0.75rem', color: '#9ca3af', fontStyle: 'italic', padding: '2px 0' }}>No data</p>
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
          <div>
            <div style={S.row}>
              <span style={{ color: '#4b5563', fontSize: '0.75rem' }}>API</span>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <RowDot ok={apiOk} />
                <span style={{ fontFamily: 'monospace', fontSize: '0.72rem', color: apiOk ? '#15803d' : '#dc2626' }}>
                  {apiHealth.status} v{apiHealth.version}
                </span>
              </div>
            </div>
            {apiHealth.ws_clients !== undefined && (
              <div style={S.row}>
                <span style={{ color: '#4b5563', fontSize: '0.75rem' }}>WS clients</span>
                <span style={S.rowMono}>{apiHealth.ws_clients}</span>
              </div>
            )}
          </div>
          {Object.keys(collectors).length > 0 && (
            <>
              <p style={S.sectionLabel}>Collectors</p>
              <div>
                {Object.entries(collectors).map(([name, c]) => (
                  <div key={name} style={S.collectorRow}>
                    <span style={{ color: '#374151', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{name}</span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
                      <RowDot ok={c.running} />
                      <span className={STATUS_TEXT[c.last_health] ?? 'text-gray-400'} style={{ fontFamily: 'monospace', fontSize: '0.72rem' }}>
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
        <p style={{ fontSize: '0.75rem', color: '#9ca3af', fontStyle: 'italic', padding: '2px 0' }}>Loading…</p>
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
    <div
      className="overflow-auto flex-1 min-h-0 items-start content-start w-full"
      style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8, padding: 8 }}
    >
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
