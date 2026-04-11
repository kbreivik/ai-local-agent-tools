"""SSH connection attempt log — append-only audit trail.

Written after every _ssh_run() call (success or failure).
Never blocks SSH itself — all writes are fire-and-forget.
"""
import json
import logging
import os
import uuid
from datetime import datetime, timezone

log = logging.getLogger(__name__)

_DDL_PG = """
CREATE TABLE IF NOT EXISTS ssh_connection_log (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    connection_id           TEXT,
    credential_source_id    TEXT,
    target_host             TEXT NOT NULL,
    target_port             INTEGER NOT NULL DEFAULT 22,
    username                TEXT,
    jump_host               TEXT,
    jump_connection_id      TEXT,
    resolved_label          TEXT,
    outcome                 TEXT NOT NULL,
    error_message           TEXT,
    duration_ms             INTEGER,
    bytes_received          INTEGER,
    triggered_by            TEXT,
    operation_id            TEXT,
    command_preview         TEXT,
    attempted_at            TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ssh_log_connection_id ON ssh_connection_log(connection_id);
CREATE INDEX IF NOT EXISTS idx_ssh_log_target_host   ON ssh_connection_log(target_host);
CREATE INDEX IF NOT EXISTS idx_ssh_log_attempted_at  ON ssh_connection_log(attempted_at DESC);
CREATE INDEX IF NOT EXISTS idx_ssh_log_outcome       ON ssh_connection_log(outcome);
"""

_DDL_SQLITE = """
CREATE TABLE IF NOT EXISTS ssh_connection_log (
    id                      TEXT PRIMARY KEY,
    connection_id           TEXT,
    credential_source_id    TEXT,
    target_host             TEXT NOT NULL,
    target_port             INTEGER NOT NULL DEFAULT 22,
    username                TEXT,
    jump_host               TEXT,
    jump_connection_id      TEXT,
    resolved_label          TEXT,
    outcome                 TEXT NOT NULL,
    error_message           TEXT,
    duration_ms             INTEGER,
    bytes_received          INTEGER,
    triggered_by            TEXT,
    operation_id            TEXT,
    command_preview         TEXT,
    attempted_at            TEXT DEFAULT (datetime('now'))
);
"""

_initialized = False


def _ts():
    return datetime.now(timezone.utc).isoformat()


def _is_pg():
    return "postgres" in os.environ.get("DATABASE_URL", "")


def init_ssh_log():
    """Create ssh_connection_log table. Called from api/main.py on startup."""
    global _initialized
    if _initialized:
        return True
    if _is_pg():
        try:
            from api.connections import _get_conn
            conn = _get_conn()
            conn.autocommit = True
            cur = conn.cursor()
            for stmt in _DDL_PG.strip().split(";"):
                stmt = stmt.strip()
                if stmt:
                    cur.execute(stmt)
            cur.close()
            conn.close()
            _initialized = True
            log.info("ssh_connection_log table ready (PostgreSQL)")
            return True
        except Exception as e:
            log.warning("ssh_log init (PG) failed: %s", e)
    try:
        from api.connections import _get_sa_conn
        from sqlalchemy import text as _t
        sa = _get_sa_conn()
        if sa:
            sa.execute(_t(_DDL_SQLITE))
            sa.commit()
            sa.close()
            _initialized = True
            log.info("ssh_connection_log table ready (SQLite)")
            return True
    except Exception as e:
        log.warning("ssh_log init (SQLite) failed: %s", e)
    return False


def write_log(*, target_host, target_port=22, username="", outcome,
              duration_ms=0, error_message="", bytes_received=0,
              connection_id="", credential_source_id="",
              jump_host="", jump_connection_id="",
              resolved_label="", triggered_by="collector",
              operation_id="", command_preview=""):
    """Write one SSH attempt record. Never raises."""
    try:
        row = {
            "id": str(uuid.uuid4()),
            "connection_id": connection_id or None,
            "credential_source_id": credential_source_id or None,
            "target_host": target_host,
            "target_port": target_port,
            "username": username or None,
            "jump_host": jump_host or None,
            "jump_connection_id": jump_connection_id or None,
            "resolved_label": resolved_label or None,
            "outcome": outcome,
            "error_message": error_message[:300] if error_message else None,
            "duration_ms": duration_ms,
            "bytes_received": bytes_received if bytes_received else None,
            "triggered_by": triggered_by or None,
            "operation_id": operation_id or None,
            "command_preview": command_preview[:120] if command_preview else None,
            "attempted_at": _ts(),
        }
        if _is_pg():
            from api.connections import _get_conn
            conn = _get_conn()
            cols = ", ".join(row.keys())
            ph = ", ".join(["%s"] * len(row))
            cur = conn.cursor()
            cur.execute(f"INSERT INTO ssh_connection_log ({cols}) VALUES ({ph})", list(row.values()))
            conn.commit()
            cur.close()
            conn.close()
        else:
            from api.connections import _get_sa_conn
            from sqlalchemy import text as _t
            sa = _get_sa_conn()
            if sa:
                cols = ", ".join(row.keys())
                ph = ", ".join([f":{k}" for k in row.keys()])
                sa.execute(_t(f"INSERT INTO ssh_connection_log ({cols}) VALUES ({ph})"), row)
                sa.commit()
                sa.close()
    except Exception as e:
        log.debug("ssh_log write_log failed (non-fatal): %s", e)


def query_log(connection_id="", target_host="", outcome="", limit=50):
    """Query recent SSH log entries."""
    conditions = []
    params = {"limit": limit}
    if connection_id:
        conditions.append("connection_id = :conn_id")
        params["conn_id"] = connection_id
    if target_host:
        conditions.append("target_host = :host")
        params["host"] = target_host
    if outcome:
        conditions.append("outcome = :outcome")
        params["outcome"] = outcome
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    sql = f"SELECT * FROM ssh_connection_log {where} ORDER BY attempted_at DESC LIMIT :limit"
    try:
        if _is_pg():
            from api.connections import _get_conn
            conn = _get_conn()
            cur = conn.cursor()
            # Convert named params to positional for psycopg2
            pg_sql = sql
            pg_vals = []
            for key in ("conn_id", "host", "outcome", "limit"):
                if f":{key}" in pg_sql:
                    pg_sql = pg_sql.replace(f":{key}", "%s")
                    pg_vals.append(params[key])
            cur.execute(pg_sql, pg_vals)
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            cur.close()
            conn.close()
            return rows
        else:
            from api.connections import _get_sa_conn
            from sqlalchemy import text as _t
            sa = _get_sa_conn()
            if not sa:
                return []
            rows = [dict(r) for r in sa.execute(_t(sql), params).mappings().fetchall()]
            sa.close()
            return rows
    except Exception as e:
        log.debug("ssh_log query_log failed: %s", e)
        return []
