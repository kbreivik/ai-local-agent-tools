# DEATHSTAR Agent Harness — Design, Constraints & Performance Guide
## Version: 2.26.x (April 2026)

Reference for understanding, testing, and improving agent task execution.
This document covers the full pipeline from user input to final output.

---

## 1. Architecture at a Glance

```
User Input (task string)
       │
       ▼
┌─────────────────────────────────────────────────────────────┐
│                    CLASSIFIER (router.py)                    │
│  keyword scoring: status | research | action | build         │
│  question-starter check: is this a question → never action   │
│  domain detection: kafka | swarm | proxmox | elastic | vm    │
└───────────────┬────────────────────────────────────┬────────┘
                │ agent_type + domain                 │
                ▼                                     │
┌──────────────────────────┐                          │
│     TOOL FILTERING        │                          │
│  allowlist per agent_type │◄─────────────────────────┘
│  + per-domain for execute │
│  semantic ranking (RAG)   │
│  always: plan/escalate/   │
│  audit_log/clarify        │
└───────────┬──────────────┘
            │ filtered + ranked tool spec
            ▼
┌──────────────────────────────────────────────────────────────┐
│                    LM STUDIO  (Qwen3-30B)                    │
│  system prompt (per agent type) + task + memory context      │
│  temperature: 0.1 (tool steps) / 0.3 (summary / force)      │
│  /no_think suffix on audit_log-only steps                    │
└───────────┬──────────────────────────────────────────────────┘
            │ tool calls / text
            ▼
┌──────────────────────────────────────────────────────────────┐
│                    AGENT LOOP (agent.py)                     │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ For each LLM turn:                                      │ │
│  │  • decode tool calls                                    │ │
│  │  • check DESTRUCTIVE_TOOLS → require plan_action gate   │ │
│  │  • invoke_tool() → MCP server → tool function           │ │
│  │  • _summarize_tool_result() → compact for LLM context   │ │
│  │  • broadcast result via WebSocket                       │ │
│  │  • check cancel flag / max step limit                   │ │
│  └─────────────────────────────────────────────────────────┘ │
└───────────┬──────────────────────────────────────────────────┘
            │ stream to frontend
            ▼
┌──────────────────────────────────────────────────────────────┐
│              RESULT STORE + OPERATION LOG                    │
│  large results → result_store (2h TTL, ref-based retrieval)  │
│  final_answer + session → operation_log (persistent)         │
│  escalations → agent_escalations table                       │
└──────────────────────────────────────────────────────────────┘
```

---

## 2. The Classifier

**File:** `api/agents/router.py` → `classify_task()`

### How it scores

```
Input tokens = words ∪ bigrams (lowercase)

BUILD check first:  any "skill", "create skill", "skill_list" → "build" immediately
Then:
  status_score   = |tokens ∩ STATUS_KEYWORDS|
  action_score   = |tokens ∩ ACTION_KEYWORDS|
  research_score = |tokens ∩ RESEARCH_KEYWORDS|

Safety rule: if first_word in QUESTION_STARTERS → never route to action
             (questions are always observe or research, even with action words)

If action_score > 0 AND NOT a question → "action"
If tie between status + research → research wins
If all scores = 0 → "ambiguous" (falls through to action prompt in most paths)
```

### Domain detection (for execute routing)

```
kafka:   broker | topic | consumer | lag | partition | kraft
swarm:   swarm | service | replica | manager | worker | container | docker
proxmox: proxmox | vm | lxc | pve | snapshot | qemu | kvm
elastic: elastic | elasticsearch | kibana | index | shard | filebeat
vm_host: disk | space | memory | ram | load | cpu | ssh | host | log | prune
```

→ Determines which EXECUTE tool allowlist is used.

### Known classifier weaknesses

