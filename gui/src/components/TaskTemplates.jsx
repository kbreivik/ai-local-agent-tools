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
      { label: 'Diagnose Kafka Under-Replication', task: '═══ FIXED INVESTIGATION CHAIN — DO NOT SKIP STEPS ═══\n\nSTEP 1: kafka_topic_inspect() (or pass topic=<topic> for focused).\n  From the result, identify partitions where isr != replicas.\n  If summary.under_replicated_partitions == 0: STOP and report HEALTHY.\n\nSTEP 2: For each broker id in replicas\\isr (missing brokers), call\n  service_placement(\'kafka_broker-\' + str(broker_id)).\n  Record which Swarm node that broker is (or isn\'t) placed on.\n\nSTEP 3: For each node identified in step 2, call swarm_node_status and\n  report its Availability and State.\n\nSTEP 4: If any node is Down, optionally call proxmox_vm_power with\n  action=\'status\' (NOT reboot) on the matching Proxmox VM to see if it\'s\n  running at the hypervisor level.\n\n═══ STRICT OUTPUT SHAPE ═══\nMISSING_BROKERS: [id1, id2]\nIMPACT: <partition count> partitions on <topic(s)> under-replicated\nROOT_CAUSE: <one sentence — node X down, broker Y stuck unscheduled, etc.>\nRESPONSIBLE_NODE: <node-name> (availability=<a>, state=<s>)\nRECOMMENDED_FIX: <one sentence — e.g. reboot VM worker-03, then kafka_broker-3 will self-schedule>' },
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
      { label: 'Drain Swarm node', task: 'Drain Swarm node {node_name} cleanly.\n\nSTEP 1: Call swarm_node_status to confirm the node exists and is currently Active. If it\'s already Drain or Down, report and stop.\nSTEP 2: Propose a plan_action with these commands (must run from a manager node): `docker node update --availability drain {node_name}`.\nSTEP 3: After plan is approved and executed, poll `docker node ps {node_name} --filter desired-state=running` every 10 seconds up to {timeout_s} seconds until the running task count is 0.\nSTEP 4: Return a structured summary:\n  NODE: <name>\n  AVAILABILITY: drain\n  TASKS_SHED: <count>\n  ELAPSED_S: <seconds>\n  STATUS: DRAINED | TIMEOUT' },
      {
        label: 'Docker overlay network health',
        task:
          'Check Docker Swarm overlay network health. From any manager node (use swarm_node_status to identify), run vm_exec `docker network ls --filter scope=swarm` and `docker network inspect ingress`. Verify ingress network is healthy: all 3 managers + 3 workers attached, no IP pool exhaustion, no stale peers. Then from one worker, test ingress reachability by running `docker network inspect <overlay_name>` for each attached swarm service. Flag any overlay network with peer_count not equal to node count, or any orphaned networks with no services attached. Read-only — do NOT create, remove, or modify networks.'
      },
    ],
  },
  {
    group: 'INFRASTRUCTURE',
    color: 'var(--green)',
    items: [
      { label: 'Disk usage — all hosts', task: 'Check disk usage on all registered VM hosts. Flag any filesystem above 80% used. Show top directories consuming space on any full disks. Use only the host names from the AVAILABLE VM HOSTS list in your system prompt as vm_exec targets; if unsure, call list_connections(platform=\'vm_host\') first.' },
      { label: 'Memory and load — all hosts', task: 'Check memory usage and load average on all registered VM hosts. Flag any hosts with free memory below 500MB or load above 4. Use only the host names from the AVAILABLE VM HOSTS list in your system prompt as vm_exec targets; if unsure, call list_connections(platform=\'vm_host\') first.' },
      { label: 'Prune Docker images', task: 'Prune unused Docker images on all VM hosts. Show before/after disk reclaimed. Use only the host names from the AVAILABLE VM HOSTS list in your system prompt as vm_exec targets; if unsure, call list_connections(platform=\'vm_host\') first.' },
      { label: 'Journalctl vacuum', task: 'Check journal disk usage on all VM hosts and vacuum journals older than 7 days if they exceed 500MB. Use only the host names from the AVAILABLE VM HOSTS list in your system prompt as vm_exec targets; if unsure, call list_connections(platform=\'vm_host\') first.' },
      { label: 'VM host overview', task: 'Give me a health summary of all registered VM hosts: disk, memory, load, uptime. Flag anything that needs attention. Use only the host names from the AVAILABLE VM HOSTS list in your system prompt as vm_exec targets; if unsure, call list_connections(platform=\'vm_host\') first.' },
      {
        label: 'Container restart loop diagnosis',
        task:
          'Identify any Docker containers that are in a restart loop (>3 restarts in the last hour or >10 in the last 24h). For each flapping container: report its host, exit code of last termination, restart count, and the last 30 journal lines from around each recent restart. Call container_config_read and container_env first for the container\'s own config, then vm_exec journalctl on the host to capture crash context. Do NOT call any restart or update tools — this is read-only diagnosis.'
      },
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
      {
        label: 'DNS resolver consistency',
        task:
          'Check DNS resolver chain health. For every DNS server configured in this environment (check via list_connections platform=pihole and platform=technitium; also check /etc/resolv.conf on agent-01), use vm_exec to run dig or nslookup against each server for a standard set of records: the agent-01 host itself, one external record (google.com), and one internal record (one of the Swarm node hostnames). Compare answers across servers — flag any split-brain where servers disagree. Report all servers\' IPs, response times, and any resolution failures.'
      },
    ],
  },
  {
    group: 'STORAGE',
    color: '#818cf8',
    items: [
      { label: 'PBS datastore health', task: 'Check Proxmox Backup Server datastore health — used space, available space, GC status, recent backup task success rate. Flag any datastores above 85% full.' },
      { label: 'TrueNAS pool status', task: 'Check TrueNAS pool status — health, used/free space, SMART status, any scrub errors. Flag any pools with degraded vdevs or high usage.' },
      { label: 'Backup status check', task: 'Check recent backup job status across PBS. How many backups completed successfully in the last 24 hours? Any failures or warnings?' },
      { label: 'Storage capacity overview', task: 'Give me a storage capacity overview: PBS datastore usage, TrueNAS pool usage, and Docker volume usage on all VM hosts. Flag anything above 80%. Use only the host names from the AVAILABLE VM HOSTS list in your system prompt as vm_exec targets; if unsure, call list_connections(platform=\'vm_host\') first.' },
    ],
  },
  {
    group: 'SECURITY',
    color: 'var(--red)',
    items: [
      { label: 'SSH access audit', task: 'Check which VM hosts have verified SSH access via credential profiles. List any hosts that have not been successfully reached in the last 7 days. Treat the AVAILABLE VM HOSTS list in your system prompt as the source of truth for which hosts should have SSH access.' },
      { label: 'Recent auth failures', task: 'Search Elasticsearch for authentication failure log entries in the last 24 hours. Summarise by host and source IP.' },
      { label: 'Firewall interface check', task: 'Check FortiGate for any interface errors, high error rates, or unusual traffic patterns in the last hour. Report any interfaces with more than 100 errors.' },
      {
        label: 'Certificate expiry check',
        task:
          'Check SSL certificate expiry dates across the infrastructure. For each reverse proxy host (nginx, caddy, traefik in AVAILABLE VM HOSTS), enumerate certificate files via vm_exec (find /etc/letsencrypt/live -name fullchain.pem, find /etc/nginx/ssl, find /etc/caddy) and run openssl x509 -enddate -noout on each. Report any cert expiring within 30 days. Also check the agent-01 self-signed certs if present. Do NOT renew or modify anything — this is read-only audit.'
      },
    ],
  },
  {
    group: 'PLATFORM',
    color: 'var(--text-2)',
    items: [
      {
        label: 'Agent success rate audit',
        task:
          'Review the agent\'s own recent performance. Fetch the last 100 operations from /api/logs/operations and aggregate by (agent_type, status). Report: (a) overall success rate (completed / total), (b) success rate per agent_type (observe, investigate, execute, build), (c) top 5 task labels that ended with status=error or escalated, (d) median wall-clock time per agent_type, (e) any patterns of hallucination_guard_exhausted or fabrication_detected firings. Output as a structured report. This is a self-monitoring task — use only read endpoints and do NOT trigger new agent runs.'
      },
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
