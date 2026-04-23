"""
PG-native memory client — drop-in replacement for MuninnClient.

Uses pg_engrams table with tsvector + access_count Hebbian scoring.
Activated when memoryBackend='postgres' setting.
"""
from __future__ import annotations
import json
import logging
import uuid
from datetime import datetime, timezone
from math import log as _log

log = logging.getLogger(__name__)


def _is_pg() -> bool:
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        if conn:
            conn.close()
            return True
    except Exception:
        pass
    return False


def _conn():
    from api.connections import _get_conn
    return _get_conn()


class PgMemoryClient:
    """PG-native engram store with tsvector keyword activation."""

    async def store(self, concept: str, content: str,
                    tags: list[str] | None = None) -> str | None:
        """Insert or strengthen an engram. If concept already exists,
        append content variation and increment access_count."""
        try:
            conn = _conn()
            cur = conn.cursor()
            # Check if concept already exists
            cur.execute(
                "SELECT id, access_count FROM pg_engrams WHERE concept = %s LIMIT 1",
                (concept,)
            )
            existing = cur.fetchone()
            if existing:
                # Strengthen — increment access_count (Hebbian)
                engram_id = existing[0]
                cur.execute(
                    """UPDATE pg_engrams
                       SET access_count = access_count + 1,
                           last_accessed_at = NOW(),
                           content = %s
                       WHERE id = %s""",
                    (content, engram_id)
                )
                conn.commit()
                cur.close(); conn.close()
                return str(engram_id)
            else:
                engram_id = str(uuid.uuid4())
                cur.execute(
                    """INSERT INTO pg_engrams (id, concept, content, tags)
                       VALUES (%s, %s, %s, %s)""",
                    (engram_id, concept, content, tags or [])
                )
                conn.commit()
                cur.close(); conn.close()
                return engram_id
        except Exception as e:
            log.debug("PgMemoryClient.store failed: %s", e)
            return None

    async def activate(self, context: list[str],
                       max_results: int = 5) -> list[dict]:
        """Retrieve engrams by keyword overlap, ranked by Hebbian score.

        Score = ts_rank * log(access_count + 1)
        — higher access_count means the engram has been useful repeatedly.
        """
        if not context:
            return []
        try:
            conn = _conn()
            cur = conn.cursor()
            query = " | ".join(
                w.replace("'", "").strip()
                for w in context
                if len(w) > 2
            )
            if not query:
                return []
            cur.execute(
                """
                SELECT id, concept, content, tags, access_count, created_at,
                       ts_rank(content_tsv, to_tsquery('english', %s)) AS rank
                FROM pg_engrams
                WHERE content_tsv @@ to_tsquery('english', %s)
                ORDER BY ts_rank(content_tsv, to_tsquery('english', %s))
                         * ln(access_count::float + 2) DESC
                LIMIT %s
                """,
                (query, query, query, max_results * 2)
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]

            # Bump access_count for retrieved engrams (Hebbian strengthening)
            ids = [r["id"] for r in rows]
            if ids:
                cur.execute(
                    "UPDATE pg_engrams SET access_count = access_count + 1, "
                    "last_accessed_at = NOW() WHERE id = ANY(%s)",
                    (ids,)
                )
                conn.commit()

            cur.close(); conn.close()

            # Shape to match MuninnClient output
            return [
                {
                    "id":      str(r["id"]),
                    "concept": r["concept"],
                    "content": r["content"],
                    "tags":    r["tags"] or [],
                }
                for r in rows[:max_results]
            ]
        except Exception as e:
            log.debug("PgMemoryClient.activate failed: %s", e)
            return []

    async def search(self, query: str, limit: int = 20) -> list[dict]:
        try:
            conn = _conn()
            cur = conn.cursor()
            cur.execute(
                """SELECT id, concept, content, tags, access_count
                   FROM pg_engrams
                   WHERE content ILIKE %s OR concept ILIKE %s
                   ORDER BY access_count DESC, created_at DESC
                   LIMIT %s""",
                (f"%{query}%", f"%{query}%", limit)
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            cur.close(); conn.close()
            return [{"id": str(r["id"]), "concept": r["concept"],
                     "content": r["content"], "tags": r["tags"] or []}
                    for r in rows]
        except Exception as e:
            log.debug("PgMemoryClient.search failed: %s", e)
            return []

    async def recent(self, limit: int = 20) -> list[dict]:
        try:
            conn = _conn()
            cur = conn.cursor()
            cur.execute(
                "SELECT id, concept, content, tags FROM pg_engrams "
                "ORDER BY created_at DESC LIMIT %s",
                (limit,)
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            cur.close(); conn.close()
            return [{"id": str(r["id"]), "concept": r["concept"],
                     "content": r["content"], "tags": r["tags"] or []}
                    for r in rows]
        except Exception as e:
            log.debug("PgMemoryClient.recent failed: %s", e)
            return []

    async def delete(self, engram_id: str) -> bool:
        try:
            conn = _conn()
            cur = conn.cursor()
            cur.execute("DELETE FROM pg_engrams WHERE id = %s", (engram_id,))
            conn.commit()
            deleted = cur.rowcount > 0
            cur.close(); conn.close()
            return deleted
        except Exception as e:
            log.debug("PgMemoryClient.delete failed: %s", e)
            return False

    async def count(self) -> int | None:
        try:
            conn = _conn()
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM pg_engrams")
            n = int(cur.fetchone()[0])
            cur.close(); conn.close()
            return n
        except Exception as e:
            log.debug("PgMemoryClient.count failed: %s", e)
            return None

    async def health(self) -> bool:
        return await self.count() is not None

    async def close(self) -> None:
        pass  # stateless — PG connections are pooled


_pg_client: PgMemoryClient | None = None


def get_pg_client() -> PgMemoryClient:
    global _pg_client
    if _pg_client is None:
        _pg_client = PgMemoryClient()
    return _pg_client
