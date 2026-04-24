"""step_tools — tool call dispatch per step — v2.45.16.

Extracted from api/routers/agent.py _run_single_agent_step.

dispatch_tool_calls() processes all tool calls in a single LLM step.
Returns a ToolsDispatchResult indicating whether the loop should
continue, break, or proceed normally.

v2.45.16: split the giant per-tool elif chain into category handler
functions (lifecycle/kafka/swarm/elastic/memory/infra/misc).
dispatch_tool_calls walks the handler list for each tool call until
one returns a result or _HANDLER_SKIP. Pure refactor — zero logic
change, every handler calls the same underlying functions as before.
"""
from __future__ import annotations
import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

log = logging.getLogger(__name__)


class ToolLoopAction(Enum):
    CONTINUE = "continue"   # inject a harness message + loop back
    BREAK    = "break"      # tool caused a hard stop
    NORMAL   = "normal"     # all tools ran; loop continues normally


@dataclass
class ToolsDispatchResult:
    action: ToolLoopAction = ToolLoopAction.NORMAL
    destructive_calls_delta: int = 0
    tool_failures_delta: int = 0


# ── Tool categorisation ─────────────────────────────────────────────
# Each frozenset lists tools owned by that category handler. Adding a
# new tool only requires appending to the right set; the dispatcher
# stays unchanged. Tools not in any specific set fall through to
# _handle_misc_tools.

_KAFKA_TOOLS = frozenset({
    "kafka_broker_status", "kafka_topic_health", "kafka_consumer_lag",
    "kafka_exec", "kafka_rolling_restart_safe", "pre_kafka_check",
    "kafka_topic_inspect", "kafka_topic_list",
})

_SWARM_TOOLS = frozenset({
    "swarm_status", "service_list", "service_health",
    "service_current_version", "service_version_history",
    "service_upgrade", "service_rollback", "node_drain", "node_activate",
    "swarm_node_status", "swarm_service_force_update",
})

_ELASTIC_TOOLS = frozenset({
    "elastic_cluster_health", "elastic_index_stats", "elastic_search_logs",
    "elastic_error_logs", "elastic_log_pattern", "elastic_kafka_logs",
    "elastic_correlate_operation",
})

_MEMORY_TOOLS = frozenset({
    "skill_search", "skill_create", "skill_regenerate", "skill_disable",
    "skill_enable", "skill_import", "runbook_search",
    "checkpoint_save", "checkpoint_restore",
})

_INFRA_TOOLS = frozenset({
    "vm_exec", "infra_lookup", "resolve_entity", "entity_history",
    "entity_events", "get_host_network", "result_fetch", "result_query",
})


# Sentinel: a handler has fully processed the tool call (messages,
# logging, state updates done inside) and the dispatcher should skip
# the shared post-tool block and continue to the next tool call.
_HANDLER_SKIP = object()


# ── Generic invoke helper ───────────────────────────────────────────

async def _invoke_generic_tool(
    fn_name: str, fn_args: dict, *, state, agent_type: str,
) -> dict:
    """Invoke a tool via the registry, clear blocked-tool state, bump metric."""
    from api.tool_registry import invoke_tool
    from api.metrics import AGENT_TOOL_CALLS
    state.last_blocked_tool = None   # successful tool call clears blocked state
    result = await asyncio.get_event_loop().run_in_executor(
        None, lambda n=fn_name, a=fn_args: invoke_tool(n, a),
    )
    try:
        AGENT_TOOL_CALLS.labels(agent_type=agent_type, tool=fn_name).inc()
    except Exception:
        pass
    return result


# ── Lifecycle sub-handlers ──────────────────────────────────────────

