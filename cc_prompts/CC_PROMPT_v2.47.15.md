# CC PROMPT — v2.47.15 — fix(agent): proactive canonical first-tool hint for status/observe tasks

## What this does

Closes the persistent `status-elastic-01` hard failure that has been the
sole hard fail in every recent baseline (v2.45.17 anchor 95.5%, v2.47.6
90.9%, v2.47.14 95.5%).

**Diagnosis from v2.47.14 baseline trace (run c852809f, 2026-04-26 20:23):**

| Field | Value |
|-------|-------|
| Test | `status-elastic-01` |
| Task | `"is elasticsearch healthy?"` |
| agent_type | `status` |
| Expected tool | `elastic_cluster_health` |
| Tools called | `["audit_log"]` (only) |
| Steps | 4 |
| Duration | 81.3s |
| Hallucination guard | fired, retried, still wrong tool |

The status-agent picks `audit_log` as its first/only tool when asked
about ES cluster health. v2.47.8 added a REACTIVE elastic hint inside
the hallucination guard (fires AFTER the model has already finalised
with no real tool calls), but the model has already committed to its
diagnosis cognitively by then and retries with the same generic
reasoning.

**Root cause**: there is no PROACTIVE first-tool nudge for status tasks.
`pipeline.py:inject_facts_block` injects a `HISTORICAL HINT` block from
MuninnDB's `get_first_tool_hint()`, but:

1. v2.47.9 disabled `record_outcome` writes during test runs, so the
   engram store doesn't get fresh data from successful runs.
2. Older engrams may suggest meta tools (`audit_log`) for ambiguous
   prompts because "audit log" is a learned generic-fallback.
3. When MuninnDB returns an empty hint, no fallback exists — the agent
   gets no guidance on which tool to call first.

**Fix**: add a deterministic keyword→canonical-tool mapping that runs
AFTER the MuninnDB lookup in `inject_facts_block`, and OVERRIDES the
MuninnDB hint when:
- MuninnDB returned empty, OR
- MuninnDB returned a meta-tool (audit_log, runbook_search, memory_recall)
  AND the task has a strong domain keyword match.

The deterministic mapping mirrors v2.47.8's reactive hints but fires
upfront. Same keyword logic, same tool names — just earlier in the loop.

This is a **status/observe-agent fix**. Investigate/research/execute
agents have richer multi-step workflows where forcing a specific first
tool would harm. Status tasks have a single-tool answer pattern: the
canonical tool answers the question.

Version bump: 2.47.14 → 2.47.15

---

## Change 1 — `api/agents/pipeline.py` — add canonical first-tool helper

CC: open `api/agents/pipeline.py`. Find the import block at the top and
the `inject_facts_block` function near the bottom. We add a small
helper right above `inject_facts_block`.

Locate the line that says:

```python
async def inject_facts_block(system_prompt: str, task: str, first_intent: str,
                             preflight_facts_block: str = "",
                             preflight_skills_block: str = ""):
```

IMMEDIATELY BEFORE that line, insert this helper:

```python
# Meta-tools that don't answer a status question — never accept these as
# the canonical first tool, even if memory hints suggest them.
_META_FIRST_TOOLS = frozenset({
    "audit_log", "runbook_search", "memory_recall", "engram_activate",
    "propose_subtask", "plan_action", "checkpoint_save",
})


def _canonical_first_tool_for_status(task: str, first_intent: str) -> str:
    """Return a canonical first tool for status/observe tasks, or "".

    Matches v2.47.8's reactive hint logic (in step_guard.py) but fires
    proactively at prompt-build time. Only applies to status/observe
    intents; investigate/execute/build have richer first-tool patterns
    that are better served by memory than by hardcoded mapping.

    Returns "" when no strong keyword match exists — caller falls
    through to MuninnDB's hint.
    """
    if first_intent not in ("status", "observe"):
        return ""
    t = (task or "").lower()
    if not t:
        return ""

    # Elastic
    if "elastic" in t or "elasticsearch" in t:
        if "index" in t or "stat" in t:
            return "elastic_index_stats"
        if "log" in t or "search" in t:
            return "elastic_search_logs"
        return "elastic_cluster_health"

    # Kafka
    if "kafka" in t:
        if "broker" in t:
            return "kafka_broker_status"
        if "lag" in t or "consumer" in t:
            return "kafka_consumer_lag"
        if "topic" in t:
            return "kafka_topic_health"
        return "kafka_broker_status"

    # Swarm
    if "swarm" in t:
        if "node" in t:
            return "swarm_node_status"
        return "swarm_status"

    # Service
    if "service" in t:
        if "list" in t or "running" in t:
            return "service_list"
        if "version" in t and "history" in t:
            return "service_version_history"
        if "version" in t:
            return "service_current_version"
        return "service_health"

    return ""
```

CC: place this block right above the existing `async def inject_facts_block(...)`
line. Match indentation (top-level — no leading spaces).

---

## Change 2 — `api/agents/pipeline.py` — apply canonical override in inject_facts_block

