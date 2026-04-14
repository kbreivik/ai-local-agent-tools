# CC PROMPT — v2.26.3 — Prompt quality: propose_subtask priority, non-Kafka investigation, observe format

## What this does
Three targeted improvements to agent system prompts:
1. RESEARCH_PROMPT: adds early propose_subtask reminder before evidence exhaustion rules
   (propose is critical but buried at bottom — model often skips it)
2. RESEARCH_PROMPT: adds non-Kafka investigation section for storage/network/security paths
3. STATUS_PROMPT: adds structured summary template at end of STOPPING RULES section
   (observe agent has no output format guide — results are inconsistent)
Version bump: v2.26.2 → v2.26.3

All changes are ADDITIONS to existing prompts, not rewrites.
The FIND strings target unique multi-line anchors in api/agents/router.py.

---

## Change 1 — api/agents/router.py

### 1a — RESEARCH_PROMPT: add early propose_subtask reminder

Find the anchor just after rule 8 in RESEARCH_PROMPT (citation format rule):

FIND (exact):
```
8. When citing documentation, use format: [Source: kafka-docs] or [Source: nginx-docs].

INVESTIGATION DEPTH RULES — follow before concluding:
```

REPLACE WITH:
```
8. When citing documentation, use format: [Source: kafka-docs] or [Source: nginx-docs].

CRITICAL — PROPOSE SUBTASK AFTER EVERY SUCCESSFUL INVESTIGATION:
After gathering evidence and writing fix steps, you MUST call propose_subtask() if:
  - Root cause is confirmed (not speculative)
  - At least one fix step is executable by the execute agent
  - Fix steps are specific (name the exact service, node, or command)
Failure to call propose_subtask when these conditions are met is a run failure.
This must happen BEFORE audit_log(). Call order: evidence → propose_subtask → audit_log → STOP.

INVESTIGATION DEPTH RULES — follow before concluding:
```

### 1b — RESEARCH_PROMPT: add non-Kafka investigation section

Find the anchor after the KAFKA INVESTIGATION section (TOOL PRIORITY FOR CONTAINER LOGS):

FIND (exact):
```
TOOL PRIORITY FOR CONTAINER LOGS:
  1. service_logs(service_name=...) — ONLY for containers on the local Docker host (agent-01)
     This uses Docker SDK on the local socket. Does NOT reach remote Swarm workers.
  2. vm_exec(host="<worker-label>", command="docker logs <container_id> --tail 50")
     Use this for containers on Swarm workers. Requires the container ID from docker ps first.
  Never call service_logs() for a Kafka broker — it's on a Swarm worker, not local.
```

REPLACE WITH:
```
TOOL PRIORITY FOR CONTAINER LOGS:
  1. service_logs(service_name=...) — ONLY for containers on the local Docker host (agent-01)
     This uses Docker SDK on the local socket. Does NOT reach remote Swarm workers.
  2. vm_exec(host="<worker-label>", command="docker logs <container_id> --tail 50")
     Use this for containers on Swarm workers. Requires the container ID from docker ps first.
  Never call service_logs() for a Kafka broker — it's on a Swarm worker, not local.

NON-KAFKA INVESTIGATION PATHS:

STORAGE (TrueNAS / PBS):
  1. elastic_error_logs(service="truenas") or elastic_error_logs(service="pbs")
     — search for backup failures, pool degradation events
  2. entity_history(entity_id="truenas:<label>:pool:<name>", hours=48)
     — see when pool status or usage_pct changed
  3. vm_exec(host="<truenas-host>", command="df -h") if reachable via SSH
  Root cause format: "Pool <name> degraded at <time> due to <disk failure / quota>."

NETWORK (FortiGate / UniFi):
  1. elastic_error_logs(service="fortigate") — interface error spikes
  2. entity_history(entity_id="fortigate:<label>:iface:<name>", hours=24)
     — when did the interface go down?
  3. entity_events(entity_id="unifi:<label>:device:<mac>", hours=24)
     — device disconnect/reconnect events
  Root cause format: "Interface <name> link dropped at <time>. Client count fell from X to Y."

COMPUTE (Proxmox VM / LXC):
  1. entity_history(entity_id="proxmox_vms:<node>:vm:<vmid>", hours=48)
     — status changes, disk usage changes
  2. vm_exec(host="<node>", command="qm status <vmid>") if node is reachable
  3. Check if Swarm worker node went Down (swarm_node_status)
  Root cause format: "VM <name> stopped at <time>. Worker node <x> is Down."

SECURITY (Elasticsearch / Wazuh):
  1. elastic_cluster_health() + elastic_index_stats()
  2. elastic_error_logs() for cluster-level errors
  3. entity_history for shard count / node count changes
```

### 1c — STATUS_PROMPT: add structured summary format at end of STOPPING RULES

Find this section near the end of STATUS_PROMPT:

FIND (exact):
```
STOPPING RULES (MANDATORY):
- Once you have gathered all data and written your summary, output it as plain text with NO tool calls.
- After you call audit_log(), output NOTHING MORE — the run ends immediately after.
- Never call audit_log() more than once per session.
- Do NOT keep calling tools after you have the answer.
```

REPLACE WITH:
```
STOPPING RULES (MANDATORY):
- Once you have gathered all data and written your summary, output it as plain text with NO tool calls.
- After you call audit_log(), output NOTHING MORE — the run ends immediately after.
- Never call audit_log() more than once per session.
- Do NOT keep calling tools after you have the answer.

REQUIRED SUMMARY FORMAT — use this at the end of every observe run:

STATUS: HEALTHY | DEGRADED | CRITICAL
  (one word — pick the worst finding)

FINDINGS:
- <component>: <status> — <specific value or count>
- (one bullet per component checked; omit if healthy unless it confirms baseline)

ACTION NEEDED:
- <specific next step> — or "None" if healthy
  (use exact names: "force-update kafka_broker-3", not "restart the service")
```

---

## Version bump
Update VERSION: 2.26.2 → 2.26.3

## Commit
```bash
git add -A
git commit -m "feat(prompts): v2.26.3 propose_subtask priority, non-Kafka paths, observe summary format"
git push origin main
```
