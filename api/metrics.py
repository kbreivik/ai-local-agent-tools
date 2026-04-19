"""
Central Prometheus metric definitions and /metrics exposition.
Keep naming stable: deathstar_<area>_<unit>_<suffix>.
"""
from prometheus_client import (
    Counter, Histogram, Gauge, Info,
    CONTENT_TYPE_LATEST, generate_latest, CollectorRegistry, REGISTRY,
)

# --- collectors ---
COLLECTOR_POLL_SECONDS = Histogram(
    "deathstar_collector_poll_seconds",
    "Collector poll duration",
    ["platform"],
    buckets=(0.1, 0.5, 1, 2, 5, 10, 20, 30, 60),
)
COLLECTOR_POLL_FAILURES = Counter(
    "deathstar_collector_poll_failures_total",
    "Collector poll failures",
    ["platform", "reason"],
)

# --- agent ---
AGENT_TASKS = Counter(
    "deathstar_agent_tasks_total",
    "Agent tasks by type and terminal status",
    ["agent_type", "status"],   # status: success, escalated, budget_exhausted, failed
)
AGENT_TOOL_CALLS = Counter(
    "deathstar_agent_tool_calls_total",
    "Tool calls made by agents",
    ["agent_type", "tool"],
)
AGENT_WALL_SECONDS = Histogram(
    "deathstar_agent_task_seconds",
    "Agent task wall-clock time",
    ["agent_type"],
    buckets=(1, 5, 10, 30, 60, 120, 300, 600),
)

# --- escalations ---
ESCALATIONS = Counter(
    "deathstar_escalations_total",
    "Escalations raised",
    ["reason"],
)

# --- kafka ---
KAFKA_UNDER_REPLICATED = Gauge(
    "deathstar_kafka_under_replicated_partitions",
    "Partitions where ISR != replicas",
    ["topic"],
)
KAFKA_BROKERS_UP = Gauge(
    "deathstar_kafka_brokers_up",
    "Reachable brokers in cluster",
)

# --- sub-agents (v2.34.4) ---
SUBAGENT_SPAWN_COUNTER = Counter(
    "deathstar_subagent_spawns_total",
    "Sub-agent spawn attempts by outcome",
    # spawned | rejected_depth | rejected_budget | rejected_destructive | proposal_only
    ["outcome"],
)

# --- budget nudges (v2.34.5) ---
BUDGET_NUDGE_COUNTER = Counter(
    "deathstar_agent_budget_nudges_total",
    "Budget nudges fired by outcome",
    # proposed_and_spawned | proposed_and_refused | not_proposed | diagnosis_present
    ["outcome"],
)

# --- hallucination guard (v2.34.8) ---
HALLUCINATION_GUARD_COUNTER = Counter(
    "deathstar_agent_hallucination_guards_total",
    "Final-answer attempts blocked by the substantive-tool-call guard",
    # outcome: retried | fallback_accepted
    ["agent_type", "outcome"],
)

# --- tool signature errors (v2.34.9) ---
TOOL_SIGNATURE_ERROR_COUNTER = Counter(
    "deathstar_tool_signature_errors_total",
    "Tool call TypeError / signature mismatch failures",
    ["tool_name"],
)

# --- vm_exec safe-pipe usage (v2.34.10) ---
VM_EXEC_PIPE_COUNTER = Counter(
    "deathstar_vm_exec_pipe_usage_total",
    "vm_exec calls that use a safe pipe stage",
    ["pipe_stage"],  # head | tail | grep | wc | sort | uniq | awk | sed | cut | tr
)

# --- vm_exec boolean chains (v2.35.9) ---
VM_EXEC_CHAIN_COUNTER = Counter(
    "deathstar_vm_exec_chain_operators_total",
    "Count of vm_exec commands using && or || boolean chains.",
    ["op"],
)

# --- task classifier decisions (v2.34.11) ---
CLASSIFIER_DECISIONS_COUNTER = Counter(
    "deathstar_agent_classifier_decisions_total",
    "Task classifier routing decisions by agent type and trigger",
    ["agent_type", "trigger"],
    # trigger values: 'build_keyword', 'research_starter', 'research_bigram',
    #                 'action_keyword', 'keyword_score', 'ambiguous'
)

# --- container introspection tools (v2.34.12) ---
CONTAINER_INTROSPECT_COUNTER = Counter(
    "deathstar_container_introspect_total",
    "Container-introspection tool invocations",
    ["tool", "outcome"],   # outcome: 'ok' | 'error'
)

