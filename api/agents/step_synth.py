"""step_synth — forced synthesis on empty / near-empty completion — v2.41.4.

Extracted from api/routers/agent.py _run_single_agent_step.

maybe_force_empty_synthesis() replaces the inner async closure
_maybe_force_empty_synthesis() that previously used nonlocal to
write state back. With StepState, state is a mutable object —
no nonlocal needed.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)


async def maybe_force_empty_synthesis(
    state,          # StepState
    client,
    messages: list,
    *,
    manager,
    session_id: str,
    operation_id: str,
    agent_type: str,
    tool_budget: int,
) -> str:
    """Run forced_synthesis when the loop exits with a missing / near-empty /
    preamble-only final_answer but substantive tool calls were made.

    Idempotent: sets state.empty_completion_synth_done after first call.
    Returns the synthesis text (or "" on no-op / failure).

    Mirrors the logic of the former _maybe_force_empty_synthesis() inner closure.
    """
    from api.agents.gates import _classify_terminal_final_answer
    from api.routers.agent import _lm_model, _extract_response_model

    if state.empty_completion_synth_done:
        return ""

    # Check if DB already has a substantive answer (from render_tool dispatch)
    _db_final = ""
    try:
        from api.db import queries as _q
        from api.db.base import get_engine as _ge
        async with _ge().connect() as _c:
            _op = await _q.get_operation(_c, operation_id)
            if _op:
                _db_final = _op.get("final_answer") or ""
    except Exception:
        pass

    _answer_to_check = state.last_reasoning or _db_final
    rescue_reason = _classify_terminal_final_answer(_answer_to_check)

    if rescue_reason is None:
        return ""  # answer is substantive — no rescue needed

    if state.substantive_tool_calls < 1:
        return ""  # never gathered data — forced synthesis would hallucinate

    # Skip if render tool already wrote a long answer
    if len(_db_final) >= 1500:
        return ""

    state.empty_completion_synth_done = True

    try:
        from api.agents.forced_synthesis import run_forced_synthesis
        from api.routers.agent import _tool_budget_for
        synth_text, harness_msg, raw_resp = run_forced_synthesis(
            client=client,
            model=_lm_model(),
            messages=messages,
            agent_type=agent_type,
            reason=rescue_reason,
            tool_count=len(state.tools_used_names),
            budget=tool_budget,
            actual_tool_names=state.tools_used_names,
            operation_id=operation_id,
            actual_tool_calls=[
                {
                    "name":   tc.get("tool") or tc.get("tool_name") or tc.get("name"),
                    "status": tc.get("status"),
                    "result": tc.get("result") or tc.get("content"),
                }
                for tc in (state.tool_history or [])
            ],
        )

        if synth_text:
            state.last_reasoning = synth_text
            try:
                await manager.send_line("reasoning", synth_text, session_id=session_id)
            except Exception:
                pass
            try:
                from api.logger import log_llm_step
                await log_llm_step(
                    operation_id=operation_id,
                    step_index=state.trace_step_index,
                    messages_delta=[{"role": "system", "content": harness_msg}],
                    response_raw=raw_resp or {"forced_synthesis": {"reason": rescue_reason, "text": synth_text}},
                    agent_type=agent_type,
                    is_subagent=state.trace_is_subagent,
                    parent_op_id=state.trace_parent_op_id,
                    temperature=0.3,
                    model=_extract_response_model(raw_resp, fallback=_lm_model()),
                    provider="lm_studio",
                )
                state.trace_step_index += 1
            except Exception as _te:
                log.debug("%s trace log failed: %s", rescue_reason, _te)
            return synth_text
    except Exception as e:
        log.warning("forced_synthesis on %s failed op=%s: %s", rescue_reason, operation_id, e)
    return ""
