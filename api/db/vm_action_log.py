"""VM action audit log — records every action taken from the VM card."""
import json
import logging
import uuid
from datetime import datetime, timezone

log = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS vm_action_log (
    id              TEXT PRIMARY KEY,
    connection_id   TEXT,
    connection_label TEXT NOT NULL,
    action          TEXT NOT NULL,
    owner_user      TEXT DEFAULT 'unknown',
    status          TEXT DEFAULT 'started',
    output          TEXT,
    started_at      TIMESTAMPTZ DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_vm_action_label ON vm_action_log(connection_label, started_at DESC);
"""

_initialized = False


def init_vm_action_log():
    global _initialized
    if _initialized:
        return
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        for stmt in _DDL.strip().split(";"):
            s = stmt.strip()
            if s:
                cur.execute(s)
        cur.close()
        conn.close()
        _initialized = True
        log.info("vm_action_log table ready")
    except Exception as e:
        log.warning("vm_action_log init failed: %s", e)


def record_action(connection_label: str, action: str, owner_user: str = "unknown",
                  connection_id: str = "") -> str:
    """Insert a started action record. Returns the action ID."""
    aid = str(uuid.uuid4())
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO vm_action_log (id, connection_id, connection_label, action, owner_user)
               VALUES (%s, %s, %s, %s, %s)""",
            (aid, connection_id or None, connection_label, action, owner_user)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        log.debug("record_action failed: %s", e)
    return aid


def complete_action(action_id: str, status: str, output: str = ""):
    """Update a vm_action_log row with completion status and output."""
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            """UPDATE vm_action_log
               SET status = %s, output = %s, completed_at = NOW()
               WHERE id = %s""",
            (status, output[:2000] if output else None, action_id)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        log.debug("complete_action failed: %s", e)


def list_recent(connection_label: str = "", limit: int = 20) -> list:
    """Return recent vm actions, optionally filtered by host."""
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        if connection_label:
            cur.execute(
                """SELECT id, connection_label, action, owner_user, status,
                          output, started_at, completed_at
                   FROM vm_action_log
                   WHERE connection_label = %s
                   ORDER BY started_at DESC LIMIT %s""",
                (connection_label, limit)
            )
        else:
            cur.execute(
                """SELECT id, connection_label, action, owner_user, status,
                          output, started_at, completed_at
                   FROM vm_action_log
                   ORDER BY started_at DESC LIMIT %s""",
                (limit,)
            )
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.close()
        conn.close()
        for r in rows:
            for k in ("started_at", "completed_at"):
                if r.get(k):
                    try:
                        r[k] = r[k].isoformat()
                    except Exception:
                        pass
        return rows
    except Exception as e:
        log.debug("list_recent failed: %s", e)
        return []