| Issue | Example | Effect |
|---|---|---|
| "restart" without context | "restart kafka" | Routes to action — correct, but skips research |
| Ambiguous vague tasks | "services" / "kafka" | action prompt but clarification gate fires |
| Research with action words | "find out why restart failed" | `find` is QUESTION_STARTER → research ✓ |
| Fix steps inside research | "diagnose and fix" | research route, fix steps never executed |
| "investigate" always → research | "investigate and restart" | never hits action; user must re-run |

---

## 3. Agent Types

Four types, each with a distinct system prompt, tool allowlist, and behavioral contract.

### 3a. Observe (status/read-only)

**Prompt:** `STATUS_PROMPT` | **Alias:** `observe`, `status`

| Contract | Value |
|---|---|
| Max tool calls | 6 (hard stop, force summary) |
| Writes anything? | No — read-only tools only |
| Pre-flight required? | No |
| Plan required? | No |
| escalate() role | Only on tool status=failed or unreachable |
| Output format | Conversational, facts-only, HEALTHY/DEGRADED/CRITICAL at end |

**Key tools available:**
- swarm_status, service_list, service_health, kafka_broker_status
- vm_exec (SSH read cmds), kafka_exec, swarm_node_status
- elastic_cluster_health, elastic_index_stats
- entity_history, entity_events, metric_trend, list_metrics
- result_fetch, result_query, service_placement, resolve_entity
- skill_search, skill_list (read-only)
- runbook_search

**Performance bottlenecks:**
- 6-tool limit forces early summary on complex multi-service checks
- `vm_exec` allowlist blocks many diagnostic commands → agent must use alternatives
- Semantic ranking may push relevant tools below top_n cutoff

---

### 3b. Investigate (research/diagnose)

**Prompt:** `RESEARCH_PROMPT` | **Alias:** `investigate`, `research`

| Contract | Value |
|---|---|
| Min tool calls | 4 before concluding (enforced by prompt) |
| Writes anything? | No — read-only + elastic + ingest |
| Pre-flight required? | No |
| Plan required? | No |
| escalate() role | Never for blocked tools |
| Output format | Structured 4-section: EVIDENCE / ROOT CAUSE / FIX STEPS / AUTOMATABLE |

**Extra tools vs observe:**
- elastic_error_logs, elastic_search_logs, elastic_log_pattern
- elastic_kafka_logs, elastic_correlate_operation
- ingest_url, ingest_pdf, search_docs
- skill_compat_check, skill_compat_check_all, skill_recommend_updates
- propose_subtask (→ creates sub-task offer in UI)

**Mandatory investigation chains:**
```
Kafka broker missing:
  kafka_broker_status → service_placement → swarm_node_status
  → vm_exec(docker ps) → vm_exec(docker logs --tail 50)
  → elastic_kafka_logs

exit code 137 (SIGKILL):
  MUST call vm_exec(dmesg | grep oom)
  before concluding OOM — could be normal Swarm lifecycle
```

**Performance bottlenecks:**
- Multi-step chains require correct tool parameter format (easy to hallucinate)
- `propose_subtask` often not called even when clear fix path exists
- Evidence section sometimes skips tier 2/3 when tier 1 shows degraded

---

### 3c. Execute (action/destructive)

**Prompt:** `ACTION_PROMPT` | **Alias:** `execute`, `action`

| Contract | Value |
|---|---|
| Pre-flight: service upgrades | pre_upgrade_check() — halt if degraded |
| Pre-flight: Kafka ops | pre_kafka_check() — bypass for remediation tasks |
| Plan gate | plan_action() REQUIRED before DESTRUCTIVE_TOOLS |
| Verification | post_upgrade_verify() after upgrades |
| escalate() role | Tool returns status=degraded/failed only |
| VM ops | vm_service_discover() first, then plan_action + vm_exec |

**DESTRUCTIVE_TOOLS (always require plan_action):**
```
service_upgrade       service_rollback       node_drain
kafka_rolling_restart_safe                   checkpoint_restore
docker_engine_update  docker_prune
skill_create          skill_regenerate       skill_disable
skill_enable          skill_import
swarm_service_force_update                   proxmox_vm_power
```

