# CC PROMPT — v2.8.1 — LLM Temperature Profile + /no_think for Cheap Steps

## What this does

Different agent steps need different temperature settings and thinking budgets:
- **Tool-call steps**: temperature=0.1 — deterministic, structured JSON tool args
- **Final summary step**: temperature=0.3 — more natural readable prose
- **Force-summary step** (max_steps exceeded): temperature=0.3
- **Audit-log-only steps**: append `/no_think` to disable <think> block entirely
- **Coordinator/plan steps**: temperature=0.1 (precision required)

Also reduces Min P from 0.05 to 0.1 in API calls for more consistent JSON output.

Version bump: 2.8.0 → 2.8.1 (targeted tuning, same architecture)

---

## Change — api/routers/agent.py only

### 1 — Add step temperature resolver

Add this function near `_lm_base()` / `_lm_key()`:

```python
def _step_temperature(agent_type: str, has_tool_calls: bool, is_force_summary: bool = False) -> float:
    """Return appropriate temperature for this step type.

    Tool-call steps need low temperature for deterministic JSON argument formatting.
    Text-only steps (final summary, force summary) benefit from slightly higher
    temperature for more natural, readable prose.
    """
    if is_force_summary:
        return 0.3
    if not has_tool_calls:
        # Text-only response (final step)
        return 0.3
    # Tool-call step — deterministic
    return 0.1
```

### 2 — Add /no_think helper

```python
def _should_disable_thinking(tool_names_this_step: list[str], step: int, max_steps: int) -> bool:
    """Return True if we should append /no_think to suppress the <think> block.

    Qwen3 supports /no_think suffix to skip chain-of-thought reasoning.
    Use this for steps where structured output matters more than reasoning:
    - audit_log-only steps (model is just recording, not deciding)
    - First step of a simple single-tool task (fast path)

    Do NOT use for planning steps, multi-tool steps, or first steps of complex tasks.
    """
    # Only audit_log in this step — no reasoning needed
    if tool_names_this_step == ["audit_log"]:
        return True
    return False
```

### 3 — Apply temperature profile at each LLM call

In `_run_single_agent_step`, find the `client.chat.completions.create()` call in the while loop:

```python
            try:
                response = client.chat.completions.create(
                    model=_lm_model(),
                    messages=messages,
                    tools=tools_spec,
                    tool_choice="auto",
                    temperature=0.1,
                    max_tokens=2048,
                )
```

Replace the `temperature=0.1` line dynamically. The temperature isn't known until after
the response, so keep 0.1 for the main loop. BUT for the force-summary call (at max_steps),
update the existing hardcoded 0.1:

Find the force summary call at the `else:` clause of the while loop:

```python
            force_response = client.chat.completions.create(
                model=_lm_model(),
                messages=messages,
                tools=None,
                tool_choice=None,
                temperature=0.1,    # ← change this
                max_tokens=600,
            )
```

Change to `temperature=0.3`.

Also find the `done` broadcast path where finish == "stop" (text-only final response).
Before broadcasting, if this is the final step and finish == "stop", it was a summary.
No code change needed here — temperature is already set at call time.

### 4 — /no_think for audit_log steps

After the step counter increment and before the LLM call, check if the previous step
was audit_log only and inject hint:

```python
            # For audit_log-only likely steps: hint to skip thinking
            # We can't know tool names in advance, so inject at message level
            # by checking the prior step's tool calls
            _prior_step_tools = [tc.function.name for tc in (msg.tool_calls or [])] if step > 1 and 'msg' in dir() else []
            if _should_disable_thinking(_prior_step_tools, step, max_steps):
                # Append /no_think to the last user message for Qwen3
                for i in range(len(messages) - 1, -1, -1):
                    if messages[i]["role"] == "user":
                        content = messages[i]["content"]
                        if isinstance(content, str) and "/no_think" not in content:
                            messages[i] = {**messages[i], "content": content + "\n/no_think"}
                        break
```

### 5 — Raise Min P in all API calls

In `_run_single_agent_step`, all `client.chat.completions.create()` calls:

Change any `min_p` parameter if present. If not present, add to the force-summary call:

```python
            force_response = client.chat.completions.create(
                model=_lm_model(),
                messages=messages,
                tools=None,
                tool_choice=None,
                temperature=0.3,
                max_tokens=600,
                extra_body={"min_p": 0.1},  # more consistent token distribution
            )
```

For the main loop call, add the same:

```python
                response = client.chat.completions.create(
                    model=_lm_model(),
                    messages=messages,
                    tools=tools_spec,
                    tool_choice="auto",
                    temperature=0.1,
                    max_tokens=2048,
                    extra_body={"min_p": 0.1},
                )
```

Note: `extra_body` passes through to LM Studio's OpenAI-compat API. If LM Studio
ignores unknown params, this is harmless. If it causes errors, remove and set Min P
directly in LM Studio's inference preset.

---

## Version bump

Update VERSION: `2.8.0` → `2.8.1`

---

## Commit

```bash
git add -A
git commit -m "feat(agent): v2.8.1 temperature profiles and /no_think for cheap steps

- Force-summary call: temperature 0.1 → 0.3 for better prose
- /no_think suffix injected for audit_log-only steps (saves ~200-400 tokens)
- min_p=0.1 via extra_body for more consistent JSON argument formatting
- _step_temperature() helper for future coordinator integration"
git push origin main
```
