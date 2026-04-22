"""step_guard — hallucination guard + fabrication detector — v2.41.2.

Extracted from api/routers/agent.py _run_single_agent_step.

run_stop_path_guards() covers the entire "finish==stop, no tool_calls"
branch: plan_action safety reminder, hallucination guard, fabrication
check. Returns a GuardOutcome so the orchestrator can continue/break/retry.
"""
from __future__ import annotations
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

log = logging.getLogger(__name__)


class GuardOutcome(Enum):
    PROCEED   = "proceed"    # answer is clean — continue to done broadcast
    RETRY     = "retry"      # injected a harness message — continue loop
    FAIL      = "fail"       # exhausted, hard fail — break loop
    RESCUED   = "rescued"    # external AI replaced the answer — break loop


async def run_stop_path_guards(
    state,             # StepState
    msg,               # LLM message object
    messages: list,
    *,
    manager,
    session_id: str,
    operation_id: str,
    agent_type: str,
    task: str,
    step: int,
    max_steps: int,
    client,
    tools_spec: list,
    is_final_step: bool,
    parent_session_id: str = "",
) -> GuardOutcome:
    """Run all stop-path guards in order.

    Order:
    1. plan_action safety check (execute/action only)
    2. hallucination guard
    3. fabrication detector

    Mutates state.last_reasoning, state.final_status, state.halluc_guard_attempts,
    state.hallucination_block_fired, state.fabrication_detected_once.
    Appends harness messages to messages and state.propose_state.
    """
    from api.agents import MIN_SUBSTANTIVE_BY_TYPE
    from api.routers.agent import _maybe_route_to_external_ai, _extract_choices

    # ── 1. plan_action safety check ───────────────────────────────────────────
    _DESTRUCTIVE_TASK_WORDS = frozenset({
        "upgrade", "downgrade", "rollback", "restart", "drain", "restore",
        "kafka_rolling_restart",
    })
    _task_words = set(re.findall(r'\b\w+\b', task.lower()))
    _has_destructive_intent = bool(_task_words & _DESTRUCTIVE_TASK_WORDS)
    _plan_called = "plan_action" in state.tools_used_names

    if (agent_type in ("action", "execute") and _has_destructive_intent
            and not _plan_called and step < max_steps - 2):
        if msg.content:
            messages.append({"role": "assistant", "content": msg.content})
        messages.append({
            "role": "user",
            "content": (
                "MANDATORY: You must call plan_action() as a TOOL before "
                "executing any destructive action. Do NOT write the plan as text. "
                "Call plan_action() now with: summary, steps (list), "
                "risk_level (low/medium/high), reversible (true/false)."
            ),
        })
        await manager.send_line(
            "step", "[safety] plan_action not yet called — reminding model",
            status="ok", session_id=session_id,
        )
        return GuardOutcome.RETRY

    # ── 2. Hallucination guard ────────────────────────────────────────────────
    _min_subst = MIN_SUBSTANTIVE_BY_TYPE.get(agent_type, 1)
    if state.substantive_tool_calls < _min_subst:
        state.halluc_guard_attempts += 1
        state.hallucination_block_fired = True
        if state.halluc_guard_attempts < state.halluc_guard_max:
            _esc_msg = {
                1: (
                    f"You finalised after {state.substantive_tool_calls} "
                    f"substantive tool call(s). Call at least {_min_subst} "
                    "data-gathering tools BEFORE your final answer. Do NOT "
                    "write an EVIDENCE block citing tools you have not called. "
                    "Meta tools (audit_log, runbook_search, memory_recall, "
                    "propose_subtask, engram_activate, plan_action) do not count."
                ),
                2: (
                    "Second attempt: you are still finalising without tool data. "
                    "The previous answer appears to cite tool calls that did not "
                    "happen. If you genuinely cannot gather data, call escalate() "
                    "with reason='insufficient_tool_access' — do NOT fabricate "
                    "tool output."
                ),
            }.get(state.halluc_guard_attempts, (
                "Final warning: call real data-returning tools or escalate. "
                "Fabricated evidence will cause this task to fail."
            ))
            if msg.content:
                messages.append({"role": "assistant", "content": msg.content})
            messages.append({"role": "system", "content": f"[harness] {_esc_msg}"})
            try:
                from api.metrics import HALLUCINATION_GUARD_COUNTER, HALLUC_GUARD_ATTEMPTS_COUNTER
                HALLUCINATION_GUARD_COUNTER.labels(agent_type=agent_type, outcome="retried").inc()
                HALLUC_GUARD_ATTEMPTS_COUNTER.labels(
                    attempt=str(state.halluc_guard_attempts), agent_type=agent_type
                ).inc()
            except Exception:
                pass
            await manager.broadcast({
                "type":              "hallucination_block",
                "session_id":        session_id,
                "substantive_count": state.substantive_tool_calls,
                "required":          _min_subst,
                "attempt":           state.halluc_guard_attempts,
                "max_attempts":      state.halluc_guard_max,
                "agent_type":        agent_type,
                "timestamp":         datetime.now(timezone.utc).isoformat(),
            })
            await manager.send_line(
                "step",
                f"[halluc-guard] final_answer blocked "
                f"(attempt {state.halluc_guard_attempts}/{state.halluc_guard_max}) — "
                f"{state.substantive_tool_calls}/{_min_subst} substantive tool calls. "
                "Forcing retry.",
                status="warning", session_id=session_id,
            )
            return GuardOutcome.RETRY

        # Exhausted
        return await _guard_exhausted(
            state, messages, manager=manager, session_id=session_id,
            operation_id=operation_id, agent_type=agent_type, task=task,
            client=client, tools_spec=tools_spec, is_final_step=is_final_step,
            parent_session_id=parent_session_id, reason="hallucination_guard_exhausted",
        )

    # ── 3. Fabrication detector ───────────────────────────────────────────────
    try:
        from api.agents.fabrication_detector import is_fabrication
        _fab_fired, _fab_detail = is_fabrication(
            msg.content or "",
            state.tools_used_names,
            min_cites=state.fabrication_min_cites,
            score_threshold=state.fabrication_score_threshold,
        )
    except Exception as _fe:
        log.debug("fabrication_detector error: %s", _fe)
        _fab_fired, _fab_detail = False, {"score": 0.0, "cited": [], "actual": [], "fabricated": []}

    if _fab_fired and not state.fabrication_detected_once:
        state.fabrication_detected_once = True
        state.halluc_guard_attempts += 1
        try:
            from api.metrics import FABRICATION_DETECTED_COUNTER
            FABRICATION_DETECTED_COUNTER.labels(
                agent_type=agent_type,
                is_subagent=str(bool(parent_session_id)).lower(),
            ).inc()
        except Exception:
            pass
        log.warning(
            "fabrication_detected operation=%s cited=%d fabricated=%d score=%.2f",
            operation_id,
            len(_fab_detail.get("cited", [])),
            len(_fab_detail.get("fabricated", [])),
            _fab_detail.get("score", 0.0),
        )
        if state.halluc_guard_attempts < state.halluc_guard_max:
            _fab_names = ", ".join(_fab_detail["fabricated"][:5]) or "(unknown)"
            if msg.content:
                messages.append({"role": "assistant", "content": msg.content})
            messages.append({
                "role": "system",
                "content": (
                    f"[harness] Your answer cites "
                    f"{len(_fab_detail['fabricated'])} tool calls that "
                    f"did not happen in this run: {_fab_names}. "
                    "You must only cite tools you have actually called. "
                    "If you need data you don't have, call the tool now "
                    "or call escalate()."
                ),
            })
            await manager.broadcast({
                "type":       "fabrication_detected",
                "session_id": session_id,
                "cited":      _fab_detail.get("cited", []),
                "fabricated": _fab_detail.get("fabricated", []),
                "score":      _fab_detail.get("score", 0.0),
                "agent_type": agent_type,
                "timestamp":  datetime.now(timezone.utc).isoformat(),
            })
            await manager.send_line(
                "step",
                f"[fabrication] final_answer cites "
                f"{len(_fab_detail['fabricated'])} uncalled tools — forcing retry.",
                status="warning", session_id=session_id,
            )
            return GuardOutcome.RETRY

        # Fabrication exhausted
        _reason = (
            f"Task failed: hallucination_guard_exhausted "
            f"(fabrication detected — score {_fab_detail.get('score', 0.0):.2f}, "
            f"{len(_fab_detail.get('fabricated', []))} uncalled tool(s) cited)."
        )
        return await _guard_exhausted(
            state, messages, manager=manager, session_id=session_id,
            operation_id=operation_id, agent_type=agent_type, task=task,
            client=client, tools_spec=tools_spec, is_final_step=is_final_step,
            parent_session_id=parent_session_id, reason=_reason,
        )

    return GuardOutcome.PROCEED


