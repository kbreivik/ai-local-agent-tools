"""Agent harness gate helpers — v2.40.3.

Extracted from api/routers/agent.py to make gate logic independently
testable and to reduce agent.py line count.

Imported back into agent.py:
    from api.agents.gates import (
        _is_preamble_only, _classify_terminal_final_answer,
        compute_final_answer, _result_count, _should_disable_thinking,
    )
"""
from __future__ import annotations

import re

__all__ = [
    "_PREAMBLE_STARTERS",
    "_VERDICT_MARKERS",
    "_is_preamble_only",
    "_classify_terminal_final_answer",
    "compute_final_answer",
    "_result_count",
    "_should_disable_thinking",
]


# ── Preamble / synthesis classification ──────────────────────────────────────

_PREAMBLE_STARTERS = (
    "i'll ", "i will ", "let me ", "let's ", "sure, ",
    "sure! ", "okay, ", "okay! ", "ok, ", "first, ",
    "first i'll ", "first let me ", "i'm going to ",
    "i am going to ", "going to ", "going to check ",
    "to answer ", "to check ",
)

_VERDICT_MARKERS = (
    "STATUS:", "FINDINGS:", "ROOT CAUSE:", "EVIDENCE:",
    "CONCLUSION:", "SUMMARY:", "UNRESOLVED:", "NEXT STEPS:",
)


def _is_preamble_only(text: str) -> bool:
    """v2.35.15 — return True for text that is a thinking preamble, not a
    synthesis.

    The LLM often emits 'I'll check ...' or 'Let me look into ...' on step 1
    before making tool calls, then never gets back to summarising. That
    stub is what ends up in final_answer.

    A text is flagged as preamble iff ALL of:
      * starts with a known preamble opener (case-insensitive)
      * does NOT contain any verdict marker (STATUS:, FINDINGS:, ...)
      * AND (is short (<200 chars) OR ends without terminal punctuation
        like '.', '!', '?' — i.e. looks cut off / ends with '...')
    """
    if not text:
        return False
    stripped = text.strip()
    if not stripped:
        return False
    low = stripped.lower()
    if not any(low.startswith(p) for p in _PREAMBLE_STARTERS):
        return False
    upper = stripped.upper()
    has_verdict = any(marker in upper for marker in _VERDICT_MARKERS)
    if has_verdict:
        return False
    ends_unfinished = (
        stripped.endswith("...")
        or stripped.endswith("…")
        or not stripped.endswith((".", "!", "?", ":", ">"))
    )
    return len(stripped) < 200 or ends_unfinished


def _classify_terminal_final_answer(text: str) -> str | None:
    """v2.35.15 — return the rescue reason for a terminal final_answer,
    or None if the text is substantive enough to stand as-is.

    Three-way dispatch:
      - empty_completion         → text is missing / whitespace-only
      - too_short_completion     → <60 chars (can't plausibly be a synthesis)
      - preamble_only_completion → thinking stub (see _is_preamble_only)
      - None                     → real answer; no rescue needed
    """
    if not (text or "").strip():
        return "empty_completion"
    stripped = text.strip()
    if len(stripped) < 60:
        return "too_short_completion"
    if _is_preamble_only(stripped):
        return "preamble_only_completion"
    return None


def compute_final_answer(steps: list[dict]) -> str:
    """v2.35.17 — derive final_answer from agent step history.

    Rule (per OpenAI chat-completions semantics): a synthesis answer is
    only valid when a step BOTH (a) finished with finish_reason='stop'
    AND (b) emitted NO tool_calls. Content emitted alongside tool_calls
    is pre-action reasoning ("I'll check the UniFi..."), not a
    user-facing answer.

    Traverses steps in REVERSE so multi-synthesis flows (e.g. a natural
    synthesis followed by a forced_synthesis rescue) pick up the most
    recent synthesis. Returns '' if no step qualifies, so v2.35.14's
    empty_completion rescue fires run_forced_synthesis.

    v2.35.16 only checked the last step and only gated on
    finish_reason — that left a hole when the LLM emitted content
    AND a tool_call in the same response (op 07d326a1, fa_len=53).
    v2.35.17 closes that hole at the source; v2.35.15
    too_short/preamble_only rescues become belt-and-suspenders.

    Used by the agent loop's per-step content handler and as the
    testable contract for tests/test_final_answer_assignment.py.
    """
    if not steps:
        return ""
    for step in reversed(steps):
        if not isinstance(step, dict):
            continue
        if step.get("finish_reason") != "stop":
            continue
        if step.get("tool_calls"):
            continue
        content = (step.get("content") or "").strip()
        if content:
            return content
    return ""


def _result_count(tool_result: dict) -> int | None:
    """Heuristic: extract a 'count of items returned' from common tool response shapes.

    Used by the v2.33.12 zero-result pivot detector to spot stuck filters.
    Returns None when no count can be inferred (so the detector ignores the call).
    """
    if not isinstance(tool_result, dict):
        return None
    # Direct count fields
    for key in ("total", "count", "hit_count", "num_results"):
        v = tool_result.get(key)
        if isinstance(v, int):
            return v
    # Array fields
    for key in ("hits", "results", "items", "entries", "logs"):
        arr = tool_result.get(key)
        if isinstance(arr, list):
            return len(arr)
    # Stringly-typed "Found N ..." summary fallback
    summary = tool_result.get("summary") or tool_result.get("message") or ""
    m = re.search(r"[Ff]ound\s+(\d+)", str(summary))
    if m:
        return int(m.group(1))
    return None


def _should_disable_thinking(tool_names_this_step: list[str], step: int, max_steps: int) -> bool:
    """Return True if we should append /no_think to suppress the <think> block.

    Qwen3 supports /no_think suffix to skip chain-of-thought reasoning.
    Use this for steps where structured output matters more than reasoning:
    - audit_log-only steps (model is just recording, not deciding)

    Do NOT use for planning steps, multi-tool steps, or first steps of complex tasks.
    """
    if tool_names_this_step == ["audit_log"]:
        return True
    return False