# --- prompt tool mentions (v2.34.13) ---
PROMPT_TOOL_MENTION_COUNTER = Counter(
    "deathstar_prompt_tool_mention_total",
    "Tool names mentioned in system prompts per agent type — "
    "a smoke test for prompt-retarget regressions",
    ["agent_type", "tool"],
)

# --- hallucination hardening (v2.34.14) ---
HALLUC_GUARD_ATTEMPTS_COUNTER = Counter(
    "deathstar_halluc_guard_attempts_total",
    "Hallucination-guard attempts by attempt number",
    ["attempt", "agent_type"],
)

HALLUC_GUARD_EXHAUSTED_COUNTER = Counter(
    "deathstar_halluc_guard_exhausted_total",
    "Agent runs that exhausted all hallucination-guard retries (task failed)",
    ["agent_type"],
)

FABRICATION_DETECTED_COUNTER = Counter(
    "deathstar_fabrication_detected_total",
    "Final answers rejected for citing uncalled tools",
    ["agent_type", "is_subagent"],
)

SUBAGENT_DISTRUST_INJECTED_COUNTER = Counter(
    "deathstar_subagent_distrust_injected_total",
    "Parent runs where sub-agent output was flagged as low-confidence",
    ["reason"],   # "halluc_guard_fired" | "fabrication_detected"
)

LLM_TRACES_WRITTEN_COUNTER = Counter(
    "deathstar_llm_traces_written_total",
    "LLM trace rows written to DB",
    ["step_type"],   # "root" | "subagent"
)

# --- prompt rendering + sanitizer + budget (v2.34.15) ---
SANITIZER_BLOCKS_COUNTER = Counter(
    "deathstar_sanitizer_blocks_total",
    "Times the LLM-inbound sanitizer redacted content",
    # pattern ∈ {jwt, uuid_key_ctx, api_key, injection, role_tag, length_cap}
    # site    ∈ {tool_result, system_prompt, entity_history, entity_ask, rag, other}
    ["pattern", "site"],
)

BUDGET_TRUNCATE_COUNTER = Counter(
    "deathstar_agent_budget_truncate_total",
    "Tool-call batches truncated to fit within the remaining per-run budget",
    ["agent_type"],
)

PROMPT_SNAPSHOT_DIVERGED_COUNTER = Counter(
    "deathstar_prompt_snapshot_diverged_total",
    "Agent prompt rendered at startup differs from the committed snapshot",
    ["prompt_name"],
)

# --- propose_subtask idempotency + sub-agent terminal feedback (v2.34.16) ---
PROPOSE_DUPLICATE_COUNTER = Counter(
    "deathstar_propose_subtask_duplicate_total",
    "propose_subtask calls rejected as duplicates of an earlier proposal in the same parent run. "
    "prior_status reflects where the earlier proposal was in its lifecycle when the duplicate landed.",
    ["prior_status"],   # pending | spawned | rejected_budget | completed | escalated | failed
)

SUBAGENT_TERMINAL_FEEDBACK_COUNTER = Counter(
    "deathstar_subagent_terminal_feedback_total",
    "Harness feedback messages injected into parent after a sub-agent terminated",
    ["terminal_status"],   # completed | escalated | failed | timeout | cap_hit
)

# --- forced synthesis on loop-exit (v2.34.17) ---
FORCED_SYNTHESIS_COUNTER = Counter(
    "deathstar_forced_synthesis_total",
    "Forced-synthesis steps run after budget-cap or similar loop-exit conditions",
    # reason ∈ {budget_cap, wall_clock, token_cap, destructive_cap, tool_failures}
    ["reason", "agent_type"],
)

FORCED_SYNTHESIS_FABRICATED_COUNTER = Counter(
    "deathstar_forced_synthesis_fabricated_total",
    "Forced-synthesis outputs flagged by the fabrication detector",
    ["agent_type"],
)

# --- skills (v2.34.2) ---
SKILL_EXEC_COUNTER = Counter(
    "deathstar_skill_executions_total",
    "Total skill executions by skill and outcome",
    ["skill_id", "outcome"],
)
SKILL_DURATION = Histogram(
    "deathstar_skill_duration_seconds",
    "Skill execution duration",
    ["skill_id"],
    buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60),
)
AUTO_PROMOTER_SCANS = Counter(
    "deathstar_auto_promoter_scans_total",
    "Auto-promoter scan invocations",
    ["triggered_by"],
)

