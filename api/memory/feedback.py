"""
Feedback loop — records agent run outcomes as MuninnDB engrams.

record_outcome()         → store end-of-run outcome + tool-sequence association
record_feedback_signal() → store implicit signal (plan approved/cancelled, escalation, error)
"""
import logging
import re
from datetime import datetime, timezone

from api.memory.client import get_client

log = logging.getLogger(__name__)

# Positive signals strengthen Hebbian links (stored N times to raise access frequency)
_POSITIVE_SIGNALS = {"plan_approved"}
_NEGATIVE_SIGNALS = {"plan_cancelled", "escalation", "tool_error", "clarification_needed"}


def _slugify(text: str) -> str:
    return re.sub(r'[^a-z0-9]+', '_', text.lower())[:40].strip('_')


async def record_outcome(
    session_id: str,
    task: str,
    agent_type: str,
    tools_used: list[str],
    status: str,            # "completed" | "failed" | "escalated" | "cancelled"
    steps: int,
    positive_signals: int = 0,
    negative_signals: int = 0,
) -> None:
    """
    Store a run outcome as a MuninnDB engram after every agent run.
    Also stores a task→tool-sequence association engram for future injection.
    Stores extra copies of successful sequences to strengthen Hebbian recall.
    """
    try:
        client = get_client()
        tool_seq = ",".join(tools_used[:8])
        task_key = task[:50].strip()
        ts = datetime.now(timezone.utc).isoformat()

        # Net feedback score
        net = positive_signals - (negative_signals * 0.5)
        feedback_label = (
            "strong_positive" if net >= 2 else
            "positive"        if net >= 1 else
            "neutral"         if net >= 0 else
            "negative"
        )

        # ── Outcome engram ────────────────────────────────────────────────────
        concept = f"outcome:{agent_type}:{_slugify(task_key)}"
        content = (
            f"Task: {task_key}\n"
            f"Agent: {agent_type} | Status: {status} | Steps: {steps}\n"
            f"Tools: {tool_seq}\n"
            f"Feedback: {feedback_label} "
            f"(pos={positive_signals}, neg={negative_signals})\n"
            f"Session: {session_id[:8]} | Time: {ts}"
        )
        tags = ["outcome", agent_type, status, feedback_label]
        await client.store(concept, content, tags)

        # ── Association engram: task description ↔ tool sequence ─────────────
        # Repeat on success to raise access-frequency (simulates Hebbian link strength)
        assoc_concept = f"tools_for:{_slugify(task_key)}"
        if status == "completed" and net >= 0:
            assoc_content = (
                f"Successful tool sequence for '{task_key}': {tool_seq}. "
                f"Outcome: {status}. Agent: {agent_type}."
            )
            assoc_tags = ["tool_association", agent_type, "success"]
            # Two stores = stronger recall weight
            await client.store(assoc_concept, assoc_content, assoc_tags)
            await client.store(assoc_concept, assoc_content, assoc_tags)
        else:
            assoc_content = (
                f"Failed/cancelled tool sequence for '{task_key}': {tool_seq}. "
                f"Outcome: {status}. Avoid or add pre-checks."
            )
            assoc_tags = ["tool_association", agent_type, "failure"]
            await client.store(assoc_concept, assoc_content, assoc_tags)

        log.debug("[feedback] outcome stored: %s status=%s", concept, status)
    except Exception as e:
        log.debug("record_outcome failed: %s", e)


async def record_feedback_signal(
    task: str,
    signal: str,
    context: str = "",
) -> None:
    """
    Store an implicit feedback signal.

    Positive signals (plan_approved): stored twice to reinforce recall.
    Negative signals (plan_cancelled, escalation, tool_error, clarification_needed):
    stored once with 'negative' polarity tag.
    """
    polarity = (
        "positive" if signal in _POSITIVE_SIGNALS else
        "negative" if signal in _NEGATIVE_SIGNALS else
        "neutral"
    )
    task_key = task[:50].strip()
    try:
        client = get_client()
        concept = f"feedback:{polarity}:{_slugify(task_key)}"
        content = (
            f"Signal '{signal}' for task '{task_key}'. "
            f"Polarity: {polarity}. Context: {context[:150]}"
        )
        tags = ["feedback", polarity, signal]
        copies = 2 if polarity == "positive" else 1
        for _ in range(copies):
            await client.store(concept, content, tags)
        log.debug("[feedback] signal stored: %s %s", signal, polarity)
    except Exception as e:
        log.debug("record_feedback_signal failed: %s", e)


async def get_past_outcomes(task: str, max_results: int = 5) -> list[dict]:
    """
    Activate MuninnDB with task keywords to find relevant past outcome engrams.
    Returns only engrams tagged 'outcome'.
    """
    try:
        client = get_client()
        # Use task words + "outcome" as context
        words = [w for w in task.lower().split() if len(w) > 3][:6]
        context = words + ["outcome", "tools_for"]
        activations = await client.activate(context, max_results=max_results * 2)
        outcomes = [
            a for a in activations
            if "outcome" in a.get("tags", []) or
               a.get("concept", "").startswith(("outcome:", "tools_for:"))
        ]
        return outcomes[:max_results]
    except Exception as e:
        log.debug("get_past_outcomes failed: %s", e)
        return []


def build_outcome_prompt_section(outcomes: list[dict]) -> str:
    """
    Format past outcome engrams into a RELEVANT PAST OUTCOMES prompt section.
    Returns empty string if no useful outcomes found.
    """
    if not outcomes:
        return ""

    lines = ["RELEVANT PAST OUTCOMES (use to guide tool selection):"]
    for o in outcomes:
        content = o.get("content", "")
        # Extract key fields from stored content
        import re
        task_m  = re.search(r"Task:\s*(.+)", content)
        status_m = re.search(r"Status:\s*(\w+)", content)
        tools_m  = re.search(r"Tools:\s*(.+)", content)

        task_s   = task_m.group(1).strip()   if task_m   else o.get("concept", "")
        status_s = status_m.group(1).strip() if status_m else "unknown"
        tools_s  = tools_m.group(1).strip()  if tools_m  else ""

        icon = "✓" if status_s == "completed" else "✗"
        line = f"  {icon} '{task_s}' → {status_s}"
        if tools_s:
            line += f" using: {tools_s}"
        lines.append(line)

    lines.append("")
    return "\n".join(lines)
