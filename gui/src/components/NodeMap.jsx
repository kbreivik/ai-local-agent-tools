/**
 * NodeMap — visual grid of Swarm nodes.
 * 3 managers top row, 3 workers bottom row (or all in a flex wrap).
 * Click node → side panel with full details.
 * Reads from /api/status/nodes + /api/status (for kafka broker placement).
 */
import { useEffect, useState, useCallback } from 'react'
import { fetchStatus } from '../api'
import VersionBadge from '../utils/VersionBadge'
import { useOptions } from '../context/OptionsContext'

const HEALTH_BG = {
  ready:   'bg-white border-green-400',
  down:    'bg-white border-red-400',
  unknown: 'bg-white border-gray-300',
}

const HEALTH_TEXT_CLS = {
  ready:   'text-green-600',
  down:    'text-red-600',
  unknown: 'text-gray-400',
}

function NodeCard({ node, isSelected, onClick, kafkaBroker, size = 'medium' }) {
  const stateKey = node.state === 'ready' ? 'ready' : node.state === 'down' ? 'down' : 'unknown'
  const border   = isSelected ? 'border-blue-500 ring-2 ring-blue-300 bg-blue-50' : HEALTH_BG[stateKey]
  const padding  = size === 'small' ? 'p-2' : size === 'large' ? 'p-4' : 'p-3'

  return (
    <button
      onClick={onClick}
      className={`relative flex flex-col items-center ${padding} rounded-lg border-2 text-xs transition-all hover:shadow-md ${border}`}
    >
      {/* Role badge */}
      <span className={`absolute top-1 right-1 text-xs px-1 rounded font-bold ${
        node.role === 'manager' ? 'bg-blue-100 text-blue-700' : 'bg-gray-100 text-gray-500'
      }`}>
        {node.role === 'manager' ? 'M' : 'W'}
      </span>

      {/* Leader star */}
      {node.leader && (
        <span className="absolute top-1 left-1 text-yellow-500 text-xs" title="Swarm Leader">★</span>
      )}

      {/* Health dot — 14px with ring */}
      <div className={`w-3.5 h-3.5 rounded-full mb-1.5 ring-2 ring-offset-2 ring-offset-white ${
        node.state === 'ready' ? 'bg-green-500 ring-green-300' :
        node.state === 'down'  ? 'bg-red-500  ring-red-300'   : 'bg-gray-300'
      }`} />

      {/* Hostname */}
      <span className="text-gray-800 font-semibold truncate max-w-full text-center" title={node.hostname}>
        {node.hostname.split('.')[0]}
      </span>

      {/* State */}
      <span className={`mt-0.5 ${HEALTH_TEXT_CLS[stateKey]}`}>{node.state}</span>

      {/* Kafka badge */}
      {kafkaBroker && (
        <span className="mt-1 text-xs bg-orange-50 text-orange-700 border border-orange-200 px-1.5 rounded font-mono">
          Kafka {kafkaBroker.id}
          {kafkaBroker.is_controller && ' ★'}
        </span>
      )}
    </button>
  )
}

function NodeDetail({ node, onClose, showVersionBadges }) {
  if (!node) return null
  return (
    <div className="mt-4 p-3 bg-gray-50 rounded-lg border border-gray-200 text-xs">
      <div className="flex justify-between items-center mb-3">
        <span className="text-gray-900 font-semibold">{node.hostname}</span>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-700">×</button>
      </div>
      <div className="divide-y divide-gray-100">
        {[
          ['ID', node.id],
          ['Role', node.role],
          ['State', node.state],
          ['Availability', node.availability],
          ['Address', node.addr],
          ['OS', node.os],
        ].map(([k, v]) => v && (
          <div key={k} className="flex justify-between gap-2 py-1">
            <span className="text-gray-500 shrink-0">{k}</span>
            <span className="text-gray-800 text-right truncate font-mono" title={v}>{v}</span>
          </div>
        ))}
        {node.engine_version && (
          <div className="flex justify-between gap-2 items-center py-1">
            <span className="text-gray-500 shrink-0">Engine</span>
            <div className="flex items-center gap-2">
              <span className="text-gray-800 font-mono">{node.engine_version}</span>
              {showVersionBadges && (
                <VersionBadge image="docker" currentTag={node.engine_version} />
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default function NodeMap({ compact = false }) {
  const [status,   setStatus]   = useState(null)
  const [selected, setSelected] = useState(null)
  const { nodeCardSize, showVersionBadges } = useOptions()

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
    return <p className="text-xs text-gray-400 animate-pulse p-3">Loading cluster map…</p>
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
        <p className="text-xs text-gray-400 italic">
          {status.swarm?.health === 'error'
            ? `Docker unreachable: ${status.swarm.message}`
            : 'No nodes yet — waiting for collector poll'}
        </p>
      ) : (
        <>
          {managers.length > 0 && (
            <div className="mb-3">
              {!compact && (
                <p className="text-xs text-gray-500 uppercase font-semibold mb-2">
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
                    size={nodeCardSize}
                  />
                ))}
              </div>
            </div>
          )}

          {workers.length > 0 && (
            <div>
              {!compact && (
                <p className="text-xs text-gray-500 uppercase font-semibold mb-2">
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
                    size={nodeCardSize}
                  />
                ))}
              </div>
            </div>
          )}

          {selectedNode && (
            <NodeDetail
              node={selectedNode}
              onClose={() => setSelected(null)}
              showVersionBadges={showVersionBadges}
            />
          )}
        </>
      )}
    </div>
  )
}
