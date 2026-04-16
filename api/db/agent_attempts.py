"""Agent attempt history — tracks what was tried on each entity and whether it worked.

Records a row per agent run including the detected entity, task type, tools used,
and outcome. Queried at the start of each agent run to inject prior-attempt context
into the system prompt so the agent can vary its strategy when previous approaches
have failed.

Dual-backend (Postgres preferred, SQLite fallback) mirroring agent_actions.py.
"""
import json
import logging
import os

log = logging.getLogger(__name__)

_TABLE = "agent_attempts"

_DDL_PG = """
CREATE TABLE IF NOT EXISTS agent_attempts (
    id           BIGSERIAL PRIMARY KEY,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    entity_id    TEXT NOT NULL,
    task_type    TEXT NOT NULL DEFAULT 'general',
    task_text    TEXT NOT NULL DEFAULT '',
    tools_used   JSONB NOT NULL DEFAULT '[]'::jsonb,
    outcome      TEXT NOT NULL DEFAULT 'unknown',
    summary      TEXT NOT NULL DEFAULT '',
    session_id   TEXT NOT NULL DEFAULT '',
    operation_id TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_attempts_entity
    ON agent_attempts (entity_id, created_at DESC);
"""

_DDL_SQLITE = """
CREATE TABLE IF NOT EXISTS agent_attempts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    entity_id    TEXT NOT NULL,
    task_type    TEXT NOT NULL DEFAULT 'general',
    task_text    TEXT NOT NULL DEFAULT '',
    tools_used   TEXT NOT NULL DEFAULT '[]',
    outcome      TEXT NOT NULL DEFAULT 'unknown',
    summary      TEXT NOT NULL DEFAULT '',
    session_id   TEXT NOT NULL DEFAULT '',
    operation_id TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_attempts_entity
    ON agent_attempts (entity_id, created_at DESC);
"""

_initialized = False


def _pg_dsn() -> str:
    return os.environ.get("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")


def _get_pg_conn():
    dsn = _pg_dsn()
    if not dsn:
        return None
    try:
        import psycopg2
        return psycopg2.connect(dsn)
    except Exception as e:
        log.debug("agent_attempts PG connect failed: %s", e)
        return None


def _get_sa_conn():
    try:
        from api.db.base import get_sync_engine
        return get_sync_engine().connect()
    except Exception:
        return None


def init_agent_attempts() -> bool:
    """Create the agent_attempts table if it doesn't exist. Idempotent."""
    global _initialized
    if _initialized:
        return True
    conn = _get_pg_conn()
    if conn:
        try:
            conn.autocommit = True
            cur = conn.cursor()
            for stmt in _DDL_PG.strip().split(";"):
                s = stmt.strip()
                if s:
                    cur.execute(s)
            cur.close(); conn.close()
            _initialized = True
            log.info("agent_attempts table ready (PostgreSQL)")
            return True
        except Exception as e:
            log.warning("agent_attempts init failed (PG): %s", e)
            try: conn.close()
            except Exception: pass
    sa = _get_sa_conn()
    if not sa:
        return False
    try:
        from sqlalchemy import text as _t
        for stmt in _DDL_SQLITE.strip().split(";"):
            s = stmt.strip()
            if s:
                sa.execute(_t(s))
        sa.commit(); sa.close()
        _initialized = True
        log.info("agent_attempts table ready (SQLite)")
        return True
    except Exception as e:
        log.warning("agent_attempts init failed (SQLite): %s", e)
        try: sa.close()
        except Exception: pass
        return False


