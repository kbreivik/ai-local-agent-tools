# CC PROMPT — v2.47.6 — fix(agent): rebuke audit_log-only step when no substantive evidence gathered

## What this does
Closes 2 of the 5 remaining mem-on failures from the v2.47.4 baseline:
`research-elastic-index-01` and `status-elastic-01`. Both fail with:

- `tools_called = []` (status-elastic-01) or `tools_called = ['audit_log']`
  (research-elastic-index-01)
- `step_count = 1` (single LLM turn)
- `failures: ["Expected tool 'elastic_cluster_health' not called ..."]`
  or `["Expected tool 'elastic_index_stats' not called ..."]`

Pattern: agent reads the prompt, sees the dense KAFKA TRIAGE / EXIT CODE /
NETWORK QUERIES sections, decides the simple elastic question is "done"
without gathering any evidence, calls `audit_log` (or nothing) and exits.

The classifier IS routing correctly — `status-elastic-01` test definition
asks for `agent_type="status"`, classifier puts it there, the OBSERVE
allowlist contains both `elastic_cluster_health` and `elastic_index_stats`.
The failure is the agent never calling them.

The existing audit_log-only path in `_run_single_agent_step` says:
> "if entire step was only audit_log calls, the agent is done"

But "done" without `state.substantive_tool_calls > 0` means the agent
never called a real tool. That's not done — that's a premature exit.
Same problem for empty `tool_calls` lists on observe/research runs that
hit `finish == "stop"` on step 1 with no evidence.

Fix: in both natural-exit paths, when an observe/research/investigate
agent reaches stop AFTER ZERO substantive tool calls AND the task names
a specific subsystem (kafka/elastic/swarm/proxmox), inject a "you
haven't gathered evidence yet" rebuke and force one more LLM turn.

Idempotent — fires once per run via a new `state.no_evidence_rebuke_fired`
flag.

Version bump: 2.47.5 → 2.47.6

---

## Change 1 — `api/agents/step_state.py` — add idempotency flag

CC: open `api/agents/step_state.py`. Find `StepState` and add near the
other fired-once flags (next to `clarification_force_nudge_fired`):

```python
    no_evidence_rebuke_fired: bool = False     # v2.47.6 — rebuke audit-only / empty exit
```

---

## Change 2 — `api/routers/agent.py` — rebuke at natural-exit path

Open `api/routers/agent.py`. Find `_run_single_agent_step` and the same
`if finish == "stop" or not msg.tool_calls:` block from v2.47.5.

After the v2.47.5 clarify-then-text-exit rescue block, BEFORE the existing
`# Synthesise degraded findings if present` block, add:

```python
                # v2.47.6 — no-evidence rebuke. Pattern observed in
                # status-elastic-01, research-elastic-index-01: agent
                # exits via finish=="stop" on step 1 having called ZERO
                # substantive tools. The dense system prompt's KAFKA
                # TRIAGE / EXIT CODE / NETWORK QUERIES sections steer the
                # model toward "this isn't a kafka problem, must be done"
                # for elastic-only tasks. Reject the empty exit and force
                # one more turn with a concrete tool hint.
                if (
                    agent_type in ("observe", "status", "investigate", "research")
                    and state.substantive_tool_calls == 0
                    and not state.no_evidence_rebuke_fired
                    and step <= 2
                ):
                    state.no_evidence_rebuke_fired = True
                    # Detect named subsystem to give a concrete hint
                    _t_lower = (task or "").lower()
                    _hint = ""
                    if "elastic" in _t_lower or "elasticsearch" in _t_lower:
                        if "index" in _t_lower or "stat" in _t_lower:
                            _hint = " Call elastic_index_stats() now."
                        elif "health" in _t_lower or "cluster" in _t_lower:
                            _hint = " Call elastic_cluster_health() now."
                        elif "log" in _t_lower or "search" in _t_lower:
                            _hint = " Call elastic_search_logs() now."
                    elif "kafka" in _t_lower:
                        if "broker" in _t_lower:
                            _hint = " Call kafka_broker_status() now."
                        elif "lag" in _t_lower or "consumer" in _t_lower:
                            _hint = " Call kafka_consumer_lag() now."
                        elif "topic" in _t_lower:
                            _hint = " Call kafka_topic_health() now."
                    elif "swarm" in _t_lower or "service" in _t_lower:
                        if "node" in _t_lower:
                            _hint = " Call swarm_node_status() now."
                        else:
                            _hint = " Call service_list() or swarm_status() now."

                    messages.append({
                        "role": "system",
                        "content": (
                            "[harness] You exited without gathering any "
                            "evidence. The user's task names a specific "
                            "subsystem and expects you to query it before "
                            "concluding. Calling audit_log() or producing "
                            "a text-only answer with zero tool calls is a "
                            "protocol failure. Re-read the task, identify "
                            "the specific tool that answers the user's "
                            "question, and call it now." + _hint
                        ),
                    })
                    await manager.send_line(
                        "step",
                        f"[harness] no-evidence rebuke — forcing one more turn"
                        + (f" ({_hint.strip()})" if _hint else ""),
                        status="warning", session_id=session_id,
                    )
                    try:
                        from api.metrics import HARNESS_NO_EVIDENCE_REBUKE_COUNTER
                        HARNESS_NO_EVIDENCE_REBUKE_COUNTER.labels(
                            agent_type=agent_type,
                        ).inc()
                    except Exception:
                        pass
                    continue   # one more LLM turn
```

