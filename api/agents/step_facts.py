"""step_facts — per-tool fact extraction, contradiction, zero-pivot, diagnostics — v2.41.3.

Extracted from api/routers/agent.py _run_single_agent_step.

process_tool_result() is called once after each tool call completes, with the
final resolved `result` dict. It mutates state.tool_history, state.run_facts,
state.zero_streaks, state.nonzero_seen, state.zero_pivot_fired.
It may append harness messages to state.propose_state and messages.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)


async def process_tool_result(
    state,            # StepState
    fn_name: str,
    fn_args: dict,
    result: dict,
    step: int,
    messages: list,
    *,
    manager,
    session_id: str,
    operation_id: str,
) -> None:
    """Run all post-tool processing: history, facts, contradiction, pivot, diagnostics.

    Mutates:
      state.tool_history
      state.run_facts
      state.zero_streaks / nonzero_seen / zero_pivot_fired
    May append to messages (zero-pivot harness nudge).
    May append to state.propose_state.queued_harness_messages (contradiction).
    """
    import json
    from api.routers.agent import _result_count

    # ── tool_history (v2.33.13) ───────────────────────────────────────────────
    _count = _result_count(result if isinstance(result, dict) else {})
    state.tool_history.append({
        "tool":   fn_name,
        "args":   fn_args if isinstance(fn_args, dict) else {},
        "result": {"total": _count if _count is not None else 0},
        "step":   step,
    })

    # ── zero-streak tracking ──────────────────────────────────────────────────
    if _count is not None:
        if _count == 0:
            state.zero_streaks[fn_name] = state.zero_streaks.get(fn_name, 0) + 1
        else:
            state.zero_streaks[fn_name] = 0
            state.nonzero_seen[fn_name] = max(state.nonzero_seen.get(fn_name, 0), _count)

    # ── v2.45.27: sliding-window zero-ratio guard ────────────────────────────
    # The strict consecutive-zero guard misses patterns where a single nonzero
    # result resets the streak (e.g. [10, 0, 0, 0, 5, 0, 0, 0] — 6/8 zeros).
    # Track the last 6 _count values per tool; when 4-of-6 are zero AND there
    # is at least one nonzero in the window AND we have not fired this signal
    # for this tool yet, inject a harness nudge.
    from collections import deque as _deque
    _ZW_SIZE = 6
    _ZW_TRIGGER = 4   # zeros in window required to fire
    if _count is not None:
        win = state.zero_window.get(fn_name)
        if win is None:
            win = _deque(maxlen=_ZW_SIZE)
            state.zero_window[fn_name] = win
        win.append(_count)
        _zeros_in_win = sum(1 for v in win if v == 0)
        _nonzeros_in_win = sum(1 for v in win if v and v > 0)
        if (
            len(win) >= _ZW_SIZE
            and _zeros_in_win >= _ZW_TRIGGER
            and _nonzeros_in_win >= 1
            and fn_name not in state.zero_pivot_fired
        ):
            state.zero_pivot_fired.add(fn_name)
            _max_seen = state.nonzero_seen.get(fn_name, 0)
            messages.append({
                "role": "system",
                "content": (
                    f"HARNESS NUDGE: In your last {_ZW_SIZE} calls to {fn_name}, "
                    f"{_zeros_in_win} returned 0 results (only {_nonzeros_in_win} "
                    f"returned data; max seen: {_max_seen}). The query shape is "
                    "mostly missing — flapping or filter-too-narrow. Stop "
                    "repeating the same pattern. Your next step must either "
                    "(a) synthesize from the calls that DID return data, "
                    "(b) broaden the filter (drop level/service/host constraints), or "
                    "(c) switch to a different tool. "
                    "Do NOT call this tool again with the same shape."
                ),
            })
            await manager.broadcast({
                "type":              "zero_result_pivot",
                "session_id":        session_id,
                "tool":              fn_name,
                "consecutive_zeros": state.zero_streaks.get(fn_name, 0),
                "prior_nonzero":     _max_seen,
                "window_size":       _ZW_SIZE,
                "window_zeros":      _zeros_in_win,
                "trigger":           "sliding_window_ratio",
                "timestamp":         datetime.now(timezone.utc).isoformat(),
            })
            await manager.send_line(
                "step",
                f"[pivot:window] {fn_name} returned 0 in {_zeros_in_win}/{_ZW_SIZE} "
                f"recent calls — nudging agent to broaden or switch",
                status="warning", session_id=session_id,
            )
            try:
                from api.metrics import ZERO_PIVOT_WINDOW_COUNTER
                ZERO_PIVOT_WINDOW_COUNTER.labels(tool=fn_name).inc()
            except Exception:
                pass

    # ── in-run fact extraction + contradiction (v2.35.2) ─────────────────────
    try:
        from api.facts.tool_extractors import extract_facts_from_tool_result
        _new_facts = extract_facts_from_tool_result(
            fn_name,
            fn_args if isinstance(fn_args, dict) else {},
            result if isinstance(result, dict) else {},
        )
    except Exception as _fe:
        log.debug("tool fact extraction failed: %s", _fe)
        _new_facts = []

    for _nf in _new_facts:
        _fk = _nf.get("fact_key")
        if not _fk:
            continue
        _nv = _nf.get("value")
        _prior = state.run_facts.get(_fk)
        if _prior is not None and _prior.get("value") != _nv:
            try:
                _prior_snip = json.dumps(_prior.get("value"), default=str)[:80]
                _new_snip   = json.dumps(_nv, default=str)[:80]
            except Exception:
                _prior_snip = str(_prior.get("value"))[:80]
                _new_snip   = str(_nv)[:80]
            _contra_msg = (
                f"[harness] Contradiction detected within this run: "
                f"{_fk} — step {_prior.get('step')} "
                f"({_prior.get('tool')}) said {_prior_snip}, "
                f"step {step} ({fn_name}) says {_new_snip}. "
                f"Resolve before concluding. The {_fk} field in your "
                f"EVIDENCE block must cite only ONE value or explicitly note the conflict."
            )
            if state.propose_state:
                state.propose_state.queued_harness_messages.append(_contra_msg)
            await manager.send_line(
                "step",
                f"[contradiction] {_fk} disagrees across step {_prior.get('step')} → step {step}",
                status="warning", session_id=session_id,
            )
            try:
                from api.metrics import INRUN_CONTRADICTION_COUNTER
                _parts = _fk.split(".")
                _prefix = ".".join(_parts[:3]) if len(_parts) >= 3 else _fk
                INRUN_CONTRADICTION_COUNTER.labels(fact_key_prefix=_prefix).inc()
            except Exception:
                pass
        state.run_facts[_fk] = {
            "value":     _nv,
            "step":      step,
            "tool":      fn_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "raw":       _nf,
        }

    # ── zero-result pivot nudge (v2.33.12) ────────────────────────────────────
    if (
        state.zero_streaks.get(fn_name, 0) >= 3
        and state.nonzero_seen.get(fn_name, 0) > 0
        and fn_name not in state.zero_pivot_fired
    ):
        state.zero_pivot_fired.add(fn_name)
        _prior_n = state.nonzero_seen[fn_name]
        messages.append({
            "role": "system",
            "content": (
                f"HARNESS NUDGE: Your last 3 calls to {fn_name} returned 0 results. "
                f"Earlier in this task, {fn_name} returned {_prior_n} result(s). "
                "Your filter is likely too narrow. Your next step must either "
                "(a) synthesize from the non-zero call's output, "
                "(b) broaden the filter (drop level/service/host constraints), or "
                "(c) switch to a different tool. "
                "Do NOT repeat the same narrow-filter pattern."
            ),
        })
        await manager.broadcast({
            "type":              "zero_result_pivot",
            "session_id":        session_id,
            "tool":              fn_name,
            "consecutive_zeros": state.zero_streaks[fn_name],
            "prior_nonzero":     _prior_n,
            "timestamp":         datetime.now(timezone.utc).isoformat(),
        })
        await manager.send_line(
            "step",
            f"[pivot] {fn_name} returned 0 · {state.zero_streaks[fn_name]}× in a row "
            f"(earlier: {_prior_n}) — nudging agent to broaden or pivot",
            status="warning", session_id=session_id,
        )
    elif (
        state.zero_streaks.get(fn_name, 0) >= 4
        and fn_name not in state.zero_pivot_fired
    ):
        state.zero_pivot_fired.add(fn_name)
        messages.append({
            "role": "system",
            "content": (
                f"HARNESS NUDGE: {fn_name} has returned 0 results for 4 consecutive calls "
                "in this task and has never returned any data. It may not be the right tool "
                "for this question. Switch to a different approach or call propose_subtask."
            ),
        })
        await manager.broadcast({
            "type":              "zero_result_pivot",
            "session_id":        session_id,
            "tool":              fn_name,
            "consecutive_zeros": state.zero_streaks[fn_name],
            "prior_nonzero":     0,
            "timestamp":         datetime.now(timezone.utc).isoformat(),
        })
        await manager.send_line(
            "step",
            f"[pivot] {fn_name} returned 0 · {state.zero_streaks[fn_name]}× with no prior "
            "data — nudging agent to switch tools",
            status="warning", session_id=session_id,
        )

    # ── live diagnostics snapshot (v2.33.15) ─────────────────────────────────
    try:
        await manager.broadcast({
            "type":                 "agent_diagnostics",
            "session_id":           session_id,
            "operation_id":         operation_id,
            "step":                 step,
            "tool_just_called":     fn_name,
            "tools_used":           list(state.tools_used_names),
            "substantive_calls":    state.substantive_tool_calls,
            "positive_signals":     state.positive_signals,
            "negative_signals":     state.negative_signals,
            "halluc_guard_attempts": state.halluc_guard_attempts,
            "run_facts_count":      len(state.run_facts),
            "timestamp":            datetime.now(timezone.utc).isoformat(),
        })
    except Exception as _diag_e:
        log.debug("agent_diagnostics broadcast failed: %s", _diag_e)
