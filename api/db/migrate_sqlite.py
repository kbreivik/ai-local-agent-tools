"""
One-time migration: copy data from SQLite → Postgres.

Usage:
    DATABASE_URL=postgresql+asyncpg://... python -m api.db.migrate_sqlite

Idempotent — skips rows that already exist by UUID (upsert on conflict).
Source SQLite path is read from SQLITE_PATH or DB_PATH env vars (same as base.py).
"""
import asyncio
import json
import logging
import os
from pathlib import Path

import aiosqlite

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("migrate")

_PROJECT_ROOT = Path(__file__).parent.parent.parent  # api/db/migrate_sqlite.py → api/db/ → api/ → project root
_SQLITE_PATH = Path(os.environ.get(
    "SQLITE_PATH",
    os.environ.get("DB_PATH", str(_PROJECT_ROOT / "data" / "hp1_agent.db")),
))


def _safe_json(v):
    if v is None:
        return None
    if isinstance(v, str):
        try:
            return json.loads(v)
        except (json.JSONDecodeError, ValueError):
            return {"raw": v}
    return v


async def _migrate_operations(src_conn, dst_conn):
    rows = await src_conn.execute_fetchall("SELECT * FROM operations")
    count = 0
    for r in rows:
        row = dict(r)
        try:
            await dst_conn.execute(
                """INSERT INTO operations (id, session_id, label, started_at, completed_at, status, triggered_by, model_used, total_duration_ms)
                   VALUES (:id, :session_id, :label, :started_at, :completed_at, :status, :triggered_by, :model_used, :total_duration_ms)
                   ON CONFLICT (id) DO NOTHING""",
                {
                    "id": str(row.get("id")),
                    "session_id": row.get("session_id", ""),
                    "label": row.get("label"),
                    "started_at": row.get("started_at"),
                    "completed_at": row.get("completed_at"),
                    "status": row.get("status", "completed"),
                    "triggered_by": row.get("triggered_by"),
                    "model_used": row.get("model_used"),
                    "total_duration_ms": row.get("total_duration_ms"),
                },
            )
            count += 1
        except Exception as e:
            log.warning("operations row %s skipped: %s", row.get("id"), e)
    log.info("operations: %d rows migrated", count)
    return count


async def _migrate_tool_calls(src_conn, dst_conn):
    rows = await src_conn.execute_fetchall("SELECT * FROM tool_calls")
    count = 0
    for r in rows:
        row = dict(r)
        try:
            await dst_conn.execute(
                """INSERT INTO tool_calls (id, operation_id, tool_name, params, result, status, model_used, duration_ms, timestamp, error_detail)
                   VALUES (:id, :operation_id, :tool_name, :params, :result, :status, :model_used, :duration_ms, :timestamp, :error_detail)
                   ON CONFLICT (id) DO NOTHING""",
                {
                    "id": str(row.get("id")),
                    "operation_id": str(row["operation_id"]) if row.get("operation_id") else None,
                    "tool_name": row.get("tool_name", ""),
                    "params": json.dumps(_safe_json(row.get("params"))),
                    "result": json.dumps(_safe_json(row.get("result"))),
                    "status": row.get("status", "ok"),
                    "model_used": row.get("model_used"),
                    "duration_ms": row.get("duration_ms"),
                    "timestamp": row.get("timestamp"),
                    "error_detail": row.get("error_detail"),
                },
            )
            count += 1
        except Exception as e:
            log.warning("tool_calls row %s skipped: %s", row.get("id"), e)
    log.info("tool_calls: %d rows migrated", count)
    return count


async def _migrate_snapshots(src_conn, dst_conn):
    rows = await src_conn.execute_fetchall("SELECT * FROM status_snapshots")
    count = 0
    for r in rows:
        row = dict(r)
        try:
            state = _safe_json(row.get("state_json") or row.get("state"))
            await dst_conn.execute(
                """INSERT INTO status_snapshots (id, component, state, is_healthy, timestamp)
                   VALUES (:id, :component, :state, :is_healthy, :timestamp)
                   ON CONFLICT (id) DO NOTHING""",
                {
                    "id": str(row.get("id")),
                    "component": row.get("component", ""),
                    "state": json.dumps(state),
                    "is_healthy": row.get("is_healthy", True),
                    "timestamp": row.get("timestamp"),
                },
            )
            count += 1
        except Exception as e:
            log.warning("status_snapshots row %s skipped: %s", row.get("id"), e)
    log.info("status_snapshots: %d rows migrated", count)
    return count


async def run_migration():
    if not _SQLITE_PATH.exists():
        log.error("SQLite file not found: %s", _SQLITE_PATH)
        return

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        log.error("DATABASE_URL not set — cannot connect to Postgres")
        return

    log.info("Source: %s", _SQLITE_PATH)
    log.info("Target: %s", database_url.split("@")[-1])  # hide credentials

    # Run migrations on target DB first to ensure schema exists
    from api.db.base import get_engine
    from api.db.migrations import run_migrations
    engine = get_engine()
    await run_migrations(engine)

    async with aiosqlite.connect(_SQLITE_PATH) as src:
        src.row_factory = aiosqlite.Row
        async with engine.begin() as dst:
            from sqlalchemy import text
            ops   = await _migrate_operations(src, dst)
            tcs   = await _migrate_tool_calls(src, dst)
            snaps = await _migrate_snapshots(src, dst)
            log.info("Migration complete: %d ops, %d tool calls, %d snapshots", ops, tcs, snaps)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_migration())
