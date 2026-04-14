"""
DB-backed operation log — stores every WS broadcast line for session replay.
On reconnect the GUI fetches the last N lines and pre-populates OutputPanel.
"""
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)

# In-memory buffer before DB flush (same pattern as api/logger.py)
_queue: asyncio.Queue | None = None
_task: asyncio.Task | None = None
_FLUSH_INTERVAL = 0.2  # seconds

# Max lines stored per session (older lines dropped)
MAX_LINES_PER_SESSION = 500
# Lines returned on reconnect
REPLAY_LINES = 150


_TABLE_VERIFIED: bool = False


async def _ensure_table(conn) -> bool:
    """Verify operation_log table exists. Creates it if missing (safety net)."""
    global _TABLE_VERIFIED
    if _TABLE_VERIFIED:
        return True
    try:
        from sqlalchemy import text as _t
        await conn.execute(_t(
            """CREATE TABLE IF NOT EXISTS operation_log (
                id         TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                type       TEXT NOT NULL,
                content    TEXT,
                metadata   TEXT,
                timestamp  TEXT NOT NULL
            )"""
        ))
        await conn.execute(_t(
            "CREATE INDEX IF NOT EXISTS idx_oplog_session ON operation_log(session_id)"
        ))
        await conn.execute(_t(
            "CREATE INDEX IF NOT EXISTS idx_oplog_ts ON operation_log(timestamp)"
        ))
        _TABLE_VERIFIED = True
        return True
    except Exception as e:
        log.error("operation_log table check failed: %s", e)
        return False


async def _flush_loop():
    from api.db.base import get_engine
    from sqlalchemy import text, bindparam

    # Pre-build the insert statement with explicit bindparams to avoid asyncpg issues
    _INSERT = text(
        "INSERT INTO operation_log "
        "(id, session_id, type, content, metadata, timestamp) "
        "VALUES (:p_id, :p_sid, :p_type, :p_content, :p_meta, :p_ts) "
        "ON CONFLICT (id) DO NOTHING"
    ).bindparams(
        bindparam("p_id"),
        bindparam("p_sid"),
        bindparam("p_type"),
        bindparam("p_content"),
        bindparam("p_meta"),
        bindparam("p_ts"),
    )

    while True:
        await asyncio.sleep(_FLUSH_INTERVAL)
        items: list[dict] = []
        while _queue and not _queue.empty():
            try:
                items.append(_queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        if not items:
            continue
        try:
            engine = get_engine()
            async with engine.begin() as conn:
                await _ensure_table(conn)
                for item in items:
                    try:
                        await conn.execute(_INSERT, {
                            "p_id":      item["id"],
                            "p_sid":     item["session_id"],
                            "p_type":    item["type"],
                            "p_content": item.get("content", "") or "",
                            "p_meta":    item.get("metadata", "{}") or "{}",
                            "p_ts":      item["timestamp"],
                        })
                    except Exception as row_e:
                        log.error("operation_log row insert failed: %s | item=%s",
                                  row_e, {k: str(v)[:80] for k, v in item.items()})
        except Exception as e:
            log.error("operation_log flush error (%d items): %s", len(items), e)


async def ensure_started():
    global _queue, _task
    if _queue is None:
        _queue = asyncio.Queue()
    if _task is None or _task.done():
        _task = asyncio.create_task(_flush_loop())


def store_line(session_id: str, msg_type: str, content: str, metadata: dict | None = None):
    """Non-blocking: queue a line for DB storage."""
    if _queue is None:
        return
    import json
    try:
        _queue.put_nowait({
            "id": str(uuid.uuid4()),
            "session_id": session_id,
            "type": msg_type,
            "content": content,
            "metadata": json.dumps(metadata or {}),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    except asyncio.QueueFull:
        pass


async def get_replay_lines(session_id: str, limit: int = REPLAY_LINES) -> list[dict]:
    """Return the last `limit` lines for a session from DB."""
    try:
        from api.db.base import get_engine
        from sqlalchemy import text
        import json
        engine = get_engine()
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT type, content, metadata, timestamp FROM operation_log "
                    "WHERE session_id = :sid ORDER BY timestamp DESC LIMIT :lim"
                ),
                {"sid": session_id, "lim": limit},
            )
            lines = []
            for row in rows:
                meta = {}
                try:
                    meta = json.loads(row[2]) if row[2] else {}
                except Exception:
                    pass
                lines.append({
                    "type": row[0],
                    "content": row[1],
                    "timestamp": row[3],
                    **meta,
                })
            lines.reverse()  # chronological order
            return lines
    except Exception as e:
        log.debug("get_replay_lines error: %s", e)
        return []


async def trim_session_log(session_id: str, max_lines: int = 500) -> int:
    """Delete oldest lines for a session if count exceeds max_lines.

    Called after session ends to enforce per-session line cap.
    Returns number of rows deleted.
    """
    if not session_id or max_lines <= 0:
        return 0
    try:
        from api.db.base import get_engine
        from sqlalchemy import text
        engine = get_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text("SELECT COUNT(*) FROM operation_log WHERE session_id = :sid"),
                {"sid": session_id},
            )
            total = result.scalar() or 0
            if total <= max_lines:
                return 0
            delete_count = total - max_lines
            await conn.execute(
                text("""
                    DELETE FROM operation_log WHERE id IN (
                        SELECT id FROM operation_log
                        WHERE session_id = :sid
                        ORDER BY timestamp ASC
                        LIMIT :n
                    )
                """),
                {"sid": session_id, "n": delete_count},
            )
            log.debug("operation_log: trimmed %d rows for session %s", delete_count, session_id)
            return delete_count
    except Exception as e:
        log.debug("trim_session_log error: %s", e)
        return 0


async def cleanup_old_logs(retention_days: int = 30) -> int:
    """Delete operation_log rows older than retention_days. Returns rows deleted."""
    if retention_days <= 0:
        return 0
    try:
        from api.db.base import get_engine
        from sqlalchemy import text
        engine = get_engine()
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    f"DELETE FROM operation_log WHERE timestamp < NOW() - INTERVAL '{int(retention_days)} days'"
                )
            )
            deleted = result.rowcount or 0
            if deleted:
                log.info("operation_log cleanup: deleted %d rows older than %d days", deleted, retention_days)
            return deleted
    except Exception as e:
        log.debug("cleanup_old_logs error: %s", e)
        return 0


async def get_active_sessions() -> list[dict]:
    """Return sessions with status=running from operations table."""
    try:
        from api.db.base import get_engine
        from sqlalchemy import text
        engine = get_engine()
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT session_id, id, label, started_at, owner_user "
                    "FROM operations WHERE status = 'running' "
                    "ORDER BY started_at DESC LIMIT 5"
                )
            )
            return [
                {
                    "session_id": r[0], "operation_id": r[1],
                    "label": r[2], "started_at": str(r[3]),
                    "owner_user": r[4],
                }
                for r in rows
            ]
    except Exception as e:
        log.debug("get_active_sessions error: %s", e)
        return []
