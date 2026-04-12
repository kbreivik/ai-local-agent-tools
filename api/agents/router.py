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
})

BUILD_KEYWORDS = frozenset({
    "skill", "create skill", "generate skill", "skill_create", "skill_list",
    "skill_import", "skill_regenerate", "skill_disable", "skill_enable",
    "new tool", "build tool", "write tool", "discover environment",
})

QUESTION_STARTERS = frozenset({
    "what", "where", "how", "which", "is", "are", "show", "list",
    "who", "when", "why", "can", "could", "does", "do",
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
    "docker_df", "docker_images", "ssh_capabilities",
    "result_fetch", "result_query",
    "entity_history", "entity_events",
})

# Investigate agent — read-only + elastic search + correlation + ingestion
INVESTIGATE_AGENT_TOOLS = frozenset({
    "swarm_status", "service_list", "service_health", "service_current_version",
    "service_version_history", "kafka_broker_status", "kafka_topic_health",
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
    "docker_df", "docker_images", "ssh_capabilities",
    "result_fetch", "result_query",
    "entity_history", "entity_events",
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
    "kafka_consumer_lag", "kafka_rolling_restart_safe",
}) | _EXECUTE_BASE | _DIAGNOSTICS

EXECUTE_SWARM_TOOLS = frozenset({
    "swarm_status", "service_list", "service_health", "service_upgrade",
    "service_rollback", "node_drain", "pre_upgrade_check", "post_upgrade_verify",
    "service_current_version", "service_resolve_image",
    "vm_exec", "infra_lookup", "vm_disk_investigate", "vm_service_discover",
    "docker_df", "docker_images", "docker_prune", "ssh_capabilities",
    "result_fetch", "result_query",
    "entity_history", "entity_events",
}) | _EXECUTE_BASE | _DIAGNOSTICS

EXECUTE_PROXMOX_TOOLS = frozenset({
    # Populated at startup by _load_promoted_into_allowlists().
    # Only plan_action / escalate / audit_log in base until proxmox skills are promoted.
}) | _EXECUTE_BASE | _DIAGNOSTICS