def record_attempt(
    *,
    entity_id: str,
    task_type: str = "general",
    task_text: str = "",
    tools_used: list | None = None,
    outcome: str = "unknown",
    summary: str = "",
    session_id: str = "",
    operation_id: str = "",
):
    """Record an agent attempt on an entity. Never raises."""
    tools_json = json.dumps(tools_used or [])
    entity_id = (entity_id or "")[:200]
    task_type = (task_type or "")[:50]
    task_text = (task_text or "")[:500]
    outcome = (outcome or "")[:20]
    summary = (summary or "")[:500]
    session_id = (session_id or "")[:128]
    operation_id = (operation_id or "")[:128]

    conn = _get_pg_conn()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO agent_attempts
                   (entity_id, task_type, task_text, tools_used, outcome,
                    summary, session_id, operation_id)
                   VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, %s)""",
                (entity_id, task_type, task_text, tools_json,
                 outcome, summary, session_id, operation_id),
            )
            conn.commit(); cur.close(); conn.close()
            return
        except Exception as e:
            log.debug("record_attempt (PG) failed: %s", e)
            try: conn.close()
            except Exception: pass
            return
    try:
        from sqlalchemy import text as _t
        sa = _get_sa_conn()
        if not sa:
            return
        sa.execute(_t(
            """INSERT INTO agent_attempts
               (entity_id, task_type, task_text, tools_used, outcome,
                summary, session_id, operation_id)
               VALUES (:eid, :tt, :tx, :tu, :oc, :sm, :sid, :oid)"""
        ), {
            "eid": entity_id, "tt": task_type, "tx": task_text,
            "tu": tools_json, "oc": outcome, "sm": summary,
            "sid": session_id, "oid": operation_id,
        })
        sa.commit(); sa.close()
    except Exception as e:
        log.debug("record_attempt (SQLite) failed: %s", e)


def get_recent_attempts(entity_id: str, limit: int = 3) -> list[dict]:
    """Return last N attempts for an entity, newest first."""
    limit = max(1, min(int(limit or 3), 20))
    conn = _get_pg_conn()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute(
                """SELECT created_at, task_type, tools_used, outcome, summary
                   FROM agent_attempts
                   WHERE entity_id = %s
                   ORDER BY created_at DESC
                   LIMIT %s""",
                (entity_id, limit),
            )
            rows = cur.fetchall(); cur.close(); conn.close()
            out = []
            for r in rows:
                when = r[0]
                try:
                    when = when.isoformat()
                except Exception:
                    when = str(when)
                tools = r[2] if isinstance(r[2], list) else (
                    json.loads(r[2]) if isinstance(r[2], str) and r[2] else []
                )
                out.append({
                    "when": when, "task_type": r[1],
                    "tools": tools, "outcome": r[3], "summary": r[4],
                })
            return out
        except Exception as e:
            log.debug("get_recent_attempts (PG) failed: %s", e)
            try: conn.close()
            except Exception: pass
            return []
    try:
        from sqlalchemy import text as _t
        sa = _get_sa_conn()
        if not sa:
            return []
        rows = sa.execute(_t(
            """SELECT created_at, task_type, tools_used, outcome, summary
               FROM agent_attempts
               WHERE entity_id = :eid
               ORDER BY created_at DESC
               LIMIT :lim"""
        ), {"eid": entity_id, "lim": limit}).fetchall()
        sa.close()
        out = []
        for r in rows:
            tools_raw = r[2]
            try:
                tools = json.loads(tools_raw) if isinstance(tools_raw, str) else (tools_raw or [])
            except Exception:
                tools = []
            out.append({
                "when": str(r[0]) if r[0] else "",
                "task_type": r[1], "tools": tools,
                "outcome": r[3], "summary": r[4],
            })
        return out
    except Exception as e:
        log.debug("get_recent_attempts (SQLite) failed: %s", e)
        return []


def _prune_old(days: int = 30) -> int:
    """Delete attempts older than N days. Returns rows deleted."""
    conn = _get_pg_conn()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM agent_attempts WHERE created_at < NOW() - INTERVAL %s",
                (f"{int(days)} days",),
            )
            n = cur.rowcount or 0
            conn.commit(); cur.close(); conn.close()
            return n
        except Exception:
            try: conn.close()
            except Exception: pass
            return 0
    try:
        from sqlalchemy import text as _t
        sa = _get_sa_conn()
        if not sa:
            return 0
        sa.execute(_t(
            "DELETE FROM agent_attempts WHERE created_at < datetime('now', :d)"
        ), {"d": f"-{int(days)} days"})
        sa.commit(); sa.close()
        return 0
    except Exception:
        return 0
