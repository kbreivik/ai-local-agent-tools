/**
 * TaskTemplates — collapsible one-click task shortcuts for the agent.
 * Grouped by domain. Clicking fills the task textarea via setTask().
 */
import { useState } from 'react'
import { useTask } from '../context/TaskContext'

const TEMPLATES = [
  {
    group: 'KAFKA',
    color: 'var(--accent)',
    items: [
      { label: 'Why is Kafka degraded?', task: 'Find out why the kafka_cluster is degraded and give me the root cause and fix steps' },
      { label: 'Kafka topic health', task: 'Check Kafka topic health and consumer lag for all topics on the hp1-logs cluster' },
      { label: 'Kafka broker status', task: 'Check Kafka broker status — how many brokers are online, which partitions are under-replicated' },
      { label: 'Recover kafka_broker-3', task: 'Recover kafka_broker-3: check swarm node status, reboot worker-03 via Proxmox if it is Down, then verify broker rejoins' },
    ],
  },
  {
    group: 'SWARM',
    color: 'var(--cyan)',
    items: [
      { label: 'Swarm node status', task: 'Check Docker Swarm node status — list all nodes, show which are Down or Drain, report any services with failed tasks' },
      { label: 'Force-update a service', task: 'Force-update the kafka_broker-3 Swarm service to clear any network/scheduling issues' },
      { label: 'Swarm service health', task: 'List all Swarm services, show replicas running vs desired, flag any that are not converged' },
    ],
  },
  {
    group: 'INFRASTRUCTURE',
    color: 'var(--green)',
    items: [
      { label: 'Disk usage — all hosts', task: 'Check disk usage on all registered VM hosts. Flag any filesystem above 80% used. Show top directories consuming space on any full disks.' },
      { label: 'Prune Docker images', task: 'Prune unused Docker images on all VM hosts. Show before/after disk reclaimed.' },
      { label: 'Memory and load — all hosts', task: 'Check memory usage and load average on all registered VM hosts. Flag any hosts with free memory below 500MB or load above 4.' },
      { label: 'Journalctl vacuum', task: 'Check journal disk usage on all VM hosts and vacuum journals older than 7 days if they exceed 500MB.' },
    ],
  },
  {
    group: 'ELASTIC / LOGS',
    color: 'var(--amber)',
    items: [
      { label: 'Elasticsearch health', task: 'Check Elasticsearch cluster health — nodes, shards, indices. Report any red or yellow indices.' },
      { label: 'Recent error logs', task: 'Search Elasticsearch for error-level log entries in the last 1 hour across all services. Summarise the top 5 error patterns.' },
      { label: 'Kafka → Elastic pipeline', task: 'Check the Kafka to Elasticsearch log pipeline: broker health, Filebeat/Logstash connectivity, and whether hp1-logs messages are being indexed.' },
    ],
  },
  {
    group: 'PROXMOX',
    color: '#a855f7',
    items: [
      { label: 'VM health overview', task: 'List all Proxmox VMs and LXC containers, show running vs stopped, flag any that are stopped unexpectedly.' },
      { label: 'Reboot worker-03', task: 'Reboot the worker-03 VM via Proxmox to recover the downed Swarm worker node.' },
    ],
  },
]

export default function TaskTemplates() {
  const { setTask } = useTask()
  const [open, setOpen] = useState(false)
  const [activeGroup, setActiveGroup] = useState(null)

  const pick = (task) => {
    setTask(task)
    setOpen(false)
    setActiveGroup(null)
  }

  return (
    <div style={{ borderBottom: '1px solid var(--border)', flexShrink: 0 }}>
      {/* Header row */}
      <button
        onClick={() => { setOpen(o => !o); setActiveGroup(null) }}
        style={{
          width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '5px 12px', background: 'none', border: 'none', cursor: 'pointer',
          fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: '0.08em',
          color: open ? 'var(--text-2)' : 'var(--text-3)',
        }}
      >
        <span>TEMPLATES</span>
        <span style={{ fontSize: 8, color: 'var(--text-3)' }}>{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div style={{ padding: '0 8px 8px' }}>
          {/* Group tabs */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 6 }}>
            {TEMPLATES.map(g => (
              <button
                key={g.group}
                onClick={() => setActiveGroup(activeGroup === g.group ? null : g.group)}
                style={{
                  padding: '2px 7px', fontSize: 8, fontFamily: 'var(--font-mono)',
                  letterSpacing: '0.06em', border: '1px solid',
                  borderColor: activeGroup === g.group ? g.color : 'var(--border)',
                  background: activeGroup === g.group ? `${g.color}18` : 'transparent',
                  color: activeGroup === g.group ? g.color : 'var(--text-3)',
                  borderRadius: 2, cursor: 'pointer',
                }}
              >
                {g.group}
              </button>
            ))}
          </div>

          {/* Template items for active group */}
          {activeGroup && (() => {
            const group = TEMPLATES.find(g => g.group === activeGroup)
            if (!group) return null
            return (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                {group.items.map(item => (
                  <button
                    key={item.label}
                    onClick={() => pick(item.task)}
                    title={item.task}
                    style={{
                      textAlign: 'left', padding: '4px 8px', fontSize: 9,
                      fontFamily: 'var(--font-mono)', letterSpacing: '0.03em',
                      background: 'var(--bg-2)', border: `1px solid var(--border)`,
                      borderLeft: `2px solid ${group.color}`,
                      borderRadius: 2, cursor: 'pointer', color: 'var(--text-2)',
                      transition: 'background 0.12s',
                    }}
                    onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-3)'}
                    onMouseLeave={e => e.currentTarget.style.background = 'var(--bg-2)'}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            )
          })()}

          {/* Show all groups if none selected */}
          {!activeGroup && (
            <div style={{ fontSize: 8, color: 'var(--text-3)', fontFamily: 'var(--font-mono)', padding: '2px 0' }}>
              Select a group above to see templates
            </div>
          )}
        </div>
      )}
    </div>
  )
}
