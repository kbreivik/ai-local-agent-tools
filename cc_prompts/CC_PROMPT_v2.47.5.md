# CC PROMPT — v2.47.5 — fix(agent): clarify-then-text-exit rescue for action/execute runs

## What this does
Closes 3 of the 5 remaining mem-on failures from the v2.47.4 baseline:
`action-drain-01`, `action-rollback-01`, `action-upgrade-01`. All three
share an identical failure mode visible in `test_run_results`:

- `clarification_question` populated (agent asked a clarifying question)
- `clarification_answer_used` populated (test answered it via prearm)
- `plan_steps_count = 0`, `plan_approved = false`
- `failures: ["Expected plan_pending, none triggered"]`
- Duration 67-91s, no timeout

Pattern: agent calls `clarifying_question()` → receives prearmed answer →
**exits with text** (`finish=="stop"`, no further tool calls) instead of
calling `plan_action()`.

The v2.45.18 clarify→plan_action injection adds a system message after
the clarification handler returns, but the model's NEXT turn produces
plain text rather than a tool call. The harness has no recovery for this
specific path — once `finish=="stop"` is reached, it falls through
`run_stop_path_guards` → degraded-findings synthesis → `done` broadcast →
break.

This fix adds a new guard in the natural-exit path: when an action/execute
agent reaches stop AND has called `clarifying_question` AND has NOT
called `plan_action`, harness rejects the empty completion and forces
one more LLM round with a hard directive.

Idempotent — fires once per run via `state.plan_force_nudge_fired`
(already declared in StepState for v2.47.3, dual-purpose here).

Version bump: 2.47.4 → 2.47.5

---

## Context — where the rescue fits

`api/routers/agent.py:_run_single_agent_step` has a while-loop with this
shape:

```python
while step < max_steps:
    ...
    _llm = await call_llm_step(...)
    response, finish, msg = _llm.response, _llm.finish, _llm.msg

    if finish == "stop" or not msg.tool_calls:
        _guard = await run_stop_path_guards(...)
        if _guard == GuardOutcome.RETRY:
            continue
        if _guard in (GuardOutcome.FAIL, GuardOutcome.RESCUED):
            break
        # GuardOutcome.PROCEED — fall through to degraded synthesis + done

        # ... degraded findings synthesis ...
        # ... maybe_force_empty_synthesis ...
        # ... done broadcast ...
        break
```

The new rescue check goes between the `# GuardOutcome.PROCEED` comment
and the existing degraded-findings synthesis block. It either `continue`s
the loop (one more LLM turn) or falls through unchanged.

---

## Change 1 — `api/routers/agent.py` — clarify-then-text-exit rescue

Open `api/routers/agent.py` and find `_run_single_agent_step`. Inside
the while-loop, locate the block that begins:

```python
            if finish == "stop" or not msg.tool_calls:
                _guard = await run_stop_path_guards(
                    ...
                )
                if _guard == GuardOutcome.RETRY:
                    continue
                if _guard in (GuardOutcome.FAIL, GuardOutcome.RESCUED):
                    break
                # GuardOutcome.PROCEED — fall through to degraded synthesis + done
```

Immediately after the `# GuardOutcome.PROCEED — fall through` comment
and BEFORE the existing `# Synthesise degraded findings if present` block,
insert:

```python
                # v2.47.5 — clarify-then-text-exit rescue.
                # Pattern observed in action-drain-01, action-rollback-01,
                # action-upgrade-01 (mem-on baseline 2026-04-25): agent
                # called clarifying_question, received prearmed answer,
                # then exited via finish=="stop" with text instead of
                # calling plan_action(). The v2.45.18 system-message
                # injection in step_tools._handle_clarifying_question
                # told the model to call plan_action() next, but the
                # model produced text. This guard rejects the empty
                # completion and forces ONE more LLM turn with a hard
                # directive. Idempotent — re-uses the v2.47.3 nudge flag.
                if (
                    agent_type in ("action", "execute")
                    and not state.plan_action_called
                    and "clarifying_question" in state.tools_used_names
                    and not state.plan_force_nudge_fired
                ):
                    state.plan_force_nudge_fired = True
                    messages.append({
                        "role": "system",
                        "content": (
                            "[harness] You called clarifying_question() and "
                            "received an answer, then exited with text instead "
                            "of calling plan_action(). For an EXECUTE-type "
                            "task this is a protocol failure. Re-read the task "
                            "and the user's clarification answer above, then "
                            "your NEXT response MUST be a plan_action() tool "
                            "call (NOT text) with concrete summary + steps. "
                            "Do NOT respond with prose. Do NOT call audit_log. "
                            "Do NOT call escalate. Call plan_action() now."
                        ),
                    })
                    await manager.send_line(
                        "step",
                        "[harness] clarify-then-text-exit rescue — forcing one "
                        "more turn for plan_action()",
                        status="warning", session_id=session_id,
                    )
                    try:
                        from api.metrics import HARNESS_PLAN_NUDGES_COUNTER
                        HARNESS_PLAN_NUDGES_COUNTER.labels(
                            agent_type=agent_type,
                        ).inc()
                    except Exception:
                        pass
                    continue   # one more LLM turn
```

