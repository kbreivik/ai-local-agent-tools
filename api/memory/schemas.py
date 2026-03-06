"""
Typed helpers for constructing engram concept/content strings.

All helpers return (concept: str, content: str, tags: list[str]) tuples
ready to pass to MuninnClient.store().
"""
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# ── Operational memory ─────────────────────────────────────────────────────────

def tool_execution_engram(
    tool_name: str,
    params: dict,
    result: dict,
    status: str,
    duration_ms: int,
) -> tuple[str, str, list[str]]:
    concept = f"tool_call:{tool_name}"
    param_summary = ", ".join(f"{k}={v!r}" for k, v in list(params.items())[:4])
    content = (
        f"Tool '{tool_name}' executed at {_now_iso()}. "
        f"Params: {param_summary or 'none'}. "
        f"Status: {status}. Duration: {duration_ms}ms. "
        f"Result summary: {str(result)[:200]}"
    )
    tags = ["tool_call", tool_name, status]
    return concept, content, tags


def status_event_engram(
    component: str,
    health: str,
    message: str = "",
    details: dict | None = None,
) -> tuple[str, str, list[str]]:
    concept = f"infra_status:{component}"
    detail_str = ""
    if details:
        interesting = {k: v for k, v in details.items()
                       if k not in ("nodes", "services", "brokers", "topics")}
        detail_str = " | ".join(f"{k}={v}" for k, v in list(interesting.items())[:5])
    content = (
        f"{component} health={health} at {_now_iso()}. "
        + (f"Message: {message}. " if message else "")
        + (f"Details: {detail_str}" if detail_str else "")
    )
    tags = ["infra", component, health]
    return concept, content, tags


def escalation_engram(
    reason: str,
    context: dict,
    operation_id: str | None = None,
) -> tuple[str, str, list[str]]:
    concept = "escalation:human_review_needed"
    content = (
        f"Escalation at {_now_iso()}: {reason}. "
        f"Context: {str(context)[:300]}"
        + (f" Operation: {operation_id}" if operation_id else "")
    )
    tags = ["escalation", "alert"]
    return concept, content, tags


# ── Documentation memory ──────────────────────────────────────────────────────

def doc_engram(
    topic: str,
    content: str,
    source: str,
    subtopic: str = "",
) -> tuple[str, str, list[str]]:
    concept = f"doc:{topic}" + (f":{subtopic}" if subtopic else "")
    tags = ["doc", topic, source]
    if subtopic:
        tags.append(subtopic)
    return concept, content, tags
