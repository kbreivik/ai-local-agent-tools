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


# Legacy alias used by existing callers. Accepts model_used kwarg so the
# Operations view gets a reasonable default from insert onwards — v2.36.7
# previously dropped it silently, leaving operations.model_used='' for
# every agent-started run.
async def log_operation(
    session_id: str,
    label: str,
    owner_user: str = "admin",
    model_used: str = "",
) -> str:
    return await log_operation_start(
        session_id, label, owner_user=owner_user, model_used=model_used,
    )


async def log_operation_complete(
    operation_id: str,
    status: str,
    duration_ms: int = 0,
) -> None:
    """Write directly to DB — bypasses queue to guarantee the write completes.

    v2.36.7: also backfills `operations.model_used` from the highest-
    step_index row in `agent_llm_traces` for this op. Covers external-AI
    escalations (v2.36.3 writes a step_index=99999 trace row with the
    external provider's model string) and LM-Studio runs where the
    API-reported model differs from the env-var label. Only overwrites
    when the trace row has a non-empty model string; otherwise the
    insert-time seed value (from run_agent / run_subtask) is preserved.
    """
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
            # v2.36.7 backfill — best-effort, never blocks the caller.
            try:
                from sqlalchemy import text as _t
                await conn.execute(
                    _t(
                        "UPDATE operations "
                        "SET model_used = COALESCE( "
                        "    (SELECT model FROM agent_llm_traces "
                        "     WHERE operation_id = :op "
                        "       AND model IS NOT NULL "
                        "       AND model <> '' "
                        "     ORDER BY step_index DESC "
                        "     LIMIT 1), "
                        "    model_used "
                        ") "
                        "WHERE id = :op"
                    ),
                    {"op": operation_id},
                )
            except Exception as _be:
                log.debug(
                    "model_used backfill for %s skipped: %s",
                    operation_id, _be,
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


async def log_llm_step(
    operation_id: str,
    step_index: int,
    messages_delta: list,
    response_raw: dict,
    system_prompt: str | None = None,
    tools_manifest: list | None = None,
    agent_type: str | None = None,
    is_subagent: bool = False,
    parent_op_id: str | None = None,
    temperature: float | None = None,
    model: str | None = None,
    provider: str = "lm_studio",
) -> None:
    """Persist one LLM round-trip. system_prompt + tools_manifest are stored
    ONCE on step_index=0; subsequent steps reference operation_id.

    Feature-flagged via AGENT_LLM_TRACE_ENABLED (default: true). Never raises.
    """
    import os as _os
    if _os.environ.get("AGENT_LLM_TRACE_ENABLED", "true").lower() not in (
        "1", "true", "yes"
    ):
        return
    try:
        from api.db import llm_traces
        if step_index == 0 and system_prompt is not None:
            llm_traces.write_system_prompt(
                operation_id=operation_id,
                system_prompt=system_prompt,
                tools_manifest=tools_manifest,
            )
        llm_traces.write_trace_step(
            operation_id=operation_id,
            step_index=step_index,
            messages_delta=messages_delta,
            response_raw=response_raw,
            agent_type=agent_type,
            is_subagent=is_subagent,
            parent_op_id=parent_op_id,
            temperature=temperature,
            model=model,
            provider=provider,
        )
    except Exception as e:
        log.debug("log_llm_step failed: %s", e)


async def log_llm_exchange(
    operation_id,
    step,
    messages,
    response_text,
    tool_calls,
    prompt_tokens,
    completion_tokens,
    model,
    duration_ms,
):
    """Store full LLM input/output for a single step. Opt-in via LOG_LLM_EXCHANGES=1."""
    _enqueue(
        q.create_tool_call,
        operation_id=operation_id,
        tool_name="_llm_exchange",
        params={
            "step": step,
            "message_count": len(messages),
            "messages": messages,
            "model": model,
        },
        result={
            "status": "ok",
            "data": {
                "response_text": response_text[:2000],
                "tool_calls_requested": [tc.get("function", {}).get("name") for tc in tool_calls] if tool_calls else [],
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        },
        status="ok",
        model_used=model,
        duration_ms=duration_ms,
        error_detail=None,
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


async def set_operation_final_answer_append(session_id: str, addition: str) -> None:
    """v2.36.8 — append text to an operation's final_answer field.

    Direct write (not queued) so the render-tool output is visible to the
    operator immediately. The write is small and infrequent compared to
    tool_call rows.
    """
    if not addition or not addition.strip():
        return
    try:
        from sqlalchemy import text as _t
        async with get_engine().begin() as conn:
            existing = await conn.execute(
                _t(
                    "SELECT final_answer FROM operations "
                    "WHERE session_id = :sid "
                    "ORDER BY started_at DESC LIMIT 1"
                ),
                {"sid": session_id},
            )
            row = existing.fetchone()
            if not row:
                return
            current = (row[0] or "").rstrip()
            sep = "\n\n" if current else ""
            new_val = current + sep + addition
            await conn.execute(
                _t(
                    "UPDATE operations SET final_answer = :val "
                    "WHERE session_id = :sid"
                ),
                {"val": new_val, "sid": session_id},
            )
    except Exception as e:
        log.error("set_operation_final_answer_append failed: %s", e)


async def set_operation_final_answer_prepend(session_id: str, prefix: str) -> None:
    """v2.36.9 — prepend text ABOVE the existing final_answer.

    Used by the end-of-run cleanup path when the render tool appended
    a table mid-run. The cleanup needs to place the agent's caption
    ABOVE the table, not below it, for correct reading order.

    Mirrors set_operation_final_answer_append: direct write, two-newline
    separator between prefix and existing content, no-op when prefix is
    empty, no-op when the operation row doesn't exist yet.
    """
    if not prefix or not prefix.strip():
        return
    try:
        from sqlalchemy import text as _t
        async with get_engine().begin() as conn:
            existing = await conn.execute(
                _t(
                    "SELECT final_answer FROM operations "
                    "WHERE session_id = :sid "
                    "ORDER BY started_at DESC LIMIT 1"
                ),
                {"sid": session_id},
            )
            row = existing.fetchone()
            if not row:
                return
            current = (row[0] or "").lstrip()
            sep = "\n\n" if current else ""
            new_val = prefix.rstrip() + sep + current
            await conn.execute(
                _t(
                    "UPDATE operations SET final_answer = :val "
                    "WHERE session_id = :sid"
                ),
                {"val": new_val, "sid": session_id},
            )
    except Exception as e:
        log.error("set_operation_final_answer_prepend failed: %s", e)


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
