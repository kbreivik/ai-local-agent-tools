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

# Words indicating a cleanup/destructive disk operation
_CLEANUP_WORDS = frozenset({
    "prune", "vacuum", "autoremove", "clean", "purge",
    "remove", "delete", "wipe", "free", "reclaim",
})


def build_step_plan(task: str) -> list:
    """
    Decompose task into sequential steps.

    Returns list of dicts:
      {"intent": str, "domain": str|None, "task": str, "step": int}

    Single-domain tasks return one step. Tasks with explicit pre-check
    language or cleanup keywords get observe steps around the execute step.
    """
    from api.agents.router import classify_task, detect_domain

    intent = classify_task(task)
    if intent == "ambiguous":
        intent = "execute"

    domain = detect_domain(task) if intent in ("execute", "action") else None

    words = set(re.findall(r'\b\w+\b', task.lower()))
    is_cleanup = bool(words & _CLEANUP_WORDS)
    has_precheck = bool(words & _CHECK_PREFIXES)

    if intent in ("execute", "action"):
        steps = []

        # Pre-check step: gather baseline before cleanup, or verify pre-conditions
        if has_precheck or is_cleanup:
            steps.append({
                "intent": "observe",
                "domain": domain,
                "task": (
                    f"Gather baseline before: {task}. "
                    "Report current disk usage, Docker df, and what will be affected. "
                    "Output structured summary: current_state={{disk_used, docker_images_gb, "
                    "docker_volumes_gb, dangling_count}}"
                ) if is_cleanup else f"Check pre-conditions before: {task}",
            })

        # Main execute step
        steps.append({
            "intent": intent,
            "domain": domain,
            "task": task,
        })

        # Verify step after cleanup operations
        if is_cleanup:
            steps.append({
                "intent": "observe",
                "domain": domain,
                "task": (
                    f"Verify result of: {task}. "
                    "Report current disk usage and compare to baseline if available. "
                    "Output: after_state={{disk_used, docker_images_gb, reclaimed_gb}}. "
                    "State clearly how much space was reclaimed."
                ),
            })
    else:
        steps = [{"intent": intent, "domain": domain, "task": task}]

    # Number steps
    for i, s in enumerate(steps):
        s["step"] = i + 1

    return steps


def format_step_header(step_num: int, total_steps: int, intent: str, domain) -> str:
    """Format a divider line shown in the output panel between steps."""
    domain_part = f"[{domain}]" if domain else ""
    return f"━━ Step {step_num}/{total_steps} · {intent}{domain_part} ━━━━━━━━━━━━━━━━━━━━━━"


def verdict_from_text(text: str) -> dict:
    """
    Extract a minimal verdict from an agent's final output text.

    Returns {"verdict": "GO"|"ASK"|"HALT", "summary": str, "state": dict|None}
    Used to pass minimal context from one step to the next.
    """
    lower = text.lower()
    words = set(re.findall(r'\b\w+\b', lower))

    # Check for negation patterns that would make halt signals false positives
    _negation_re = re.compile(
        r'\b(no|zero|0|not|never|previously|resolved|fixed|cleared|recovered)\s+'
        r'(error|errors|failed|failure|offline|degraded|unhealthy|critical)',
        re.IGNORECASE,
    )

    # Explicit failure / degraded keywords → HALT (unless negated)
    halt_signals = {"degraded", "critical", "offline", "failed", "unhealthy", "halt"}
    if halt_signals & words:
        matches_in_text = halt_signals & words
        negated = {m for m in matches_in_text if _negation_re.search(lower)}
        if matches_in_text - negated:
            return {"verdict": "HALT", "summary": text[:300]}

    # "error" checked with stricter context
    if re.search(r'\b(error|errors)\b', lower) and not _negation_re.search(lower):
        if re.search(r'\b(tool error|status.*error|error.*status|failed with error|error occurred)\b', lower):
            return {"verdict": "HALT", "summary": text[:300]}

    # Ambiguous / warning keywords → ASK
    ask_signals = {"warning", "caution", "unknown", "uncertain", "partial"}
    if ask_signals & words:
        return {"verdict": "ASK", "summary": text[:300]}

    result = {"verdict": "GO", "summary": text[:300]}

    # Extract structured state for passing between steps (observe → execute → verify)
    state = {}
    for key in ("current_state", "after_state", "disk_used", "reclaimed_gb",
                "docker_images_gb", "docker_volumes_gb", "dangling_count"):
        m = re.search(rf'{key}[=:]\s*([0-9.]+\s*(?:GB|MB|TB|%)?)', text, re.IGNORECASE)
        if m:
            state[key] = m.group(1).strip()
    if state:
        result["state"] = state

    return result
