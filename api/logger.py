"""
Async logger — thin async API over api.db.queries.

Batch-buffered writes: items queue in memory, flushed every 100ms or when
threshold is reached. Immediate writes only where the caller needs a return value
(log_operation_start). Never blocks the agent loop.
"""
import asyncio
import logging
from typing import Any

from api.db.base import get_engine
from api.db import queries as q

log = logging.getLogger(__name__)

_FLUSH_INTERVAL = 0.10   # seconds
_FLUSH_THRESHOLD = 10    # items before an early flush

_queue: asyncio.Queue = asyncio.Queue()
_flush_task: asyncio.Task | None = None


# ── Background flush loop ─────────────────────────────────────────────────────

async def _drain() -> None:
    items = []
    while not _queue.empty():
        items.append(_queue.get_nowait())
        if len(items) >= _FLUSH_THRESHOLD:
            break
    if not items:
        return
    try:
        async with get_engine().begin() as conn:
            for fn, kwargs in items:
                try:
                    await fn(conn, **kwargs)
                except Exception as e:
                    log.warning("Logger write failed (%s): %s", fn.__name__, e)
    except Exception as e:
        log.error("Logger DB connection failed: %s", e)


async def _flush_loop() -> None:
    while True:
        await asyncio.sleep(_FLUSH_INTERVAL)
        await _drain()


async def ensure_started() -> None:
    """Start the background flush task. Called once from lifespan."""
    global _flush_task
    if _flush_task is None or _flush_task.done():
        _flush_task = asyncio.create_task(_flush_loop())


async def flush_now() -> None:
    """Drain queue immediately (call on shutdown)."""
    await _drain()


def _enqueue(fn, **kwargs) -> None:
    _queue.put_nowait((fn, kwargs))


# ── Public write API ──────────────────────────────────────────────────────────

async def log_operation_start(
    session_id: str,
    label: str,
    triggered_by: str = "api",
    model_used: str = "",
    owner_user: str = "admin",
) -> str:
    """Create operation record immediately. Returns UUID str (caller needs the ID)."""
    async with get_engine().begin() as conn:
        return await q.create_operation(
            conn, session_id, label, triggered_by, model_used, owner_user=owner_user
        )


# Legacy alias used by existing callers
async def log_operation(session_id: str, label: str, owner_user: str = "admin") -> str:
    return await log_operation_start(session_id, label, owner_user=owner_user)


async def log_operation_complete(
    operation_id: str,
    status: str,
    duration_ms: int = 0,
) -> None:
    """Write operation completion directly to DB — no queue, guaranteed write."""
    if not operation_id:
        return
    try:
        async with get_engine().begin() as conn:
            await q.complete_operation(
                conn,
                operation_id=operation_id,
                status=status,
                total_duration_ms=duration_ms,
            )
    except Exception as e:
        log.error("log_operation_complete failed for %s: %s", operation_id, e)


# Legacy alias
async def complete_operation(operation_id: str, status: str = "completed") -> None:
    await log_operation_complete(operation_id, status)


async def log_tool_call(
    operation_id: str | None,
    tool_name: str,
    params: dict,
    result: Any,
    model_used: str,
    duration_ms: int,
    status: str = "",
    error_detail: str | None = None,
) -> None:
    if not isinstance(result, dict):
        result = {"raw": str(result)}
    resolved_status = status or result.get("status", "error")
    _enqueue(
        q.create_tool_call,
        operation_id=operation_id,
        tool_name=tool_name,
        params=params,
        result=result,
        status=resolved_status,
        model_used=model_used,
        duration_ms=duration_ms,
        error_detail=error_detail,
    )


async def log_status_snapshot(
    component: str,
    state: dict,
    is_healthy: bool = True,
) -> None:
    healthy = state.get("status") not in ("error", "failed", "degraded") if isinstance(state, dict) else is_healthy
    _enqueue(q.create_snapshot, component=component, state=state, is_healthy=healthy)


async def log_escalation(
    operation_id: str | None,
    tool_call_id: str | None,
    reason: str,
    context: dict,
) -> None:
    _enqueue(
        q.create_escalation,
        operation_id=operation_id,
        tool_call_id=tool_call_id,
        reason=reason,
        context=context,
    )


async def set_operation_feedback(session_id: str, feedback: str) -> None:
    """Update feedback field on operation by session_id (immediate write)."""
    async with get_engine().begin() as conn:
        await q.set_operation_feedback(conn, session_id, feedback)


async def set_operation_final_answer(session_id: str, final_answer: str) -> None:
    """Store agent final answer on operation by session_id (enqueued)."""
    _enqueue(q.set_operation_final_answer, session_id=session_id, final_answer=final_answer)


async def log_audit(
    event_type: str,
    entity_id: str | None = None,
    entity_type: str | None = None,
    detail: dict | None = None,
    source: str = "api",
) -> None:
    _enqueue(
        q.create_audit_entry,
        event_type=event_type,
        entity_id=entity_id,
        entity_type=entity_type,
        detail=detail or {},
        source=source,
    )
