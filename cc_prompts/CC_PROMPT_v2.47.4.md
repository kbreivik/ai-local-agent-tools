# CC PROMPT — v2.47.4 — fix(agent): clarification ceiling — block 3rd clarifying_question and force action

## What this does
Closes the 4 clarify-test timeouts visible only on mem-off
(clarify-01, clarify-02, clarify-03, clarify-04 — all timed out at
240s/180s/240s/150s).

Root cause: with memory disabled, the agent has no first-tool hint and no
prior context. When the test pre-arms an answer to a clarifying_question,
the agent receives it via `wait_for_clarification` — but the v2.45.18
clarify→plan_action injection only fires AFTER clarification is answered.
On clarify-* tests where the agent asks ANOTHER clarifying_question after
the first one (because the prompt is genuinely ambiguous and memory isn't
filling the gap), the second question doesn't have a pre-armed answer
deposited for it. The agent waits 300s on `wait_for_clarification`, then
times out, then the run ends.

Fix: cap `clarifying_question` calls at 2 per run via a harness counter in
`step_state.py`. After the 2nd, the harness:
1. Blocks the LLM from calling `clarifying_question` a third time (returns
   a tool error from the dispatcher)
2. Injects a system message: "You have asked enough. Make your best
   judgment from available information and proceed with the task."

Same idempotency pattern as the budget nudge and the v2.47.3 plan_force
nudge.

Version bump: 2.47.3 → 2.47.4

---

## Context

`clarifying_question` is in the META_TOOLS list — it doesn't count against
the regular tool budget. That's correct in principle (tests SHOULD be able
to clarify), but with no upper bound the agent can loop indefinitely on
ambiguous prompts. The fix isn't to block clarification entirely — it's
to cap it at a reasonable number and force forward progress.

---

## Change 1 — `api/agents/step_state.py` — add clarification counter

CC: open `api/agents/step_state.py`. Find the `StepState` dataclass.
Add a new counter near the other per-run counters:

```python
    clarifying_question_count: int = 0      # v2.47.4 — cap at 2 per run
    clarification_force_nudge_fired: bool = False  # v2.47.4
```

Match the existing field declaration style (default value, type hint).

---

## Change 2 — `api/agents/step_tools.py` — count + cap clarifying_question

CC: open `api/agents/step_tools.py`. Find the dispatcher block that handles
`clarifying_question` (the v2.45.18 fix put a handler around it; look for
`fn_name == "clarifying_question"` or `_handle_clarifying_question`).

The existing handler probably looks like:

```python
    if fn_name == "clarifying_question":
        return await _handle_clarifying_question(
            tc, fn_args,
            state=state, session_id=session_id, task=task, manager=manager,
            messages=messages,
        )
```

Right BEFORE this block, insert the counter + cap:

```python
    # v2.47.4 — cap clarifying_question calls. The agent already has a
    # clarification mechanism; without an upper bound it can loop on
    # ambiguous prompts (especially on mem-off where there's no prior
    # context to fill the gap). After 2 clarifications, harness rejects
    # further calls and injects a "make your best judgment" directive.
    if fn_name == "clarifying_question":
        state.clarifying_question_count += 1
        _CLARIFY_CEILING = 2
        if state.clarifying_question_count > _CLARIFY_CEILING:
            # Reject the call; emit a tool result that points the LLM forward
            await manager.send_line(
                "step",
                f"[harness] clarifying_question #{state.clarifying_question_count} "
                f"blocked — ceiling is {_CLARIFY_CEILING}/run",
                status="warning", session_id=session_id,
            )
            if not state.clarification_force_nudge_fired:
                state.clarification_force_nudge_fired = True
                messages.append({
                    "role": "system",
                    "content": (
                        f"[harness] You have called clarifying_question "
                        f"{state.clarifying_question_count} times. The maximum is "
                        f"{_CLARIFY_CEILING}. Further clarification calls will be "
                        "rejected. You now have all the information you are going "
                        "to get from the user. Make your best judgment from the "
                        "task description and any context already provided, then "
                        "proceed with the task. "
                        "If this is an EXECUTE-type task, your next tool call "
                        "MUST be plan_action(). "
                        "If this is an INVESTIGATE/OBSERVE task, call the most "
                        "specific status tool for the system the user named."
                    ),
                })
                try:
                    from api.metrics import HARNESS_CLARIFY_CEILING_COUNTER
                    HARNESS_CLARIFY_CEILING_COUNTER.labels(
                        agent_type=getattr(state, "agent_type", "unknown"),
                    ).inc()
                except Exception:
                    pass
            # Return a tool error so the model sees the rejection in the
            # conversation history and learns the directive applies.
            return {
                "status":  "error",
                "message": (
                    f"clarifying_question rejected — ceiling {_CLARIFY_CEILING}/run "
                    "reached. Make your best judgment and proceed."
                ),
            }
```

CC: this block goes immediately ABOVE the existing
`if fn_name == "clarifying_question":` handler dispatch, NOT replacing it.
Calls 1 and 2 still fall through to the existing handler. Call 3+ is
rejected with the directive injected.

---

## Change 3 — `api/metrics.py` — register the counter

CC: open `api/metrics.py`. Add (next to the v2.47.3 plan-nudge counter):

```python
HARNESS_CLARIFY_CEILING_COUNTER = Counter(
    "deathstar_harness_clarify_ceiling_total",
    "clarifying_question calls rejected by harness ceiling (v2.47.4)",
    labelnames=["agent_type"],
)
```

---

## Verify

```bash
python -m py_compile api/agents/step_state.py api/agents/step_tools.py api/metrics.py
grep -n "clarifying_question_count\|CLARIFY_CEILING" api/agents/step_state.py api/agents/step_tools.py
```

Expected: counter and ceiling logic present, no syntax errors.

After deploy, run the clarify-* tests on mem-off via the Tests panel:

```bash
TOKEN=<paste hp1_auth cookie>
for tid in clarify-01 clarify-02 clarify-03 clarify-04; do
    curl -s -b "hp1_auth=$TOKEN" -X POST http://localhost:8000/api/tests/run \
        -H 'Content-Type: application/json' \
        -d "{\"test_ids\": [\"$tid\"], \"memory_enabled\": false}"
    sleep 60
done
```

Expected: all 4 either pass cleanly OR fail with a non-timeout reason
(e.g. "Expected plan_pending" — which v2.47.3 then catches).

The container log should show `[harness] clarifying_question #3 blocked`
and `[harness] clarification ceiling reached, forcing forward progress`
for tests that hit the cap.

---

## Version bump

Update `VERSION`: `2.47.3` → `2.47.4`

---

## Commit

```
git add -A
git commit -m "fix(agent): v2.47.4 clarification ceiling — cap clarifying_question at 2/run, force forward progress"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```

After this lands together with v2.47.2 (memory poisoning) and v2.47.3
(plan force), the next mem-off baseline should hit ≥94% and mem-on
should return to ≥95% — both above the v2.45.17 anchor.
