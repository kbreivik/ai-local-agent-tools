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
      {
        label: 'Why is Kafka degraded?',
        task: 'Kafka_cluster is showing DEGRADED status. Check BOTH kafka_broker_status AND kafka_consumer_lag. Determine whether the cause is: (a) high consumer lag from logstash, (b) a missing broker, or (c) under-replicated partitions. Give me the root cause and specific fix steps.',
      },
      { label: 'Consumer lag check', task: 'Check Kafka consumer lag: call kafka_consumer_lag and report which consumer groups are behind, by how much, and whether the lag is growing or shrinking. Check if logstash is running and healthy.' },
      { label: 'Kafka broker status', task: 'Check Kafka broker status — how many brokers are online, which partitions are under-replicated, report ISR status for topic hp1-logs.' },
      { label: 'Kafka topic health', task: 'Check Kafka topic health for all topics: partition count, replication factor, ISR status. Flag any under-replicated partitions.' },
      { label: 'Recover kafka_broker-3', task: 'Recover kafka_broker-3: check swarm node status, reboot worker-03 via Proxmox if it is Down, then verify broker rejoins the cluster.' },
      { label: 'Kafka → Elastic pipeline', task: 'Check the full Kafka to Elasticsearch log pipeline: broker health, consumer lag, logstash service status and logs, and whether hp1-logs messages are being indexed in Elasticsearch.' },
    ],
  },
  {
    group: 'SWARM',
    color: 'var(--cyan)',
    items: [
      { label: 'Swarm node status', task: 'Check Docker Swarm node status — list all nodes, show which are Down or Drain, report any services with failed tasks.' },
      { label: 'Service health overview', task: 'List all Swarm services, show replicas running vs desired, flag any that are not converged. Show placement for any failing services.' },
      { label: 'Force-update logstash', task: 'Force-update the logstash_logstash Swarm service to recover from any stale network or scheduling issues.' },
      { label: 'Force-update kafka_broker-3', task: 'Force-update the kafka_broker-3 Swarm service to clear any network or scheduling issues on worker-03.' },
      { label: 'Swarm cluster health', task: 'Give me a full Swarm cluster health report: nodes, managers, workers, services, tasks. Flag anything not in desired state.' },
    ],
  },
  {
    group: 'INFRASTRUCTURE',
    color: 'var(--green)',
    items: [
      { label: 'Disk usage — all hosts', task: 'Check disk usage on all registered VM hosts. Flag any filesystem above 80% used. Show top directories consuming space on any full disks.' },
      { label: 'Memory and load — all hosts', task: 'Check memory usage and load average on all registered VM hosts. Flag any hosts with free memory below 500MB or load above 4.' },
      { label: 'Prune Docker images', task: 'Prune unused Docker images on all VM hosts. Show before/after disk reclaimed.' },
      { label: 'Journalctl vacuum', task: 'Check journal disk usage on all VM hosts and vacuum journals older than 7 days if they exceed 500MB.' },
      { label: 'VM host overview', task: 'Give me a health summary of all registered VM hosts: disk, memory, load, uptime. Flag anything that needs attention.' },
    ],
  },
  {
    group: 'ELASTIC',
    color: 'var(--amber)',
    items: [
      { label: 'Elasticsearch health', task: 'Check Elasticsearch cluster health — nodes, shards, indices. Report any red or yellow indices and unassigned shards.' },
      { label: 'Recent error logs', task: 'Search Elasticsearch for error-level log entries in the last 1 hour across all services. Summarise the top 5 error patterns with counts.' },
      { label: 'Logstash → ES errors', task: 'Check if Logstash is successfully writing to Elasticsearch. Look for bulk request errors, connection failures, or 429 responses in logstash logs and ES error logs.' },
      { label: 'Index stats', task: 'Show Elasticsearch index stats: document counts, index sizes, shard health. Flag any indices with high error rates or unusually low doc counts.' },
    ],
  },
  {
    group: 'PROXMOX',
    color: '#a855f7',
    items: [
      { label: 'VM health overview', task: 'List all Proxmox VMs and LXC containers, show running vs stopped, CPU and memory usage. Flag any that are stopped unexpectedly or consuming excessive resources.' },
      { label: 'Reboot worker-03', task: 'Reboot the worker-03 VM via Proxmox to recover the downed Swarm worker node. Verify it comes back online and the kafka_broker-3 service reschedules.' },
      { label: 'Reboot Proxmox VM', task: 'Reboot the Proxmox VM named `{target}`.\n\nRequired sequence — do NOT skip or reorder:\n\n1. Call `infra_lookup` with `{target}` to confirm the VM exists and capture its node placement and entity_id. If it doesn\'t exist, stop and report.\n2. Call `swarm_node_status` (if `{target}` looks like a Swarm node label) to record its pre-reboot state. If it\'s not a Swarm member, skip this.\n3. Call `plan_action` with:\n      summary: "Reboot VM {target} via Proxmox API"\n      steps:\n        - "Confirm target: {target} exists"\n        - "(If Swarm worker) drain optionally — skipped unless user asks"\n        - "Send Proxmox reboot command"\n        - "Wait up to 180s for SSH on {target}"\n        - "Report final status"\n      risk_level: "medium"\n      reversible: true\n4. After plan approval: call `proxmox_vm_power` with vm_label={target}, action="reboot".\n5. Poll `vm_exec` with a harmless command ("uptime") against {target} every 10s until it returns successfully or 180s elapses.\n6. When SSH returns, call `swarm_node_status` again (if applicable) to confirm the node re-joined the cluster with status=Ready.\n7. Summarise: whether reboot succeeded, wall-clock time from reboot command to SSH return, any Swarm tasks that rescheduled, any kafka broker that came back.\n\nDo not use vm_exec for anything except the post-reboot liveness poll. Do not touch other VMs.' },
      { label: 'VM resource usage', task: 'Check CPU, memory, and disk usage for all Proxmox VMs. Identify any VMs running above 80% resource utilization.' },
      { label: 'LXC container status', task: 'List all LXC containers in Proxmox, show their status, resource allocation, and uptime. Flag any that are stopped or have problems.' },
    ],
  },
  {
    group: 'NETWORK',
    color: '#22d3ee',
    items: [
      { label: 'UniFi device status', task: 'Check UniFi network device status — list all APs and switches, show which are connected vs disconnected, report client counts and any devices with issues.' },
      { label: 'FortiGate interface status', task: 'Check FortiGate interface status — list all interfaces, show which are up/down, report any errors or unusual traffic on key interfaces.' },
      { label: 'Network connectivity check', task: 'Check overall network health: FortiGate interface status, UniFi device connectivity, and whether all registered services are reachable.' },
      { label: 'UniFi client count', task: 'How many wireless clients are currently connected to UniFi? Break down by AP if possible. Flag any APs that are offline.' },
    ],
  },
  {
    group: 'STORAGE',
    color: '#818cf8',
    items: [
      { label: 'PBS datastore health', task: 'Check Proxmox Backup Server datastore health — used space, available space, GC status, recent backup task success rate. Flag any datastores above 85% full.' },
      { label: 'TrueNAS pool status', task: 'Check TrueNAS pool status — health, used/free space, SMART status, any scrub errors. Flag any pools with degraded vdevs or high usage.' },
      { label: 'Backup status check', task: 'Check recent backup job status across PBS. How many backups completed successfully in the last 24 hours? Any failures or warnings?' },
      { label: 'Storage capacity overview', task: 'Give me a storage capacity overview: PBS datastore usage, TrueNAS pool usage, and Docker volume usage on all VM hosts. Flag anything above 80%.' },
    ],
  },
  {
    group: 'SECURITY',
    color: 'var(--red)',
    items: [
      { label: 'SSH access audit', task: 'Check which VM hosts have verified SSH access via credential profiles. List any hosts that have not been successfully reached in the last 7 days.' },
      { label: 'Recent auth failures', task: 'Search Elasticsearch for authentication failure log entries in the last 24 hours. Summarise by host and source IP.' },
      { label: 'Firewall interface check', task: 'Check FortiGate for any interface errors, high error rates, or unusual traffic patterns in the last hour. Report any interfaces with more than 100 errors.' },
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
