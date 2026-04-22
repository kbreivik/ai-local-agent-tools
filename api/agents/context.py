"""Agent context-building helpers — v2.40.4.

Extracted from api/routers/agent.py.

Provides functions that assemble context blocks for injection into
agent system prompts. All functions are sync, pure or near-pure
(DB reads only, no side effects).

Imported back into agent.py:
    from api.agents.context import (
        _build_prerun_external_context,
        _extract_working_memory,
        _build_subagent_context,
    )
"""
from __future__ import annotations
import logging
import re

log = logging.getLogger(__name__)


def _extract_working_memory(think_text: str, step: int) -> str:
    """Extract key facts from a model <think> block for inter-step continuity.

    Parses numbers, hostnames, ref tokens, status words, and tool plans
    from the model's reasoning. Returns a compact string (≤120 chars)
    suitable for prepending to the next step's user message.

    Returns empty string if nothing useful found.
    """
    if not think_text or len(think_text) < 20:
        return ""

    facts = []

    # Result store refs
    refs = re.findall(r'rs-[a-f0-9]{8,}', think_text)
    if refs:
        facts.append(f"ref={refs[0]}")

    # Numbers with units (disk, memory, counts)
    nums = re.findall(
        r'(\d+(?:\.\d+)?)\s*(GB|MB|TB|%|clients?|devices?|images?|containers?)',
        think_text, re.IGNORECASE
    )
    for val, unit in nums[:3]:
        facts.append(f"{val}{unit.lower()}")

    # Hostnames / labels in quotes or after "on "
    hosts = re.findall(r'(?:on|host|label)\s+["\']?([\w-]{3,30})["\']?', think_text, re.IGNORECASE)
    if hosts:
        facts.append(f"host={hosts[0]}")

    # Status findings
    statuses = re.findall(
        r'\b(healthy|degraded|critical|error|ok|success|failed|stopped|running)\b',
        think_text, re.IGNORECASE
    )
    if statuses:
        facts.append(f"status={statuses[0].lower()}")

    if not facts:
        return ""

    return f"[Step {step} found: {', '.join(facts[:5])}]"


def _build_prerun_external_context(
    task: str,
    preflight_facts_block: str = "",
    max_facts: int = 60,
) -> str:
    """Build a context digest for force-external prerun calls.

    synthesize_replace at prerun has no tool-call history to flatten —
    the message list is just [system_prompt, user_task]. This helper
    pulls real infrastructure state from known_facts so that external AI
    has evidence to synthesise from rather than responding 'I don't know'.

    Returns a formatted string injected as the `digest` param of
    synthesize_replace. Empty string on any failure (safe fallback).
    """
    parts: list[str] = []

    # 1. Preflight facts (entity-specific, highest signal)
    if preflight_facts_block and preflight_facts_block.strip():
        parts.append(preflight_facts_block.strip())

    # 2. Broad infra facts from known_facts — top confident rows
    try:
        from api.db.known_facts import get_confident_facts
        rows = get_confident_facts(min_confidence=0.7, max_rows=max_facts)
        if rows:
            lines = ["INFRASTRUCTURE STATE (from knowledge store):"]
            for r in rows:
                key = r.get("fact_key", "")
                val = r.get("fact_value", "")
                conf = r.get("confidence", 0.0)
                if isinstance(val, (list, dict)):
                    import json as _json
                    val = _json.dumps(val)
                lines.append(f"  {key} = {val}  (confidence={conf:.2f})")
            parts.append("\n".join(lines))
    except Exception as _e:
        log.debug("_build_prerun_external_context: known_facts query failed: %s", _e)

    # 3. Entity history — recent changes and events for preflight candidates
    try:
        from api.db.entity_history import get_recent_changes_summary, get_events
        from api.agents.preflight import tier1_regex_extract

        candidates = tier1_regex_extract(task)
        entity_ids = [c.entity_id for c in candidates[:5]]  # cap to avoid bloat

        history_lines: list[str] = []
        for eid in entity_ids:
            summary = get_recent_changes_summary(eid, hours=24)
            if summary:
                history_lines.append(f"  {eid}: {summary}")
            warn_events = get_events(eid, hours=24, severity="warning", limit=2)
            crit_events = get_events(eid, hours=24, severity="critical", limit=2)
            for ev in (crit_events + warn_events):
                ev_str = ev.get("description") or ev.get("event_type", "")
                if ev_str:
                    history_lines.append(f"  {eid} [{ev.get('severity','?')}]: {ev_str}")

        if history_lines:
            parts.append(
                "RECENT ENTITY ACTIVITY (last 24h):\n" + "\n".join(history_lines)
            )
    except Exception as _eh:
        log.debug("_build_prerun_external_context: entity history failed: %s", _eh)

    if not parts:
        return ""

    header = (
        "NOTE: The following facts and recent activity were gathered by "
        "infrastructure collectors and represent current known state. "
        "Use this as your primary evidence. "
        "Do NOT invent values not present here.\n\n"
    )
    return header + "\n\n".join(parts)


def _build_subagent_context(parent_diagnosis: str, scope_entity: str,
                            parent_session_id: str) -> str:
    """Compact 3-line parent summary injected into a sub-agent's system prompt.

    Sub-agents deliberately do NOT inherit the parent's full tool history —
    that's the point of isolation. They get:
      - parent's last DIAGNOSIS (if any)
      - entity scope (if given)
      - parent task id for traceability
    """
    lines = []
    if parent_diagnosis:
        lines.append(f"PARENT DIAGNOSIS SO FAR: {parent_diagnosis[:500]}")
    if scope_entity:
        lines.append(f"SCOPE: {scope_entity}")
    lines.append(f"PARENT_TASK_ID: {parent_session_id}")
    lines.append(
        "You are a sub-agent. Your parent delegated this task to you. "
        "Be focused. Return a DIAGNOSIS section in your final answer."
    )
    return "\n".join(lines)
