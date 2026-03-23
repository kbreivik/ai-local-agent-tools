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
})

# Execute agent — destructive tools, filtered by domain
_EXECUTE_BASE = frozenset({
    "plan_action", "escalate", "audit_log", "clarifying_question",
    "checkpoint_save", "checkpoint_restore",
})

EXECUTE_KAFKA_TOOLS = frozenset({
    "pre_kafka_check", "kafka_broker_status", "kafka_topic_health",
    "kafka_consumer_lag", "kafka_rolling_restart_safe",
}) | _EXECUTE_BASE

EXECUTE_SWARM_TOOLS = frozenset({
    "swarm_status", "service_list", "service_health", "service_upgrade",
    "service_rollback", "node_drain", "pre_upgrade_check", "post_upgrade_verify",
    "service_current_version", "service_resolve_image",
}) | _EXECUTE_BASE

EXECUTE_PROXMOX_TOOLS = frozenset({
    # Promoted proxmox skills injected at startup via _load_promoted_into_allowlists()
}) | _EXECUTE_BASE

EXECUTE_GENERAL_TOOLS = frozenset({
    "service_upgrade", "service_rollback", "node_drain",
    "docker_engine_update",
}) | _EXECUTE_BASE

# Build agent — skill management tools only (no destructive infra tools)
BUILD_AGENT_TOOLS = frozenset({
    "skill_create", "skill_regenerate", "skill_disable", "skill_enable",
    "skill_import", "skill_search", "skill_list", "skill_info",
    "skill_health_summary", "skill_generation_config", "validate_skill_live",
    "discover_environment", "service_catalog_list", "storage_health",
    "skill_compat_check", "skill_compat_check_all", "skill_export_prompt",
    "plan_action", "audit_log", "escalate",
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
    except Exception:
        pass  # DB unavailable during tests


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

NETWORK QUERIES: For questions about IP addresses, hostnames, ports, or how to
connect to this agent from other machines: call get_host_network() tool first.

STOPPING RULES (MANDATORY):
- Once you have gathered all data and written your summary, output it as plain text with NO tool calls.
- After you call audit_log(), output NOTHING MORE — the run ends immediately after.
- Never call audit_log() more than once per session.
- Do NOT keep calling tools after you have the answer.

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
    Return 'observe', 'investigate', 'execute', 'build', or 'ambiguous'.
    Backward-compat: may also return 'status', 'research', 'action'.

    Scoring: count keyword hits per category, return winner.
    Build intent checked first — any skill management keyword routes to build.
    Action always beats status when tied (safer to confirm).
    'ambiguous' returned when top two categories are tied and both > 0.
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
    _QUESTION_STARTERS = frozenset({
        "what", "where", "how", "which", "is", "are", "show", "list",
        "who", "when", "why", "can", "could", "does", "do",
    })
    first_word = words[0] if words else ""
    _is_question = first_word in _QUESTION_STARTERS

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
