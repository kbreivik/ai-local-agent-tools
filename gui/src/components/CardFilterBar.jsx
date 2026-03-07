export const ALL_CARD_KEYS = [
  { key: 'swarm_nodes',    label: 'Swarm Nodes' },
  { key: 'kafka_brokers',  label: 'Kafka' },
  { key: 'swarm_services', label: 'Services' },
  { key: 'elasticsearch',  label: 'Elastic' },
  { key: 'muninndb',       label: 'MuninnDB' },
  { key: 'system_summary', label: 'System' },
]

export default function CardFilterBar({ activeFilters, onToggle, onToggleAll }) {
  const allActive = ALL_CARD_KEYS.every(c => activeFilters.includes(c.key))

  return (
    <div className="bg-white border-b border-gray-100 px-3 py-1.5 flex items-center gap-2 shrink-0 flex-wrap">
      <span className="text-xs text-gray-400 mr-1">Cards:</span>
      <button
        onClick={onToggleAll}
        className={`text-xs px-2 py-0.5 rounded-full border cursor-pointer transition-colors ${
          allActive
            ? 'bg-blue-100 text-blue-700 border-blue-300'
            : 'bg-white text-gray-500 border-gray-200 hover:border-gray-300'
        }`}
      >
        All
      </button>
      {ALL_CARD_KEYS.map(({ key, label }) => {
        const active = activeFilters.includes(key)
        return (
          <button
            key={key}
            onClick={() => onToggle(key)}
            className={`text-xs px-2 py-0.5 rounded-full border cursor-pointer transition-colors ${
              active
                ? 'bg-blue-100 text-blue-700 border-blue-300'
                : 'bg-white text-gray-500 border-gray-200 hover:border-gray-300'
            }`}
          >
            {label}
          </button>
        )
      })}
    </div>
  )
}
