"""Async logger — writes every tool call and agent decision to SQLite."""
import json
from datetime import datetime, timezone

from api.db import get_db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def log_operation(session_id: str, label: str) -> int:
    """Create an operation record. Returns operation_id."""
    db = await get_db()
    try:
        cur = await db.execute(
            "INSERT INTO operations (session_id, label, started_at, status) VALUES (?, ?, ?, ?)",
            (session_id, label, _now(), "running"),
        )
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()


async def complete_operation(operation_id: int, status: str = "completed"):
    db = await get_db()
    try:
        await db.execute(
            "UPDATE operations SET completed_at=?, status=? WHERE id=?",
            (_now(), status, operation_id),
        )
        await db.commit()
    finally:
        await db.close()


async def log_tool_call(
    operation_id: int,
    tool_name: str,
    params: dict,
    result: dict,
    model_used: str,
    duration_ms: int,
) -> int:
    status = result.get("status", "error") if isinstance(result, dict) else "error"
    db = await get_db()
    try:
        cur = await db.execute(
            """INSERT INTO tool_calls
               (operation_id, tool_name, params, result, status, model_used, duration_ms, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                operation_id,
                tool_name,
                json.dumps(params),
                json.dumps(result),
                status,
                model_used,
                duration_ms,
                _now(),
            ),
        )
        await db.commit()
        return cur.lastrowid
    finally:
        await db.close()


async def log_status_snapshot(component: str, state: dict):
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO status_snapshots (component, state_json, timestamp) VALUES (?, ?, ?)",
            (component, json.dumps(state), _now()),
        )
        await db.commit()
    finally:
        await db.close()
