"""
Memory hooks — fire-and-forget async callbacks wired into key agent events.

after_tool_call()       → store significant tool executions as operational memory
after_status_snapshot() → store health-change events (degradation / recovery)
before_tool_call()      → retrieve relevant context from memory for agent injection
"""
import asyncio
import logging
from typing import Any

from api.memory.client import get_client
from api.memory.schemas import tool_execution_engram, status_event_engram

log = logging.getLogger(__name__)

# Tools that are too noisy to store in memory
_SKIP_TOOLS = {"get_status", "get_health", "ping"}

# Only store health changes (avoid spamming "healthy" every 30s)
_prev_status_health: dict[str, str] = {}


def _fire(coro) -> None:
    """Schedule a coroutine without blocking the caller."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(coro)
        else:
            loop.run_until_complete(coro)
    except Exception as e:
        log.debug("Memory hook fire failed: %s", e)


# ── Public hooks ──────────────────────────────────────────────────────────────

def after_tool_call(
    tool_name: str,
    params: dict,
    result: Any,
    status: str,
    duration_ms: int,
) -> None:
    """Store notable tool executions as operational engrams (non-blocking)."""
    if tool_name in _SKIP_TOOLS:
        return
    if not isinstance(result, dict):
        result = {"raw": str(result)}

    async def _store():
        try:
            concept, content, tags = tool_execution_engram(
                tool_name, params, result, status, duration_ms
            )
            client = get_client()
            await client.store(concept, content, tags)
        except Exception as e:
            log.debug("after_tool_call memory hook error: %s", e)

    _fire(_store())


def after_status_snapshot(
    component: str,
    state: dict,
) -> None:
    """Store health transition events (only on change) as infrastructure engrams."""
    health = state.get("health", "unknown")
    prev = _prev_status_health.get(component)
    _prev_status_health[component] = health

    # Only record on change, or first observation
    if prev == health and prev is not None:
        return

    async def _store():
        try:
            message = state.get("message", "")
            concept, content, tags = status_event_engram(component, health, message, state)
            client = get_client()
            await client.store(concept, content, tags)
        except Exception as e:
            log.debug("after_status_snapshot memory hook error: %s", e)

    _fire(_store())


def after_elastic_error(
    service: str,
    error_message: str,
    log_timestamp: str = "",
) -> None:
    """Store Elastic-sourced error events as operational memory engrams (non-blocking)."""
    async def _store():
        try:
            client = get_client()
            concept = f"log_error:{service}"
            content = (
                f"Error in '{service}' at {log_timestamp or 'unknown time'}: {error_message[:200]}"
            )
            await client.store(concept, content,
                               ["log_error", "elasticsearch", service])
        except Exception as e:
            log.debug("after_elastic_error memory hook error: %s", e)

    _fire(_store())


async def after_correlation(
    operation_id: str,
    anomalies: list[str],
    error_count: int,
    error_summary: str,
    operation_label: str = "",
) -> None:
    """
    Store correlation results as MuninnDB engrams.
    Fires 'repeated error' trigger if anomalies found.
    """
    if not anomalies and error_count == 0:
        return
    try:
        client = get_client()
        concept = f"correlation:{operation_id[:8]}"
        content = (
            f"Operation '{operation_label}' had {error_count} correlated log errors. "
            f"Anomalies: {'; '.join(anomalies)}. {error_summary[:200]}"
        )
        tags = ["correlation", "anomaly"] if anomalies else ["correlation"]
        await client.store(concept, content, tags)

        # Check repeated error trigger
        if anomalies:
            await _check_repeated_error_trigger(operation_label, anomalies, client)
    except Exception as e:
        log.debug("after_correlation memory hook error: %s", e)


async def _check_repeated_error_trigger(
    operation_label: str, anomalies: list[str], client
) -> None:
    """
    Fires when error + upgrade engrams co-activate strongly.
    Escalates if a repeated known-bad pattern is detected.
    """
    try:
        context = [operation_label] + anomalies[:2]
        activations = await client.activate(context, max_results=5)

        # Look for previous upgrade_result failures for the same context
        failure_engrams = [
            a for a in activations
            if "upgrade_result" in a.get("concept", "")
            and "failed" in a.get("content", "").lower()
        ]

        if len(failure_engrams) >= 1:
            from api.alerts import fire_alert
            svc_hint = operation_label.replace("upgrade ", "").strip()
            fire_alert(
                component=svc_hint or "infrastructure",
                severity="critical",
                message=(
                    f"Repeated error pattern: '{operation_label}' matches {len(failure_engrams)} "
                    f"past failure(s). Memory: {[f.get('concept') for f in failure_engrams[:2]]}. "
                    f"Recommend escalation."
                ),
                source="memory_trigger",
            )
    except Exception as e:
        log.debug("Repeated error trigger check failed: %s", e)


async def before_tool_call(
    tool_name: str,
    params: dict,
) -> list[dict]:
    """
    Retrieve memory context relevant to this tool call.
    Returns list of activation dicts (may be empty).
    Called in the agent loop before dispatching the tool.
    """
    if tool_name in _SKIP_TOOLS:
        return []
    try:
        context_terms = [tool_name]
        # Add key param values as context hints
        for v in list(params.values())[:3]:
            if isinstance(v, str) and len(v) < 100:
                context_terms.append(v)
        client = get_client()
        return await client.activate(context_terms, max_results=3)
    except Exception as e:
        log.debug("before_tool_call memory hook error: %s", e)
        return []
