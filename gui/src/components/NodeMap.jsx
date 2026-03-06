/**
 * NodeMap — visual grid of Swarm nodes.
 * 3 managers top row, 3 workers bottom row (or all in a flex wrap).
 * Click node → side panel with full details.
 * Reads from /api/status/nodes + /api/status (for kafka broker placement).
 */
import { useEffect, useState, useCallback } from 'react'
import { fetchStatus } from '../api'

const HEALTH_BG = {
  ready:   'bg-green-900 border-green-700',
  down:    'bg-red-900 border-red-700',
  unknown: 'bg-slate-800 border-slate-700',
}

const HEALTH_GLOW = {
  ready:   'text-green-400',
  down:    'text-red-400',
  unknown: 'text-slate-500',
}

function NodeCard({ node, isSelected, onClick, kafkaBroker }) {
  const stateKey = node.state === 'ready' ? 'ready' : node.state === 'down' ? 'down' : 'unknown'
  const border = isSelected ? 'border-blue-500 ring-1 ring-blue-500' : HEALTH_BG[stateKey]

  return (
    <button
      onClick={onClick}
      className={`relative flex flex-col items-center p-3 rounded-lg border text-xs transition-all hover:opacity-90 ${border} ${isSelected ? '' : HEALTH_BG[stateKey]}`}
    >
      {/* Role badge */}
      <span className={`absolute top-1 right-1 text-xs px-1 rounded font-bold ${
        node.role === 'manager' ? 'bg-blue-800 text-blue-300' : 'bg-slate-700 text-slate-400'
      }`}>
        {node.role === 'manager' ? 'M' : 'W'}
      </span>

      {/* Leader star */}
      {node.leader && (
        <span className="absolute top-1 left-1 text-yellow-400 text-xs" title="Swarm Leader">★</span>
      )}

      {/* Health dot */}
      <div className={`w-3 h-3 rounded-full mb-1.5 ${
        node.state === 'ready' ? 'bg-green-500' :
        node.state === 'down' ? 'bg-red-500' : 'bg-slate-500'
      }`} />

      {/* Hostname */}
      <span className="text-slate-200 font-semibold truncate max-w-full text-center" title={node.hostname}>
        {node.hostname.split('.')[0]}
      </span>

      {/* State */}
      <span className={`mt-0.5 ${HEALTH_GLOW[stateKey]}`}>{node.state}</span>

      {/* Kafka badge */}
      {kafkaBroker && (
        <span className="mt-1 text-xs bg-orange-900 text-orange-300 px-1.5 rounded font-mono">
          Kafka {kafkaBroker.id}
          {kafkaBroker.is_controller && ' ★'}
        </span>
      )}
    </button>
  )
}

function NodeDetail({ node, onClose }) {
  if (!node) return null
  return (
    <div className="mt-4 p-3 bg-slate-900 rounded-lg border border-slate-700 text-xs">
      <div className="flex justify-between items-center mb-3">
        <span className="text-slate-200 font-semibold">{node.hostname}</span>
        <button onClick={onClose} className="text-slate-500 hover:text-slate-300">×</button>
      </div>
      <div className="space-y-1.5">
        {[
          ['ID', node.id],
          ['Role', node.role],
          ['State', node.state],
          ['Availability', node.availability],
          ['Address', node.addr],
          ['OS', node.os],
          ['Engine', node.engine_version],
        ].map(([k, v]) => v && (
          <div key={k} className="flex justify-between gap-2">
            <span className="text-slate-500 shrink-0">{k}</span>
            <span className="text-slate-300 text-right truncate font-mono" title={v}>{v}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function NodeMap({ compact = false }) {
  const [status, setStatus] = useState(null)
  const [selected, setSelected] = useState(null)

  const refresh = useCallback(() => {
    fetchStatus()
      .then(setStatus)
      .catch(() => {})
  }, [])

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, 15_000)
    return () => clearInterval(id)
  }, [refresh])

  if (!status) {
    return <p className="text-xs text-slate-500 animate-pulse p-3">Loading cluster map…</p>
  }

  const nodes = status.swarm?.nodes ?? []
  const brokers = status.kafka?.brokers ?? []

  // Build hostname→broker lookup (heuristic: broker host contains node hostname)
  const brokerByNode = {}
  for (const broker of brokers) {
    for (const node of nodes) {
      const shortHost = node.hostname.split('.')[0].toLowerCase()
      if (broker.host.toLowerCase().includes(shortHost)) {
        brokerByNode[node.id] = broker
      }
    }
  }

  const managers = nodes.filter(n => n.role === 'manager')
  const workers  = nodes.filter(n => n.role !== 'manager')

  const selectedNode = nodes.find(n => n.id === selected)

  const cardCols = compact ? 'grid-cols-3' : 'grid-cols-3'

  return (
    <div className={compact ? 'px-2 py-2' : 'p-4'}>
      {nodes.length === 0 ? (
        <p className="text-xs text-slate-500 italic">
          {status.swarm?.health === 'error'
            ? `Docker unreachable: ${status.swarm.message}`
            : 'No nodes yet — waiting for collector poll'}
        </p>
      ) : (
        <>
          {managers.length > 0 && (
            <div className="mb-3">
              {!compact && (
                <p className="text-xs text-slate-500 uppercase font-semibold mb-2">
                  Managers ({managers.length})
                </p>
              )}
              <div className={`grid ${cardCols} gap-2`}>
                {managers.map(n => (
                  <NodeCard
                    key={n.id}
                    node={n}
                    isSelected={selected === n.id}
                    onClick={() => setSelected(selected === n.id ? null : n.id)}
                    kafkaBroker={brokerByNode[n.id]}
                  />
                ))}
              </div>
            </div>
          )}

          {workers.length > 0 && (
            <div>
              {!compact && (
                <p className="text-xs text-slate-500 uppercase font-semibold mb-2">
                  Workers ({workers.length})
                </p>
              )}
              <div className={`grid ${cardCols} gap-2`}>
                {workers.map(n => (
                  <NodeCard
                    key={n.id}
                    node={n}
                    isSelected={selected === n.id}
                    onClick={() => setSelected(selected === n.id ? null : n.id)}
                    kafkaBroker={brokerByNode[n.id]}
                  />
                ))}
              </div>
            </div>
          )}

          {selectedNode && (
            <NodeDetail
              node={selectedNode}
              onClose={() => setSelected(null)}
            />
          )}
        </>
      )}
    </div>
  )
}
