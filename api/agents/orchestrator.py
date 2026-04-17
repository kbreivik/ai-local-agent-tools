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


# ── v2.33.13: contradiction detection in synthesis ─────────────────────────────
# Catch agents concluding "no X were found" when their own tool history
# contains a non-zero result for X earlier in the same task.

_NEGATIVE_CLAIM_PATTERNS = [
    r"\bno\s+(?:error|warning|critical|log|entries?|events?|issues?|problems?)",
    r"\b(?:zero|0)\s+(?:error|warning|critical|log|entries?|events?|issues?)",
    r"\bnot?\s+found",
    r"\bno\s+\w+\s+(?:were|was)?\s*found",
    r"\bnothing\s+(?:found|detected|returned)",
    r"\bno\s+results?",
]


def detect_negative_claim(text: str) -> list:
    """Return list of negative-claim phrases found in the text (case-insensitive)."""
    if not text:
        return []
    found = []
    low = text.lower()
    for pat in _NEGATIVE_CLAIM_PATTERNS:
        for m in re.finditer(pat, low):
            found.append(m.group(0))
    return found


def detect_contradictions(final_text: str, tool_history: list) -> list:
    """
    Check if final_text asserts 'nothing found' while tool_history shows > 0
    results from earlier calls. Returns list of contradictions found.

    tool_history entry shape (from agent loop):
      {"tool": "elastic_search_logs", "args": {...}, "result": {...}, "step": N}
    """
    negatives = detect_negative_claim(final_text)
    if not negatives:
        return []

    # _result_count lives in api.routers.agent — import lazily to avoid cycle
    from api.routers.agent import _result_count

    nonzero_by_tool = {}
    for call in tool_history or []:
        if not isinstance(call, dict):
            continue
        count = _result_count(call.get("result"))
        if count and count > 0:
            tool = call.get("tool", "")
            prev = nonzero_by_tool.get(tool)
            if not prev or count > prev["count"]:
                nonzero_by_tool[tool] = {
                    "count": count,
                    "step": call.get("step"),
                    "args": call.get("args", {}),
                }

    contradictions = []
    for tool, info in nonzero_by_tool.items():
        contradictions.append({
            "tool": tool,
            "step": info["step"],
            "nonzero_count": info["count"],
            "args": info["args"],
            "negative_claim_snippets": negatives[:2],
        })
    return contradictions


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
            return {"verdict": "HALT", "summary": text[:1500]}

    # "error" checked with stricter context
    if re.search(r'\b(error|errors)\b', lower) and not _negation_re.search(lower):
        if re.search(r'\b(tool error|status.*error|error.*status|failed with error|error occurred)\b', lower):
            return {"verdict": "HALT", "summary": text[:1500]}

    # Ambiguous / warning keywords → ASK
    ask_signals = {"warning", "caution", "unknown", "uncertain", "partial"}
    if ask_signals & words:
        return {"verdict": "ASK", "summary": text[:1500]}

    result = {"verdict": "GO", "summary": text[:1500]}

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


def extract_structured_verdict(text: str, step_info: dict) -> dict:
    """Extract verdict with structured context. Alias for verdict_from_text for now."""
    return verdict_from_text(text or "")


# ── Coordinator ───────────────────────────────────────────────────────────────

_COORDINATOR_SYSTEM = """You are a task coordinator for an infrastructure AI system.

Given a task and the result of the last step, decide what to do next.
Respond ONLY with valid JSON — no prose, no markdown, no explanation outside the JSON.

Available next values:
  "done"      — task is fully answered, no more steps needed
  "continue"  — run another tool/step (specify which in context)
  "query"     — need more data before deciding (specify what in context)
  "escalate"  — something went wrong or needs human review

Response format (strict JSON):
{
  "next": "done|continue|query|escalate",
  "reason": "one sentence, max 80 chars",
  "context": "what to tell the next agent step (max 150 chars)",
  "tool_hint": "optional: name of tool the next step should try first"
}"""


def run_coordinator(
    task: str,
    step_summary: str,
    step_verdict: str,
    available_tools: list[str],
    client,
    model: str,
) -> dict:
    """Run a lightweight coordinator to decide the next action.

    Args:
        task:           Original user task
        step_summary:   Compact summary of what the last step found (≤200 chars)
        step_verdict:   GO | ASK | HALT from verdict_from_text()
        available_tools: Names of tools available to the next step
        client:         OpenAI-compat client (LM Studio)
        model:          Model name string

    Returns coordinator decision dict with keys: next, reason, context, tool_hint
    Falls back to {"next": "done", "reason": "coordinator unavailable", ...} on error.
    """
    import json as _json

    # If verdict is already HALT, don't even call the coordinator
    if step_verdict == "HALT":
        return {"next": "escalate", "reason": "step returned HALT",
                "context": step_summary[:150], "tool_hint": ""}

    tools_str = ", ".join(available_tools[:15]) if available_tools else "none"

    user_msg = (
        f"Task: {task[:200]}\n"
        f"Last step result: {step_summary[:200]}\n"
        f"Verdict: {step_verdict}\n"
        f"Available tools: {tools_str}\n\n"
        "What should happen next?"
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _COORDINATOR_SYSTEM},
                {"role": "user",   "content": user_msg + "\n/no_think"},
            ],
            tools=None,
            temperature=0.1,
            max_tokens=200,
        )
        text = response.choices[0].message.content or ""
        # Strip any markdown fences
        text = text.strip().strip("```json").strip("```").strip()
        decision = _json.loads(text)
        # Validate required keys
        if "next" not in decision:
            raise ValueError("missing 'next' key")
        return decision
    except Exception as e:
        import logging as _log
        _log.getLogger(__name__).debug("coordinator failed: %s", e)
        # Safe fallback: if verdict was GO, continue; otherwise done
        return {
            "next": "continue" if step_verdict == "GO" else "done",
            "reason": f"coordinator unavailable ({type(e).__name__})",
            "context": step_summary[:150],
            "tool_hint": "",
        }


