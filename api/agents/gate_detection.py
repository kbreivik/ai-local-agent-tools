"""Gate-fired detection shared between the trace digest and the UI trace view.

A "gate" is any harness-initiated message injected into the LLM conversation:
- hallucination_guard  (substantive-tool-call block)
- fabrication_detected (sub-agent cited uncalled tools)
- subagent_distrust    (parent warned about unreliable sub-agent output)
- budget_truncate      (tool_calls batch truncated)
- budget_nudge         (70% handoff nudge → propose_subtask)
- sanitizer            (content redacted before entering the LLM)

The Python detector walks a list of step rows (messages_delta fields) and the
JS detector at gui/src/utils/gateDetection.js mirrors the same logic. Keep
them in sync — a snapshot test asserts both report the same counts on a
known fixture.
"""
from __future__ import annotations

from typing import Iterable


GATE_DEFS = (
    "halluc_guard",
    "fabrication",
    "distrust",
    "budget_truncate",
    "budget_nudge",
    "sanitizer",
)


def _empty_gates() -> dict:
    return {name: {"count": 0, "details": []} for name in GATE_DEFS}


def _iter_delta_messages(step: dict) -> Iterable[dict]:
    for m in (step.get("messages_delta") or []):
        if isinstance(m, dict):
            yield m


def detect_gates_from_steps(steps: list) -> dict:
    """Scan trace steps and return a count+detail dict per gate type.

    Each step is expected to have at minimum: ``step_index``, ``messages_delta``.
    The detector is forgiving: missing fields default to empty, non-string
    content is coerced via str().
    """
    gates = _empty_gates()
    for s in steps or []:
        step_idx = s.get("step_index", 0)
        for m in _iter_delta_messages(s):
            content = m.get("content")
            if not isinstance(content, str):
                content = str(content or "")
            if not content:
                continue
            lowered = content.lower()

            if "[harness]" in content and "substantive tool call" in lowered:
                gates["halluc_guard"]["count"] += 1
                gates["halluc_guard"]["details"].append(
                    {"step": step_idx, "snippet": content[:160]}
                )
            if (
                "[harness]" in content
                and "flagged" in lowered
                and ("fabrication" in lowered or "halluc_guard_fired" in lowered)
            ):
                gates["distrust"]["count"] += 1
                gates["distrust"]["details"].append(
                    {"step": step_idx, "snippet": content[:160]}
                )
            if "[harness]" in content and "tool budget" in lowered:
                gates["budget_truncate"]["count"] += 1
                gates["budget_truncate"]["details"].append(
                    {"step": step_idx, "snippet": content[:160]}
                )
            if "harness nudge" in lowered and "propose_subtask" in lowered:
                gates["budget_nudge"]["count"] += 1
                gates["budget_nudge"]["details"].append(
                    {"step": step_idx, "snippet": content[:160]}
                )
            if "[redacted]" in lowered:
                gates["sanitizer"]["count"] += 1
                gates["sanitizer"]["details"].append(
                    {"step": step_idx, "snippet": content[:160]}
                )

    fabrication_count = _count_fabrication(steps)
    if fabrication_count:
        gates["fabrication"]["count"] = fabrication_count
    return gates


def _count_fabrication(steps: list) -> int:
    """Count tool_result messages that report fabrication_detected=True.

    Handled separately because the fabrication_detected signal lives on the
    sub-agent tool_result payload, not on an injected harness message.
    """
    import json

    count = 0
    for s in steps or []:
        for m in _iter_delta_messages(s):
            if m.get("role") != "tool":
                continue
            content = m.get("content")
            if not isinstance(content, str):
                continue
            if "fabrication_detected" not in content:
                continue
            try:
                payload = json.loads(content)
            except Exception:
                continue
            guard = (payload or {}).get("harness_guard") or {}
            if guard.get("fabrication_detected"):
                count += 1
    return count