**Tool allowlists by domain:**

| Domain | Additional tools vs base |
|---|---|
| kafka | pre_kafka_check, kafka_rolling_restart_safe, kafka_exec, swarm_service_force_update |
| swarm | service_upgrade, service_rollback, node_drain, pre_upgrade_check, post_upgrade_verify, vm_exec, docker_prune |
| proxmox | proxmox_vm_power (+ promoted skills) |
| general | service_upgrade, service_rollback, docker_prune, vm_exec, proxmox_vm_power, swarm_service_force_update |

**All execute domains include:** plan_action, escalate, audit_log, clarifying_question,
checkpoint_save/restore, agent_status, postgres_health, service_logs,
vm_exec_allowlist_*, runbook_search, resolve_entity, entity_history, entity_events

**Performance bottlenecks:**
- plan_action gate introduces user-in-the-loop latency (intentional)
- Vague tasks trigger clarifying_question before any action
- Escalate-when-blocked is a known failure mode (prompt tries to prevent it)
- escalate-blocked → must call plan_action (sometimes model forgets)

---

### 3d. Build (skill management)

**Prompt:** `BUILD_PROMPT`

| Contract | Value |
|---|---|
| Scope | skill_create/regenerate/disable/enable/import + discovery |
| Plan required? | Yes — skill_create/regenerate/disable are destructive |
| Validation | validate_skill_live() after create |
| escalate() | Available |

**Tools:** skill_* family, discover_environment, service_catalog_list,
validate_skill_live, plan_action, audit_log, escalate, vm_exec_allowlist_*

**Promoted skills:** After `lifecycle_state=promoted`, skills are automatically
injected into the relevant EXECUTE domain allowlist at startup via
`_load_promoted_into_allowlists()`.

---

## 4. Tool System

### 4a. Tool filtering + ranking pipeline

```
All tools in registry (from mcp_server/server.py)
        │
        ▼
filter_tools(agent_type, domain)
  → intersection with agent allowlist
  → for execute: also domain allowlist (kafka/swarm/proxmox/general)
        │
        ▼
rank_tools_for_task(task, filtered_spec, top_n=8)
  → embed task string (RAG model)
  → embed each tool description (cached 5 min)
  → cosine similarity ranking
  → +0.2 boost for MuninnDB-remembered successful sequences
  → always include: plan_action, escalate, audit_log, clarifying_question,
                    result_fetch, result_query, propose_subtask, runbook_search
        │
        ▼
LLM sees: ranked top_n + always-include set
```

