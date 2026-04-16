# CC PROMPT — v2.32.5 — Enforced tool call budgets per agent type

## What this does
Adds code-level enforcement of tool call budgets per agent type. Currently, only the
observe prompt mentions "6 tool calls" as a text instruction — the code only enforces
max_steps (LLM inference rounds), not total tool calls. One step can fire multiple tool
calls, so the actual tool usage can far exceed the intended budget (e.g. investigate
used 21 tool calls in testing).

This adds a `_tool_call_count` check inside the tool execution loop. When the budget
is exhausted, the harness injects a "tool budget reached — summarize now" user message
and the model produces its final answer without further tool calls.

Version bump: 2.32.4 → 2.32.5

## Change 1 — api/routers/agent.py — Add tool call budget constants

Find the line:

```python
_MAX_STEPS_BY_TYPE = {"status": 12, "observe": 12, ...}
```

Add immediately after it:

```python
# ─── Tool call budgets per agent type (v2.32.5) ──────────────────────────────
# Unlike max_steps (LLM inference rounds), this counts actual tool invocations.
# When exhausted, the harness forces a summary — no more tool calls allowed.
_MAX_TOOL_CALLS_BY_TYPE = {
    "status": 8, "observe": 8,
    "research": 16, "investigate": 16,
    "action": 14, "execute": 14,
    "build": 12,
}
```

## Change 2 — api/routers/agent.py — Check tool call budget in the loop

In `_run_single_agent_step`, inside the main `while step < max_steps:` loop, find the
section right AFTER the cancellation check and the cap_exceeded check (which checks
wall-clock, tokens, destructive calls, and tool failures). There should be a line:

```python
            step += 1
```

Right AFTER `step += 1` and AFTER the `_cap_exceeded` check block, add a new check:

```python
            # v2.32.5: Tool call budget enforcement
            _tool_budget = _MAX_TOOL_CALLS_BY_TYPE.get(agent_type, 16)
            if len(tools_used_names) >= _tool_budget:
                await manager.send_line(
                    "step",
                    f"[budget] Tool call budget reached ({len(tools_used_names)}/{_tool_budget}) "
                    f"— forcing summary",
                    status="ok", session_id=session_id,
                )
                # Inject force-summary message and let the model produce final text
                messages.append({
                    "role": "user",
                    "content": (
                        f"TOOL BUDGET REACHED ({len(tools_used_names)}/{_tool_budget}). "
                        "You have used all available tool calls. "
                        "Write your final summary NOW as plain text — no more tool calls allowed. "
                        "Use the data you have already gathered."
                    ),
                })
                try:
                    force_response = client.chat.completions.create(
                        model=_lm_model(),
                        messages=messages,
                        tools=None,
                        tool_choice=None,
                        temperature=0.3,
                        max_tokens=800,
                        extra_body={"min_p": 0.1},
                    )
                    forced_text = force_response.choices[0].message.content or ""
                    if forced_text:
                        last_reasoning = forced_text
                        await manager.send_line("reasoning", forced_text, session_id=session_id)
                except Exception as _fe:
                    log.debug("Tool budget force summary failed: %s", _fe)

                if is_final_step:
                    choices = _extract_choices(last_reasoning) if last_reasoning else None
                    await manager.broadcast({
                        "type": "done", "session_id": session_id, "agent_type": agent_type,
                        "content": last_reasoning or f"Agent reached tool budget ({_tool_budget}).",
                        "status": "ok", "choices": choices or [],
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                break
```

## Change 3 — api/routers/agent.py — Stream budget status

In the tool execution inner loop (`for tc in msg.tool_calls:`), right before each tool
is invoked, add a budget warning when approaching the limit. Find the line where
`tools_used_names.append(fn_name)` is called and add after it:

```python
                tools_used_names.append(fn_name)
                # v2.32.5: Warn when approaching tool budget
                _tb = _MAX_TOOL_CALLS_BY_TYPE.get(agent_type, 16)
                if len(tools_used_names) == _tb - 2:
                    messages_budget_warning = True  # flag checked below
```

Actually, this is unnecessary complexity. The budget check at the top of the loop is
sufficient — it checks before each new LLM call, which is the right granularity. If the
model fires 3 tool calls in one batch that pushes it over budget, the next iteration
will catch it and force the summary. This is acceptable since the overshoot is at most
one batch (typically 1-3 calls).

DELETE this Change 3 — the budget check in Change 2 is sufficient.

## Version bump

Update VERSION file: 2.32.4 → 2.32.5

## Commit

```bash
git add -A
git commit -m "feat(agents): v2.32.5 enforced tool call budgets per agent type

Adds _MAX_TOOL_CALLS_BY_TYPE: observe=8, investigate=16, execute=14,
build=12. Checked at the start of each LLM inference step — when the
budget is exhausted, the harness forces a summary with no further tool
calls.

Previously only max_steps (LLM rounds) was enforced, but one step can
fire multiple tool calls. Investigate agent used 21 calls in testing;
budget of 16 would have stopped it earlier with the same findings."
git push origin main
```
