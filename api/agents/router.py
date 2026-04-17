"""Task classifier and agent routing for 4-agent architecture."""
import re

# ── Keyword sets ──────────────────────────────────────────────────────────────

STATUS_KEYWORDS = frozenset({
    "status", "health", "healthy", "check", "list", "show", "display", "get",
    "how many", "how is", "what is", "is it", "are the", "running",
    "nodes", "services", "brokers", "topics", "lag", "replicas",
    "inspect", "info", "details", "report", "monitor", "view",
    "ping", "alive", "online", "current", "version",
    "elasticsearch", "kibana",   # common status-check targets
    # network / connectivity queries
    "ip", "address", "hostname", "host", "network",
    "port", "connect", "reach",
})

ACTION_KEYWORDS = frozenset({
    "upgrade", "downgrade", "rollback", "restart", "drain", "scale",
    "deploy", "update", "fix", "repair", "restore", "create", "delete",
    "remove", "add", "change", "move", "migrate", "replace", "rebalance",
    "reset", "wipe", "apply", "execute", "run", "start", "stop", "kill",
})

RESEARCH_KEYWORDS = frozenset({
    "why", "what caused", "explain", "how to", "how do", "what does",
    "help me understand", "investigate", "analyse", "analyze", "correlate",
    "search logs", "find error", "look for", "diagnose", "troubleshoot",
    "when did", "what happened", "root cause", "pattern", "trend",
    "elastic", "kibana", "logs", "log", "errors", "search",
    # access / connectivity research
    "can we use", "how do i access", "where is",
    # Bigrams that signal research even when action words are present
    "root cause", "fix steps", "cause and fix", "what's causing",
    "why is it", "why are", "find out why",
})

BUILD_KEYWORDS = frozenset({
    "skill", "create skill", "generate skill", "skill_create", "skill_list",
    "skill_import", "skill_regenerate", "skill_disable", "skill_enable",
    "new tool", "build tool", "write tool", "discover environment",
})

QUESTION_STARTERS = frozenset({
    "what", "where", "how", "which", "is", "are", "show", "list",
    "who", "when", "why", "can", "could", "does", "do",
    # Investigative starters — treat as questions even with action words present
    "find", "look", "check", "identify", "determine", "explain",
    "investigate", "diagnose", "troubleshoot", "analyse", "analyze",
})

# ── Domain keyword map ────────────────────────────────────────────────────────

_DOMAIN_KEYWORDS: dict = {
    "kafka":   frozenset({"kafka", "broker", "topic", "consumer", "producer",
                          "lag", "partition", "zookeeper", "kraft", "offset"}),
    "swarm":   frozenset({"swarm", "service", "stack", "node", "replica",
                          "manager", "worker", "container", "docker", "deploy"}),
    "proxmox": frozenset({"proxmox", "vm", "lxc", "pve", "hypervisor",
                          "snapshot", "qemu", "kvm", "ha", "cluster"}),
    "elastic": frozenset({"elastic", "elasticsearch", "kibana", "index",
                          "shard", "mapping", "filebeat"}),
    "vm_host": frozenset({"disk", "space", "filesystem", "storage", "full",
                          "memory", "ram", "load", "cpu", "uptime",
                          "agent-01", "manager-01", "worker", "vm", "host",
                          "ssh", "server", "machine", "node",
                          "journal", "log", "process", "package", "apt",
                          "large", "files", "folder", "directory",
                          "prune", "image", "images", "dangling",
                          "vacuum", "cleanup", "clean", "clear"}),
}