CC: this goes inside the `if finish == "stop" or not msg.tool_calls:`
block. The `continue` re-enters the while-loop without breaking out, so
`step` increments naturally and the next LLM call happens with the
hardened directive in messages.

---

## Change 2 — same file, audit_log-only path

Find this existing block (further down in the same loop):

```python
            # Fix 1C: if entire step was only audit_log calls, the agent is done
            # Exception: if escalate was just blocked, the model may call audit_log
            # as a confused "done" signal — don't treat it as completion; let loop continue.
            _step_names = [tc.function.name for tc in msg.tool_calls]
            if (_step_names and all(n == "audit_log" for n in _step_names)
                    and state.last_blocked_tool != "escalate"):
```

Add the same clarify-then-no-plan check inside this branch BEFORE the
synthesis. Right after the `_step_names` line and before the existing
block runs, insert:

```python
            _step_names = [tc.function.name for tc in msg.tool_calls]

            # v2.47.5 — audit_log-only step on action/execute that already
            # clarified but never planned: same rescue path. The model
            # took clarification answer → wrote audit_log → would otherwise
            # exit. Force one more turn for plan_action().
            if (
                _step_names
                and all(n == "audit_log" for n in _step_names)
                and agent_type in ("action", "execute")
                and not state.plan_action_called
                and "clarifying_question" in state.tools_used_names
                and not state.plan_force_nudge_fired
            ):
                state.plan_force_nudge_fired = True
                # Mark the audit_log result as a harness-rejected
                # placeholder so the model sees explicit feedback
                messages.append({
                    "role": "system",
                    "content": (
                        "[harness] You called audit_log() after the "
                        "clarification but never called plan_action(). "
                        "audit_log() is for AFTER an action completes — "
                        "not as a substitute for plan_action(). Your NEXT "
                        "response MUST be plan_action() as a tool call "
                        "with concrete summary + steps. "
                        "Do NOT call audit_log() again. "
                        "Do NOT respond with text."
                    ),
                })
                await manager.send_line(
                    "step",
                    "[harness] audit_log-only after clarify rescue — "
                    "forcing plan_action()",
                    status="warning", session_id=session_id,
                )
                try:
                    from api.metrics import HARNESS_PLAN_NUDGES_COUNTER
                    HARNESS_PLAN_NUDGES_COUNTER.labels(
                        agent_type=agent_type,
                    ).inc()
                except Exception:
                    pass
                continue

            if (_step_names and all(n == "audit_log" for n in _step_names)
                    and state.last_blocked_tool != "escalate"):
                # ... existing audit-log-only-done block stays unchanged ...
```

CC: place the new block BEFORE the existing `if (_step_names and all(...))`
check. Both checks read the same `_step_names` local. The new block
catches the action/execute case before the existing block treats it as
done.

---

## Verify

```bash
python -m py_compile api/routers/agent.py

grep -n "clarify-then-text-exit\|audit_log-only after clarify" api/routers/agent.py
```

Expected: two matches (one per insertion site).

After deploy, re-run the 3 failing action tests via the Tests panel or:

```bash
TOKEN=<paste hp1_auth cookie>
for tid in action-drain-01 action-rollback-01 action-upgrade-01; do
    curl -s -b "hp1_auth=$TOKEN" -X POST http://localhost:8000/api/tests/run \
        -H 'Content-Type: application/json' \
        -d "{\"test_ids\": [\"$tid\"]}"
    sleep 100
done
```

Expected: all 3 pass with `plan_steps_count > 0` and `plan_approved=false`
(test cancels). Container log should show
`[harness] clarify-then-text-exit rescue — forcing one more turn for plan_action()`
or the audit_log variant for each test.

---

## Version bump

Update `VERSION`: `2.47.4` → `2.47.5`

---

## Commit

```
git add -A
git commit -m "fix(agent): v2.47.5 clarify-then-text-exit rescue for action/execute runs"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```

After deploy, run the test suite — `full-mem-on-baseline` should hit
≥93% (closes the 3 action-test failures, leaves the 2 elastic failures
that v2.47.6 targets).
