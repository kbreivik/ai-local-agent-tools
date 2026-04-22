# CC PROMPT — v2.41.1 — refactor(agents): extract step_llm.py — LLM call + trace

## Context

SPEC: `cc_prompts/SPEC_v2.41_AGENT_SPLIT.md`
Depends on: v2.41.0 (StepState) must be DONE first.

Extracts the per-step LLM call, token accounting, trace persistence, and
working memory injection from `_run_single_agent_step` into
`api/agents/step_llm.py`. Pure refactor — zero logic change.

Version bump: 2.41.0 → 2.41.1.

---

## What lives in step_llm.py

The section to extract covers (in order):
1. Working memory injection into `messages` (step > 1)
2. Step header broadcast (`── Step N ──`)
3. `/no_think` injection for cheap steps
4. Flush queued_harness_messages from propose_state into messages
5. `client.chat.completions.create()` call
6. Token counting into state.total_prompt_tokens / completion_tokens
7. LLM trace persistence (`log_llm_step`)
8. `LOG_LLM_EXCHANGES` optional full-exchange logging
9. `last_reasoning` assignment on `finish == "stop" and not msg.tool_calls`
10. `msg.content` broadcast + working memory extraction

Returns a `LlmStepResult` dataclass so the orchestrator can branch on it.

---

## Change 1 — create `api/agents/step_llm.py`

```python
"""step_llm — per-step LLM call, trace, and working memory — v2.41.1.

Extracted from api/routers/agent.py _run_single_agent_step.
"""
from __future__ import annotations
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class LlmStepResult:
    """Return value from call_llm_step."""
    response: Any         # raw OpenAI-compat response object
    finish: str           # finish_reason string
    msg: Any              # response.choices[0].message
    hard_error: bool = False   # True if LM Studio raised an exception


async def call_llm_step(
    state,            # StepState
    client,           # OpenAI-compat client
    messages: list,
    tools_spec: list,
    step: int,
    max_steps: int,
    system_prompt: str,
    *,
    manager,
    session_id: str,
    operation_id: str,
    agent_type: str,
    is_final_step: bool = True,
) -> LlmStepResult:
    """Execute one LLM step: inject context, call model, persist trace.

    Mutates:
      - messages (working memory injection, /no_think injection,
        queued_harness_messages flush, last_reasoning on stop)
      - state.total_prompt_tokens / completion_tokens
      - state.working_memory
      - state.last_reasoning (on finish==stop + no tool_calls)
      - state.trace_prev_msg_count / trace_step_index

    Returns LlmStepResult. If hard_error=True, caller should set
    state.final_status = "error" and break the loop.
    """
    import time as _time
    from api.routers.agent import (
        _should_disable_thinking, _extract_working_memory,
        _lm_model, _extract_response_model,
    )

    # 1. Working memory injection (step > 1)
    if step > 1 and state.working_memory and len(messages) >= 2:
        for i in range(len(messages) - 1, -1, -1):
            if messages[i]["role"] == "user" and isinstance(messages[i].get("content"), str):
                if not messages[i]["content"].startswith("[Step"):
                    messages[i] = {
                        **messages[i],
                        "content": f"{state.working_memory}\n{messages[i]['content']}",
                    }
                break

    # 2. Step header broadcast
    await manager.send_line("step", f"── Step {step} ──", session_id=session_id)

    # 3. /no_think injection for cheap steps
    try:
        _prior_tools = []
        if step > 1:
            # get last assistant message's tool_calls names
            for _m in reversed(messages):
                if _m.get("role") == "assistant" and _m.get("tool_calls"):
                    _prior_tools = [tc["function"]["name"] for tc in _m["tool_calls"]]
                    break
        if _should_disable_thinking(_prior_tools, step, max_steps):
            for i in range(len(messages) - 1, -1, -1):
                if messages[i]["role"] == "user":
                    content = messages[i]["content"]
                    if isinstance(content, str) and "/no_think" not in content:
                        messages[i] = {**messages[i], "content": content + "\n/no_think"}
                    break
    except Exception as _nte:
        log.debug("no_think injection failed: %s", _nte)

    # 4. Flush queued harness messages from propose_state
    if state.propose_state and state.propose_state.queued_harness_messages:
        for _qm in state.propose_state.queued_harness_messages:
            messages.append({"role": "system", "content": _qm})
        state.propose_state.queued_harness_messages.clear()

    # 5. LLM call
    _step_t0 = _time.monotonic()
    try:
        from api.routers.agent import _step_temperature
        _temp = _step_temperature(agent_type, has_tool_calls=True, is_force_summary=False)
        response = client.chat.completions.create(
            model=_lm_model(),
            messages=messages,
            tools=tools_spec,
            tool_choice="auto",
            temperature=_temp,
            max_tokens=2048,
            extra_body={"min_p": 0.1},
        )
    except Exception as e:
        await manager.broadcast({
            "type": "error", "session_id": session_id,
            "content": f"LM Studio error: {e}", "status": "error",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        return LlmStepResult(response=None, finish="error", msg=None, hard_error=True)

    # 6. Token counting
    if hasattr(response, "usage") and response.usage:
        state.total_prompt_tokens     += getattr(response.usage, "prompt_tokens", 0) or 0
        state.total_completion_tokens += getattr(response.usage, "completion_tokens", 0) or 0

    msg    = response.choices[0].message
    finish = response.choices[0].finish_reason

    # 7. LLM trace persistence
    try:
        _msgs_delta = messages[state.trace_prev_msg_count:]
        state.trace_prev_msg_count = len(messages)
        _resp_raw: dict = {}
        try:
            _resp_raw = response.model_dump()
        except Exception:
            try:
                _resp_raw = response.to_dict()
            except Exception:
                _resp_raw = {
                    "choices": [{"finish_reason": finish, "message": {
                        "content": msg.content or "",
                        "tool_calls": [
                            {"id": tc.id, "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            }}
                            for tc in (msg.tool_calls or [])
                        ],
                    }}],
                    "usage": (
                        {
                            "prompt_tokens": getattr(response.usage, "prompt_tokens", 0) or 0,
                            "completion_tokens": getattr(response.usage, "completion_tokens", 0) or 0,
                        }
                        if hasattr(response, "usage") and response.usage else {}
                    ),
                }
        from api.logger import log_llm_step
        await log_llm_step(
            operation_id=operation_id,
            step_index=state.trace_step_index,
            messages_delta=_msgs_delta,
            response_raw=_resp_raw,
            system_prompt=(system_prompt if state.trace_step_index == 0 else None),
            tools_manifest=(tools_spec if state.trace_step_index == 0 else None),
            agent_type=agent_type,
            is_subagent=state.trace_is_subagent,
            parent_op_id=state.trace_parent_op_id,
            temperature=_temp,
            model=_extract_response_model(response, fallback=_lm_model()),
            provider="lm_studio",
        )
        state.trace_step_index += 1
    except Exception as _te:
        log.debug("log_llm_step failed: %s", _te)

    # 8. Optional full-exchange logging
    if os.environ.get("LOG_LLM_EXCHANGES", "").lower() in ("1", "true", "yes"):
        try:
            from api.logger import log_llm_exchange
            await log_llm_exchange(
                operation_id, step, messages,
                response_text=msg.content or "",
                tool_calls=[{"function": {"name": tc.function.name}} for tc in (msg.tool_calls or [])],
                prompt_tokens=getattr(response.usage, "prompt_tokens", 0) or 0 if hasattr(response, "usage") and response.usage else 0,
                completion_tokens=getattr(response.usage, "completion_tokens", 0) or 0 if hasattr(response, "usage") and response.usage else 0,
                model=_lm_model(),
                duration_ms=int((_time.monotonic() - _step_t0) * 1000),
            )
        except Exception:
            pass

    # 9. last_reasoning assignment (stop path only, no tool_calls)
    if finish == "stop" and not msg.tool_calls:
        state.last_reasoning = msg.content or ""

    # 10. Content broadcast + working memory extraction
    if msg.content:
        await manager.send_line("reasoning", msg.content, session_id=session_id)
        _wm = _extract_working_memory(msg.content, step)
        if _wm:
            state.working_memory = _wm

    return LlmStepResult(response=response, finish=finish, msg=msg)
```

