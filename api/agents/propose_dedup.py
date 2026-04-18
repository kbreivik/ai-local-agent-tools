"""Within-run deduplication for propose_subtask calls (v2.34.16).

The parent agent sometimes re-proposes an identical subtask before the first
proposal has produced a result. That burns spawn budget and adds no
information. This module provides:

- ``subtask_dedup_key(args)`` — canonical hash of {task, executable_steps,
  manual_steps} so argument-order differences don't break the dedup.
- ``ProposeState`` — plain holder for the parent run's proposal map +
  queued terminal-feedback messages. Only the parent run's handler manipulates
  it; tests construct one directly via ``make_parent_state()``.
- ``handle_propose_subtask(args, state, step_index)`` — returns
  ``{"status": "duplicate_proposal", ...}`` if a prior proposal with the
  same dedup key exists. Otherwise records the new key with status='pending'
  and returns ``{"status": "new"}`` so the caller continues with its normal
  spawn flow.
- ``on_subagent_terminal(sub_op_id, terminal_status, final_answer,
  fabrication_detail, halluc_guard_detail, state, dedup_key)`` — updates
  the map entry AND queues a ``[harness]`` system message describing the
  sub-agent outcome so the parent's next completion call sees it.

The inline propose_subtask handler in ``api/routers/agent.py`` wires this in;
the pure functions here have no FastAPI / DB dependencies so they're unit
testable without fixtures.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field


@dataclass
class ProposeState:
    """Parent-run dedup state. One instance per agent run."""
    proposed_subtask_keys: set = field(default_factory=set)
    # key -> {"status", "sub_op_id", "proposed_at_step"}
    proposed_subtask_map: dict = field(default_factory=dict)
    queued_harness_messages: list = field(default_factory=list)


def make_parent_state() -> ProposeState:
    """Test helper — returns a fresh parent state."""
    return ProposeState()


def subtask_dedup_key(proposed_args: dict) -> str:
    """Stable hash of the proposal shape, for within-run dedup.

    Uses task OR objective as the headline field (callers pass either shape);
    executable_steps and manual_steps are normalised to lists.
    """
    task = (proposed_args.get("task") or proposed_args.get("objective") or "").strip()
    canonical = {
        "task":             task,
        "executable_steps": proposed_args.get("executable_steps") or [],
        "manual_steps":     proposed_args.get("manual_steps") or [],
    }
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def handle_propose_subtask(
    proposed_args: dict,
    state: ProposeState,
    step_index: int,
) -> dict:
    """Check the proposal against prior proposals in this parent run.

    Returns one of:
      {"status": "new", "key": "..."}                   — first time seen
      {"status": "duplicate_proposal", "key": "...",
       "prior": {...}, "harness_message": "[harness] ..."}
                                                         — duplicate detected
    """
    key = subtask_dedup_key(proposed_args)

    if key in state.proposed_subtask_keys:
        prior = dict(state.proposed_subtask_map.get(key, {}))
        prior_status = prior.get("status", "pending")
        sub_op_id = prior.get("sub_op_id") or "<pending>"
        proposed_at = prior.get("proposed_at_step", "?")

        try:
            from api.metrics import PROPOSE_DUPLICATE_COUNTER
            PROPOSE_DUPLICATE_COUNTER.labels(prior_status=prior_status).inc()
        except Exception:
            pass

        harness_message = (
            f"[harness] You already proposed this exact subtask at step "
            f"{proposed_at} (sub_op_id={sub_op_id}, status={prior_status}). "
            f"Do NOT re-propose. Your options: "
            f"(a) wait for the prior sub-agent result in your next turn, "
            f"(b) propose a DIFFERENT subtask with different steps, "
            f"(c) synthesise your own final_answer from evidence gathered so far, "
            f"(d) call escalate() if you cannot make progress."
        )
        return {
            "status":         "duplicate_proposal",
            "key":            key,
            "prior":          prior,
            "harness_message": harness_message,
        }

    state.proposed_subtask_keys.add(key)
    state.proposed_subtask_map[key] = {
        "status":            "pending",
        "sub_op_id":         None,
        "proposed_at_step":  step_index,
    }
    return {"status": "new", "key": key}


def mark_spawned(state: ProposeState, key: str, sub_op_id: str) -> None:
    entry = state.proposed_subtask_map.get(key)
    if not entry:
        return
    entry["status"] = "spawned"
    entry["sub_op_id"] = sub_op_id


def mark_rejected(state: ProposeState, key: str, outcome: str) -> None:
    entry = state.proposed_subtask_map.get(key)
    if not entry:
        return
    entry["status"] = outcome   # e.g. "rejected_budget", "rejected_depth"


def on_subagent_terminal(
    sub_op_id: str,
    terminal_status: str,
    final_answer: str,
    fabrication_detail: dict | None,
    halluc_guard_detail: dict | None,
    state: ProposeState,
    dedup_key: str | None,
) -> str | None:
    """Update the dedup entry AND queue a harness system message describing
    the sub-agent outcome so the parent sees it on its next turn.

    Returns the queued message (or None if there was nothing worth injecting).
    """
    if dedup_key and dedup_key in state.proposed_subtask_map:
        state.proposed_subtask_map[dedup_key]["status"] = terminal_status
        state.proposed_subtask_map[dedup_key]["sub_op_id"] = sub_op_id

    warnings: list[str] = []
    if halluc_guard_detail and halluc_guard_detail.get("fired"):
        warnings.append(
            f"Sub-agent's hallucination guard fired "
            f"{halluc_guard_detail.get('attempts', 1)}× before terminating."
        )
    if fabrication_detail and float(fabrication_detail.get("score", 0) or 0) > 0.5:
        fabbed = fabrication_detail.get("fabricated") or []
        sample = ", ".join(fabbed[:5]) if fabbed else "unknown tools"
        warnings.append(
            f"Sub-agent output cited {len(fabbed)} tool(s) that did not run: "
            f"{sample}. Do NOT treat its EVIDENCE block as factual."
        )
    if terminal_status == "escalated":
        warnings.append(
            "Sub-agent ESCALATED (did not execute). Your proposed action "
            "was not performed; operator must decide."
        )
    elif terminal_status in ("failed", "cap_hit", "timeout"):
        warnings.append(
            f"Sub-agent {terminal_status.upper()}. Consider a different approach "
            "or escalate yourself."
        )

    if not warnings:
        return None

    msg = (
        f"[harness] Sub-agent {sub_op_id[:8] if sub_op_id else '<unknown>'} "
        f"returned status={terminal_status}. "
        + " ".join(warnings)
        + " Do NOT repeat the same propose_subtask. Review your evidence and "
        + "either synthesise a final_answer or take a different action."
    )
    state.queued_harness_messages.append(msg)

    try:
        from api.metrics import SUBAGENT_TERMINAL_FEEDBACK_COUNTER
        SUBAGENT_TERMINAL_FEEDBACK_COUNTER.labels(
            terminal_status=terminal_status or "unknown"
        ).inc()
    except Exception:
        pass

    return msg
