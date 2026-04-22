"""
Centralised query layer — all database access goes through here.
No raw SQL anywhere else in the codebase.
Handles both Postgres (asyncpg) and SQLite (aiosqlite) transparently.
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, func, update, text, desc, and_
from sqlalchemy.ext.asyncio import AsyncConnection

from api.db.models import (
    operations, tool_calls, status_snapshots,
    audit_log,
)
from api.db.base import DB_BACKEND


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


def _json(val: Any) -> Any:
    """For SQLite: store as JSON string. For Postgres: pass native dict."""
    if DB_BACKEND == "sqlite" and val is not None:
        return json.dumps(val)
    return val


def _row_to_dict(row) -> dict:
    if row is None:
        return {}
    d = dict(row._mapping)
    # Parse JSON strings back to dicts for SQLite
    for k, v in d.items():
        if isinstance(v, str) and v and v[0] in ('{', '['):
            try:
                d[k] = json.loads(v)
            except (json.JSONDecodeError, ValueError):
                pass
        if isinstance(v, datetime):
            d[k] = v.isoformat()
    return d


def _rows(result) -> list[dict]:
    return [_row_to_dict(r) for r in result.fetchall()]


# ── Operations ────────────────────────────────────────────────────────────────

async def create_operation(
    conn: AsyncConnection,
    session_id: str,
    label: str,
    triggered_by: str = "agent",
    model_used: str = "",
    owner_user: str = "admin",
) -> str:
    op_id = _new_id()
    await conn.execute(operations.insert().values(
        id=op_id,
        session_id=session_id,
        label=label,
        started_at=_now(),
        status="running",
        triggered_by=triggered_by,
        model_used=model_used,
        owner_user=owner_user,
    ))
    return op_id


async def complete_operation(
    conn: AsyncConnection,
    operation_id: str,
    status: str,
    total_duration_ms: int = 0,
) -> None:
    await conn.execute(
        update(operations)
        .where(operations.c.id == operation_id)
        .values(completed_at=_now(), status=status, total_duration_ms=total_duration_ms)
    )


async def get_operations(
    conn: AsyncConnection,
    limit: int = 50,
    offset: int = 0,
    status_filter: str = "all",
) -> list[dict]:
    """List operations with tool-call count + agent_type.

    v2.37.2: agent_type is sourced from the first agent_llm_traces step
    for each operation (same pattern as /api/logs/operations/recent),
    since agent_type is not a column on the operations table. COALESCE
    falls back to 'observe' so no row ever shows `?`.
    """
    where = ""
    params: dict = {"lim": limit, "off": offset}
    if status_filter != "all":
        where = "WHERE o.status = :status"
        params["status"] = status_filter

    sql = f"""
        SELECT
            o.id,
            o.session_id,
            o.label,
            o.started_at,
            o.completed_at,
            o.status,
            o.triggered_by,
            o.model_used,
            o.total_duration_ms,
            o.feedback,
            o.feedback_at,
            o.final_answer,
            o.owner_user,
            COALESCE((
                SELECT t.agent_type
                FROM agent_llm_traces t
                WHERE t.operation_id = o.id::text
                  AND t.agent_type IS NOT NULL
                ORDER BY t.step_index ASC
                LIMIT 1
            ), 'observe')                                AS agent_type,
            (
                SELECT COUNT(*)
                FROM tool_calls tc
                WHERE tc.operation_id = o.id
            )                                            AS tool_call_count
        FROM operations o
        {where}
        ORDER BY o.started_at DESC
        LIMIT :lim OFFSET :off
    """

    result = await conn.execute(text(sql), params)
    rows = []
    for r in result:
        rows.append({
            "id": str(r[0]) if r[0] else None,
            "session_id": r[1],
            "label": r[2],
            "task": r[2],
            "started_at": r[3].isoformat() if r[3] else None,
            "completed_at": r[4].isoformat() if r[4] else None,
            "status": r[5],
            "triggered_by": r[6],
            "model_used": r[7],
            "total_duration_ms": r[8],
            "feedback": r[9],
            "feedback_at": r[10],
            "final_answer": r[11],
            "owner_user": r[12],
            "agent_type": r[13] or "observe",
            "tool_call_count": int(r[14]) if r[14] is not None else 0,
        })
    return rows


async def get_operation(conn: AsyncConnection, op_id: str) -> dict:
    result = await conn.execute(select(operations).where(operations.c.id == op_id))
    row = result.fetchone()
    return _row_to_dict(row) if row else {}


async def get_operation_by_session(conn: AsyncConnection, session_id: str) -> dict:
    """Return the most recent operation for a given session_id."""
    result = await conn.execute(
        select(operations)
        .where(operations.c.session_id == session_id)
        .order_by(desc(operations.c.started_at))
        .limit(1)
    )
    row = result.fetchone()
    return _row_to_dict(row) if row else {}


async def set_operation_feedback(
    conn: AsyncConnection, session_id: str, feedback: str
) -> bool:
    now = _now().isoformat()
    r = await conn.execute(
        update(operations)
        .where(operations.c.session_id == session_id)
        .values(feedback=feedback, feedback_at=now)
    )
    return r.rowcount > 0


async def set_operation_final_answer(
    conn: AsyncConnection, session_id: str, final_answer: str
) -> bool:
    r = await conn.execute(
        update(operations)
        .where(operations.c.session_id == session_id)
        .values(final_answer=final_answer)
    )
    return r.rowcount > 0


# ── Tool Calls ────────────────────────────────────────────────────────────────

async def create_tool_call(
    conn: AsyncConnection,
    operation_id: str | None,
    tool_name: str,
    params: dict,
    result: dict,
    status: str,
    model_used: str,
    duration_ms: int,
    error_detail: str | None = None,
) -> str:
    tc_id = _new_id()
    await conn.execute(tool_calls.insert().values(
        id=tc_id,
        operation_id=operation_id,
        tool_name=tool_name,
        params=_json(params),
        result=_json(result),
        status=status,
        model_used=model_used,
        duration_ms=duration_ms,
        timestamp=_now(),
        error_detail=error_detail,
    ))
    return tc_id


async def get_tool_calls(
    conn: AsyncConnection,
    limit: int = 100,
    offset: int = 0,
    status_filter: str = "all",
    tool_filter: str = "",
    session_id: str = "",
    model_filter: str = "",
    date_from: str = "",
    date_to: str = "",
) -> tuple[list[dict], int]:
    q = select(
        tool_calls,
        operations.c.session_id,
        operations.c.label.label("op_label"),
    ).outerjoin(operations, tool_calls.c.operation_id == operations.c.id)

    filters = []
    if status_filter != "all":
        filters.append(tool_calls.c.status == status_filter)
    if tool_filter:
        filters.append(tool_calls.c.tool_name.contains(tool_filter))
    if session_id:
        filters.append(operations.c.session_id == session_id)
    if model_filter:
        filters.append(tool_calls.c.model_used.contains(model_filter))
    if date_from:
        filters.append(tool_calls.c.timestamp >= date_from)
    if date_to:
        filters.append(tool_calls.c.timestamp <= date_to)
    if filters:
        q = q.where(and_(*filters))

    count_q = select(func.count()).select_from(q.subquery())
    total_r = await conn.execute(count_q)
    total = total_r.scalar() or 0

    q = q.order_by(desc(tool_calls.c.timestamp)).limit(limit).offset(offset)
    result = await conn.execute(q)
    return _rows(result), total


async def get_tool_calls_for_operation(
    conn: AsyncConnection, operation_id: str
) -> list[dict]:
    result = await conn.execute(
        select(tool_calls)
        .where(tool_calls.c.operation_id == operation_id)
        .order_by(tool_calls.c.timestamp)
    )
    return _rows(result)


# ── Status Snapshots ──────────────────────────────────────────────────────────

async def create_snapshot(
    conn: AsyncConnection,
    component: str,
    state: dict,
    is_healthy: bool,
) -> str:
    snap_id = _new_id()
    await conn.execute(status_snapshots.insert().values(
        id=snap_id,
        component=component,
        state=_json(state),
        is_healthy=is_healthy,
        timestamp=_now(),
    ))
    return snap_id


async def get_latest_snapshot(conn: AsyncConnection, component: str) -> dict:
    """Return the most recent snapshot for a component, or {} if none."""
    result = await conn.execute(
        select(status_snapshots)
        .where(status_snapshots.c.component == component)
        .order_by(desc(status_snapshots.c.timestamp))
        .limit(1)
    )
    row = result.fetchone()
    return _row_to_dict(row) if row else {}


async def get_snapshots_since(
    conn: AsyncConnection, component: str, since_iso: str, limit: int = 500
) -> list[dict]:
    """Return snapshots for a component since a given ISO timestamp."""
    result = await conn.execute(
        select(status_snapshots)
        .where(
            and_(
                status_snapshots.c.component == component,
                status_snapshots.c.timestamp >= since_iso,
            )
        )
        .order_by(status_snapshots.c.timestamp)
        .limit(limit)
    )
    return _rows(result)


async def get_snapshots(
    conn: AsyncConnection, component: str, limit: int = 20
) -> list[dict]:
    result = await conn.execute(
        select(status_snapshots)
        .where(status_snapshots.c.component == component)
        .order_by(desc(status_snapshots.c.timestamp))
        .limit(limit)
    )
    return _rows(result)


# ── Audit Log ─────────────────────────────────────────────────────────────────

async def create_audit_entry(
    conn: AsyncConnection,
    event_type: str,
    entity_id: str | None,
    entity_type: str | None,
    detail: dict,
    source: str = "api",
) -> str:
    entry_id = _new_id()
    await conn.execute(audit_log.insert().values(
        id=entry_id,
        event_type=event_type,
        entity_id=entity_id,
        entity_type=entity_type,
        detail=_json(detail),
        timestamp=_now(),
        source=source,
    ))
    return entry_id


async def get_audit_entries(
    conn: AsyncConnection,
    event_type: str = "",
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    q = select(audit_log).order_by(desc(audit_log.c.timestamp)).limit(limit).offset(offset)
    if event_type:
        q = q.where(audit_log.c.event_type == event_type)
    result = await conn.execute(q)
    return _rows(result)


# ── Stats ─────────────────────────────────────────────────────────────────────

async def get_stats(conn: AsyncConnection) -> dict:
    # Total operations
    r = await conn.execute(select(func.count()).select_from(operations))
    total_ops = r.scalar() or 0

    # Success rate
    r = await conn.execute(
        select(func.count()).select_from(operations)
        .where(operations.c.status == "completed")
    )
    completed = r.scalar() or 0
    success_rate = round(completed / total_ops * 100, 1) if total_ops else 0.0

    # Avg duration
    r = await conn.execute(
        select(func.avg(operations.c.total_duration_ms))
        .where(operations.c.total_duration_ms.isnot(None))
    )
    avg_dur = round(r.scalar() or 0, 0)

    # Most used tools
    r = await conn.execute(
        select(tool_calls.c.tool_name, func.count().label("cnt"))
        .group_by(tool_calls.c.tool_name)
        .order_by(desc("cnt"))
        .limit(5)
    )
    most_used = [{"tool": row[0], "count": row[1]} for row in r.fetchall()]

    # Local vs external (local = contains "lmstudio" or "qwen")
    r = await conn.execute(
        select(func.count()).select_from(tool_calls)
        .where(tool_calls.c.model_used.isnot(None))
    )
    total_tc = r.scalar() or 0
    r = await conn.execute(
        select(func.count()).select_from(tool_calls)
        .where(
            and_(
                tool_calls.c.model_used.isnot(None),
                tool_calls.c.model_used != "direct",
            )
        )
    )
    model_calls = r.scalar() or 0

    # Unresolved escalations — read from agent_escalations (canonical table)
    try:
        from api.connections import _get_conn as _pg
        _ec = _pg()
        if _ec:
            _cur = _ec.cursor()
            _cur.execute(
                "SELECT COUNT(*) FROM agent_escalations WHERE acknowledged = FALSE"
            )
            unresolved = (_cur.fetchone() or [0])[0]
            _cur.close()
            _ec.close()
        else:
            unresolved = 0
    except Exception:
        unresolved = 0

    # Total tool calls
    r = await conn.execute(select(func.count()).select_from(tool_calls))
    total_calls = r.scalar() or 0

    return {
        "total_operations": total_ops,
        "total_tool_calls": total_calls,
        "success_rate": success_rate,
        "avg_duration_ms": avg_dur,
        "most_used_tools": most_used,
        "local_vs_external_ratio": round(model_calls / total_tc, 2) if total_tc else 0.0,
        "escalations_unresolved": unresolved,
    }
