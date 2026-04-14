"""Runbooks — saved step-by-step procedures, created from manual checklist completions
or agent proposals. Searchable by agents via runbook_search() tool."""
import json
import logging
import uuid
from datetime import datetime, timezone

log = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS runbooks (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    steps       JSONB NOT NULL DEFAULT '[]',
    source      TEXT NOT NULL DEFAULT 'manual_completion',
    proposal_id TEXT NOT NULL DEFAULT '',
    tags        TEXT[] NOT NULL DEFAULT '{}',
    run_count   INTEGER NOT NULL DEFAULT 0,
    created_by  TEXT NOT NULL DEFAULT 'user',
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_runbooks_source ON runbooks(source);
CREATE INDEX IF NOT EXISTS idx_runbooks_tags   ON runbooks USING gin(tags);
"""

_initialized = False

def _ts():
    return datetime.now(timezone.utc).isoformat()

def init_runbooks():
    global _initialized
    if _initialized: return
    try:
        from api.connections import _get_conn
        conn = _get_conn(); conn.autocommit = True
        cur = conn.cursor()
        for stmt in _DDL.strip().split(";"):
            s = stmt.strip()
            if s: cur.execute(s)
        cur.close(); conn.close()
        _initialized = True
        log.info("runbooks table ready")
    except Exception as e:
        log.warning("runbooks init failed: %s", e)

def create_runbook(title: str, description: str, steps: list,
                   source: str = "manual_completion", proposal_id: str = "",
                   tags: list = None, created_by: str = "user") -> str:
    """Insert a new runbook. Returns the runbook ID."""
    rid = str(uuid.uuid4())
    try:
        from api.connections import _get_conn
        conn = _get_conn(); cur = conn.cursor()
        cur.execute(
            """INSERT INTO runbooks
               (id, title, description, steps, source, proposal_id, tags, created_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (rid, title, description, json.dumps(steps),
             source, proposal_id or "", tags or [], created_by),
        )
        conn.commit(); cur.close(); conn.close()
        return rid
    except Exception as e:
        log.debug("create_runbook failed: %s", e)
        return ""

def search_runbooks(query: str, limit: int = 5) -> list:
    """Full-text search on title + description + tags. Used by runbook_search() tool."""
    try:
        from api.connections import _get_conn
        conn = _get_conn(); cur = conn.cursor()
        cur.execute(
            """SELECT id, title, description, steps, source, tags, run_count, created_at
               FROM runbooks
               WHERE title ILIKE %s OR description ILIKE %s
                  OR %s = ANY(tags)
               ORDER BY run_count DESC, created_at DESC
               LIMIT %s""",
            (f"%{query}%", f"%{query}%", query.lower(), limit),
        )
        rows = cur.fetchall(); cur.close(); conn.close()
        return [
            {"id": r[0], "title": r[1], "description": r[2],
             "steps": r[3] or [], "source": r[4], "tags": list(r[5] or []),
             "run_count": r[6], "created_at": r[7].isoformat() if r[7] else ""}
            for r in rows
        ]
    except Exception as e:
        log.debug("search_runbooks failed: %s", e)
        return []

def list_runbooks(limit: int = 50) -> list:
    try:
        from api.connections import _get_conn
        conn = _get_conn(); cur = conn.cursor()
        cur.execute(
            """SELECT id, title, description, steps, source, tags, run_count, created_by, created_at
               FROM runbooks ORDER BY created_at DESC LIMIT %s""",
            (limit,),
        )
        rows = cur.fetchall(); cur.close(); conn.close()
        return [
            {"id": r[0], "title": r[1], "description": r[2],
             "steps": r[3] or [], "source": r[4], "tags": list(r[5] or []),
             "run_count": r[6], "created_by": r[7],
             "created_at": r[8].isoformat() if r[8] else ""}
            for r in rows
        ]
    except Exception as e:
        log.debug("list_runbooks failed: %s", e)
        return []

def delete_runbook(runbook_id: str) -> bool:
    try:
        from api.connections import _get_conn
        conn = _get_conn(); cur = conn.cursor()
        cur.execute("DELETE FROM runbooks WHERE id=%s", (runbook_id,))
        conn.commit(); cur.close(); conn.close()
        return True
    except Exception as e:
        log.debug("delete_runbook failed: %s", e)
        return False

def increment_run_count(runbook_id: str):
    try:
        from api.connections import _get_conn
        conn = _get_conn(); cur = conn.cursor()
        cur.execute(
            "UPDATE runbooks SET run_count=run_count+1, updated_at=NOW() WHERE id=%s",
            (runbook_id,),
        )
        conn.commit(); cur.close(); conn.close()
    except Exception:
        pass
