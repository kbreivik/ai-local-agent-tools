# CC PROMPT — v2.45.18 — fix(agent): clarify→plan_action — append system message to LLM messages list

## What this does
Fixes 4 still-failing action tests where the model calls `audit_log` after
`clarifying_question` instead of `plan_action`. v2.45.13 injected the directive
into a WS broadcast list — the LLM never saw it. This prompt injects the
directive into the actual LLM `messages` list passed into the next step.

Pattern matches existing harness injections in step_tools.py (sub-agent
distrust signal, batch-budget nudge, propose_subtask dedup) which all do
`messages.append({"role": "system", ...})` directly.

Version bump: 2.45.17 → 2.45.18

---

## Context (read before editing)

`api/agents/step_tools.py` currently has:

```python
async def _handle_clarifying_question(
    tc, fn_args: dict, *,
    state, session_id: str, task: str, manager,
) -> dict:
    ...
    return {
        "status":  "ok",
        "answer":  answer,
        "message": f"User answered: {answer}.{_directive}",
        ...
    }
```

And the lifecycle dispatcher calls it without passing `messages`:

```python
    if fn_name == "clarifying_question":
        return await _handle_clarifying_question(
            tc, fn_args,
            state=state, session_id=session_id, task=task, manager=manager,
        )
```

The result dict eventually gets appended as `{"role": "tool", "tool_call_id":
tc.id, "content": tool_content}` by the dispatcher. The model reads this and
ignores the `Your NEXT tool call MUST be plan_action()` directive embedded in
the tool message.

The fix: inject a separate `{"role": "system", "content": ...}` message into
the LLM messages list right after the answer arrives, so it sits in the
conversation context the LLM sees on its next turn.

---

## Change 1 — `api/agents/step_tools.py` — add `messages` param to handler

Find this function signature:

```python
async def _handle_clarifying_question(
    tc, fn_args: dict, *,
    state, session_id: str, task: str, manager,
) -> dict:
```

Replace with:

```python
async def _handle_clarifying_question(
    tc, fn_args: dict, *,
    state, session_id: str, task: str, manager, messages: list,
) -> dict:
```

---

## Change 2 — `api/agents/step_tools.py` — inject system message after answer

Inside `_handle_clarifying_question`, find the existing `answer = await
wait_for_clarification(session_id)` block followed by the
`_is_cancel = answer.lower() in (...)` and `_directive = (...)` lines, and
the `return {...}` dict.

Right BEFORE the `return {...}` statement, insert:

```python
    # v2.45.18 — inject system message into the LLM messages list so the
    # directive is visible in the conversation context on the next turn.
    # The tool result message alone (with embedded directive) is being
    # ignored by the model; a follow-up system message is the pattern that
    # works (see sub-agent distrust signal and budget-truncate nudge).
    if not _is_cancel:
        messages.append({
            "role": "system",
            "content": (
                f"[harness] User clarification received: '{answer}'. "
                "You now have all information needed to proceed. "
                "Your NEXT tool call MUST be plan_action() with concrete "
                "summary + steps. "
                "Do NOT call audit_log. "
                "Do NOT ask another clarifying_question. "
                "Do NOT call escalate. "
                "Call plan_action() now."
            ),
        })
        await manager.send_line(
            "step",
            "[clarify→plan] system directive injected into LLM context",
            status="ok", session_id=session_id,
        )
```

---

## Change 3 — `api/agents/step_tools.py` — pass `messages` from dispatcher

Find this block in `_handle_lifecycle_tools`:

```python
    if fn_name == "clarifying_question":
        return await _handle_clarifying_question(
            tc, fn_args,
            state=state, session_id=session_id, task=task, manager=manager,
        )
```

Replace with:

```python
    if fn_name == "clarifying_question":
        return await _handle_clarifying_question(
            tc, fn_args,
            state=state, session_id=session_id, task=task, manager=manager,
            messages=messages,
        )
```

---

## Verify

```bash
python -m py_compile api/agents/step_tools.py
grep -A2 "clarify→plan" api/agents/step_tools.py | head -10
```

Expected: harness system message string present, no syntax errors.

---

## Version bump

Update `VERSION`: `2.45.17` → `2.45.18`

---

## Commit

```
git add -A
git commit -m "fix(agent): v2.45.18 inject clarify→plan_action system message into LLM messages list"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```

After deploy, expect action-drain-01, action-activate-01, orch-verify-01 to
move from `clarify→audit_log` escape into `clarify→plan_action` flow.