---

## Change 2 — `api/routers/agent.py` — wire step_llm

Add import near top:
```python
from api.agents.step_llm import call_llm_step, LlmStepResult
```

Inside `_run_single_agent_step`, inside the while loop, locate the block starting
with the working-memory injection and ending after the `msg.content` broadcast.
Replace the entire block (steps 1–10 above) with a single call:

```python
            _llm = await call_llm_step(
                state, client, messages, tools_spec, step, max_steps, system_prompt,
                manager=manager, session_id=session_id, operation_id=operation_id,
                agent_type=agent_type, is_final_step=is_final_step,
            )
            if _llm.hard_error:
                break
            response, finish, msg = _llm.response, _llm.finish, _llm.msg
```

The variables `response`, `finish`, `msg` remain in scope for the rest of the
loop body (guard check, tool dispatch). Everything else that previously read
`total_prompt_tokens`, `_working_memory`, `last_reasoning`, `_trace_step_index`
now reads from `state.*`.

---

## Verification

```bash
python -c "from api.agents.step_llm import call_llm_step; print('ok')"
python -m pytest tests/ -x -q 2>&1 | tail -10
```

---

## Version bump

Update `VERSION`: `2.41.0` → `2.41.1`

---

## Commit

```
git add -A
git commit -m "refactor(agents): v2.41.1 extract step_llm.py — LLM call, trace, working memory"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
