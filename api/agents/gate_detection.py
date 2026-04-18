"""Gate-fired detection shared between the trace digest and the UI trace view.

A "gate" is any harness-initiated message injected into the LLM conversation:
- hallucination_guard  (substantive-tool-call block)
- fabrication_detected (sub-agent cited uncalled tools)
- subagent_distrust    (parent warned about unreliable sub-agent output)
- budget_truncate      (tool_calls batch truncated)
- budget_nudge         (70% handoff nudge → propose_subtask)
- sanitizer            (content redacted before entering the LLM)
- forced_synthesis     (tools-free completion after a hard-cap loop exit)

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
    "forced_synthesis",
    "inrun_contradiction",
    "fact_age_rejection",
    "runbook_injected",
)


_RUNBOOK_MARKER = "═══ ACTIVE RUNBOOK:"


def _empty_gates() -> dict:
    return {name: {"count": 0, "details": []} for name in GATE_DEFS}


def _iter_delta_messages(step: dict) -> Iterable[dict]:
    for m in (step.get("messages_delta") or []):
        if isinstance(m, dict):
            yield m


def detect_gates_from_steps(steps: list, system_prompt: str | None = None) -> dict:
    """Scan trace steps and return a count+detail dict per gate type.

    Each step is expected to have at minimum: ``step_index``, ``messages_delta``.
    The detector is forgiving: missing fields default to empty, non-string
    content is coerced via str().

    ``system_prompt`` (optional): the rendered system prompt for this operation.
    Used to detect prompt-level gates (e.g. runbook_injected) that are not
    recorded per-step in messages_delta.
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
            if "[harness]" in content and "cap" in lowered and (
                "budget-cap" in lowered
                or "wall-clock cap" in lowered
                or "token cap" in lowered
                or "destructive-call cap" in lowered
                or "consecutive-tool-failure cap" in lowered
            ):
                gates["forced_synthesis"]["count"] += 1
                gates["forced_synthesis"]["details"].append(
                    {"step": step_idx, "snippet": content[:160]}
                )
            # v2.35.2 — in-run cross-tool contradiction advisory
            if "[harness] Contradiction detected within this run" in content:
                gates["inrun_contradiction"]["count"] += 1
                gates["inrun_contradiction"]["details"].append(
                    {"step": step_idx, "snippet": content[:160]}
                )
            # v2.35.3 — fact-age rejection on tool results
            if (
                "[harness] Fact-age rejection" in content
                or "[harness] Hard fact-age rejection" in content
            ):
                gates["fact_age_rejection"]["count"] += 1
                gates["fact_age_rejection"]["details"].append(
                    {"step": step_idx, "snippet": content[:180]}
                )

    fabrication_count = _count_fabrication(steps)
    if fabrication_count:
        gates["fabrication"]["count"] = fabrication_count

    # v2.35.4 — runbook injection is a prompt-level event, so it's 0 or 1 per
    # operation. Scan system_prompt first (authoritative), then messages for
    # backward-compat with traces that captured the system message in-line.
    runbook_name = None
    if isinstance(system_prompt, str) and _RUNBOOK_MARKER in system_prompt:
        import re
        m = re.search(r"═══ ACTIVE RUNBOOK:\s*([^\s═]+)\s*═══", system_prompt)
        runbook_name = m.group(1) if m else "<unknown>"
    if not runbook_name:
        runbook_name = _find_injected_runbook_name(steps)
    if runbook_name:
        gates["runbook_injected"]["count"] = 1
        gates["runbook_injected"]["details"].append(
            {"step": 0, "snippet": f"runbook={runbook_name}"}
        )
    return gates


def _find_injected_runbook_name(steps: list) -> str | None:
    """Scan all messages across all steps for the ACTIVE RUNBOOK marker.
    Returns the runbook name on first hit, else None."""
    import re
    pattern = re.compile(r"═══ ACTIVE RUNBOOK:\s*([^\s═]+)\s*═══")
    for s in steps or []:
        for m in _iter_delta_messages(s):
            content = m.get("content")
            if not isinstance(content, str):
                content = str(content or "")
            if _RUNBOOK_MARKER not in content:
                continue
            match = pattern.search(content)
            if match:
                return match.group(1)
            return "<unknown>"
    return None


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