CC: same file. Find the block inside `inject_facts_block` that ends with:

```python
        # MuninnDB first-tool hint (step 0)
        try:
            from api.memory.feedback import get_first_tool_hint
            first_tool_hint = await get_first_tool_hint(task, first_intent) or ""
            if first_tool_hint:
                hint_block = (
                    f"HISTORICAL HINT: For tasks similar to this, "
                    f"successful runs typically started with: {first_tool_hint}. "
                    f"Consider this as your first tool call."
                )
                injected_sections.append(hint_block)
        except Exception as e:
            log.debug("first_tool_hint failed: %s", e)
```

Replace the WHOLE try/except block with:

```python
        # MuninnDB first-tool hint (step 0)
        try:
            from api.memory.feedback import get_first_tool_hint
            first_tool_hint = await get_first_tool_hint(task, first_intent) or ""
        except Exception as e:
            log.debug("first_tool_hint failed: %s", e)
            first_tool_hint = ""

        # v2.47.15 — proactive canonical first-tool override for
        # status/observe tasks. When the task has a strong domain
        # keyword match, the canonical tool wins over MuninnDB's hint
        # if MuninnDB returned nothing or a meta-tool (audit_log,
        # runbook_search). Fixes the persistent status-elastic-01
        # failure where the model picks audit_log instead of
        # elastic_cluster_health.
        canonical = _canonical_first_tool_for_status(task, first_intent)
        if canonical and (not first_tool_hint
                          or first_tool_hint in _META_FIRST_TOOLS):
            if first_tool_hint and first_tool_hint != canonical:
                log.info(
                    "first_tool_hint canonical override: muninn=%s -> canonical=%s "
                    "(task=%r intent=%s)",
                    first_tool_hint, canonical, task[:80], first_intent,
                )
            first_tool_hint = canonical

        if first_tool_hint:
            # v2.47.15 — stronger directive for canonical hints; the
            # weaker "Consider this" wording from MuninnDB hints was
            # ignored by the model on status-elastic-01.
            if canonical and first_tool_hint == canonical:
                hint_block = (
                    f"FIRST TOOL DIRECTIVE: For this task, your FIRST "
                    f"tool call MUST be {first_tool_hint}(). This is the "
                    f"canonical tool for this question type. Do NOT call "
                    f"audit_log, runbook_search, or any meta-tool first. "
                    f"Call {first_tool_hint}() now."
                )
            else:
                hint_block = (
                    f"HISTORICAL HINT: For tasks similar to this, "
                    f"successful runs typically started with: {first_tool_hint}. "
                    f"Consider this as your first tool call."
                )
            injected_sections.append(hint_block)
```

CC: keep the surrounding code (everything before `# MuninnDB first-tool hint`
and everything after the `if first_tool_hint:` block) unchanged. The
indentation must match the existing block (inside the outer try/except
of `inject_facts_block`).

---

## Verify

```bash
python -m py_compile api/agents/pipeline.py

# Confirm helper is defined
grep -n "_canonical_first_tool_for_status\|_META_FIRST_TOOLS" api/agents/pipeline.py
# Expected: 2 distinct definitions + 2 usages in inject_facts_block

# Confirm directive wording is in place
grep -n "FIRST TOOL DIRECTIVE" api/agents/pipeline.py
# Expected: 1 match

# Confirm no syntax issues by importing
python -c "from api.agents.pipeline import _canonical_first_tool_for_status; \
  assert _canonical_first_tool_for_status('is elasticsearch healthy?', 'status') == 'elastic_cluster_health'; \
  assert _canonical_first_tool_for_status('show kafka consumer lag', 'status') == 'kafka_consumer_lag'; \
  assert _canonical_first_tool_for_status('is elasticsearch healthy?', 'execute') == ''; \
  print('canonical hint OK')"
```

After deploy + fresh smoke or full baseline:

1. Trace for `status-elastic-01` should show `elastic_cluster_health`
   as the FIRST tool called (not `audit_log`)
2. Score should hit 100% on smoke (status-elastic-01 was the sole fail)
3. Full baseline hard score should reach **96.6%** (22/22 hard pass)
   — improvement of 1pp over the v2.45.17 anchor

---

## What this does NOT do

- **Does not affect investigate/research/execute/build agents.** Their
  first-tool decisions stay memory-driven via MuninnDB.
- **Does not change the reactive v2.47.8 hint** in step_guard.py. Both
  layers now exist: proactive (this prompt) + reactive (existing) for
  defence in depth.
- **Does not register settings or env vars.** The keyword mapping is
  deterministic and tied to the actual tool names — making it tunable
  would invite drift between settings and the agent's tool allowlist.

---

## Version bump

Update `VERSION`: `2.47.14` → `2.47.15`

---

## Commit

```bash
git add -A
git commit -m "fix(agent): v2.47.15 proactive canonical first-tool hint for status/observe tasks"
git push origin main
```

Deploy:

```bash
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
