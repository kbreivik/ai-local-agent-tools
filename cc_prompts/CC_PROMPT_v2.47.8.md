# CC PROMPT — v2.47.8 — fix(agent): stronger clarification rejection + specific halluc-guard hints

## What this does
Closes the remaining 5 mem-on baseline failures from the v2.47.6 baseline
(2026-04-26 08:59 run). Trace data shows v2.47.3/4/5/6 are firing but
their effects don't actually fix the failures. Two precise changes:

**Action tests** (action-drain, -rollback, -upgrade, -activate):
v2.47.3 force-plan nudge fires correctly at step 4. The nudge appends a
system message saying "call plan_action() next." The model ignores the
message and calls `clarifying_question` anyway in the same batch. Then on
the next round, calls `clarifying_question` AGAIN. Eventually v2.47.4
ceiling blocks at attempt 3, agent gives up and calls a hallucinated tool.

Fix: after `state.plan_force_nudge_fired = True`, REJECT subsequent
`clarifying_question` calls in the same run (not just nudge). The model
is being told "do not call clarifying_question" via system message; we
make that contract enforceable at dispatch time.

**Elastic tests** (status-elastic-01, research-elastic-index-01):
Trace shows agent calls ZERO tools on step 1, tries to final_answer.
Halluc guard fires retry with the GENERIC message "call data-gathering
tools BEFORE your final answer." Agent doesn't know which tool to call
because the prompt is dense (KAFKA TRIAGE, EXIT CODES, NETWORK QUERIES
sections). After 3 retries, halluc guard exhausts and fails the run.

The v2.47.6 no-evidence rebuke I added doesn't fire because halluc guard
catches the case first (different code path).

Fix: when the halluc guard fires its retry, detect named subsystems in
the task (elastic/kafka/swarm) and append a specific tool hint to the
existing escalation message. "Call elastic_cluster_health() now." plus
the existing message gives the model exact direction.

Version bump: 2.47.7 → 2.47.8

---

## Change 1 — `api/agents/step_tools.py` — reject `clarifying_question` after force-plan-nudge fires

CC: open `api/agents/step_tools.py`. Find `_handle_lifecycle_tools` and
the v2.47.4 clarification ceiling block (search for `_CLARIFY_CEILING = 2`).

The structure currently looks like:

```python
    if fn_name == "clarifying_question":
        state.clarifying_question_count += 1
        _CLARIFY_CEILING = 2
        if state.clarifying_question_count > _CLARIFY_CEILING:
            # ...reject after 3rd call...
            return {"status": "error", "message": "clarifying_question rejected — ceiling..."}
    if fn_name == "clarifying_question":
        return await _handle_clarifying_question(...)
```

ADD a new rejection check between the count-and-ceiling block and the
fall-through dispatch. The new rejection is:

```python
        # v2.47.8 — reject clarifying_question if force-plan nudge has
        # already fired for this run. Pattern observed in action-drain-01
        # (2026-04-26 08:59): v2.47.3 nudge appends a system message
        # telling the model "do not ask another clarifying_question",
        # but the model ignores it and calls clarifying_question anyway.
        # The nudge is advisory; this is enforceable. Once we've told
        # the model to stop clarifying and start planning, every
        # subsequent clarifying_question call is rejected at dispatch.
        if (
            state.plan_force_nudge_fired
            and getattr(state, "agent_type", "") in ("action", "execute")
        ):
            await manager.send_line(
                "step",
                "[harness] clarifying_question rejected — force-plan nudge "
                "already fired this run, agent must call plan_action() now",
                status="warning", session_id=session_id,
            )
            if not state.clarification_force_nudge_fired:
                state.clarification_force_nudge_fired = True
                messages.append({
                    "role": "system",
                    "content": (
                        "[harness] clarifying_question is REJECTED for the "
                        "rest of this run because force-plan nudge already "
                        "fired. You have been told twice that your next "
                        "tool call must be plan_action(). Stop trying to "
                        "clarify and CALL plan_action() with concrete "
                        "summary + steps based on the task you were given. "
                        "If the entity ID does not exist, plan_action() "
                        "with that ID and let the user reject — do NOT "
                        "ask another clarifying question."
                    ),
                })
                try:
                    from api.metrics import HARNESS_CLARIFY_CEILING_COUNTER
                    HARNESS_CLARIFY_CEILING_COUNTER.labels(
                        agent_type=getattr(state, "agent_type", "unknown"),
                    ).inc()
                except Exception:
                    pass
            return {
                "status":  "error",
                "message": (
                    "clarifying_question rejected — force-plan nudge "
                    "already fired this run. You MUST call plan_action() "
                    "next with concrete summary and steps. The user has "
                    "given you the task; act on it."
                ),
            }
```

CC: this block goes IMMEDIATELY AFTER the existing `_CLARIFY_CEILING = 2`
ceiling block and BEFORE the fall-through `if fn_name == "clarifying_question": return await _handle_clarifying_question(...)`.

The first ceiling rejection (count > 2) keeps working as before. The new
rejection (force-plan-nudge fired) catches the action-test failure mode
specifically — the model that's stuck in "I need to clarify" loops never
makes it to count 3 because v2.47.5's clarify-then-text-exit rescue hits
first. This new gate fires at clarifying_question call #2 if the nudge
flag is set, which is exactly what we need for action tests.