async def _handle_plan_action(
    tc, fn_args: dict, *,
    state, session_id: str, task: str, manager, owner_user: str,
) -> dict:
    """Broadcast plan to GUI, suspend until user approves/rejects."""
    # v2.31.10 blackout gate
    try:
        from api.db.agent_blackouts import check_active_blackout
        active_bo = check_active_blackout(tool_name="")
    except Exception:
        active_bo = None
    if active_bo:
        state.plan_action_called = True  # prevent re-trigger loop
        result = {
            "status":   "blocked",
            "approved": False,
            "message":  (f"Blocked by active blackout: "
                         f"{active_bo.get('label','')} — "
                         f"{active_bo.get('reason','')}"),
            "data":     {"approved": False, "blackout": active_bo},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await manager.send_line(
            "step",
            f"[blackout] Plan blocked — {active_bo.get('label','')}",
            status="warning", session_id=session_id,
        )
        return result

    from api.lock import plan_lock
    from api.agents.tool_metadata import enrich_plan_steps
    from api.confirmation import wait_for_confirmation
    from api.memory.feedback import record_feedback_signal as _rfs

    state.plan_action_called = True
    # Try to acquire the global destructive lock
    lock_ok = await plan_lock.acquire(session_id, owner_user)
    if not lock_ok:
        lock_info = plan_lock.get_info()
        await manager.send_line(
            "step",
            f"[lock] Destructive lock held by {lock_info['owner_user']} — plan blocked",
            status="ok", session_id=session_id,
        )
        return {
            "status": "locked",
            "approved": False,
            "message": (f"System locked by {lock_info['owner_user']} "
                        f"(session {lock_info['session_id'][:8]}). "
                        "Wait for their plan to complete."),
            "data": {"approved": False},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # Intercept: broadcast plan to GUI, suspend until approved/rejected
    plan = {
        "summary":    fn_args.get("summary", ""),
        "steps":      fn_args.get("steps") or [],
        "risk_level": fn_args.get("risk_level", "medium"),
        "reversible": fn_args.get("reversible", True),
    }

    # v2.31.14 — reject empty plans before showing modal
    _plan_summary = (plan["summary"] or "").strip()
    _plan_steps   = [s for s in plan["steps"] if s]
    if not _plan_summary or not _plan_steps:
        await plan_lock.release(session_id)
        state.plan_action_called = False
        state.negative_signals += 1
        await manager.send_line(
            "step",
            "[plan] Rejected — empty summary or steps; asking model to retry",
            status="warning", session_id=session_id,
        )
        return {
            "status":   "error",
            "approved": False,
            "message": (
                "plan_action() rejected: "
                f"{'empty summary' if not _plan_summary else 'empty steps list'}. "
                "Required: summary (non-empty prose describing the overall change) "
                "AND steps (list of 2-6 concrete actions, each a short sentence). "
                "Retry with BOTH fields populated. Example:\n"
                "plan_action(\n"
                "  summary=\"Prune unused Docker images on all Swarm nodes\",\n"
                "  steps=[\"Get docker system df before state on each host\",\n"
                "         \"Run docker image prune -a -f on each host\",\n"
                "         \"Get docker system df after state on each host\",\n"
                "         \"Report reclaimed bytes per host\"],\n"
                "  risk_level=\"medium\",\n"
                "  reversible=False,\n"
                ")"
            ),
            "data": {"approved": False, "reason": "empty_plan"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # v2.33.6 — enrich each step with blast-radius metadata
    enriched_steps, plan_radius = enrich_plan_steps(plan["steps"])

    # Refuse any plan with more than one fleet-radius step
    _n_fleet = sum(1 for s in enriched_steps if s.get("radius") == "fleet")
    if _n_fleet > 1:
        await plan_lock.release(session_id)
        state.plan_action_called = False
        state.negative_signals += 1
        await manager.send_line(
            "step",
            "[plan] Rejected — multiple fleet-radius steps; asking model to split",
            status="warning", session_id=session_id,
        )
        return {
            "status":   "error",
            "approved": False,
            "message": (
                "plan_action() rejected: plan has multiple fleet-radius steps. "
                "Split into separate tasks."
            ),
            "data": {"approved": False, "reason": "multiple_fleet_radius"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    plan["steps"] = enriched_steps
    plan["plan_radius"] = plan_radius
    await manager.broadcast({
        "type":       "plan_pending",
        "plan":       plan,
        "session_id": session_id,
        "timestamp":  datetime.now(timezone.utc).isoformat(),
    })
    await manager.send_line(
        "step", f"[plan] Waiting for user approval: {plan['summary']}",
        status="ok", session_id=session_id,
    )
    approved = await wait_for_confirmation(session_id)
    if approved:
        state.positive_signals += 1
        asyncio.create_task(_rfs(task, "plan_approved", plan["summary"][:120]))
        result = {
            "status":   "ok",
            "approved": True,
            "message":  "User confirmed. Proceed with plan.",
            "data":     {"approved": True},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await manager.send_line(
            "step", "[plan] Approved — executing plan.",
            status="ok", session_id=session_id,
        )
    else:
        state.negative_signals += 1
        asyncio.create_task(_rfs(task, "plan_cancelled", plan["summary"][:120]))
        result = {
            "status":   "ok",
            "approved": False,
            "message":  "User cancelled. Do not proceed.",
            "data":     {"approved": False},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await manager.send_line(
            "step", "[plan] Cancelled by user — stopping.",
            status="ok", session_id=session_id,
        )
    await plan_lock.release(session_id)
    return result


async def _handle_clarifying_question(
    tc, fn_args: dict, *,
    state, session_id: str, task: str, manager,
) -> dict:
    """Broadcast clarification prompt to GUI and suspend until answered."""
    from api.clarification import wait_for_clarification
    from api.memory.feedback import record_feedback_signal as _rfs

    question = fn_args.get("question", "")
    options  = fn_args.get("options") or []
    state.negative_signals += 1   # task was ambiguous — mild negative signal
    asyncio.create_task(_rfs(task, "clarification_needed", question[:120]))
    await manager.broadcast({
        "type":      "clarification_needed",
        "question":  question,
        "options":   options,
        "session_id": session_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    await manager.send_line(
        "step", f"[clarification] Waiting for user: {question}",
        status="ok", session_id=session_id,
    )
    answer = await wait_for_clarification(session_id)
    _is_cancel = answer.lower() in (
        "cancel", "timeout — proceed with best guess", "",
    )
    _directive = (
        "" if _is_cancel
        else " Your NEXT tool call MUST be plan_action(). Do NOT call audit_log."
    )
    return {
        "status":  "ok",
        "answer":  answer,
        "message": f"User answered: {answer}.{_directive}",
        "data":    {"question": question, "answer": answer},
        "next_required_tool": None if _is_cancel else "plan_action",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def _handle_propose_subtask(
    tc, fn_args: dict, *,
    state, session_id: str, operation_id: str, task: str,
    agent_type: str, messages: list, step: int,
    manager, owner_user: str,
) -> None:
    """In-band sub-agent spawn or legacy proposal-card fallback.

    Does its own messages.append + log_tool_call + state updates. The
    caller treats this as _HANDLER_SKIP — shared post-tool processing
    is not run for propose_subtask.
    """
    import api.logger as logger_mod
    from api.metrics import AGENT_TOOL_CALLS
    from api.routers.agent import (
        _lm_model,
        _spawn_and_wait_subagent,
        _SUBAGENT_MIN_PARENT_RESERVE,
        _tool_budget_for,
    )
    from api.agents.propose_dedup import (
        handle_propose_subtask as _handle_pst,
        mark_spawned as _mark_spawned,
        mark_rejected as _mark_rejected,
    )

    # Parse arguments — preserve the original re-parse from tc.function.arguments.
    try:
        _pst_args = json.loads(tc.function.arguments or "{}")
    except Exception:
        _pst_args = {}

    _pst_task         = (_pst_args.get("task") or "")[:500]
    _pst_exec_steps   = _pst_args.get("executable_steps", []) or []
    _pst_manual_steps = _pst_args.get("manual_steps", []) or []

    # v2.34.16 — dedup identical proposals within this run
    _dedup = _handle_pst(_pst_args, state.propose_state, step_index=step)
    _pst_dedup_key = _dedup.get("key")
    if _dedup.get("status") == "duplicate_proposal":
        messages.append({
            "role":    "system",
            "content": _dedup.get("harness_message", ""),
        })
        _dup_result = {
            "status":    "duplicate_proposal",
            "key":       _pst_dedup_key,
            "prior":     _dedup.get("prior") or {},
            "message": (
                "Duplicate propose_subtask rejected by harness. "
                "See the harness note above and pick a different "
                "next step."
            ),
        }
        messages.append({
            "role": "assistant", "content": None, "tool_calls": [tc],
        })
        messages.append({
            "role":         "tool",
            "tool_call_id": tc.id,
            "content":      json.dumps(_dup_result),
        })
        await logger_mod.log_tool_call(
            operation_id=operation_id, tool_name="propose_subtask",
            params=_pst_args, result=_dup_result, model_used=_lm_model(),
            duration_ms=0, status="ok",
        )
        state.tools_used_names.append("propose_subtask")
        try:
            AGENT_TOOL_CALLS.labels(
                agent_type=agent_type, tool="propose_subtask",
            ).inc()
        except Exception:
            pass
        await manager.send_line(
            "step",
            f"[subtask] duplicate proposal rejected (key={_pst_dedup_key})",
            status="warning", session_id=session_id,
        )
        return

    # v2.34.0 in-band spawn fields
    _pst_objective  = (_pst_args.get("objective") or "").strip()
    _pst_sub_type   = (_pst_args.get("agent_type") or "").strip().lower()
    _pst_scope      = (_pst_args.get("scope_entity") or "").strip() or None
    _pst_sub_budget = int(_pst_args.get("budget_tools") or 0)
    _pst_allow_dest = bool(_pst_args.get("allow_destructive", False))

    # v2.34.4: Auto-promote legacy `task=` calls to in-band spawn
    if not _pst_objective and _pst_task:
        _pst_objective = _pst_task
    if not _pst_sub_type:
        _inherit = {
            "investigate": "investigate",
            "research":    "investigate",
            "observe":     "observe",
            "status":      "observe",
            "execute":     "execute",
            "action":      "execute",
            "build":       "investigate",
        }
        _pst_sub_type = _inherit.get(agent_type, "investigate")

    _inband_ok = bool(_pst_objective) and _pst_sub_type in (
        "observe", "investigate", "execute",
    )
    _pst_result = None

    if _inband_ok:
        _parent_budget = _tool_budget_for(agent_type)
        _parent_remaining = max(
            0, _parent_budget - len(state.tools_used_names),
        )
        _parent_diag = ""
        for _m in reversed(messages[-6:]):
            _c = _m.get("content") or ""
            if isinstance(_c, str) and "DIAGNOSIS:" in _c:
                _parent_diag = _c.split("DIAGNOSIS:", 1)[1][:500]
                break

        if _pst_sub_budget <= 0:
            _pst_sub_budget = min(
                8,
                max(0, _parent_remaining - _SUBAGENT_MIN_PARENT_RESERVE),
            )

        try:
            _spawn = await _spawn_and_wait_subagent(
                parent_session_id=session_id,
                parent_operation_id=operation_id,
                owner_user=owner_user,
                objective=_pst_objective,
                agent_type=_pst_sub_type,
                scope_entity=_pst_scope,
                budget_tools=_pst_sub_budget,
                allow_destructive=_pst_allow_dest,
                parent_remaining_budget=_parent_remaining,
                parent_agent_type=agent_type,
                parent_diagnosis=_parent_diag,
                parent_budget_tools=_parent_budget,
                parent_tools_used=len(state.tools_used_names),
            )
        except Exception as _se:
            log.warning("sub-agent spawn crashed: %s", _se)
            _spawn = {"ok": False, "error": f"spawn crashed: {_se}"}

        if _spawn.get("ok"):
            _sub_guard = _spawn.get("harness_guard") or {}
            _pst_result = {
                "status":          "sub_agent_done",
                "sub_task_id":     _spawn.get("sub_task_id"),
                "terminal_status": _spawn.get("terminal_status"),
                "final_answer":    _spawn.get("final_answer", ""),
                "diagnosis":       _spawn.get("diagnosis", ""),
                "tools_used":      _spawn.get("tools_used", 0),
                "harness_guard":   _sub_guard,
                "message": (
                    "Sub-agent completed. Synthesize using its "
                    "final_answer above — do NOT re-verify its "
                    "findings. Write your final summary now."
                ),
            }
            # v2.34.16 — dedup map: spawned → terminal
            try:
                _mark_spawned(
                    state.propose_state, _pst_dedup_key,
                    _spawn.get("sub_task_id") or "",
                )
                from api.agents.propose_dedup import (
                    on_subagent_terminal as _on_sub_term,
                )
                _fab_detail = _sub_guard.get("fabrication_detail")
                _guard_detail = {
                    "fired":    bool(_sub_guard.get("halluc_guard_fired")),
                    "attempts": _sub_guard.get("halluc_guard_attempts") or 1,
                } if _sub_guard.get("halluc_guard_fired") else None
                _on_sub_term(
                    sub_op_id=_spawn.get("sub_task_id") or "",
                    terminal_status=(_spawn.get("terminal_status") or ""),
                    final_answer=_spawn.get("final_answer", ""),
                    fabrication_detail=(
                        _fab_detail if isinstance(_fab_detail, dict) else None
                    ),
                    halluc_guard_detail=_guard_detail,
                    state=state.propose_state,
                    dedup_key=_pst_dedup_key,
                )
            except Exception as _dse:
                log.debug("propose_dedup terminal hook failed: %s", _dse)
            await manager.send_line(
                "step",
                f"[subagent] done — {_spawn.get('terminal_status')} "
                f"(tools={_spawn.get('tools_used', 0)})",
                status="ok", session_id=session_id,
            )
            # v2.34.14: parent-side distrust signal
            _sub_halluc_fired = bool(_sub_guard.get("halluc_guard_fired"))
            _sub_fab_detected = bool(_sub_guard.get("fabrication_detected"))
            if _sub_halluc_fired or _sub_fab_detected:
                _reason = (
                    "fabrication_detected" if _sub_fab_detected
                    else "halluc_guard_fired"
                )
                try:
                    from api.metrics import SUBAGENT_DISTRUST_INJECTED_COUNTER
                    SUBAGENT_DISTRUST_INJECTED_COUNTER.labels(
                        reason=_reason,
                    ).inc()
                except Exception:
                    pass
                _distrust_msg = (
                    f"[harness] Sub-agent output was flagged "
                    f"(halluc_guard_fired={_sub_halluc_fired}, "
                    f"fabrication_detected={_sub_fab_detected}, "
                    f"state.substantive_tool_calls="
                    f"{_sub_guard.get('state.substantive_tool_calls', 0)}). "
                    "Do NOT synthesise a conclusion from this sub-agent "
                    "output. Your options: (a) continue the investigation "
                    "yourself with your remaining tool budget, (b) call "
                    "escalate() with reason='subagent_unreliable'. Do not "
                    "reverse your own prior evidence based on this "
                    "sub-agent's unverified claims."
                )
                messages.append({
                    "role": "system",
                    "content": _distrust_msg,
                })
                await manager.send_line(
                    "step",
                    f"[subagent] distrust signal injected — {_reason}",
                    status="warning", session_id=session_id,
                )
            try:
                from api.metrics import (
                    SUBAGENT_SPAWN_COUNTER, BUDGET_NUDGE_COUNTER,
                )
                SUBAGENT_SPAWN_COUNTER.labels(outcome="spawned").inc()
                if state.budget_nudge_fired:
                    BUDGET_NUDGE_COUNTER.labels(
                        outcome="proposed_and_spawned").inc()
            except Exception:
                pass
        else:
            # Spawn refused by guardrails — surface to the model
            _pst_result = {
                "status": "error",
                "message": _spawn.get(
                    "error", "sub-agent spawn refused"),
            }
            await manager.send_line(
                "step",
                f"[subagent] refused — {_pst_result['message']}",
                status="error", session_id=session_id,
            )
            try:
                from api.metrics import (
                    SUBAGENT_SPAWN_COUNTER, BUDGET_NUDGE_COUNTER,
                )
                _err = (_pst_result.get("message") or "").lower()
                if "depth" in _err:
                    _outcome = "rejected_depth"
                elif "budget" in _err or "insufficient" in _err:
                    _outcome = "rejected_budget"
                elif "destructive" in _err:
                    _outcome = "rejected_destructive"
                else:
                    _outcome = "rejected_budget"
                SUBAGENT_SPAWN_COUNTER.labels(outcome=_outcome).inc()
                if state.budget_nudge_fired:
                    BUDGET_NUDGE_COUNTER.labels(
                        outcome="proposed_and_refused").inc()
            except Exception:
                pass
            # v2.34.16 — dedup map: rejected
            try:
                _mark_rejected(
                    state.propose_state, _pst_dedup_key, _outcome,
                )
            except Exception:
                pass

    else:
        # ── Legacy proposal-card path ────────────────────
        _proposal_id = str(uuid.uuid4())
        _card_task = _pst_task or _pst_objective or task[:500]

        _confidence = "medium"
        try:
            from api.connections import list_connections
            if list_connections("vm_host"):
                _confidence = "high"
        except Exception:
            pass

        try:
            from api.db.subtask_proposals import save_proposal
            save_proposal(
                proposal_id=_proposal_id,
                parent_session_id=session_id,
                parent_op_id=operation_id,
                task=_card_task,
                executable_steps=_pst_exec_steps,
                manual_steps=_pst_manual_steps,
                confidence=_confidence,
            )
        except Exception as _spe:
            log.debug("save_proposal failed: %s", _spe)

        await manager.broadcast({
            "type": "subtask_proposed",
            "session_id": session_id,
            "proposal_id": _proposal_id,
            "task": _card_task,
            "executable_steps": _pst_exec_steps,
            "manual_steps": _pst_manual_steps,
            "confidence": _confidence,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        await manager.send_line(
            "step",
            f"[subtask] Proposal recorded — '{_card_task[:70]}' "
            f"({_confidence} confidence). User notified.",
            status="ok", session_id=session_id,
        )
        try:
            from api.metrics import SUBAGENT_SPAWN_COUNTER
            # v2.34.4 canary: fires when harness falls through to v2.24.0
            # proposal-only behaviour. Should be 0 in steady state —
            # auto-promotion above means only truly empty propose_subtask
            # calls land here.
            SUBAGENT_SPAWN_COUNTER.labels(outcome="proposal_only").inc()
        except Exception:
            pass
        _pst_result = {
            "status": "proposed",
            "proposal_id": _proposal_id,
            "confidence": _confidence,
            "message": (
                "Proposal recorded. User will see an offer to run "
                "this as an automated sub-agent or as a manual "
                "runbook checklist. Please provide your final "
                "investigation summary now."
            ),
        }

    messages.append({"role": "assistant", "content": None, "tool_calls": [tc]})
    messages.append({
        "role": "tool",
        "tool_call_id": tc.id,
        "content": json.dumps(_pst_result),
    })
    await logger_mod.log_tool_call(
        operation_id=operation_id, tool_name="propose_subtask",
        params=_pst_args, result=_pst_result, model_used=_lm_model(),
        duration_ms=0, status="ok",
    )
    state.tools_used_names.append("propose_subtask")
    try:
        AGENT_TOOL_CALLS.labels(
            agent_type=agent_type, tool="propose_subtask",
        ).inc()
    except Exception:
        pass


# ── Category routers ────────────────────────────────────────────────

async def _handle_lifecycle_tools(
    *, tc, fn_name: str, fn_args: dict, state, session_id: str,
    operation_id: str, task: str, agent_type: str, messages: list,
    step: int, manager, owner_user: str, client,
):
    """Flow-control / lifecycle tools.

    Returns a result dict, or _HANDLER_SKIP (propose_subtask handles
    its own messages + logging). Raises NotImplementedError for any
    tool not in this category so the dispatcher can try the next
    handler.
    """
    if fn_name == "plan_action":
        return await _handle_plan_action(
            tc, fn_args,
            state=state, session_id=session_id, task=task,
            manager=manager, owner_user=owner_user,
        )
    if fn_name == "clarifying_question":
        return await _handle_clarifying_question(
            tc, fn_args,
            state=state, session_id=session_id, task=task, manager=manager,
        )
    if fn_name == "propose_subtask":
        await _handle_propose_subtask(
            tc, fn_args,
            state=state, session_id=session_id,
            operation_id=operation_id, task=task, agent_type=agent_type,
            messages=messages, step=step,
            manager=manager, owner_user=owner_user,
        )
        return _HANDLER_SKIP
    if (fn_name == "escalate"
            and agent_type in ("action", "execute")
            and not state.plan_action_called):
        # Fix 2: Block premature escalation — agent must plan first
        state.last_blocked_tool = "escalate"
        await manager.send_line(
            "step",
            "[safety] escalate() blocked — plan_action() must be called next",
            status="ok", session_id=session_id,
        )
        return {
            "status": "blocked",
            "message": (
                "escalate() blocked. You MUST call plan_action() next. "
                "Do not call audit_log. Do not stop. "
                "Call plan_action() with your proposed upgrade steps NOW. "
                "plan_action() is the required next step."
            ),
            "data": None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    raise NotImplementedError


async def _handle_kafka_tools(
    *, tc, fn_name: str, fn_args: dict, state, session_id: str,
    operation_id: str, task: str, agent_type: str, messages: list,
    step: int, manager, owner_user: str, client,
) -> dict:
    if fn_name not in _KAFKA_TOOLS:
        raise NotImplementedError
    return await _invoke_generic_tool(
        fn_name, fn_args, state=state, agent_type=agent_type,
    )


async def _handle_swarm_tools(
    *, tc, fn_name: str, fn_args: dict, state, session_id: str,
    operation_id: str, task: str, agent_type: str, messages: list,
    step: int, manager, owner_user: str, client,
) -> dict:
    if fn_name not in _SWARM_TOOLS:
        raise NotImplementedError
    return await _invoke_generic_tool(
        fn_name, fn_args, state=state, agent_type=agent_type,
    )


async def _handle_elastic_tools(
    *, tc, fn_name: str, fn_args: dict, state, session_id: str,
    operation_id: str, task: str, agent_type: str, messages: list,
    step: int, manager, owner_user: str, client,
) -> dict:
    if fn_name not in _ELASTIC_TOOLS:
        raise NotImplementedError
    return await _invoke_generic_tool(
        fn_name, fn_args, state=state, agent_type=agent_type,
    )


async def _handle_memory_tools(
    *, tc, fn_name: str, fn_args: dict, state, session_id: str,
    operation_id: str, task: str, agent_type: str, messages: list,
    step: int, manager, owner_user: str, client,
) -> dict:
    if fn_name not in _MEMORY_TOOLS:
        raise NotImplementedError
    return await _invoke_generic_tool(
        fn_name, fn_args, state=state, agent_type=agent_type,
    )


async def _handle_infra_tools(
    *, tc, fn_name: str, fn_args: dict, state, session_id: str,
    operation_id: str, task: str, agent_type: str, messages: list,
    step: int, manager, owner_user: str, client,
) -> dict:
    if fn_name not in _INFRA_TOOLS:
        raise NotImplementedError
    return await _invoke_generic_tool(
        fn_name, fn_args, state=state, agent_type=agent_type,
    )


async def _handle_misc_tools(
    *, tc, fn_name: str, fn_args: dict, state, session_id: str,
    operation_id: str, task: str, agent_type: str, messages: list,
    step: int, manager, owner_user: str, client,
) -> dict:
    """Fallback: any tool not claimed by a specific category handler."""
    return await _invoke_generic_tool(
        fn_name, fn_args, state=state, agent_type=agent_type,
    )


_HANDLERS = (
    _handle_lifecycle_tools,
    _handle_kafka_tools,
    _handle_swarm_tools,
    _handle_elastic_tools,
    _handle_memory_tools,
    _handle_infra_tools,
    _handle_misc_tools,
)


# ── Main dispatcher ─────────────────────────────────────────────────

async def dispatch_tool_calls(
    state,              # StepState
    msg,                # LLM message with .tool_calls
    messages: list,
    tools_spec: list,
    *,
    manager,
    session_id: str,
    operation_id: str,
    agent_type: str,
    task: str,
    step: int,
    client,
    owner_user: str,
    parent_session_id: str = "",
    is_final_step: bool = True,
    allowed_tools: frozenset,
    destructive_tools: frozenset,
    tool_budget: int,
) -> ToolsDispatchResult:
    """Dispatch all tool_calls from one LLM step.

    Covers: destructive pre-flight, global lock check, batch-budget
    trim, per-tc dispatch (via category handlers defined above),
    auto-verify, audit writes, fact-age rejection, GUI stream, and
    tool-result append. The per-tool elif chain is replaced by
    _HANDLERS — each is tried in order until one returns a result or
    _HANDLER_SKIP (misc is the catch-all fallback).
    """
    # Lazy imports to avoid circular dependency with api.routers.agent
    import api.logger as logger_mod
    from api.agents import META_TOOLS
    from api.agents.step_facts import process_tool_result
    from api.lock import plan_lock
    from api.metrics import AGENT_TOOL_CALLS
    from api.routers.agent import (
        _auto_verify,
        _lm_model,
        _summarize_tool_result,
        _tool_budget_for,
    )

    _destructive_calls_delta = 0
    _tool_failures_delta = 0

    # Pre-flight safety check: if any destructive tool is requested in this
    # batch without plan_action already called, block it and inject a reminder.
    _req_tools = {tc.function.name for tc in msg.tool_calls}
    _destructive_req = _req_tools & destructive_tools
    # Check vm_exec write commands (prune, autoremove, vacuum, etc.)
    _VM_WRITE_PATTERNS = ['prune', 'autoremove', 'vacuum', 'clean', 'purge', 'remove']
    for _btc in msg.tool_calls:
        if _btc.function.name == 'vm_exec':
            try:
                _vargs = json.loads(_btc.function.arguments)
                _vcmd = _vargs.get('command', '').lower()
                if any(p in _vcmd for p in _VM_WRITE_PATTERNS):
                    if 'plan_action' not in state.tools_used_names:
                        _destructive_req = _destructive_req | {'vm_exec(write)'}
            except Exception:
                pass
    if _destructive_req and "plan_action" not in state.tools_used_names:
        block_msg = (
            "STOP. You requested destructive tool(s) "
            f"{sorted(_destructive_req)} without calling plan_action() first. "
            "You MUST call plan_action() before any destructive action. "
            "Call plan_action() now."
        )
        await manager.send_line(
            "step", f"[safety] Blocked {_destructive_req} — plan_action required first",
            status="ok", session_id=session_id,
        )
        # Return a synthetic tool result for each blocked tool, then re-prompt
        for _btc in msg.tool_calls:
            if _btc.function.name in _destructive_req:
                messages.append({
                    "role": "tool",
                    "tool_call_id": _btc.id,
                    "content": json.dumps({
                        "status": "blocked",
                        "message": "plan_action() must be called before this tool.",
                    }),
                })
        # Also append tool results for any non-destructive tools in same batch
        for _btc in msg.tool_calls:
            if _btc.function.name not in _destructive_req:
                messages.append({
                    "role": "tool",
                    "tool_call_id": _btc.id,
                    "content": json.dumps({"status": "blocked", "message": "Batch blocked"}),
                })
        messages.append({"role": "user", "content": block_msg})
        return ToolsDispatchResult(
            action=ToolLoopAction.CONTINUE,
            destructive_calls_delta=_destructive_calls_delta,
            tool_failures_delta=_tool_failures_delta,
        )

    # Also block if global lock is held by a different session
    if _destructive_req and plan_lock.is_locked_by_other(session_id):
        lock_info = plan_lock.get_info()
        block_msg = (
            f"STOP. Destructive tool(s) {sorted(_destructive_req)} blocked — "
            f"global plan lock held by {lock_info['owner_user']}. "
            "Wait for the other operation to complete."
        )
        await manager.send_line("step", f"[lock] Blocked by global lock (owner: {lock_info['owner_user']})", status="ok", session_id=session_id)
        for _btc in msg.tool_calls:
            messages.append({
                "role": "tool",
                "tool_call_id": _btc.id,
                "content": json.dumps({"status": "locked", "message": block_msg}),
            })
        messages.append({"role": "user", "content": block_msg})
        return ToolsDispatchResult(
            action=ToolLoopAction.CONTINUE,
            destructive_calls_delta=_destructive_calls_delta,
            tool_failures_delta=_tool_failures_delta,
        )

    # v2.34.15: budget truncation — the step-level budget check above
    # stops us entering a fresh step at cap, but it did not stop us
    # executing a *batch* that overflows cap. If the model proposes
    # N tool calls and only K fit within the remaining budget, execute
    # the first K, drop the rest with a harness nudge, and synthesise
    # tool_result placeholders for the dropped ones so the OpenAI
    # tool_call_id contract is preserved on the next turn.
    _proposed_tcs = list(msg.tool_calls or [])
    _tool_budget = _tool_budget_for(agent_type)
    _remaining = _tool_budget - len(state.tools_used_names)
    _dropped_tcs: list = []
    if _remaining <= 0:
        _dropped_tcs = _proposed_tcs
        _proposed_tcs = []
    elif len(_proposed_tcs) > _remaining:
        _dropped_tcs = _proposed_tcs[_remaining:]
        _proposed_tcs = _proposed_tcs[:_remaining]

    if _dropped_tcs:
        _dropped_names = [t.function.name for t in _dropped_tcs]
        _kept_names = [t.function.name for t in _proposed_tcs]
        log.warning(
            "budget truncate operation=%s proposed=%d remaining=%d "
            "kept=%s dropped=%s",
            operation_id, len(msg.tool_calls or []), _remaining,
            _kept_names, _dropped_names,
        )
        try:
            from api.metrics import BUDGET_TRUNCATE_COUNTER
            BUDGET_TRUNCATE_COUNTER.labels(agent_type=agent_type).inc()
        except Exception:
            pass
        await manager.send_line(
            "step",
            f"[budget] Truncated batch: kept {len(_kept_names)}/"
            f"{len(_dropped_tcs) + len(_kept_names)} tools — "
            f"dropped {_dropped_names}",
            status="ok", session_id=session_id,
        )
        # Emit synthetic tool_result for every dropped call
        for _dtc in _dropped_tcs:
            messages.append({
                "role": "tool",
                "tool_call_id": _dtc.id,
                "content": json.dumps({
                    "status": "skipped",
                    "message": (
                        f"Tool '{_dtc.function.name}' dropped — "
                        f"batch exceeded remaining tool budget "
                        f"({_remaining}). Continue with the evidence "
                        f"already gathered; do not retry."
                    ),
                }),
            })
        # Harness nudge so the model understands what happened.
        if _proposed_tcs:
            _nudge = (
                f"[harness] You proposed {len(msg.tool_calls)} tool "
                f"calls but only {_remaining} fit within your "
                f"remaining budget. Executed: {_kept_names}. "
                f"Skipped: {_dropped_names}. Continue with what you "
                f"have — do not re-propose the skipped tools."
            )
        else:
            _nudge = (
                f"[harness] Tool budget exhausted "
                f"({len(state.tools_used_names)}/{_tool_budget}). Produce "
                f"your final_answer now based on evidence gathered, "
                f"or call escalate() if you cannot."
            )
        messages.append({"role": "user", "content": _nudge})

    halt = False
    for tc in _proposed_tcs:
        fn_name = tc.function.name
        state.tools_used_names.append(fn_name)
        if fn_name not in META_TOOLS:
            state.substantive_tool_calls += 1  # v2.34.8: hallucination guard counter
        tool_content_suffix = ""  # v2.32.2: populated by auto-verify after destructive tools
        try:
            fn_args = json.loads(tc.function.arguments)
        except json.JSONDecodeError:
            fn_args = {}

        # Retrieve memory context before executing
        from api.memory.hooks import before_tool_call, after_tool_call as _mem_after
        mem_context = await before_tool_call(fn_name, fn_args)
        if mem_context:
            await manager.send_line(
                "memory",
                f"[memory] {len(mem_context)} relevant engram(s) activated",
                tool=fn_name, status="ok", session_id=session_id,
            )

        t0 = time.monotonic()
        # Block duplicate audit_log calls — the model tends to loop on it.
        # One audit_log per session is sufficient.
        if fn_name == "audit_log" and state.audit_logged:
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps({
                    "status": "ok",
                    "message": "Audit already recorded for this session.",
                }),
            })
            await manager.send_line(
                "step", "[audit_log] skipped — already logged once this run",
                status="ok", session_id=session_id,
            )
            continue
        if fn_name == "audit_log":
            state.audit_logged = True

        # ── Category-handler dispatch ───────────────────────────────
        result = None
        try:
            for _handler in _HANDLERS:
                try:
                    result = await _handler(
                        tc=tc, fn_name=fn_name, fn_args=fn_args,
                        state=state, session_id=session_id,
                        operation_id=operation_id, task=task,
                        agent_type=agent_type, messages=messages,
                        step=step, manager=manager,
                        owner_user=owner_user, client=client,
                    )
                    break
                except NotImplementedError:
                    continue
        except Exception as e:
            err_str = str(e)
            result = {"status": "error", "message": err_str, "data": None,
                      "timestamp": datetime.now(timezone.utc).isoformat()}
            # v2.34.9: track kwarg hallucination via TypeError fingerprints
            if isinstance(e, TypeError) or (
                "unexpected keyword argument" in err_str
                or "missing 1 required positional argument" in err_str
                or "missing" in err_str and "required positional" in err_str
            ):
                try:
                    from api.metrics import TOOL_SIGNATURE_ERROR_COUNTER
                    TOOL_SIGNATURE_ERROR_COUNTER.labels(tool_name=fn_name).inc()
                except Exception:
                    pass
            if "401" in err_str or "403" in err_str or "Unauthorized" in err_str:
                await manager.send_line(
                    "step",
                    f"[auth] Token may have expired — tool {fn_name!r} got auth error. "
                    "Try stopping and re-running the task.",
                    status="error", session_id=session_id,
                )
            log.debug("Tool %r raised exception:", fn_name, exc_info=True)
            state.negative_signals += 1
            from api.memory.feedback import record_feedback_signal as _rfs
            asyncio.create_task(_rfs(task, "tool_error", f"{fn_name}: {str(e)[:80]}"))

        # Defensive: misc is the catch-all, so this should never fire. If it
        # does, something is wrong with the handler chain.
        if result is None:
            result = {
                "status":    "error",
                "message":   f"Unknown tool: {fn_name}",
                "data":      None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        # Handler signalled "I already did all the processing" (propose_subtask).
        if result is _HANDLER_SKIP:
            continue

        duration_ms = int((time.monotonic() - t0) * 1000)
        result_status = result.get("status", "error") if isinstance(result, dict) else "error"
        result_msg = result.get("message", "") if isinstance(result, dict) else str(result)

        if fn_name in destructive_tools:
            _destructive_calls_delta += 1
            # v2.32.2: Auto-verify after successful destructive action
            if result_status == "ok" or (isinstance(result, dict) and result.get("data", {}).get("approved")):
                _vr = await _auto_verify(fn_name, fn_args, session_id, operation_id)
                if _vr and not _vr["passed"]:
                    # Verification failed — inject warning into model context
                    _verify_warning = (
                        f"[HARNESS VERIFY WARNING] After {fn_name} returned ok, "
                        f"auto-verification via {_vr['verify_tool']} returned "
                        f"{_vr['verify_status']}: {_vr['verify_message']}. "
                        f"The action may not have taken effect yet."
                    )
                    tool_content_suffix = f"\n\n{_verify_warning}"
                elif _vr and _vr["passed"]:
                    tool_content_suffix = (
                        f"\n\n[HARNESS VERIFY OK] {_vr['verify_tool']} confirmed: "
                        f"{_vr['verify_status']}"
                    )
                else:
                    tool_content_suffix = ""

        # Store tool execution in memory (non-blocking)
        _mem_after(fn_name, fn_args, result, result_status, duration_ms)

        # Log to SQLite
        await logger_mod.log_tool_call(
            operation_id, fn_name, fn_args, result,
            _lm_model(), duration_ms
        )

        # v2.36.8-dispatch (tightened v2.36.9) — render tool: append
        # rendered markdown to operations.final_answer so the operator
        # sees the table in the Operations view. LLM context stays
        # small (only the short ack message), the operator-facing
        # field gets the full rendered output. Counter is read at
        # cleanup time to decide caption-prepend vs wholesale-overwrite.
        if fn_name == "result_render_table" and isinstance(result, dict):
            _data = result.get("data") or {}
            _md = _data.get("render_markdown") if isinstance(_data, dict) else None
            if isinstance(_md, str) and _md.strip():
                try:
                    await logger_mod.set_operation_final_answer_append(
                        session_id, _md,
                    )
                    state.render_tool_calls += 1   # v2.36.9 — seen by cleanup
                    try:
                        from api.metrics import RENDER_TOOL_CALLS
                        _outcome = "truncated" if _data.get("truncated") else "ok"
                        if _data.get("row_count", 0) == 0:
                            _outcome = "no_rows"
                        RENDER_TOOL_CALLS.labels(outcome=_outcome).inc()
                    except Exception:
                        pass
                except Exception as _re_e:
                    log.debug(
                        "render tool append failed (session=%s): %s",
                        session_id, _re_e,
                    )

        # Immutable audit row for destructive / remote-exec tools (v2.31.2)
        try:
            from api.db.agent_actions import write_action, is_audited
            if is_audited(fn_name):
                write_action(
                    session_id=session_id,
                    operation_id=operation_id,
                    task_id=session_id,           # no separate task_id today
                    tool_name=fn_name,
                    args=fn_args,
                    result_status=result_status,
                    result_summary=result_msg,
                    duration_ms=duration_ms,
                    owner_user=owner_user,
                    was_planned=state.plan_action_called,
                )
        except Exception as _ae:
            log.debug("agent_actions write failed: %s", _ae)

        # ── v2.35.3: fact-age rejection ──────────────────────────────
        # If the tool reports a value that contradicts a high-confidence
        # recently-verified known_fact, filter the tool result per the
        # configured aggression mode. Real tool result is preserved in
        # the audit trail above; only the LLM-visible copy is modified.
        try:
            from api.agents.fact_age_rejection import check_and_apply_rejection
            from api.db.known_facts import _get_facts_settings as _gfs_far
            _far_settings = _gfs_far()
            # Pull explicit fact-age settings (floats may not have dot in value)
            try:
                from mcp_server.tools.skills.storage import get_backend as _gb_far
                _be_far = _gb_far()
                for _k, _default, _cast in (
                    ("factAgeRejectionMode",         "medium", str),
                    ("factAgeRejectionMaxAgeMin",    5,        int),
                    ("factAgeRejectionMinConfidence", 0.85,    float),
                ):
                    _v = _be_far.get_setting(_k)
                    if _v is None or str(_v).strip() == "":
                        _far_settings.setdefault(_k, _default)
                    else:
                        try:
                            _far_settings[_k] = _cast(_v)
                        except (TypeError, ValueError):
                            _far_settings[_k] = _default
            except Exception:
                _far_settings.setdefault("factAgeRejectionMode", "medium")
                _far_settings.setdefault("factAgeRejectionMaxAgeMin", 5)
                _far_settings.setdefault("factAgeRejectionMinConfidence", 0.85)

            _mode_far = _far_settings.get("factAgeRejectionMode", "medium")
            _modified_result, _rej_msgs, _rej_failure = check_and_apply_rejection(
                tool_name=fn_name,
                args=fn_args if isinstance(fn_args, dict) else {},
                result=result if isinstance(result, dict) else {},
                settings=_far_settings,
            )
            if _rej_failure == "fact_age_rejection":
                # Hard mode: replace with error sentinel so the LLM sees failure
                result = {
                    "status":     "error",
                    "error_type": "fact_age_rejection",
                    "message":    _rej_msgs[0] if _rej_msgs else "fact_age_rejection",
                    "data":       None,
                    "timestamp":  datetime.now(timezone.utc).isoformat(),
                }
                result_status = "error"
                result_msg = result["message"]
                for _qm in _rej_msgs:
                    state.propose_state.queued_harness_messages.append(_qm)
                try:
                    from api.metrics import FACT_AGE_REJECTIONS_COUNTER
                    FACT_AGE_REJECTIONS_COUNTER.labels(
                        mode=str(_mode_far), source_rejected="agent_tool",
                    ).inc()
                except Exception:
                    pass
            elif _rej_msgs:
                # Soft or Medium: harness messages + possibly modified result
                if _modified_result is not None and _modified_result is not result:
                    result = _modified_result
                    if isinstance(result, dict):
                        result_status = result.get("status", result_status)
                        result_msg = result.get("message", result_msg)
                for _qm in _rej_msgs:
                    state.propose_state.queued_harness_messages.append(_qm)
                try:
                    from api.metrics import FACT_AGE_REJECTIONS_COUNTER
                    FACT_AGE_REJECTIONS_COUNTER.labels(
                        mode=str(_mode_far), source_rejected="agent_tool",
                    ).inc()
                except Exception:
                    pass
                await manager.send_line(
                    "step",
                    f"[fact_age_rejection] {fn_name} — "
                    f"{len(_rej_msgs)} advisory (mode={_mode_far})",
                    tool=fn_name, status="warning", session_id=session_id,
                )
        except Exception as _far_e:
            log.debug("fact_age_rejection check failed: %s", _far_e)

        # Stream to GUI
        await manager.send_line(
            "tool",
            f"[{fn_name}] → {result_status} | {result_msg}",
            tool=fn_name, status=result_status, session_id=session_id,
        )

        # Summarize tool result for LLM context (full result in DB audit trail)
        tool_content = _summarize_tool_result(fn_name, result, result_status, result_msg,
                                             operation_id=operation_id, session_id=session_id)

        messages.append({
            "role": "tool",
            "tool_call_id": tc.id,
            "content": tool_content + tool_content_suffix,
        })

        await process_tool_result(
            state, fn_name, fn_args, result, step, messages,
            manager=manager, session_id=session_id,
            operation_id=operation_id,
        )

        _is_hard_failure = result_status in ("failed", "escalated") or (fn_name == "escalate" and result_status != "blocked")
        _is_degraded = result_status == "degraded"
        _is_investigate = agent_type in ("research", "investigate", "status", "observe")

        if _is_hard_failure or result_status == "error":
            _tool_failures_delta += 1

        if _is_degraded and _is_investigate:
            # Research/investigate/observe agents: degraded is a FINDING, not a halt.
            # Accumulate and keep going — synthesis fires at end of run.
            state.negative_signals += 1
            state.degraded_findings.append(f"{fn_name}: {result_msg[:120]}")
            await manager.send_line(
                "step",
                f"[degraded] {fn_name} reported degraded — continuing investigation",
                tool=fn_name, status="warning", session_id=session_id,
            )

        elif _is_hard_failure or (_is_degraded and not _is_investigate):
            state.negative_signals += 1
            from api.memory.feedback import record_feedback_signal as _rfs2
            asyncio.create_task(_rfs2(
                task, "escalation", f"{fn_name} returned {result_status}: {result_msg[:80]}"
            ))
            await manager.send_line(
                "halt",
                f"HALT: {fn_name} returned {result_status}",
                tool=fn_name, status="escalated", session_id=session_id,
            )
            # Record in persistent escalation table
            try:
                from api.routers.escalations import record_escalation
                esc_reason = f"{fn_name} returned {result_status}: {result_msg[:200]}"
                if fn_name == "escalate" and result_status != "blocked":
                    esc_reason = result_msg or fn_args.get("reason", "Agent escalated")
                record_escalation(
                    session_id=session_id,
                    reason=esc_reason[:500],
                    operation_id=operation_id,
                    severity="critical" if result_status == "failed" else "warning",
                )
                await manager.broadcast({
                    "type": "escalation_recorded",
                    "session_id": session_id,
                    "reason": esc_reason[:200],
                    "severity": "critical" if result_status == "failed" else "warning",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
            except Exception as _re:
                log.debug("record_escalation failed: %s", _re)
            # Synthesis: explain root cause + steps before halting
            try:
                _synth_ctx = "\n".join(
                    [f"- {f}" for f in state.degraded_findings]
                    or [f"- {fn_name} returned {result_status}: {result_msg[:120]}"]
                )
                _synth_resp = client.chat.completions.create(
                    model=_lm_model(),
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are a concise infrastructure ops assistant. "
                                "Produce a 4-section investigation report in plain text:\n\n"
                                "EVIDENCE:\n"
                                "- (one bullet per finding: tool → result)\n\n"
                                "ROOT CAUSE: (one specific sentence)\n\n"
                                "FIX STEPS:\n"
                                "1. (specific action with exact command if known)\n"
                                "2. ...\n\n"
                                "AUTOMATABLE (if re-run as action task):\n"
                                "- (step N — tool that would execute it)\n\n"
                                "No markdown headers. No padding. Be specific: use exact "
                                "exit codes, IPs, container names, and timestamps from the findings."
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                f"Task: {task}\n\nFindings:\n{_synth_ctx}\n\n"
                                "Explain root cause and provide remediation steps."
                            ),
                        },
                    ],
                    tools=None,
                    temperature=0.3,
                    max_tokens=400,
                )
                _synth_text = _synth_resp.choices[0].message.content or ""
                if _synth_text.strip():
                    state.last_reasoning = _synth_text.strip()
                    await manager.send_line("reasoning", _synth_text, session_id=session_id)
            except Exception as _se:
                log.debug("Halt synthesis failed: %s", _se)
            halt = True
            state.final_status = "escalated"
            break

    if halt:
        await manager.send_line(
            "halt", "Agent halted — human review required.",
            status="escalated", session_id=session_id,
        )
        return ToolsDispatchResult(
            action=ToolLoopAction.BREAK,
            destructive_calls_delta=_destructive_calls_delta,
            tool_failures_delta=_tool_failures_delta,
        )

    return ToolsDispatchResult(
        action=ToolLoopAction.NORMAL,
        destructive_calls_delta=_destructive_calls_delta,
        tool_failures_delta=_tool_failures_delta,
    )
