# api/agents/orchestrator.py
"""Step-through orchestrator for multi-domain tasks.

build_step_plan() decomposes a task into sequential steps.
Each step specifies an intent + optional domain.
The actual LLM execution happens in agent.py (_run_single_agent_step per step).
Context between steps is a minimal verdict object (~50 tokens), not prose.
"""
import re


# Words that suggest the task wants a pre-check before executing
_CHECK_PREFIXES = frozenset({
    "verify", "check", "ensure", "confirm", "validate", "first",
    "before", "after checking", "make sure",
})


def build_step_plan(task: str) -> list:
    """
    Decompose task into sequential steps.

    Returns list of dicts:
      {"intent": str, "domain": str|None, "task": str, "step": int}

    Single-domain tasks return one step. Tasks with explicit pre-check
    language get an observe step prepended before the execute step.
    """
    from api.agents.router import classify_task, detect_domain

    intent = classify_task(task)
    if intent == "ambiguous":
        intent = "execute"

    domain = detect_domain(task) if intent in ("execute", "action") else None

    words = set(re.findall(r'\b\w+\b', task.lower()))

    # Prepend an observe step when task explicitly asks for a pre-check
    if intent in ("execute", "action") and words & _CHECK_PREFIXES:
        steps = [
            {
                "step":   1,
                "intent": "observe",
                "domain": None,
                "task":   f"Check pre-conditions before: {task}",
            },
            {
                "step":   2,
                "intent": intent,
                "domain": domain,
                "task":   task,
            },
        ]
    else:
        steps = [{"step": 1, "intent": intent, "domain": domain, "task": task}]

    return steps


def format_step_header(step_num: int, total_steps: int, intent: str, domain) -> str:
    """Format a divider line shown in the output panel between steps."""
    domain_part = f"[{domain}]" if domain else ""
    return f"━━ Step {step_num}/{total_steps} · {intent}{domain_part} ━━━━━━━━━━━━━━━━━━━━━━"


def verdict_from_text(text: str) -> dict:
    """
    Extract a minimal verdict from an agent's final output text.

    Returns {"verdict": "GO"|"ASK"|"HALT", "summary": str}
    Used to pass minimal context from one step to the next.
    """
    lower = text.lower()
    words = set(re.findall(r'\b\w+\b', lower))

    # Check for negation patterns that would make halt signals false positives
    # e.g. "no errors", "zero failed", "not degraded", "previously failed"
    _negation_re = re.compile(
        r'\b(no|zero|0|not|never|previously|resolved|fixed|cleared|recovered)\s+'
        r'(error|errors|failed|failure|offline|degraded|unhealthy|critical)',
        re.IGNORECASE,
    )

    # Explicit failure / degraded keywords → HALT (unless negated)
    halt_signals = {"degraded", "critical", "offline", "failed", "unhealthy", "halt"}
    if halt_signals & words:
        # Check if all matches are negated
        matches_in_text = halt_signals & words
        negated = {m for m in matches_in_text if _negation_re.search(lower)}
        if matches_in_text - negated:  # At least one non-negated halt signal
            return {"verdict": "HALT", "summary": text[:300]}

    # "error" is checked separately with stricter context to avoid "no errors" false positives
    if re.search(r'\b(error|errors)\b', lower) and not _negation_re.search(lower):
        # Only flag HALT if "error" appears in a clearly negative context
        if re.search(r'\b(tool error|status.*error|error.*status|failed with error|error occurred)\b', lower):
            return {"verdict": "HALT", "summary": text[:300]}

    # Ambiguous / warning keywords → ASK
    ask_signals = {"warning", "caution", "unknown", "uncertain", "partial"}
    if ask_signals & words:
        return {"verdict": "ASK", "summary": text[:300]}

    return {"verdict": "GO", "summary": text[:300]}
