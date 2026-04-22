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