CC: place this AFTER the v2.47.5 clarify-then-text-exit rescue block and
BEFORE the degraded findings synthesis. The structure inside the
`if finish == "stop" or not msg.tool_calls:` branch will be:

1. `run_stop_path_guards` → handle RETRY/FAIL/RESCUED
2. v2.47.5 clarify-then-text-exit rescue (continues if fires)
3. **v2.47.6 no-evidence rebuke (continues if fires)**  ← NEW
4. degraded findings synthesis
5. `maybe_force_empty_synthesis`
6. done broadcast + break

The same pattern goes into the audit_log-only branch lower in the loop.
Find:

```python
            _step_names = [tc.function.name for tc in msg.tool_calls]

            # v2.47.5 — audit_log-only step on action/execute that already...
            if (
                _step_names
                and all(n == "audit_log" for n in _step_names)
                and agent_type in ("action", "execute")
                ...
            ):
                ...
                continue
```

Right after the v2.47.5 audit-log-only-after-clarify block and BEFORE the
existing `if (_step_names and all(...))` check, insert:

```python
            # v2.47.6 — audit_log-only step on observe/research/investigate
            # with ZERO substantive tool calls: agent called audit_log as
            # a "done" signal without gathering evidence. Same rebuke as
            # the natural-exit path. Idempotent.
            if (
                _step_names
                and all(n == "audit_log" for n in _step_names)
                and agent_type in ("observe", "status", "investigate", "research")
                and state.substantive_tool_calls == 0
                and not state.no_evidence_rebuke_fired
            ):
                state.no_evidence_rebuke_fired = True
                _t_lower = (task or "").lower()
                _hint = ""
                if "elastic" in _t_lower:
                    if "index" in _t_lower or "stat" in _t_lower:
                        _hint = " Call elastic_index_stats() now."
                    elif "health" in _t_lower or "cluster" in _t_lower:
                        _hint = " Call elastic_cluster_health() now."
                elif "kafka" in _t_lower:
                    if "broker" in _t_lower:
                        _hint = " Call kafka_broker_status() now."
                    elif "lag" in _t_lower:
                        _hint = " Call kafka_consumer_lag() now."

                messages.append({
                    "role": "system",
                    "content": (
                        "[harness] You called audit_log() without gathering "
                        "evidence first. audit_log() is for AFTER you have "
                        "called the read-only status tools the user's task "
                        "implies. Re-read the task and call the specific "
                        "tool that answers it now." + _hint
                    ),
                })
                await manager.send_line(
                    "step",
                    f"[harness] audit_log-only no-evidence rebuke"
                    + (f" — {_hint.strip()}" if _hint else ""),
                    status="warning", session_id=session_id,
                )
                try:
                    from api.metrics import HARNESS_NO_EVIDENCE_REBUKE_COUNTER
                    HARNESS_NO_EVIDENCE_REBUKE_COUNTER.labels(
                        agent_type=agent_type,
                    ).inc()
                except Exception:
                    pass
                continue
```

---

## Change 3 — `api/metrics.py` — register the counter

CC: open `api/metrics.py`. Add (next to the v2.47.3
HARNESS_PLAN_NUDGES_COUNTER and v2.47.4 HARNESS_CLARIFY_CEILING_COUNTER):

```python
HARNESS_NO_EVIDENCE_REBUKE_COUNTER = Counter(
    "deathstar_harness_no_evidence_rebuke_total",
    "No-evidence rebukes fired (v2.47.6) — agent tried to exit without "
    "gathering evidence on a subsystem-specific task",
    labelnames=["agent_type"],
)
```

If the file uses `prometheus_client.Counter` directly or a different
registry pattern, match the existing style.

---

## Verify

```bash
python -m py_compile api/agents/step_state.py api/routers/agent.py api/metrics.py

grep -n "no_evidence_rebuke_fired\|no-evidence rebuke" \
    api/agents/step_state.py api/routers/agent.py
```

Expected: state field declared once, two rebuke sites in agent.py.

After deploy, re-run the 2 failing elastic tests:

```bash
TOKEN=<paste hp1_auth cookie>
for tid in research-elastic-index-01 status-elastic-01; do
    curl -s -b "hp1_auth=$TOKEN" -X POST http://localhost:8000/api/tests/run \
        -H 'Content-Type: application/json' \
        -d "{\"test_ids\": [\"$tid\"]}"
    sleep 90
done
```

Expected: both pass. Container log should show
`[harness] no-evidence rebuke — forcing one more turn (Call elastic_*_stats() now.)`
on at least one turn for each test.

If a test still fails, inspect the operation_log for that operation_id —
the rebuke MAY have fired but the model still didn't call the right
tool. That's a separate harder problem (model compliance) requiring
either tighter tool selection (boost `elastic_*` tools at prompt time
when task names elastic) or a second-stage rebuke that lists the exact
tools available in the agent's current allowlist.

---

## Version bump

Update `VERSION`: `2.47.5` → `2.47.6`

---

## Commit

```
git add -A
git commit -m "fix(agent): v2.47.6 rebuke audit_log-only step when no substantive evidence gathered"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```

After both v2.47.5 and v2.47.6 land, the next mem-on baseline should
close all 5 remaining failures from the v2.47.4 run, putting score at
or above 95% (matching the v2.45.17 anchor of 95.5%).