# --- known_facts (v2.35.0) ---
KNOWN_FACTS_TOTAL = Gauge(
    "deathstar_known_facts_total",
    "Total rows in known_facts_current",
)
KNOWN_FACTS_CONFIDENT_TOTAL = Gauge(
    "deathstar_known_facts_confident_total",
    "Rows with confidence >= factInjectionThreshold",
)
KNOWN_FACTS_CONFLICTS_TOTAL = Gauge(
    "deathstar_known_facts_conflicts_total",
    "Pending unresolved conflicts",
)
FACTS_UPSERTED_COUNTER = Counter(
    "deathstar_facts_upserted_total",
    "Fact upsert actions",
    ["source", "action"],   # action ∈ {insert, touch, change, contradict, conflict, noop}
)
FACTS_CONTRADICTIONS_COUNTER = Counter(
    "deathstar_facts_contradictions_total",
    "Cross-source contradictions detected",
    ["source_a", "source_b"],
)
FACTS_LOCK_EVENTS_COUNTER = Counter(
    "deathstar_facts_lock_events_total",
    "Lock lifecycle events",
    ["action"],   # created | removed | enforced | overridden
)
FACTS_REFRESH_STALE_GAUGE = Gauge(
    "deathstar_facts_refresh_stale_total",
    "Facts past expected refresh cadence",
    ["platform"],
)

# --- in-run contradiction + agent_observation fact writes (v2.35.2) ---
INRUN_CONTRADICTION_COUNTER = Counter(
    "deathstar_inrun_contradictions_total",
    "Cross-tool contradictions detected within a single agent run",
    ["fact_key_prefix"],   # truncated to first 3 dotted segments for cardinality safety
)

AGENT_OBSERVATION_FACTS_WRITTEN_COUNTER = Counter(
    "deathstar_agent_observation_facts_written_total",
    "Facts written to known_facts from completed agent runs",
    # wrote | skipped_fabrication | skipped_halluc | skipped_nonterminal | skipped_cap
    ["wrote_or_skipped"],
)

# --- fact-age rejection (v2.35.3) ---
FACT_AGE_REJECTIONS_COUNTER = Counter(
    "deathstar_fact_age_rejections_total",
    "Tool results modified or blocked due to disagreement with recent facts",
    ["mode", "source_rejected"],   # mode: soft|medium|hard, source_rejected: agent_tool
)

# --- preflight (v2.35.1) ---
PREFLIGHT_RESOLUTIONS_COUNTER = Counter(
    "deathstar_preflight_resolutions_total",
    "Preflight resolution outcomes",
    ["outcome"],   # direct | regex | keyword_db | llm_fallback | ambiguous | zero_hit
)
PREFLIGHT_DISAMBIGUATION_OUTCOME_COUNTER = Counter(
    "deathstar_preflight_disambiguation_outcome_total",
    "How users resolved an ambiguous preflight",
    ["result"],    # auto_proceed | user_picked | cancelled | timeout
)
PREFLIGHT_FACTS_INJECTED = Histogram(
    "deathstar_preflight_facts_injected_count",
    "Facts injected per preflight",
    buckets=(0, 1, 2, 5, 10, 20, 40, 100),
)

# Added in v2.35.5 — which resolution path produced the injected facts.
PREFLIGHT_FACT_SOURCE_COUNTER = Counter(
    "deathstar_preflight_fact_source_total",
    "Which resolution path produced the facts injected at preflight",
    ["source"],   # inventory_match | direct_entity | ambiguous_skip | no_facts_found
)

# --- runbook injection (v2.35.4) ---
RUNBOOK_MATCHES_COUNTER = Counter(
    "deathstar_runbook_matches_total",
    "Runbook matches by injection mode",
    ["runbook_name", "mode"],   # mode: augment | replace | replace+shrink
)
RUNBOOK_SELECTION_DECISIONS_COUNTER = Counter(
    "deathstar_runbook_selection_decisions_total",
    "Classifier outcomes",
    ["classifier_mode", "outcome"],   # outcome: matched | no_match | disabled
)

# --- build info ---
BUILD = Info("deathstar_build", "Build metadata")


def render_metrics() -> tuple[bytes, str]:
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