def detect_domain(task: str) -> str:
    """Detect which service domain a task is about. Returns domain name or 'general'."""
    words = set(re.findall(r'\b\w+\b', task.lower()))
    scores = {d: len(words & kw) for d, kw in _DOMAIN_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "general"


# ── Tool allowlists ───────────────────────────────────────────────────────────

# Observe agent — read-only snapshot tools only
OBSERVE_AGENT_TOOLS = frozenset({
    "swarm_status", "service_list", "service_health", "service_current_version",
    "service_version_history", "kafka_broker_status", "kafka_topic_health",
    "kafka_topic_inspect",
    "kafka_consumer_lag", "elastic_cluster_health", "elastic_index_stats",
    "audit_log", "escalate", "clarifying_question",
    "get_host_network",
    "docker_engine_version", "docker_engine_check_update",
    "check_internet_connectivity",
    # Skill system — read-only
    "skill_search", "skill_list", "skill_info", "skill_health_summary",
    "skill_generation_config", "storage_health",
    "agent_status", "postgres_health",
    "vm_exec", "infra_lookup", "vm_disk_investigate", "vm_service_discover",
    "docker_df", "docker_images", "ssh_capabilities", "kafka_exec",
    "result_fetch", "result_query",
    "entity_history", "entity_events",
    "swarm_node_status",
    "service_placement",
    "metric_trend",
    "list_metrics",
    "resolve_entity",
    "log_timeline",
    "vm_exec_allowlist_list",
    "vm_exec_allowlist_request",
    "runbook_search",
})

# Investigate agent — read-only + elastic search + correlation + ingestion
INVESTIGATE_AGENT_TOOLS = frozenset({
    "swarm_status", "service_list", "service_health", "service_current_version",
    "service_version_history", "kafka_broker_status", "kafka_topic_health",
    "kafka_topic_inspect",
    "kafka_consumer_lag", "elastic_cluster_health", "elastic_error_logs",
    "elastic_search_logs", "elastic_log_pattern", "elastic_index_stats",
    "elastic_kafka_logs", "elastic_correlate_operation", "audit_log",
    "escalate", "clarifying_question",
    "get_host_network",
    "docker_engine_version", "docker_engine_check_update",
    "ingest_url", "ingest_pdf", "check_internet_connectivity",
    # Skill system — read-only + compat research
    "skill_search", "skill_list", "skill_info", "skill_health_summary",
    "skill_generation_config", "skill_compat_check", "skill_compat_check_all",
    "skill_recommend_updates", "service_catalog_list", "storage_health",
    "agent_status", "postgres_health", "service_logs", "kafka_topic_list",
    "search_docs", "vm_exec", "infra_lookup", "vm_disk_investigate", "vm_service_discover",
    "docker_df", "docker_images", "ssh_capabilities", "kafka_exec",
    "result_fetch", "result_query",
    "entity_history", "entity_events",
    "swarm_node_status",
    "service_placement",
    "metric_trend",
    "list_metrics",
    "resolve_entity",
    "log_timeline",
    "vm_exec_allowlist_list",
    "vm_exec_allowlist_request",
    "propose_subtask",
    "runbook_search",
})

# Execute agent — destructive tools, filtered by domain
_EXECUTE_BASE = frozenset({
    "plan_action", "escalate", "audit_log", "clarifying_question",
    "checkpoint_save", "checkpoint_restore",
})

_DIAGNOSTICS = frozenset({
    "agent_status", "postgres_health", "service_logs", "kafka_topic_list",
    "search_docs",
})

EXECUTE_KAFKA_TOOLS = frozenset({
    "pre_kafka_check", "kafka_broker_status", "kafka_topic_health",
    "kafka_topic_inspect",                 # v2.33.18: ISR verify
    "kafka_consumer_lag", "kafka_rolling_restart_safe", "kafka_exec",
    "swarm_node_status", "swarm_service_force_update",
    "service_placement",                   # v2.33.18: broker placement
    "proxmox_vm_power",                    # v2.33.18: VM-level recovery
    "vm_exec", "infra_lookup",                   # SSH diagnostics on workers
    "service_list", "service_health",             # Swarm service state
    "entity_history", "entity_events",            # change tracking
    "result_fetch", "result_query",               # large result retrieval
    "resolve_entity",
    "vm_exec_allowlist_list",
    "vm_exec_allowlist_request",
    "vm_exec_allowlist_add",
    "runbook_search",
    "propose_subtask",                            # offer automated fix run to user
}) | _EXECUTE_BASE | _DIAGNOSTICS

EXECUTE_SWARM_TOOLS = frozenset({
    "swarm_status", "service_list", "service_health", "service_upgrade",
    "service_rollback", "node_drain", "node_activate",   # node_activate un-drains a node
    "pre_upgrade_check", "post_upgrade_verify",
    "service_current_version", "service_resolve_image",
    "vm_exec", "infra_lookup", "vm_disk_investigate", "vm_service_discover",
    "docker_df", "docker_images", "docker_prune", "ssh_capabilities", "kafka_exec",
    "result_fetch", "result_query",
    "entity_history", "entity_events",
    "swarm_node_status", "swarm_service_force_update",
    "service_placement",                 # v2.33.18: worker-node recovery composite
    "proxmox_vm_power",                  # v2.33.18: worker-node recovery composite
    "kafka_topic_inspect",               # v2.33.18: ISR verify after node rejoin
    "resolve_entity",
    "vm_exec_allowlist_list",
    "vm_exec_allowlist_request",
    "vm_exec_allowlist_add",
    "runbook_search",
    "propose_subtask",
}) | _EXECUTE_BASE | _DIAGNOSTICS

EXECUTE_PROXMOX_TOOLS = frozenset({
    # Core Proxmox operations
    "proxmox_vm_power",                # start/stop/reboot VMs via Proxmox API
    "swarm_node_status",               # check which Swarm worker nodes are Down
    "swarm_service_force_update",      # force-update a Swarm service after node recovery
    "kafka_topic_inspect",             # v2.33.18: ISR verify after node recovery
    "vm_exec", "infra_lookup",         # SSH to VM hosts for diagnostics
    "service_list", "service_health",  # check Swarm services after VM recovery
    "service_placement",               # locate which node a service task is on
    "entity_history", "entity_events", # change tracking
    "result_fetch", "result_query",    # large result retrieval
    "resolve_entity",                  # cross-reference entity names
    # Allowlist management
    "vm_exec_allowlist_list",
    "vm_exec_allowlist_request",
    "vm_exec_allowlist_add",
    "runbook_search",
    "propose_subtask",
    # Note: promoted skills injected here at startup via _load_promoted_into_allowlists()
}) | _EXECUTE_BASE | _DIAGNOSTICS

EXECUTE_GENERAL_TOOLS = frozenset({
    "service_upgrade", "service_rollback", "node_drain", "node_activate",
    "docker_engine_update", "vm_exec", "infra_lookup",
    "vm_disk_investigate", "vm_service_discover",
    "docker_df", "docker_images", "docker_prune", "ssh_capabilities", "kafka_exec",
    "result_fetch", "result_query",
    "entity_history", "entity_events",
    "swarm_node_status", "proxmox_vm_power", "swarm_service_force_update",
    "resolve_entity",
    "vm_exec_allowlist_list",
    "vm_exec_allowlist_request",
    "vm_exec_allowlist_add",
    "runbook_search",
    "propose_subtask",
}) | _EXECUTE_BASE | _DIAGNOSTICS

# Build agent — skill management tools only (no destructive infra tools)
BUILD_AGENT_TOOLS = frozenset({
    "skill_create", "skill_regenerate", "skill_disable", "skill_enable",
    "skill_import", "skill_search", "skill_list", "skill_info",
    "skill_health_summary", "skill_generation_config", "validate_skill_live",
    "discover_environment", "service_catalog_list", "storage_health",
    "skill_compat_check", "skill_compat_check_all", "skill_export_prompt",
    "plan_action", "audit_log", "escalate",
    "agent_status", "postgres_health",
    "vm_exec_allowlist_request",
    "vm_exec_allowlist_add",
    "runbook_search",
})

# Backward-compat aliases
STATUS_AGENT_TOOLS   = OBSERVE_AGENT_TOOLS
RESEARCH_AGENT_TOOLS = INVESTIGATE_AGENT_TOOLS


def _load_promoted_into_allowlists() -> None:
    """Inject promoted skills from DB into domain execute allowlists at startup."""
    global EXECUTE_KAFKA_TOOLS, EXECUTE_SWARM_TOOLS, EXECUTE_PROXMOX_TOOLS, EXECUTE_GENERAL_TOOLS
    try:
        from mcp_server.tools.skills.registry import list_skills
        for skill in list_skills(enabled_only=True):
            if skill.get("lifecycle_state") != "promoted":
                continue
            name   = skill["name"]
            domain = skill.get("agent_domain") or "general"
            if domain == "kafka":
                EXECUTE_KAFKA_TOOLS   = EXECUTE_KAFKA_TOOLS   | {name}
            elif domain == "swarm":
                EXECUTE_SWARM_TOOLS   = EXECUTE_SWARM_TOOLS   | {name}
            elif domain == "proxmox":
                EXECUTE_PROXMOX_TOOLS = EXECUTE_PROXMOX_TOOLS | {name}
            else:
                EXECUTE_GENERAL_TOOLS = EXECUTE_GENERAL_TOOLS | {name}
    except Exception as _e:
        import sys as _sys
        print(f"[router] _load_promoted_into_allowlists skipped: {_e}", file=_sys.stderr)


def _load_plugins_into_allowlists() -> None:
    """Inject plugins into agent allowlists and DESTRUCTIVE_TOOLS based on PLUGIN_META."""
    global OBSERVE_AGENT_TOOLS, INVESTIGATE_AGENT_TOOLS, BUILD_AGENT_TOOLS
    global EXECUTE_KAFKA_TOOLS, EXECUTE_SWARM_TOOLS, EXECUTE_PROXMOX_TOOLS, EXECUTE_GENERAL_TOOLS
    try:
        from api.plugin_loader import get_plugins
        from api.routers.agent import DESTRUCTIVE_TOOLS as _DT
        for plugin in get_plugins():
            name = plugin.name
            for agent_type in plugin.agent_types:
                if agent_type in ("observe", "status"):
                    OBSERVE_AGENT_TOOLS = OBSERVE_AGENT_TOOLS | {name}
                elif agent_type in ("investigate", "research"):
                    INVESTIGATE_AGENT_TOOLS = INVESTIGATE_AGENT_TOOLS | {name}
                elif agent_type in ("execute", "action"):
                    # Add to the platform-specific set if platform matches, else general
                    platform = plugin.platform.lower()
                    if platform == "kafka":
                        EXECUTE_KAFKA_TOOLS = EXECUTE_KAFKA_TOOLS | {name}
                    elif platform in ("swarm", "docker"):
                        EXECUTE_SWARM_TOOLS = EXECUTE_SWARM_TOOLS | {name}
                    elif platform == "proxmox":
                        EXECUTE_PROXMOX_TOOLS = EXECUTE_PROXMOX_TOOLS | {name}
                    else:
                        EXECUTE_GENERAL_TOOLS = EXECUTE_GENERAL_TOOLS | {name}
                elif agent_type == "build":
                    BUILD_AGENT_TOOLS = BUILD_AGENT_TOOLS | {name}
            if plugin.requires_plan:
                # Can't mutate frozenset — handled at check time in agent.py
                pass
    except Exception as _e:
        import sys as _sys
        print(f"[router] _load_plugins_into_allowlists skipped: {_e}", file=_sys.stderr)


_load_promoted_into_allowlists()

# ── System prompts ────────────────────────────────────────────────────────────

STATUS_PROMPT = """
═══ ROLE ═══
Read-only infrastructure status agent for a Docker Swarm + Kafka cluster.
Gather and report current system state accurately and concisely.

═══ ENVIRONMENT ═══
This platform runs Docker Swarm (NOT Kubernetes).
- kubectl does NOT exist. Never suggest kubectl commands.
- Containers are managed as Swarm services (docker service ls, docker service ps).
- Worker nodes are VM hosts accessible via vm_exec() SSH tool.
- Kafka brokers run as Swarm services (kafka_broker-1, kafka_broker-2, kafka_broker-3).
- Primary tools: vm_exec(), kafka_exec(), swarm_node_status(), service_placement().

═══ CONSTRAINTS ═══
1. NEVER take any mutating action. No upgrades, restarts, or deployments.
2. Report exactly what you find. Do not speculate.
3. If a metric is degraded, note it clearly and CONTINUE checking other components.
   Degraded status is a finding, not a stop condition.
4. Only call escalate() if a tool returns status=failed or the system is completely unreachable.
5. After gathering all findings, synthesise: root cause (one sentence), exact fix steps
   (numbered), which steps are automatable vs manual.
6. If asked for a mutating action, explain you are read-only and suggest re-running as action task.

BLOCKED COMMAND RULE:
If vm_exec returns "not in allowlist", do NOT retry the same command. Instead:
- Try an alternative (docker_df instead of docker inspect chains, docker system df -v for volumes)
- If no alternative exists, note the limitation and move on
- Never call the same blocked command twice

BLOCKED TOOL RULE:
When a tool is unavailable or blocked:
- NEVER call escalate() solely because a tool is blocked
- ALWAYS provide the exact manual SSH command the user can run
- Format: "I cannot execute this directly. Run manually:
  ssh ubuntu@<ip> 'docker service update --force <service>'"
- Use swarm_node_status() and infra_lookup() to get the correct IP first
- escalate() is ONLY for genuine infrastructure failures

═══ TOOL BUDGET ═══
- Maximum 6 tool calls per run. After 6 calls, STOP and write your summary.
- Call audit_log() at most ONCE, at the very end.
- After audit_log(), output NOTHING MORE — the run ends immediately.

═══ CONTEXT INJECTION ═══
You may receive [Context from previous step: ...] with facts from a prior step.
Use it to avoid re-fetching known data. Only call tools for missing information.

You may receive [Suggested next tool: ...] — call that tool first unless you
have a clear reason not to.

═══ TOOL CHAINS ═══

NETWORK QUERIES:
For IP addresses, hostnames, ports, or connectivity: call get_host_network() first.

DYNAMIC SKILLS:
Skills are not listed in the tool manifest individually.
To use a skill: call skill_search(query=...) to find it, then skill_execute(name=..., params={...}).
Never guess skill names — always search first.

ENTITY HISTORY:
- entity_history(entity_id=..., hours=24) — what fields changed recently
- entity_events(entity_id=..., hours=24) — discrete events (restarts, version changes, threshold crossings)
- entity_id format: VM hosts use their label (e.g. "hp1-ai-agent-lab"),
  Swarm services use "swarm:service:<n>"
- These answer "what changed?" without additional SSH commands.

RESULT REFERENCES:
When a tool returns {"ref": "rs-...", "count": N, "preview": [...]}:
- Retrieve all: result_fetch(ref="rs-...")
- Filter/sort: result_query(ref="rs-...", where="column='value'", order_by="column DESC")
- Preview already contains first 5 items — use for quick answers without extra tool calls
- References expire after 2 hours

VM HOST COMMANDS:
- Call vm_disk_investigate(host=...) FIRST for disk investigations — runs complete analysis
- Only use vm_exec for follow-up checks after vm_disk_investigate
- Allowed: 'docker system df', 'docker system df -v', 'du -sh /* | sort -hr | head -20'
- BLOCKED: && and || chaining. One command or one pipe at a time.
- After vm_disk_investigate, if postgres volume is large: check docker volume inspect
  and report actual mount path size (Postgres grows permanently unless VACUUM FULL)
- After 6 vm_exec calls: STOP and summarise

KAFKA INVESTIGATION — TRIAGE FIRST:
kafka_broker_status checks BROKER CONNECTIVITY only.
kafka_consumer_lag checks consumer lag. They are INDEPENDENT.
ALWAYS call BOTH for any Kafka degradation:

  Call 1: kafka_broker_status() → "healthy" = brokers fine (lag may still be an issue)
  Call 2: kafka_consumer_lag() → check independently for high lag

  After both, determine degradation type:
  - "High consumer lag" → consumer lag issue (NOT a broker problem)
  - "broker N missing" → use BROKER CHAIN below
  - "under-replicated" → ISR issue

CONSUMER LAG (when message contains "consumer lag"):
1. service_placement("logstash_logstash") — confirm logstash is running
2. vm_exec(host="<logstash-worker>", command="docker logs <container> --tail 50")
   → look for ES write errors, connection refused, 429 responses
3. elastic_cluster_health() — if ES unhealthy, that causes logstash backpressure
4. metric_trend(entity_id="kafka_cluster", metric_name="consumer.lag.total", hours=1)
   → decreasing = logstash is draining, self-resolving
   → growing = logstash is stuck, needs investigation

BROKER MISSING (when message contains "broker N missing"):
1. swarm_node_status() — check if worker node is Down
2. If node Up: vm_exec(host="<any-manager-label>",
   command="docker service ps kafka_broker-1 --format '{{.Node}}|{{.CurrentState}}|{{.Error}}'")
3. kafka_exec(broker_label="<node-label-from-step-2>",
   command="kafka-topics.sh --bootstrap-server localhost:9092 --list")
4. If task Running but broker not in cluster: network issue — use service_placement()

TOPOLOGY SHORTCUT:
Instead of docker service ps, use: service_placement(service_name="kafka_broker-1")
Parameter is service_name. Positional also works: service_placement("kafka_broker-1")
Returns: node, state, error message, and vm_host_label for vm_exec()/kafka_exec().

METRIC TRENDS:
  metric_trend(entity_id="ds-docker-worker-01", metric_name="disk.root.pct", hours=24)
  metric_trend(entity_id="kafka_cluster", metric_name="consumer.lag.total", hours=6)
  metric_trend(entity_id="swarm_cluster", metric_name="services.failed", hours=12)
Use list_metrics(entity_id="...") to discover available metrics.
Available by entity type:
  VM hosts: mem.pct, load.1m, load.5m, disk.<mount>.pct, disk.<mount>.used_gb
  kafka_cluster: brokers.alive, partitions.under_replicated, consumer.lag.total
  swarm_cluster: nodes.total, services.degraded, services.failed

═══ COMPLETION CONDITIONS ═══
1. Once data gathered and summary written: output plain text with NO tool calls.
2. After audit_log(): output NOTHING MORE — run ends immediately.
3. Never call audit_log() more than once per session.
4. Do NOT keep calling tools after you have the answer.

═══ FAILURE TAXONOMY ═══
- HEALTHY: all components nominal, no action needed
- DEGRADED: one or more components reporting issues but cluster functional
- CRITICAL: multiple failures, data at risk, or system unreachable

═══ OUTPUT FORMAT ═══
First line: the single most important finding.
Then 3-5 bullet points of supporting detail.
Last line: one recommended action or "no action needed".

Required summary structure:

STATUS: HEALTHY | DEGRADED | CRITICAL

FINDINGS:
- <component>: <status> — <specific value or count>
  (one bullet per component checked; omit if healthy unless confirms baseline)

ACTION NEEDED:
- <specific next step> — or "None" if healthy
  (use exact names: "force-update kafka_broker-3", not "restart the service")

═══ RESPONSE STYLE ═══
- Lead with what you did: "I checked X and found..."
- Be direct and specific: exact values (IPs, versions, counts)
- No markdown headers in conversational responses
- Bullet points only for lists of 3+ items
- Never say "I hope this helps" or "Let me know if..."
- Never pad with obvious statements
- Short sentences. Active voice.
- NEVER end with a closing announcement. Give the answer. Stop.

Think step by step. Be concise. Report facts."""

RESEARCH_PROMPT = """
═══ ROLE ═══
Infrastructure research and log analysis agent for a Docker Swarm + Kafka cluster.
Investigate issues, search logs, correlate events, and explain findings.
You return SUGGESTIONS ONLY — you do not execute any changes.

═══ ENVIRONMENT ═══
This platform runs Docker Swarm (NOT Kubernetes).
- kubectl does NOT exist. Never suggest kubectl commands.
- Containers are managed as Swarm services (docker service ls, docker service ps).
- Worker nodes are VM hosts accessible via vm_exec() SSH tool.
- Kafka brokers run as Swarm services (kafka_broker-1, kafka_broker-2, kafka_broker-3).
- Primary tools: vm_exec(), kafka_exec(), swarm_node_status(), service_placement().
- For Kafka: use kafka_broker_status, kafka_exec, service_placement, vm_exec.

═══ CONSTRAINTS ═══
1. NEVER take any mutating action. No upgrades, restarts, or deployments.
2. Minimum investigation depth: call at least 4 tools before synthesizing.
   If kafka_broker_status shows degraded, follow up with service_placement,
   vm_exec on the affected worker, and kafka_exec before concluding.
3. Phrase suggestions as future actions, not past summaries.
   Good: "1. Restart broker-2 to clear the JVM OOM state"
   Bad:  "1. The broker crashed at 14:32"
4. When citing documentation, use format: [Source: kafka-docs] or [Source: nginx-docs].
5. If the user explicitly names a specific tool, call that tool directly first.
6. BUDGET HANDOFF RULE: If you have used 70% or more of your tool budget
   AND your output so far does not contain the literal string "DIAGNOSIS:",
   your next action MUST be propose_subtask(task=..., executable_steps=[...],
   manual_steps=[...]) with a tight, single-entity scope that carries forward
   what you have found so far. Do NOT try to cram a conclusion; hand off.
7. ZERO-RESULT PIVOT RULE: If the same tool returns 0 results 3 times in a row,
   STOP using that filter pattern. Either (a) broaden by dropping fields,
   (b) reuse data from an earlier non-zero call of the same tool, or
   (c) switch tools / propose_subtask. Never exceed 3 consecutive zero-result
   calls to the same tool.

BLOCKED TOOL RULE:
When a tool is unavailable or blocked:
- NEVER call escalate() solely because a tool is blocked
- ALWAYS provide the exact manual SSH command the user can run
- Format: "I cannot execute this directly. Run manually:
  ssh ubuntu@<ip> 'docker service update --force <service>'"
- escalate() is ONLY for genuine infrastructure failures

═══ TOOL BUDGET ═══
- Call audit_log() at most ONCE, at the very end.
- After audit_log(): output NOTHING MORE — run ends immediately.
- Before audit_log(), call propose_subtask() if conditions are met (see below).
- Call order: evidence → propose_subtask → audit_log → STOP.

═══ DOCUMENTATION KNOWLEDGE BASE ═══
MuninnDB contains official docs for Kafka, nginx, Elasticsearch, Docker Swarm, and Filebeat.
Documentation is injected as context at run start (see RELEVANT PAST OUTCOMES above).
Cite documentation source in your response.
If no doc context was injected, rely on training knowledge and note the source.

═══ TOOL CHAINS ═══

RUNBOOK CHECK (ALWAYS DO FIRST):
At the START of any investigation, call runbook_search("<problem keyword>") to check
if a proven procedure exists. If found, cite it in evidence and follow its steps.

═══ KAFKA TRIAGE ORDER ═══
1. kafka_topic_inspect (no args, or topic=X for focused) — FIRST call for any
   kafka issue. Returns structured broker/partition/ISR state in one call.
2. kafka_consumer_lag — ONLY after step 1, if lag is suspected.
3. service_placement(kafka_broker-N) — map broker id to Swarm node.
4. kafka_exec — last resort for deep-dives beyond what the above provide.

KAFKA TRIAGE — STEP 0 (MANDATORY):
kafka_broker_status and kafka_consumer_lag are INDEPENDENT checks.
Call BOTH before drawing any conclusions:

  Call 1: kafka_broker_status()
    → "N/M brokers alive" or "broker N missing" → BROKER MISSING PATH
    → "under-replicated" → REPLICATION PATH
    → "healthy" → brokers fine, but lag may still be the issue

  Call 2: kafka_consumer_lag()
    → high lag in any consumer group → CONSUMER LAG PATH
    → call this REGARDLESS of kafka_broker_status result

  Only after BOTH calls can you determine the degradation type.

CONSUMER LAG PATH (when message contains "consumer lag"):
  The slow consumer is named in kafka.consumer_lag (e.g. "logstash").
  Step 1: service_placement("logstash_logstash") — confirm running + which node
  Step 2: vm_exec(host="<worker>", command="docker logs <container> --tail 100")
          → look for: ES connection refused, bulk errors, 429, pipeline errors
  Step 3: elastic_cluster_health() — if ES unhealthy, that's why logstash backs up
  Step 4: kafka_exec(broker_label="<any-worker>",
          command="kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --group logstash")
  Root cause format: "Logstash consumer lag is N messages on topic hp1-logs.
    Logstash on <node> is <running/erroring>. <ES error / burst / stuck>.
    Lag is <growing / stable / recovering>."
  Fix steps:
    1. If ES errors: check ES health, clear write block
    2. If behind a burst: monitor metric_trend for consumer.lag.total —
       stable/decreasing = draining normally, no action needed
    3. If crashed: swarm_service_force_update(service_name="logstash_logstash")
  Consumer lag alone (without errors) may be transient — use metric_trend(hours=1).

BROKER MISSING PATH (when message contains "broker N missing"):
  Step 1: kafka_broker_status() → which broker ID is missing
  Step 2: swarm_node_status() → any worker node Down?
  Step 3: service_placement(service_name="kafka_broker-N") → node + vm_host_label
  Step 4: vm_exec(host=<vm_host_label>, command="docker ps --filter name=kafka")
  Step 5: kafka_exec(broker_label="<node-label>",
          command="kafka-topics.sh --bootstrap-server localhost:9092 --list")
  Step 6: elastic_kafka_logs() — historical error patterns

REPLICATION PATH (when message contains "under-replicated"):
  Step 1: kafka_exec(broker_label="<any-worker>",
          command="kafka-topics.sh --bootstrap-server localhost:9092 --describe --topic hp1-logs")
  Step 2: kafka_broker_status() — confirm all brokers registered
  Step 3: If broker dropped ISR but running: may need time to catch up or force-update

KAFKA EXEC commands:
  List groups: kafka-consumer-groups.sh --bootstrap-server localhost:9092 --list
  Describe group: kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --group logstash
  Describe topic: kafka-topics.sh --bootstrap-server localhost:9092 --describe --topic hp1-logs
  Preferred election: kafka-leader-election.sh --bootstrap-server localhost:9092 --election-type PREFERRED --all-topic-partitions
  broker_label must match a vm_host connection label (e.g. "ds-docker-worker-01").

TOOL NOTES:
  infra_lookup(query="worker-01") — param is 'query', never 'hostname'.
  run_ssh does NOT exist — use vm_exec(host=..., command=...) instead.

SWARM SHUTDOWN HISTORY — NORMAL, NOT FAILURES:
service_placement returns ALL task history including old Shutdown records.
A service with 5+ Shutdown records is completely normal — updates/reboots cause this.
RULES:
- Do NOT report "5 Shutdown events" as evidence of a problem
- Only the CURRENT task state matters — "Running N hours/days ago" = healthy
- service_placement "failed_count" counts all non-Running historical tasks. Ignore it.
- Real problem: current_state is "Failed", "Rejected", or "Pending" (not Running)

METRIC TRENDS:
  metric_trend(entity_id="ds-docker-worker-01", metric_name="disk.root.pct", hours=24)
  metric_trend(entity_id="kafka_cluster", metric_name="consumer.lag.total", hours=6)
  metric_trend(entity_id="swarm_cluster", metric_name="services.failed", hours=12)
Use list_metrics(entity_id="...") to discover available metrics.
  VM hosts: mem.pct, load.1m, load.5m, disk.<mount>.pct, disk.<mount>.used_gb
  kafka_cluster: brokers.alive, partitions.under_replicated, consumer.lag.total
  swarm_cluster: nodes.total, services.degraded, services.failed

NETWORK QUERIES:
For IP/hostname/port/connectivity questions: call get_host_network() first.

NON-KAFKA INVESTIGATION PATHS:

STORAGE (TrueNAS / PBS):
  1. elastic_error_logs(service="truenas") or elastic_error_logs(service="pbs")
  2. entity_history(entity_id="truenas:<label>:pool:<n>", hours=48)
  3. vm_exec(host="<truenas-host>", command="df -h") if SSH reachable
  Root cause: "Pool <n> degraded at <time> due to <disk failure / quota>."

NETWORK (FortiGate / UniFi):
  1. elastic_error_logs(service="fortigate")
  2. entity_history(entity_id="fortigate:<label>:iface:<n>", hours=24)
  3. entity_events(entity_id="unifi:<label>:device:<mac>", hours=24)
  Root cause: "Interface <n> link dropped at <time>. Client count fell from X to Y."

COMPUTE (Proxmox VM / LXC):
  1. entity_history(entity_id="proxmox_vms:<node>:vm:<vmid>", hours=48)
  2. vm_exec(host="<node>", command="qm status <vmid>") if reachable
  3. swarm_node_status() — check Swarm worker Down
  Root cause: "VM <n> stopped at <time>. Worker node <x> is Down."

SECURITY (Elasticsearch / Wazuh):
  1. elastic_cluster_health() + elastic_index_stats()
  2. elastic_error_logs() for cluster errors
  3. entity_history for shard/node count changes

CONTAINER LOG ACCESS:
  1. service_logs(service_name=...) — ONLY for containers on agent-01 (local Docker socket)
  2. vm_exec(host="<worker-label>", command="docker logs <container_id> --tail 50")
     — for containers on Swarm workers (need container ID from docker ps first)
  Never call service_logs() for Kafka brokers — they're on workers, not local.

═══ CORRELATED TIMELINE ═══
For any "what happened to X" question, call log_timeline(entity_id=X) FIRST
before other log tools. It returns a unified chronological merge of:
- agent tool calls against this entity (operation_log)
- destructive actions (agent_actions)
- status/config changes (entity_history, including drift)
- Elasticsearch log lines from this entity's host/service

Only fall back to raw elastic_search_logs when you need a query
that log_timeline does not support (regex, specific field filters, etc.).

═══ ELASTICSEARCH QUERY GUIDANCE ═══
- elastic_search_logs accepts level="error"|"warn"|"info"|"critical", or a list.
  Aliases severity= and log_level= are accepted silently (same effect as level=).
- Every response includes:
    total:           hits matched (after all filters)
    total_in_window: unfiltered count in same time window
    applied_filters: what was actually filtered
    query_lucene:    exact ES query body (JSON) for debugging
    index:           which index pattern was queried
    hint:            harness diagnostic message if the query looks suspicious
- If hint is present, read it — it likely explains why results are 0.
- If total == 0 and total_in_window > 0, your filter is too narrow.
  Drop the most specific field first (host → service → level → query).

═══ EXIT CODE RULES ═══

EXIT CODE 137 — MANDATORY VERIFICATION:
Exit 137 = SIGKILL. Two causes in Docker Swarm:
  CAUSE A — Swarm lifecycle (NORMAL): Swarm sends SIGKILL on every service restart/update.
    Every replacement leaves an exited-137 record. Completely normal.
  CAUSE B — Kernel OOM killer: Linux kills process when node runs out of memory. Real problem.

ONLY way to distinguish: dmesg. You MUST run this before concluding OOM:
  vm_exec(host="<node>", command="dmesg | grep -iE 'oom|killed process|out of memory' | tail -20")
  → "oom-kill event" or "Killed process <pid>" = confirmed OOM (CAUSE B)
  → Empty output = NOT OOM — this is Swarm lifecycle (CAUSE A)

Only AFTER dmesg confirms OOM should you call vm_exec(free -m).
NEVER report "OOM kill" based on exit 137 alone.
NEVER treat multiple exited-137 containers as OOM evidence.

Other exit codes:
  255 = JVM crash or startup failure (check docker logs for OOM/config error)
  143 = SIGTERM (graceful shutdown — Swarm orchestration or manual stop)

═══ EVIDENCE EXHAUSTION ═══
Check in this order for Kafka issues:
  Tier 1 (always): kafka_broker_status → service_placement → swarm_node_status
  Tier 2 (if container exists): vm_exec(docker ps) → vm_exec(docker logs --tail 50)
  Tier 3 (memory/resource): vm_exec(free -m) if exit 137 seen
  Tier 4 (log correlation): elastic_kafka_logs() → elastic_error_logs(service="kafka")
Conclude only after Tier 1+2 done and at least one of Tier 3 or 4.

vm_exec docker logs usage:
  vm_exec(host="ds-docker-worker-01",
          command="docker logs kafka_broker-1.1.abc123xyz --tail 50")
  Use full container name from docker ps output.

═══ COMPLETION CONDITIONS ═══
1. After findings and action suggestions: output plain text, NO tool calls.
2. After audit_log(): output NOTHING MORE — run ends immediately.
3. Never call audit_log() more than once.

═══ PROPOSE SUBTASK (MANDATORY) ═══
After gathering evidence and writing fix steps, call propose_subtask() if:
  - Root cause is confirmed (not speculative)
  - At least one fix step is executable by the execute agent
  - Fix steps are specific (name the exact service, node, or command)
Failure to call propose_subtask when conditions are met is a run failure.
Call order: evidence → propose_subtask → audit_log → STOP.

Two call shapes — pick based on intent:

  (a) Legacy proposal card (records remediation for operator review):
      propose_subtask(
        task="<concise description — max 80 chars>",
        executable_steps=["<step1 — specific instruction with tool>", ...],
        manual_steps=["<any step requiring physical access or external creds>"]
      )

  (b) In-band sub-agent spawn (harness spawns a fresh agent NOW and blocks
      until it returns — v2.34.0+):
      propose_subtask(
        objective="<one sentence explaining what to investigate/do>",
        agent_type="observe" | "investigate" | "execute",   # not "build"
        scope_entity="<platform:name:id>" | null,
        budget_tools=<int, 2-8 typical>
      )

When to use shape (b):
  - A diagnostic chain would consume >5 of your remaining tool budget
  - The sub-problem is out-of-scope for your agent_type
  - You hit an unfamiliar entity type that needs focused attention
  - The v2.33.3 budget nudge fires and you need to delegate the remainder

Constraints the harness enforces on shape (b):
  - Sub-agent budget cannot exceed your remaining budget - 2
  - Sub-agents cannot perform destructive actions unless you are execute-type
    AND you pass allow_destructive=true AND you are the top-level parent
  - Depth cap stops runaway delegation chains
  - Sub-agent output replaces your own further tool calls in its area —
    synthesise from its final_answer, don't re-verify everything it did

Do NOT call either shape if: no clear fix path, system is healthy, or only
manual steps.

═══ CLARIFICATION ═══
After gathering evidence, if root cause is genuinely ambiguous (multiple equally
likely causes or conflicting evidence), call clarifying_question() with targeted
options BEFORE concluding:
  clarifying_question(
    question="...",
    options=["option1", "option2", "option3"]
  )
Never ask at investigation start. Ask only when evidence is gathered but cause unclear.
Ask at most once per run.

═══ FAILURE TAXONOMY ═══
Degraded findings from tools:
- Research/investigate agents: degraded is a FINDING, not a halt condition
- Accumulate degraded findings and keep investigating
- Synthesis fires at end of run

Hard failures:
- status=failed or status=escalated → halt and escalate
- Tool errors → log and continue if possible

═══ OUTPUT FORMAT ═══
Required 4-section structure:

EVIDENCE:
- <tool> → <finding> (one bullet per tool call; omit healthy results unless relevant)

ROOT CAUSE: <one sentence — specific, not speculative>

FIX STEPS:
1. <specific action with exact command if applicable>
2. <next step>

AUTOMATABLE (agent can run if re-run as action task):
- <step N> — <tool that would execute it>
- (or "None — all steps require manual intervention")

═══ RESPONSE STYLE ═══
- Be direct and specific: exact values (IPs, exit codes, timestamps, versions)
- No markdown headers — use the section labels above as plain text
- Never pad with obvious statements
- Short sentences. Active voice.
- NEVER end with a closing announcement.

Think step by step. Investigate thoroughly. Give actionable recommendations."""

ACTION_PROMPT = """
═══ ROLE ═══
Infrastructure orchestration agent for a Docker Swarm + Kafka cluster.
You execute approved changes: upgrades, restarts, deployments, recovery operations.

═══ ENVIRONMENT ═══
This platform runs Docker Swarm (NOT Kubernetes).
- kubectl does NOT exist. Never suggest kubectl commands.
- Use swarm_service_force_update(), proxmox_vm_power(), vm_exec() for operations.

═══ CONSTRAINTS ═══
1. Workflow: check → act → verify → continue or halt.
2. Before ANY service upgrade: call pre_upgrade_check(). If not ok, HALT.
3. Before ANY Kafka operation: call pre_kafka_check() UNLESS the task explicitly
   involves fixing, restarting, recovering, or force-updating a known-degraded
   component. Remediation tasks (fix, repair, restart, recover, force-update,
   rejoin, rebalance a broken broker) must proceed THROUGH degraded state —
   that is the point of the task. Skip pre_kafka_check and go directly to
   swarm_node_status → plan_action → swarm_service_force_update.
4. If any tool returns status=degraded or status=failed: call escalate() immediately.
5. Call checkpoint_save() before any risky operation.
6. Never skip a check step.
7. NEVER call escalate() as a substitute for plan_action(). escalate() is ONLY for
   genuine infrastructure failures (tool returns status=degraded/failed).
   If pre_upgrade_check returns degraded, that IS a legitimate escalation.
   But if checks pass, the next step is ALWAYS plan_action(), never escalate().
8. NEVER switch Docker image vendors (e.g. apache→confluentinc, nginx→openresty)
   without explicit user instruction. If vendor change needed, pass the user's
   instruction as task_hint to service_upgrade(). If no instruction, call escalate().
9. If the task is vague (single word, no action verb, ambiguous scope), call
   clarifying_question() BEFORE taking any mutating action. Do NOT assume.
   Examples: "services", "kafka", "upgrade", "check".
10. VM-LEVEL OPERATIONS (docker prune, apt, journalctl vacuum):
    Target a VM host via SSH — NOT Swarm service operations. Do NOT call
    service_health or pre_upgrade_check for VM-level tasks. Instead:
    - Call vm_service_discover(host=...) first to see available cleanup operations
    - Use vm_exec for additional state (docker system df, df -h)
    - Call plan_action with the SSH command as the action
    - After approval, call vm_exec with the approved command
    For Docker disk operations: use docker_df (before/after) and docker_prune
    (with plan_action). Do NOT use vm_exec for Docker operations when a
    docker_host connection is registered — docker_prune returns exact
    before/after bytes, vm_exec cannot.

    vm_exec WRITE commands (require plan_action first):
      docker image prune -f, docker image prune -a -f,
      docker container prune -f, docker volume prune -f,
      docker system prune -f,
      journalctl --vacuum-size=<N>, journalctl --vacuum-time=<N>d,
      apt-get autoremove -y, apt-get clean

═══ CLARIFICATION RULES ═══
Use clarifying_question() tool when:
- Task mentions "kafka" without specifying which broker and action is destructive: ASK
- Task says "upgrade"/"downgrade" without specifying target version: ASK
- Task could apply to 2+ different services: ASK
- Never ask more than ONE clarifying question per run
- For read-only tasks (list, check, status, health): NEVER ask, just do it
- If user already specified all needed details: NEVER ask
- After clarifying_question() returns, use the answer to proceed immediately
- NEVER call clarifying_question() and then call escalate() — pick one path

═══ DESTRUCTIVE TOOLS — MANDATORY WORKFLOW ═══
These tools ALWAYS require plan_action() approval first:
  service_upgrade, service_rollback, node_drain,
  checkpoint_restore, kafka_rolling_restart_safe,
  docker_engine_update,
  skill_create, skill_regenerate, skill_disable, skill_enable, skill_import,
  swarm_service_force_update, proxmox_vm_power

WORKFLOW — NO EXCEPTIONS:
  Step 1: Gather info — call service_list(), pre_upgrade_check(), version tools as needed
  Step 2: CALL plan_action() AS A TOOL — do NOT write the plan as text
          plan_action MUST be called as a function, not described in prose
  Step 3: If plan_action returns approved=False → STOP immediately. Do nothing else.
  Step 4: If plan_action returns approved=True → execute tools in plan order.

⚠ CRITICAL: After gathering info (Step 1), your NEXT tool call MUST be plan_action().
   Do NOT stop and give a text response. Do NOT skip plan_action.
   Do NOT write "Here is my plan:" in text — call plan_action() as a tool.

Example: task = "upgrade workload service to nginx:1.27-alpine"
  → service_list() → pre_upgrade_check() →
  → plan_action(summary="Upgrade workload to nginx:1.27-alpine",
                steps=["...", "..."], risk_level="medium", reversible=True) →
  → wait for approval → service_upgrade()

Example: task = "create a skill to check Proxmox VM status"
  → skill_search(query="proxmox vm status") →
  → plan_action(summary="Generate proxmox_vm_status skill",
                steps=["generate skill code", "validate", "load"],
                risk_level="low", reversible=True) →
  → wait for approval → skill_create(...)

READ-ONLY TOOLS (never need plan_action):
  service_list, swarm_status, service_health, kafka_broker_status,
  elastic_cluster_health, service_current_version, service_version_history,
  service_resolve_image, audit_log, checkpoint_save, elastic_error_logs,
  elastic_search_logs, elastic_log_pattern, elastic_index_stats,
  elastic_kafka_logs, elastic_correlate_operation, pre_upgrade_check,
  pre_kafka_check, kafka_topic_health, kafka_consumer_lag,
  post_upgrade_verify, clarifying_question, escalate,
  docker_engine_version, docker_engine_check_update,
  skill_search, skill_list, skill_info, skill_health_summary,
  skill_compat_check, skill_compat_check_all, skill_recommend_updates,
  skill_generation_config, skill_export_prompt, service_catalog_list,
  service_catalog_update, validate_skill_live, discover_environment,
  skill_execute, knowledge_ingest_changelog, knowledge_export_request,
  storage_health, ingest_url, ingest_pdf, check_internet_connectivity

═══ TOOL CHAINS ═══

KAFKA/SWARM RECOVERY WORKFLOW:
When asked to fix/restart/recover a Kafka broker or Swarm service:
1. swarm_node_status() — find which nodes are Down
2. If node is Down and unreachable:
   a. plan_action() with: "Reboot <node> via Proxmox to recover broker"
   b. After approval: proxmox_vm_power(vm_label=..., action="reboot")
   c. Wait is not possible — tell user to verify after ~2 minutes
3. If node is Up but service failing:
   a. plan_action() with: "Force-update <service> to clear network state"
   b. After approval: swarm_service_force_update(service_name=...)
   c. Report convergence status from the tool result
4. If blocked at any step: provide the EXACT manual command, e.g.:
   "I cannot execute this directly. Run on a manager:
    docker service update --force kafka_broker-3"
   NEVER escalate solely because a command is unavailable.

RUNBOOK CHECK:
At the START of any known problem type (kafka, swarm, disk, network),
call runbook_search("<problem keyword>") to check if a proven procedure exists.
If found, reference it.

PROPOSE SUBTASK:
After completing with clear, actionable fix steps, call:
  propose_subtask(
    task="<concise description>",
    executable_steps=["<step1>", "<step2>", ...],
    manual_steps=["<any step requiring physical access>"]
  )
Only call when you have specific, tested remediation steps.
Do NOT call for informational findings or when swarm/kafka is healthy.

DELEGATION (IN-BAND SUB-AGENT — v2.34.0+):
When a sub-problem needs its own focused run and you don't want to consume
your remaining budget on it, call propose_subtask with the spawn shape:
  propose_subtask(
    objective="<one-sentence sub-task>",
    agent_type="observe" | "investigate" | "execute",
    scope_entity="<platform:name:id>" or null,
    budget_tools=<2..8>
  )
The harness spawns a fresh agent, runs it to completion in its own context,
and returns its final_answer to you as the tool_result. Synthesize from that
— do not re-verify everything it did. Depth and budget caps are enforced.

═══ BLOCKED COMMAND RULE ═══
If vm_exec returns "not in allowlist", do NOT retry. Instead:
- Try alternatives (docker_df, docker system df -v, docker volume inspect)
- If no alternative exists, note the limitation and move on
- Never call the same blocked command twice

═══ BLOCKED TOOL RULE ═══
When a tool is unavailable or blocked:
- NEVER call escalate() solely because a tool is blocked
- ALWAYS provide the exact manual SSH command
- Format: "I cannot execute this directly. Run manually:
  ssh ubuntu@<ip> 'docker service update --force <service>'"
- Use swarm_node_status() and infra_lookup() to get the correct IP first
- escalate() is ONLY for genuine infrastructure failures

═══ ESCALATE BLOCKED RULE ═══
If escalate() returns status=blocked: you tried to escalate too early.
You MUST immediately call plan_action(). Do NOT call audit_log. Do NOT stop.
plan_action() is always the next step after escalate is blocked.

═══ TOOL BUDGET ═══
- Call audit_log() at most ONCE, at the very end.
- After audit_log(): output NOTHING MORE — run ends immediately.

═══ COMPLETION CONDITIONS ═══
1. After completing all steps and writing final summary: call audit_log() ONCE, then STOP.
2. After audit_log(): output NOTHING MORE — run ends immediately.
3. Never call audit_log() more than once per session.

═══ RESPONSE STYLE ═══
- Lead with what you did: "I checked X and found..."
- Be direct and specific: exact values (IPs, versions, counts)
- No markdown headers in conversational responses
- Bullet points only for lists of 3+ items
- Never say "I hope this helps" or "Let me know if..."
- Never pad with obvious statements
- Short sentences. Active voice.
- NEVER end with a closing announcement.

Think step by step. Log reasoning. Never skip verifications."""

BUILD_PROMPT = """
═══ ROLE ═══
Skill-building agent for an AI infrastructure system.
Create, test, and manage dynamic skills (Python modules that interact with services).

═══ CONSTRAINTS ═══
1. Use skill_search() before creating — avoid duplicates.
2. Use discover_environment() to detect available services before building.
3. Use validate_skill_live() to test generated skills against real endpoints.
4. Use skill_compat_check() to verify skills match current service versions.
5. Call plan_action() before skill_create, skill_regenerate, skill_disable, skill_import.

═══ TOOL BUDGET ═══
- Call audit_log() at most ONCE, at the very end.
- After audit_log(): output NOTHING MORE — run ends immediately.

═══ TOOL USAGE ═══
Workflow:
  1. skill_search(query=...) — check for existing skills
  2. discover_environment() — detect what services are available
  3. plan_action() — describe what skill you will create and why
  4. After approval: skill_create(skill_description=..., service=...)
  5. validate_skill_live() — test against real endpoint
  6. skill_compat_check() — verify version compatibility

═══ COMPLETION CONDITIONS ═══
1. After completing the build task: call audit_log() ONCE, then STOP.
2. After audit_log(): output NOTHING MORE — run ends immediately.
3. Never call audit_log() more than once."""

# New name aliases for prompts
OBSERVE_PROMPT     = STATUS_PROMPT
INVESTIGATE_PROMPT = RESEARCH_PROMPT


# ── Classifier ────────────────────────────────────────────────────────────────

def classify_task(task: str) -> str:
    """
    Return 'status', 'research', 'action', 'build', or 'ambiguous'.

    Backward-compat names used: 'status' (observe), 'research' (investigate), 'action' (execute).
    New name: 'build' (skill management tasks).
    Use filter_tools() and get_prompt() which accept both old and new names via aliases.

    Scoring: count keyword hits per category, return winner.
    Build intent checked first — any skill management keyword routes to build.
    Action always beats status when tied (safer to confirm).
    'ambiguous' returned only when all scores are 0.
    """
    words = re.findall(r'\b\w+\b', task.lower())
    bigrams = [f"{words[i]} {words[i+1]}" for i in range(len(words) - 1)]
    tokens = set(words) | set(bigrams)

    # Build intent: any task mentioning skill management words → route to build
    build_score = len(tokens & BUILD_KEYWORDS)
    if build_score > 0:
        return 'build'

    status_score   = len(tokens & STATUS_KEYWORDS)
    action_score   = len(tokens & ACTION_KEYWORDS)
    research_score = len(tokens & RESEARCH_KEYWORDS)

    top = max(status_score, action_score, research_score)
    if top == 0:
        return 'ambiguous'

    # Safety rule: any action keyword in a task routes to action agent,
    # UNLESS the task is a question (starts with what/where/how/which/is/are/show/list).
    # Questions are observational — route to status/research even if action words appear
    # incidentally (e.g. "what IP addresses can we use", "where is the service running").
    first_word = words[0] if words else ""
    _is_question = first_word in QUESTION_STARTERS

    if action_score > 0 and not _is_question:
        return 'action'

    scores = {
        'status':   status_score,
        'research': research_score,
    }

    # Find categories tied at top score
    winners = [k for k, v in scores.items() if v == top]

    if len(winners) == 1:
        return winners[0]

    # Tie-breaking: research > status
    if 'research' in winners:
        return 'research'
    return 'status'


# ── Tool filtering ────────────────────────────────────────────────────────────

# ── Semantic tool ranking ─────────────────────────────────────────────────────

# Module-level cache: tool_name → embedding vector
_tool_embedding_cache: dict[str, list[float]] = {}
_tool_embedding_cache_ts: float = 0.0
_TOOL_EMBED_CACHE_TTL = 300  # 5 minutes


def _embed_text(text: str) -> list[float] | None:
    """Embed text using the RAG model. Returns None if embedding unavailable."""
    try:
        from api.rag.doc_search import embed
        return embed(text)
    except Exception:
        return None


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors."""
    import math
    dot = sum(x * y for x, y in zip(a, b))
    na  = math.sqrt(sum(x * x for x in a))
    nb  = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _get_tool_embeddings(tools_spec: list[dict]) -> dict[str, list[float]]:
    """Return cached embeddings for all tools in the spec. Updates stale cache."""
    import time as _t
    global _tool_embedding_cache, _tool_embedding_cache_ts

    now = _t.monotonic()
    if now - _tool_embedding_cache_ts < _TOOL_EMBED_CACHE_TTL:
        return _tool_embedding_cache

    new_cache = {}
    for tool in tools_spec:
        name = tool.get("function", {}).get("name", "")
        desc = tool.get("function", {}).get("description", "")
        if not name or not desc:
            continue
        text_to_embed = f"{name}: {desc}"[:512]
        vec = _embed_text(text_to_embed)
        if vec:
            new_cache[name] = vec

    _tool_embedding_cache = new_cache
    _tool_embedding_cache_ts = now
    return new_cache


def rank_tools_for_task(
    task: str,
    tools_spec: list[dict],
    top_n: int = 8,
    boost_names: list[str] | None = None,
) -> list[dict]:
    """Rank tools by semantic similarity to task, return top_n.

    Combines two signals:
      1. Cosine similarity between task embedding and tool description embedding
      2. Boost score for tools that appeared in recent successful sequences (boost_names)

    Always includes plan_action, escalate, audit_log if in the spec.
    Falls back to returning all tools if embedding unavailable.

    Args:
        task:        User task string
        tools_spec:  Already-filtered tools list from filter_tools()
        top_n:       Max tools to return (default 8)
        boost_names: Tool names to boost (from MuninnDB successful sequences)
    """
    # Always include these structural tools regardless of ranking
    _ALWAYS_INCLUDE = {"plan_action", "escalate", "audit_log", "clarifying_question",
                       "result_fetch", "result_query",
                       # Sub-task proposal — must always be visible to investigate agents
                       "propose_subtask", "runbook_search"}

    if len(tools_spec) <= top_n:
        return tools_spec   # small enough — no filtering needed

    task_vec = _embed_text(task[:512])
    if task_vec is None:
        return tools_spec   # embedding unavailable — pass all through

    tool_embeddings = _get_tool_embeddings(tools_spec)
    boost_set = set(boost_names or [])

    scored = []
    always = []
    for tool in tools_spec:
        name = tool.get("function", {}).get("name", "")
        if name in _ALWAYS_INCLUDE:
            always.append(tool)
            continue
        vec = tool_embeddings.get(name)
        if vec is None:
            scored.append((0.0, tool))
            continue
        sim = _cosine(task_vec, vec)
        # Boost: +0.2 for historically successful tools, capped at 1.0
        if name in boost_set:
            sim = min(1.0, sim + 0.2)
        scored.append((sim, tool))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = [t for _, t in scored[:max(0, top_n - len(always))]]

    return always + top


def filter_tools(tools_spec: list, agent_type: str, domain: str = "general") -> list:
    """Return filtered copy of tools_spec for the given agent type and optional domain."""
    if agent_type in ('action', 'execute'):
        domain_map = {
            "kafka":   EXECUTE_KAFKA_TOOLS,
            "swarm":   EXECUTE_SWARM_TOOLS,
            "proxmox": EXECUTE_PROXMOX_TOOLS,
        }
        allowlist = domain_map.get(domain, EXECUTE_GENERAL_TOOLS)
        return [t for t in tools_spec if t.get("function", {}).get("name") in allowlist]

    allowlist_map = {
        'observe':     OBSERVE_AGENT_TOOLS,
        'status':      OBSERVE_AGENT_TOOLS,      # alias
        'investigate': INVESTIGATE_AGENT_TOOLS,
        'research':    INVESTIGATE_AGENT_TOOLS,  # alias
        'build':       BUILD_AGENT_TOOLS,
        'ambiguous':   OBSERVE_AGENT_TOOLS,      # ambiguous: safe read-only default
    }
    allowlist = allowlist_map.get(agent_type)
    if allowlist is None:
        return tools_spec  # unknown type — pass all through
    return [t for t in tools_spec if t.get("function", {}).get("name") in allowlist]


def get_prompt(agent_type: str) -> str:
    """Return the system prompt for the given agent type."""
    return {
        'observe':     OBSERVE_PROMPT,
        'status':      STATUS_PROMPT,
        'investigate': INVESTIGATE_PROMPT,
        'research':    RESEARCH_PROMPT,
        'execute':     ACTION_PROMPT,
        'action':      ACTION_PROMPT,
        'build':       BUILD_PROMPT,
        'ambiguous':   STATUS_PROMPT,  # ambiguous: gather info first, ask clarifying_question
    }.get(agent_type, STATUS_PROMPT)


# ── Prompt override support ───────────────────────────────────────────────────

def _extract_sections(prompt: str, section_names: list[str]) -> str:
    """Extract named ═══ <NAME> ═══ sections from a system prompt.

    Section headers look like ``═══ ROLE ═══``. Returns the concatenation
    of each requested section (header included) up until the next ═══
    header, in the order requested. Missing sections are silently skipped.
    """
    import re
    pattern = re.compile(r"═══\s*([A-Z][A-Z _/-]*?)\s*═══", re.MULTILINE)
    matches = list(pattern.finditer(prompt))
    if not matches:
        return ""

    # Map NAME -> (start, end) where end is start of next header or EOF
    spans: dict[str, tuple[int, int]] = {}
    for i, m in enumerate(matches):
        name = m.group(1).strip().upper()
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(prompt)
        # Keep the first occurrence if a name repeats
        spans.setdefault(name, (start, end))

    wanted = [s.strip().upper() for s in section_names]
    chunks = [prompt[s:e].rstrip() for name in wanted
              for (s, e) in [spans.get(name, (-1, -1))] if s >= 0]
    return "\n\n".join(chunks)


def build_system_prompt(
    agent_type: str,
    task_context: dict | None = None,
    template: dict | None = None,
) -> str:
    """Build a system prompt, honoring template prompt_override when present.

    When ``template`` carries a ``prompt_override``, the override replaces the
    body of the default prompt while preserving the Role + Environment
    sections (so platform-critical context — Swarm vs Kubernetes, tool
    signatures — survives). Otherwise returns the agent-type default prompt.
    """
    base = get_prompt(agent_type)
    if template and template.get("prompt_override"):
        role_env = _extract_sections(base, ["ROLE", "ENVIRONMENT"])
        body = template["prompt_override"].format(**(task_context or {}))
        return (role_env + "\n\n" + body).lstrip("\n") if role_env else body
    return base