def should_use_coordinator(steps: list[dict]) -> bool:
    """Return True if this task warrants coordinator-guided multi-step execution.

    Single-step tasks skip the coordinator (no overhead needed).
    Multi-step tasks or tasks with check/cleanup words use coordinator.
    """
    return len(steps) > 1


# ── v2.34.1: prior-attempts injection for cross-task learning ─────────────────
# Pulls from agent_attempts to give the agent memory of what has already been
# tried on the same entity, so repeat investigations don't re-walk dead ends.

def _coordinator_prior_attempts_enabled() -> bool:
    """Check opt-out setting. Defaults to enabled."""
    try:
        from mcp_server.tools.skills.storage import get_backend
        val = get_backend().get_setting("coordinatorPriorAttemptsEnabled")
        if val is None:
            return True
        return str(val).lower() not in ("false", "0", "no", "off")
    except Exception:
        return True


def fetch_prior_attempts(
    scope_entity: str | None,
    agent_type: str,
    limit: int = 3,
    window_days: int = 7,
) -> list[dict]:
    """
    Fetch up to `limit` most-recent agent_attempts for this scope_entity
    within the last `window_days`, regardless of agent_type (cross-type
    context is useful — investigate informs execute and vice versa).

    Returns empty list when scope_entity is missing or feature is disabled.
    Synchronous: wraps the sync agent_attempts store.
    """
    if not scope_entity:
        return []
    if not _coordinator_prior_attempts_enabled():
        return []
    try:
        from api.db.agent_attempts import get_recent_attempts
    except Exception:
        return []

    try:
        rows = get_recent_attempts(scope_entity, limit=limit) or []
    except Exception:
        return []

    from datetime import datetime, timedelta, timezone
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)

    filtered = []
    for r in rows:
        when = r.get("when") or ""
        try:
            dt = datetime.fromisoformat(when.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            dt = None
        if dt is None or dt >= cutoff:
            filtered.append(r)
    return filtered[:limit]


def format_attempts_for_prompt(attempts: list[dict], agent_type: str) -> str:
    """
    Render the attempts as a system-prompt-ready section.
    Returns '' if the list is empty OR all attempts are same-type and succeeded
    (skip noisy injection for routine ops).

    Input rows follow get_recent_attempts shape:
      {"when", "task_type", "tools" (list), "outcome", "summary"}
    """
    if not attempts:
        return ""

    all_same_and_done = (
        len(attempts) >= 3
        and all(a.get("task_type") == agent_type for a in attempts)
        and all(a.get("outcome") == "done" for a in attempts)
    )
    if all_same_and_done:
        return ""

    n = len(attempts)
    lines = ["═══ PRIOR ATTEMPTS ON THIS ENTITY ═══"]
    lines.append(
        f"{n} previous task{'s' if n != 1 else ''} "
        f"attempted this entity in the last 7 days:"
    )
    lines.append("")

    for a in attempts:
        when = (a.get("when") or "")[:16].replace("T", " ")
        tools = a.get("tools") or []
        tools_count = len(tools)
        tools_str = ", ".join(tools[:6]) if tools else "—"
        if tools_count > 6:
            tools_str += f", ... (+{tools_count - 6} more)"
        objective = (a.get("summary") or "")[:80] or "(no summary)"
        diag = (a.get("summary") or "").strip()
        outcome = a.get("outcome") or "unknown"
        task_type = a.get("task_type") or "?"

        lines.append(f"[{when} UTC] {task_type} — {objective}")
        lines.append(
            f"  outcome: {outcome} · tools({tools_count}): {tools_str}"
        )
        if diag:
            lines.append(f"  diagnosis: \"{diag[:160]}\"")
        else:
            lines.append("  diagnosis: (none emitted)")
        lines.append("")

    lines.append("GUIDANCE:")
    lines.append(
        "  - Do not repeat the exact tool sequence from a done-outcome "
        "attempt unless you have a specific reason. Start from the last diagnosis."
    )
    lines.append(
        "  - If a prior attempt timed out at a specific tool, consider "
        "an alternative first (e.g. log_timeline instead of raw elastic_search_logs)."
    )
    lines.append(
        "  - If a prior diagnosis resolved the problem but it's back, "
        "state that explicitly in your final_answer."
    )

    return "\n".join(lines)