async def _guard_exhausted(
    state, messages, *, manager, session_id, operation_id, agent_type, task,
    client, tools_spec, is_final_step, parent_session_id, reason,
) -> GuardOutcome:
    """Shared logic when guard is exhausted — try external AI rescue, then fail."""
    from api.routers.agent import _maybe_route_to_external_ai, _extract_choices
    try:
        from api.metrics import HALLUC_GUARD_EXHAUSTED_COUNTER
        HALLUC_GUARD_EXHAUSTED_COUNTER.labels(agent_type=agent_type).inc()
    except Exception:
        pass

    state.last_reasoning = reason
    await manager.send_line(
        "halt",
        f"[halluc-guard] exhausted — failing task to block fabricated evidence.",
        status="failed", session_id=session_id,
    )

    # Try gate_failure external AI rescue
    try:
        _router_synth = await _maybe_route_to_external_ai(
            session_id=session_id, operation_id=operation_id,
            task=task, agent_type=agent_type, messages=messages,
            tool_calls_made=len(state.tools_used_names),
            tool_budget=0, diagnosis_emitted=False,
            consecutive_tool_failures=0,
            halluc_guard_exhausted=True,
            fabrication_detected_count=(2 if state.fabrication_detected_once else 0),
            external_calls_this_op=0,
            scope_entity=parent_session_id or "",
            is_prerun=False,
        )
        if _router_synth:
            state.last_reasoning = _router_synth
            state.final_status = "completed"
            if is_final_step:
                await manager.broadcast({
                    "type": "done", "session_id": session_id, "agent_type": agent_type,
                    "content": state.last_reasoning, "status": "ok", "choices": [],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
            return GuardOutcome.RESCUED
    except Exception as _re:
        log.warning(
            "EXTERNAL_AI_ROUTE_FAIL rule=gate_failure session=%s err=%s", session_id, _re,
        )
        try:
            await manager.send_line(
                "halt",
                f"[external-ai] rescue route failed — {type(_re).__name__}: {str(_re)[:200]}",
                status="failed", session_id=session_id,
            )
        except Exception:
            pass
        state.final_status = "escalation_failed"

    if is_final_step:
        await manager.broadcast({
            "type": "done", "session_id": session_id, "agent_type": agent_type,
            "content": state.last_reasoning, "status": "failed", "choices": [],
            "reason": "hallucination_guard_exhausted",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    if state.final_status != "escalation_failed":
        state.final_status = "failed"
    return GuardOutcome.FAIL
