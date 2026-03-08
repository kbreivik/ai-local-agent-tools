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


async def _flush_loop():
    from api.db.base import get_engine
    from sqlalchemy import text

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
                for item in items:
                    await conn.execute(
                        text(
                            "INSERT INTO operation_log (id, session_id, type, content, metadata, timestamp) "
                            "VALUES (:id, :session_id, :type, :content, :metadata, :timestamp)"
                        ),
                        item,
                    )
        except Exception as e:
            log.debug("operation_log flush error: %s", e)


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