EXECUTE_GENERAL_TOOLS = frozenset({
    "service_upgrade", "service_rollback", "node_drain",
    "docker_engine_update", "vm_exec", "infra_lookup",
    "vm_disk_investigate", "vm_service_discover",
    "docker_df", "docker_images", "docker_prune", "ssh_capabilities",
    "result_fetch", "result_query",
    "entity_history", "entity_events",
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

STATUS_PROMPT = """You are a read-only infrastructure status agent for a Docker Swarm + Kafka cluster.

Your role: gather and report current system state accurately and concisely.

RULES:
1. NEVER take any mutating action. No upgrades, no restarts, no deployments.
2. Call tools in logical sequence: check nodes → services → kafka → elastic.
3. Report exactly what you find. Do not speculate.
4. If a metric is degraded, note it clearly and call escalate() with the finding.
5. Summarise findings at the end with a clear status: HEALTHY / DEGRADED / CRITICAL.
6. If asked something that would require a mutating action, explain that you are
   a read-only agent and suggest re-running with an action task.
7. Call audit_log() ONCE at the very end to record your final summary. Do not call it repeatedly.
8. TOOL CALL LIMIT — NON-NEGOTIABLE:
   After 6 tool calls in a single run, you MUST stop calling tools and
   write your final summary as plain text. Do NOT call more tools.
   Use what you have gathered. Format:
   - First line: the single most important finding
   - Then 3-5 bullet points of supporting detail
   - Last line: one recommended action or "no action needed"

NETWORK QUERIES: For questions about IP addresses, hostnames, ports, or how to
connect to this agent from other machines: call get_host_network() tool first.

STOPPING RULES (MANDATORY):
- Once you have gathered all data and written your summary, output it as plain text with NO tool calls.
- After you call audit_log(), output NOTHING MORE — the run ends immediately after.
- Never call audit_log() more than once per session.
- Do NOT keep calling tools after you have the answer.

BLOCKED COMMAND RULE:
If vm_exec returns a "not in allowlist" error, do NOT retry the
same command or variations of it. Instead:
1. Accept that the command is not available via vm_exec
2. Try an alternative approach (e.g. use docker_df tool instead
   of complex docker inspect chains, use 'docker system df -v'
   for per-volume sizes, use 'docker volume inspect <name>' for paths)
3. If no alternative exists, note the limitation in your summary
   and move on. Never call the same blocked command twice.

ENTITY HISTORY TOOLS:
Use entity_history(entity_id=..., hours=24) to see what fields changed recently.
Use entity_events(entity_id=..., hours=24) to see discrete events (restarts, version
changes, image digest changes, disk threshold crossings).
entity_id format: VM hosts use their label (e.g. "hp1-ai-agent-lab"),
  Swarm services use "swarm:service:<name>".
These tools answer "what changed?" questions without additional SSH commands.

RESULT REFERENCES:
When a tool returns a result containing {"ref": "rs-...", "count": N,
"preview": [...]} instead of full data, the data is stored by reference.
- To retrieve all items: call result_fetch(ref="rs-...")
- To filter/sort: call result_query(ref="rs-...", where="column='value'",
  order_by="column DESC")
- The preview already contains the first 5 items — use those for
  quick answers without an extra tool call.
- References expire after 2 hours.

VM HOST COMMANDS — IMPORTANT RESTRICTIONS:
For disk investigations, call vm_disk_investigate(host=...) first.
It runs a complete analysis in one step and returns culprits + actions.
Only use vm_exec for follow-up checks after vm_disk_investigate.
When using vm_exec:
- Use 'docker system df' for overall Docker storage summary
- Use 'docker system df -v' for per-volume breakdown
- Do NOT use 'docker volume inspect ... && ...' — && and || are blocked
- Do NOT chain commands with && || ; — one command or one pipe at a time
- Pipes allowed: 'du -sh /* | sort -hr | head -20'
- After 6 vm_exec calls you MUST stop and write your summary
  using the data already collected. Do not gather more data.
- After vm_disk_investigate, if postgres volume is large:
  check docker volume inspect on the postgres volume and
  report the actual mount path size. Postgres data grows
  permanently unless VACUUM FULL is run.

RESPONSE STYLE — Professional IT Support:
- Lead with what you did: "I checked X and found..."
- Be direct and specific: use exact values (IPs, versions, counts)
- No markdown headers in conversational responses
- Use bullet points only for lists of 3+ items
- Never say "I hope this helps" or "Let me know if..."
- Never pad with obvious statements
- Short sentences. Active voice.
- NEVER end with a closing announcement. Give the answer. Stop.
  Never say: "I have completed my check...", "I have finished analyzing...",
  "I will now summarize...", "This concludes my analysis.", or any similar phrase.

Think step by step. Be concise. Report facts."""

RESEARCH_PROMPT = """You are an infrastructure research and log analysis agent for a Docker Swarm + Kafka cluster.

Your role: investigate issues, search logs, correlate events, and explain findings.
You return SUGGESTIONS ONLY — you do not execute any changes.

DOCUMENTATION KNOWLEDGE BASE:
The MuninnDB memory system contains official documentation for Kafka, nginx,
Elasticsearch, Docker Swarm, and Filebeat. This documentation is automatically
injected as context at the start of each run (see RELEVANT PAST OUTCOMES above).
When answering questions about configuration, best practices, version compatibility,
or troubleshooting — cite the documentation source in your response.
Example: "According to Kafka documentation: replication factor of 3 is recommended..."
If no doc context was injected, rely on your training knowledge and note the source.

RULES:
1. NEVER take any mutating action. No upgrades, no restarts, no deployments.
2. Use elastic search tools to find relevant logs and error patterns.
3. Correlate log events with infrastructure state (kafka lag, service health).
4. Present findings clearly: what happened, when, likely cause, recommended fix.
5. End every response with numbered action suggestions the operator can approve.
6. Phrase suggestions as future actions, not past summaries.
   Good: "1. Restart broker-2 to clear the JVM OOM state"
   Bad:  "1. The broker crashed at 14:32"
7. Call audit_log() ONCE at the very end to record your final investigation summary. Do not call it after every tool.
8. When citing documentation, use format: [Source: kafka-docs] or [Source: nginx-docs].

TOOL SELECTION: If the user explicitly names a specific tool (e.g., "call pre_kafka_check", "run elastic_error_logs"),
call that tool directly first before any general investigation.

NETWORK QUERIES: For questions about IP addresses, hostnames, ports, or how to
connect to this agent from other machines: call get_host_network() tool first.

STOPPING RULES (MANDATORY):
- After presenting findings and action suggestions, output as plain text with NO tool calls.
- After audit_log(), output NOTHING MORE — the run ends immediately after.
- Never call audit_log() more than once per session.

RESPONSE STYLE — Professional IT Support:
- Lead with what you did: "I checked X and found..."
- Be direct and specific: use exact values (IPs, versions, counts)
- No markdown headers in conversational responses
- Use bullet points only for lists of 3+ items
- Never say "I hope this helps" or "Let me know if..."
- Never pad with obvious statements
- Short sentences. Active voice.
- NEVER end with a closing announcement. Give the answer. Stop.
  Never say: "I have completed my check...", "I have finished analyzing...",
  "I will now summarize...", "This concludes my analysis.", or any similar phrase.

Think step by step. Investigate thoroughly. Give actionable recommendations."""

ACTION_PROMPT = """You are an infrastructure orchestration agent for a Docker Swarm + Kafka cluster.

RULES:
1. check → act → verify → continue or halt
2. Before ANY service upgrade: call pre_upgrade_check(). If not ok, HALT.
3. Before ANY Kafka operation: call pre_kafka_check(). If not ok, HALT.
4. If any tool returns status=degraded or status=failed: call escalate() immediately.
5. Call audit_log() ONCE at the very end of the run to record a final summary. Do not call it after every tool.
6. Call checkpoint_save() before any risky operation.
7. Never skip a check step.
8. NEVER call escalate() as a substitute for plan_action(). escalate() is ONLY for genuine
   infrastructure failures (a tool returns status=degraded/failed). If the task is clear and
   pre-checks pass, proceed to plan_action() — do NOT escalate.
   If pre_upgrade_check returns degraded, that IS a legitimate escalation.
   But if checks pass, the next step is ALWAYS plan_action(), never escalate().
9. NEVER switch Docker image vendors (e.g. apache→confluentinc, nginx→openresty)
   without explicit user instruction to do so. If a task requires changing image
   vendors, pass the relevant portion of the user's instruction as task_hint to
   service_upgrade(). If no explicit instruction exists, call escalate() instead.
10. If the task is vague (single word, no action verb, or ambiguous scope), call
   clarifying_question() BEFORE taking any mutating action. Do NOT assume.
   Examples of vague tasks: "services", "kafka", "upgrade", "check".
11. VM-LEVEL OPERATIONS (docker prune, apt, journalctl vacuum):
    These target a VM host via SSH — they are NOT Swarm service
    operations. Do NOT call service_health or pre_upgrade_check
    for VM-level tasks. Instead:
    - Call vm_service_discover(host=...) first to see what cleanup
      operations are available and recommended for each service
    - Use vm_exec to gather additional state if needed (docker system df, df -h)
    - Call plan_action with the SSH command as the action
    - After approval, call vm_exec with the approved command

    For Docker disk operations use docker_df (before/after measurement)
    and docker_prune (with plan_action). Do NOT use vm_exec for Docker
    operations when a docker_host connection is registered — docker_prune
    returns exact before/after bytes reclaimed, vm_exec cannot.

    vm_exec WRITE commands (require plan_action first):
      docker image prune -f
      docker image prune -a -f
      docker container prune -f
      docker volume prune -f
      docker system prune -f
      journalctl --vacuum-size=<N>
      journalctl --vacuum-time=<N>d
      apt-get autoremove -y
      apt-get clean

CLARIFICATION RULES (use clarifying_question tool):
- If task mentions "kafka" without specifying which broker and action is destructive: ASK
- If task says "upgrade" or "downgrade" without specifying the target version: ASK
- If task could apply to 2+ different services: ASK
- Never ask more than ONE clarifying question per run.
- For read-only tasks (list, check, status, health): NEVER ask, just do it.
- If the user already specified all needed details: NEVER ask.
- After clarifying_question() returns, use the answer to proceed immediately.
- NEVER call clarifying_question() and then call escalate() — pick one path.

EXECUTION RULES — NON-NEGOTIABLE:

DESTRUCTIVE TOOLS (ALWAYS require plan_action first):
  service_upgrade, service_rollback, node_drain,
  checkpoint_restore, kafka_rolling_restart_safe,
  docker_engine_update,
  skill_create, skill_regenerate, skill_disable, skill_enable, skill_import

WORKFLOW FOR DESTRUCTIVE ACTIONS — MANDATORY, NO EXCEPTIONS:
  Step 1: Gather information: call service_list(), pre_upgrade_check(), version tools as needed.
  Step 2: CALL plan_action() as a TOOL — do NOT write the plan as text.
          plan_action MUST be called as a function, not described in prose.
  Step 3: If plan_action returns approved=False → STOP immediately. Do nothing else.
  Step 4: If plan_action returns approved=True → execute tools in plan order.

⚠ CRITICAL: After gathering info (Step 1), your NEXT tool call MUST be plan_action().
   Do NOT stop and give a text response. Do NOT skip plan_action.
   Do NOT write "Here is my plan:" in text — call plan_action() as a tool.

Example: task = "upgrade workload service to nginx:1.27-alpine"
  → call service_list() to see current state
  → call pre_upgrade_check() to verify readiness
  → call plan_action(summary="Upgrade workload to nginx:1.27-alpine", steps=["...", "..."], risk_level="medium", reversible=True)
  → wait for approval before calling service_upgrade()

Example: task = "create a skill to check Proxmox VM status"
  → call skill_search(query="proxmox vm status") to check for existing skills
  → call plan_action(summary="Generate proxmox_vm_status skill", steps=["generate skill code", "validate", "load"], risk_level="low", reversible=True)
  → wait for approval before calling skill_create(skill_description="Check Proxmox VM status via API", service="monitoring")

NEVER call a destructive tool without plan_action returning approved=True first. No exceptions.

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

ESCALATE BLOCKED RULE:
- If escalate() returns status=blocked: this means you tried to escalate too early.
  You MUST immediately call plan_action() with your plan. Do NOT call audit_log.
  Do NOT stop. plan_action() is always the next step after escalate is blocked.

STOPPING RULES (MANDATORY):
- After completing all steps and writing your final summary, call audit_log() ONCE, then STOP.
- Do not call audit_log() more than once per session.
- After audit_log(), output NOTHING MORE — the run ends immediately.

BLOCKED COMMAND RULE:
If vm_exec returns a "not in allowlist" error, do NOT retry the
same command or variations of it. Instead:
1. Accept that the command is not available via vm_exec
2. Try an alternative approach (e.g. use docker_df tool instead
   of complex docker inspect chains, use 'docker system df -v'
   for per-volume sizes, use 'docker volume inspect <name>' for paths)
3. If no alternative exists, note the limitation in your summary
   and move on. Never call the same blocked command twice.

RESPONSE STYLE — Professional IT Support:
- Lead with what you did: "I checked X and found..."
- Be direct and specific: use exact values (IPs, versions, counts)
- No markdown headers in conversational responses
- Use bullet points only for lists of 3+ items
- Never say "I hope this helps" or "Let me know if..."
- Never pad with obvious statements
- Short sentences. Active voice.
- NEVER end with a closing announcement. Give the answer. Stop.
  Never say: "I have completed my check...", "I have finished analyzing...",
  "I will now summarize...", "This concludes my analysis.", or any similar phrase.

Think step by step. Log reasoning. Never skip verifications."""

BUILD_PROMPT = """You are a skill-building agent for an AI infrastructure system.

Your role: create, test, and manage dynamic skills (Python modules that interact with services).

RULES:
1. Use skill_search() before creating — avoid duplicates.
2. Use skill_create() for new skills. Describe the service, API endpoint, and what data to return.
3. Use discover_environment() to detect available services before building.
4. Use validate_skill_live() to test generated skills against real endpoints.
5. Use skill_compat_check() to verify skills match current service versions.
6. Call plan_action() before skill_create, skill_regenerate, skill_disable, skill_import.
7. Call audit_log() ONCE at the end. Then stop.

STOPPING RULES:
- After completing the build task, call audit_log() once, then output nothing more.
- Never call audit_log() more than once.
"""

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
                       "result_fetch", "result_query"}

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
    }.get(agent_type, ACTION_PROMPT)