**Risk:** If top_n is too small, critical tools get dropped. If semantic ranking
is poor quality (embeddings don't match tool descriptions well), wrong tools surface.

### 4b. Tool categories by function

| Category | Tools |
|---|---|
| Swarm read | swarm_status, service_list, service_health, service_current_version, service_version_history |
| Swarm write | service_upgrade, service_rollback, node_drain, node_activate, swarm_service_force_update |
| Kafka read | kafka_broker_status, kafka_topic_health, kafka_consumer_lag, kafka_topic_list |
| Kafka write | kafka_rolling_restart_safe, kafka_exec (blocked cmds via allowlist) |
| VM / SSH | vm_exec, vm_disk_investigate, vm_service_discover, kafka_exec, ssh_capabilities |
| Docker local | docker_df, docker_images, docker_prune, service_logs, docker_engine_version |
| Elastic | elastic_cluster_health, elastic_index_stats, elastic_error_logs, elastic_search_logs, elastic_log_pattern, elastic_kafka_logs, elastic_correlate_operation |
| Proxmox | proxmox_vm_power |
| Metrics | metric_trend, list_metrics |
| Entity | entity_history, entity_events, resolve_entity |
| Memory | result_fetch, result_query |
| Gates | plan_action, escalate, pre_upgrade_check, pre_kafka_check, post_upgrade_verify, checkpoint_save, checkpoint_restore |
| Control flow | clarifying_question, audit_log, propose_subtask, runbook_search |
| Infra lookup | infra_lookup, swarm_node_status, service_placement, get_host_network |
| Skills | skill_search, skill_list, skill_info, skill_create, skill_regenerate, skill_disable, skill_enable, skill_import, skill_health_summary, validate_skill_live, discover_environment |
| Ingest | ingest_url, ingest_pdf, search_docs |
| Allowlist | vm_exec_allowlist_list, vm_exec_allowlist_request, vm_exec_allowlist_add |

### 4c. vm_exec allowlist

`vm_exec` runs SSH commands on vm_host connections. All commands are validated
against a two-layer allowlist at runtime:

```
Layer 1: BASE_PATTERNS (hardcoded, always present, seeded into DB as is_base=True)
  df, du, free, uptime, uname, hostname, whoami, date, timedatectl
  docker ps, docker images, docker logs, docker inspect, docker system df
  docker service ls, docker service ps, docker node ls
  ... (full list in api/db/vm_exec_allowlist.py)

Layer 2: DB patterns (user-managed via Settings → Allowlist tab)
  scope=permanent   — persists across restarts
  scope=session     — auto-deleted when session ends
```

**Blocked → agent must provide manual SSH command instead of escalating.**

Commands NOT on allowlist and how agent should respond:
```
Blocked: docker service update --force <svc>  →  swarm_service_force_update() tool
Blocked: complex && chains                     →  split into single commands
Blocked: docker volume inspect && ...          →  docker_df tool, or vm_disk_investigate
```

### 4d. Large result handling

When a tool returns a large list (>3000 bytes, >5 items):
```
Tool result                     →   result_store (Postgres, 2h TTL)
                                →   returns: {"ref": "rs-...", "count": N, "preview": [first 5]}
LLM sees the preview immediately
LLM can call result_fetch(ref=...) for full list
LLM can call result_query(ref=..., where=..., order_by=...) to filter
```

---

## 5. Gates & Checks

### 5a. plan_action gate

Called by agent as a tool. Returns `approved=True/False` based on user confirmation
in the UI (or auto-approved if plan_lock is open). Controls all destructive operations.

```python
# Agent must call this BEFORE destructive tools:
plan_action(
    summary="Brief description of what will happen",
    steps=["Step 1: ...", "Step 2: ..."],
    risk_level="low" | "medium" | "high",
    reversible=True | False
)
# Returns: {"approved": True/False, "plan_id": "..."}
```

**Failure modes:**
- Agent writes plan as text instead of calling plan_action() as tool → no gate fires
- Agent calls escalate() instead of plan_action() when checks pass
- escalate() returns status=blocked → agent must then call plan_action() (sometimes forgets)

### 5b. Pre-flight checks

| Check | When used | What it does | Skip when |
|---|---|---|---|
| pre_upgrade_check() | Before service_upgrade | Full swarm readiness: node count, replica health, quorum | Never |
| pre_kafka_check() | Before Kafka operations | Broker health, ISR state, consumer lag | Task is a remediation (fix/repair/recover/restart/force-update) |

**Pre-flight bypass rule (critical):**
Remediation tasks — tasks that explicitly fix a known-broken component — skip
`pre_kafka_check` because checking health before fixing what's broken is circular.
Precautionary operations (expanding cluster, adding partitions) still gate.

### 5c. Escalation

`escalate()` is a tool that creates a persistent escalation record and fires
the `escalation_recorded` WebSocket event (amber banner in UI).

**Correct use:** Tool returned `status=degraded` or `status=failed` — real infra failure.
**Wrong use:** Calling escalate() because a tool is not in the allowlist.
**Blocked response:** When escalate is called before plan_action, it returns
`status=blocked` — agent must then call plan_action().

### 5d. clarifying_question

A tool that pauses the agent loop and presents choices to the user in the UI.

```python
clarifying_question(
    question="Which broker should I restart?",
    options=["kafka_broker-1 (worker-01)", "kafka_broker-2 (worker-02)", "All three"]
)
```

**Fire when:** Task is vague (single word, no action verb), or task applies to 2+
services and the operation is destructive. Never for read-only tasks.

### 5e. checkpoint_save / checkpoint_restore

Saves current service state snapshot before risky ops.
Called by: execute agent before `service_upgrade`, `node_drain`, `kafka_rolling_restart_safe`.

---

## 6. Prompt Quality Factors

What determines whether a task runs well:

### Positive factors

| Factor | Effect |
|---|---|
| Clear action verb | Classifier routes correctly |
| Named target | No clarifying_question needed |
| Runbook exists | Agent follows proven procedure |
| Tool allowlist has what's needed | No blocked-cmd detours |
| MuninnDB has relevant past outcomes | Boost hints surface correct tools |
| entity_id available on card | EntityDrawer Ask uses entity context |

### Negative factors / failure modes

| Failure | Root cause | Mitigation |
|---|---|---|
| Wrong agent type routed | Keyword collision in classifier | Improve keyword sets; add bigrams |
| Tool not visible to LLM | Semantic ranking dropped it | Lower top_n threshold; check embeddings |
| Agent hallucinates kubectl | Training data bias | Explicit "NO kubectl" in every prompt — already there |
| plan_action called as prose | LLM skips tool call | "CALL plan_action() as a TOOL" instruction |
| Escalates on blocked tool | Misunderstood escalate role | "BLOCKED TOOL RULE" section in prompts |
| OOM diagnosed from exit 137 alone | Exit 137 = Swarm lifecycle too | Mandatory dmesg check rule added |
| Investigate stops at tier 1 | Not enough investigation depth | "min 4 tool calls" + evidence tier rules |
| propose_subtask never called | Agent doesn't know when to use it | "RULE — PROPOSE SUB-TASK" section |
| audit_log called mid-run | Loop terminates early | "ONCE at the end" rule + "output NOTHING MORE after" |

---

## 7. Skills System

Skills are Python modules generated by the build agent (via `skill_create`) and
stored in the DB. They appear in the tool registry as callable tools.

### Lifecycle

```
skill_create(description, service)
  → LLM generates Python skill module
  → validate_skill_live() tests against real endpoints
  → skill written to DB with lifecycle_state="draft"

Operator promotes via UI:
  lifecycle_state: draft → active → promoted

At startup:
  _load_promoted_into_allowlists() reads DB
  → injects promoted skill names into domain execute allowlists
```

### Skill execution path

```
Agent calls skill_execute(name="my_skill", params={...})
  → skills/registry.py → loads skill module from DB
  → calls skill.execute(**params)
  → returns standard {status, data, message} dict
```

### Skill trust levels

| State | Visible to | Can execute |
|---|---|---|
| draft | build agent | Yes (via validate_skill_live) |
| active | All agents (search/list) | No (skill_execute blocked in non-build) |
| promoted | All agents + injected into allowlists | Yes, in domain execute agent |

---

## 8. Memory & Context Injection

### MuninnDB (long-term memory)

- Stores successful tool sequences, past outcomes, documentation
- At run start: relevant memories injected into system prompt as `[RELEVANT PAST OUTCOMES]`
- Provides `boost_names` for semantic tool ranking (+0.2 cosine boost)

### Operation log

Every run creates an `operation_log` record:
- `session_id`, `task`, `owner_user`, `status`, `final_answer`
- Used by sub-task system to inject parent investigation context into child execute run

### Result store

- Large tool outputs stored with 2h TTL
- `ref="rs-..."` returned to LLM; full data fetched on demand
- Prevents context window overflow on large `service_list`, `vm_exec` outputs

### Entity history

- `entity_changes` + `entity_events` tables (Postgres)
- Written by collectors on each poll cycle
- Available via `entity_history(entity_id, hours)` and `entity_events(entity_id, hours)`
- Entity IDs: `proxmox_vms:node:vm:vmid`, `swarm:service:name`, `docker:name`, etc.

---

## 9. Sub-task (Propose → Execute) Flow

```
Investigate agent runs → finds clear fix path
  → calls propose_subtask(task, executable_steps, manual_steps)
  → proposal written to DB with status=pending

UI: AgentFeed shows inline offer: "Execute: restart kafka_broker-3?"
  → user clicks Accept or Dismiss

Accept → POST /api/agent/subtask
  → new session_id, operation_id created
  → parent final_answer injected as context
  → execute agent runs with pre-filled context
  → follows standard execute workflow (plan_action gate etc.)
```

---

## 10. Current Known Issues & Improvement Targets

### Classifier
- [ ] "investigate and fix" always routes to research (never executes)
- [ ] Ambiguous score=0 tasks fallback to action prompt — should maybe prompt for type
- [ ] No bigram scoring for "force restart", "rolling restart" etc.

### Tool allowlists
- [ ] EXECUTE_PROXMOX_TOOLS is thin — relies entirely on promoted skills
- [ ] vm_exec allowlist has no pattern for `apt list --upgradable` (common request)
- [ ] `node_activate` not in any allowlist (node_drain has no undo tool available to agent)

### Agent prompts
- [ ] STATUS_PROMPT + RESEARCH_PROMPT both include full Kafka workflow docs — duplication
- [ ] propose_subtask still frequently not called when it should be
- [ ] No runbook for: disk cleanup, TrueNAS pool issues, FortiGate interface down
- [ ] Investigate prompt has no guidance for non-Kafka investigate paths (TrueNAS, UniFi)

### Skills
- [ ] No promoted skills for proxmox domain (EXECUTE_PROXMOX_TOOLS is effectively empty)
- [ ] skill_compat_check only covers Kafka + Swarm — PBS/TrueNAS skills may be stale

### Entity system
- [ ] EntityDrawer Ask uses 300 token limit — insufficient for complex entity questions
- [ ] Ask suggestions are static (status/section only) — should use entity metadata

### Result store
- [ ] No way for agent to paginate result_query results (returns all matching rows)
- [ ] 2h TTL may be too short for long investigations with multiple sessions

---

## 11. Testing Checklist

### Task routing tests (no LLM needed — unit test classifier)

```python
from api.agents.router import classify_task, detect_domain

# Observe
assert classify_task("check kafka status") == "status"
assert classify_task("how many nodes are running") == "status"
assert classify_task("what is the current version") == "status"

# Research
assert classify_task("why is broker 2 missing") == "research"
assert classify_task("investigate disk usage growth") == "research"
assert classify_task("what caused the restart") == "research"

# Action
assert classify_task("restart kafka broker 3") == "action"
assert classify_task("upgrade workload to nginx:1.27") == "action"
assert classify_task("fix the kafka cluster") == "action"

# Build
assert classify_task("create a skill for proxmox") == "build"

# Edge: questions with action words → research/status
assert classify_task("how do I restart the service") == "research"
assert classify_task("show me the running services") == "status"

# Domain
assert detect_domain("kafka broker is down") == "kafka"
assert detect_domain("worker-03 disk is full") == "vm_host"
assert detect_domain("proxmox vm crashed") == "proxmox"
```

### Gate tests (require running API)

```bash
# plan_action gate fires for service_upgrade
curl -X POST http://localhost:8000/api/agent/run \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"task": "upgrade workload to nginx:1.27-alpine"}'
# Expect: plan_action called before service_upgrade

# Pre-kafka check bypass for remediation
curl -X POST http://localhost:8000/api/agent/run \
  -d '{"task": "fix kafka broker 3 after worker-03 rebooted"}'
# Expect: NO pre_kafka_check call, goes straight to swarm_node_status → plan_action

# Blocked tool → manual SSH command (not escalation)
# trigger by asking for a command not in vm_exec allowlist
```

### End-to-end scenarios

| Scenario | Expected path | Pass criteria |
|---|---|---|
| "check swarm status" | observe → swarm_status → service_health → audit_log | All facts reported, ≤6 tools |
| "why is kafka degraded" | research → kafka_broker_status → service_placement → vm_exec → elastic_kafka_logs | 4+ tools, structured output |
| "restart kafka broker 3" | action → swarm_node_status → plan_action → swarm_service_force_update → audit_log | plan_action fires, no escalate |
| "investigate disk and fix" | research → vm_disk_investigate → propose_subtask | sub-task offered to user |
| "create skill for PBS snapshots" | build → skill_search → plan_action → skill_create → validate_skill_live | plan fires before create |

---

## 12. Prompt Engineering Notes

### What works well
- "ENVIRONMENT — READ BEFORE ANY TOOL CALL" header prevents kubectl hallucinations
- Explicit numbered rules prevent the most common failure modes
- "After audit_log(), output NOTHING MORE" stops run continuation
- "BLOCKED TOOL RULE (CRITICAL)" reduces false escalations
- "EXIT CODE 137 — MANDATORY VERIFICATION RULE" prevents OOM false positives
- Temperature 0.1 for tool steps gives deterministic JSON arg formatting

### What needs improvement
- propose_subtask call rate is low — consider adding example task → propose_subtask mapping
- Runbooks not consistently checked at start of known problem types
- STATUS_PROMPT is 200+ lines — may exceed what the model reads thoroughly
- No structured output for observe agent (research has 4-section template)
- clarifying_question() still sometimes called for clear tasks (over-trigger)

### Temperature strategy

| Step type | Temperature | Reason |
|---|---|---|
| Tool-call steps | 0.1 | Deterministic JSON formatting |
| Summary / final answer | 0.3 | More natural prose |
| Force summary (limit hit) | 0.3 | Best prose under constraint |
| audit_log-only step | 0.3 + /no_think | Skip reasoning overhead for logging |

---

## 13. File Reference

| File | Role |
|---|---|
| `api/agents/router.py` | Classifier, allowlists, system prompts, semantic ranking |
| `api/routers/agent.py` | Agent loop, DESTRUCTIVE_TOOLS, plan gate, WebSocket stream |
| `api/tool_registry.py` | Tool registry, invoke_tool() dispatcher |
| `mcp_server/server.py` | All @mcp.tool() registrations |
| `mcp_server/tools/vm.py` | vm_exec, kafka_exec, swarm_node_status, swarm_service_force_update, proxmox_vm_power |
| `mcp_server/tools/swarm.py` | Swarm read/write tools, pre_upgrade_check, service_upgrade |
| `mcp_server/tools/kafka.py` | Kafka status, rolling restart, pre_kafka_check |
| `mcp_server/tools/elastic.py` | All Elasticsearch tools |
| `mcp_server/tools/orchestration.py` | plan_action, escalate, checkpoint, audit_log, clarifying_question |
| `mcp_server/tools/metric_tools.py` | metric_trend, list_metrics |
| `mcp_server/tools/entity_history_tools.py` | entity_history, entity_events |
| `mcp_server/tools/skill_meta_tools.py` | All skill_* tools, validate_skill_live, discover_environment |
| `api/db/vm_exec_allowlist.py` | vm_exec command whitelist (DB + hardcoded base) |
| `api/db/entity_history.py` | entity_changes, entity_events tables |
| `api/db/result_store.py` | Large result reference storage |
| `api/db/subtask_proposals.py` | Proposal lifecycle |
| `api/memory/` | MuninnDB hooks, trigger evaluations |