---

## Change 2 — `api/agents/step_guard.py` — task-specific hint in halluc-guard retry message

CC: open `api/agents/step_guard.py`. Find `run_stop_path_guards` and the
section that builds `_esc_msg` for the halluc guard retry (search for
`_esc_msg = {`).

The current structure:

```python
        if state.halluc_guard_attempts < state.halluc_guard_max:
            _esc_msg = {
                1: ("You finalised after ... call at least N tools..."),
                2: ("Second attempt: ..."),
            }.get(state.halluc_guard_attempts, ("Final warning: ..."))
            if msg.content:
                messages.append({"role": "assistant", "content": msg.content})
            messages.append({"role": "system", "content": f"[harness] {_esc_msg}"})
```

REPLACE the `messages.append({"role": "system", ...})` line with code that
appends a task-specific hint. Insert this BEFORE the `messages.append`:

```python
            # v2.47.8 — task-specific tool hint. Pattern observed in
            # status-elastic-01 (2026-04-26 08:59): agent reasons about
            # elasticsearch but calls zero tools, halluc guard fires
            # generic "call data-gathering tools" message. Without a
            # specific tool name, the model retries with the same
            # generic reasoning. Detecting subsystem keywords in the
            # task and appending a concrete tool hint makes the retry
            # actionable.
            _t_lower = (task or "").lower()
            _hint = ""
            if "elastic" in _t_lower or "elasticsearch" in _t_lower:
                if "index" in _t_lower or "stat" in _t_lower:
                    _hint = " For this task, call elastic_index_stats() now."
                elif "log" in _t_lower or "search" in _t_lower:
                    _hint = " For this task, call elastic_search_logs() now."
                else:
                    _hint = " For this task, call elastic_cluster_health() now."
            elif "kafka" in _t_lower:
                if "broker" in _t_lower:
                    _hint = " For this task, call kafka_broker_status() now."
                elif "lag" in _t_lower or "consumer" in _t_lower:
                    _hint = " For this task, call kafka_consumer_lag() now."
                elif "topic" in _t_lower:
                    _hint = " For this task, call kafka_topic_health() now."
                else:
                    _hint = " For this task, call kafka_broker_status() now."
            elif "swarm" in _t_lower:
                if "node" in _t_lower:
                    _hint = " For this task, call swarm_node_status() now."
                else:
                    _hint = " For this task, call swarm_status() now."
            elif "service" in _t_lower:
                if "list" in _t_lower:
                    _hint = " For this task, call service_list() now."
                else:
                    _hint = " For this task, call service_health() now."

            _esc_msg = _esc_msg + _hint
```

CC: the `_esc_msg = _esc_msg + _hint` line happens AFTER the dict lookup
that builds the original message and BEFORE the `messages.append` call.
The message remains in the same `[harness]` framing, just with a
specific tool name appended when one applies.

---

## Verify

```bash
python -m py_compile api/agents/step_tools.py api/agents/step_guard.py

grep -n "force-plan nudge already fired this run" api/agents/step_tools.py
# Expected: 1 match (rejection block exists)

grep -n "task-specific tool hint" api/agents/step_guard.py
# Expected: 1 match (hint block exists)
```

After deploy, the 5 remaining failures should close on the next mem-on
baseline:

- **action-drain-01, action-rollback-01, action-upgrade-01, action-activate-01**:
  After 2 tool calls without plan_action, force-plan nudge fires AND
  rejects subsequent clarifying_question. Agent's only path forward is
  plan_action() → test passes with `plan_steps_count > 0`.

- **status-elastic-01**: First halluc guard retry now reads
  "Call elastic_cluster_health() now." — model has explicit direction
  on the second LLM turn → tool gets called → test passes.

- **research-elastic-index-01**: Same as above with `elastic_index_stats`.

Predicted score: ≥95% mem-on (matching the v2.45.17 anchor of 95.5%).

If a test still fails after this lands, the harness has done all it
reasonably can. Further fixes would require either: (a) tighter prompt
engineering on the OBSERVE/ACTION system prompts, (b) tool-result-level
intervention (synthetic plan_action call from harness), or (c) accepting
soft-failure status on these specific tests.

---

## Version bump

Update `VERSION`: `2.47.7` → `2.47.8`

---

## Commit

```
git add -A
git commit -m "fix(agent): v2.47.8 stronger clarification rejection + specific halluc-guard hints"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```

After this lands, run a fresh `full-mem-on-baseline` from the Tests panel
(~47 min). Then:

```bash
docker exec -i hp1-postgres psql -U hp1 -d hp1_agent -c "
SELECT suite_name, started_at, score_pct, weighted_pct, passed, failed
FROM test_runs
ORDER BY started_at DESC LIMIT 3;
"
```

Expected: most-recent mem-on row at ≥95% with passed≥21. If yes, the
v2.45.17 → v2.47.x cycle is closed and we move to architectural work
(`step_tools.py` and `preflight.py` size reduction) or operational items
(worker-03 reboot, real notification test).
