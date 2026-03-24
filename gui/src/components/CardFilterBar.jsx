// Status overview cards (DashboardCards top section)
const STATUS_CARD_KEYS = [
  { key: 'swarm_nodes',      label: 'Nodes',    group: 'status' },
  { key: 'kafka_brokers',    label: 'Kafka',    group: 'status' },
  { key: 'swarm_services',   label: 'Services', group: 'status' },
  { key: 'elasticsearch',    label: 'Elastic',  group: 'status' },
  { key: 'muninndb',         label: 'MuninnDB', group: 'status' },
  { key: 'system_summary',   label: 'Agent',    group: 'status' },
]

// Infra detail sections (ServiceCards bottom section)
const INFRA_SECTION_KEYS = [
  { key: 'containers_local', label: 'Docker',   group: 'infra' },
  { key: 'containers_swarm', label: 'Swarm',    group: 'infra' },
  { key: 'vms',              label: 'VMs',      group: 'infra' },
  { key: 'external',         label: 'External', group: 'infra' },
]

export const ALL_CARD_KEYS = [...STATUS_CARD_KEYS, ...INFRA_SECTION_KEYS]

function Chip({ label, active, group, onClick }) {
  const activeStyle = group === 'infra'
    ? 'bg-violet-100 text-violet-700 border-violet-300'
    : 'bg-blue-100 text-blue-700 border-blue-300'
  return (
    <button
      onClick={onClick}
      className={`text-xs px-2 py-0.5 rounded-full border cursor-pointer transition-colors ${
        active ? activeStyle : 'bg-white text-gray-500 border-gray-200 hover:border-gray-300'
      }`}
    >
      {label}
    </button>
  )
}

export default function CardFilterBar({ activeFilters, onToggle, onToggleAll }) {
  const allActive = ALL_CARD_KEYS.every(c => activeFilters.includes(c.key))

  return (
    <div className="bg-white border-b border-gray-100 px-3 py-1.5 flex items-center gap-1.5 shrink-0 flex-wrap">
      <Chip label="All" active={allActive} group="status" onClick={onToggleAll} />
      <span className="h-3.5 w-px bg-gray-200 mx-0.5" />
      {STATUS_CARD_KEYS.map(({ key, label, group }) => (
        <Chip key={key} label={label} active={activeFilters.includes(key)} group={group} onClick={() => onToggle(key)} />
      ))}
      <span className="h-3.5 w-px bg-gray-200 mx-0.5" />
      <span className="text-[10px] text-gray-400">Infra:</span>
      {INFRA_SECTION_KEYS.map(({ key, label, group }) => (
        <Chip key={key} label={label} active={activeFilters.includes(key)} group={group} onClick={() => onToggle(key)} />
      ))}
    </div>
  )
}
