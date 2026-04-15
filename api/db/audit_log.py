"""connection_audit_log — records credential rotation events and admin overrides."""
import json
import logging
import os
import uuid
from datetime import datetime, timezone

log = logging.getLogger(__name__)

_DDL_PG = """
CREATE TABLE IF NOT EXISTS connection_audit_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type      TEXT NOT NULL,
    profile_id      TEXT,
    performed_by    TEXT NOT NULL DEFAULT '',
    override_reason TEXT NOT NULL DEFAULT '',
    connection_ids  TEXT[] DEFAULT '{}',
    test_results    JSONB DEFAULT '{}',
    timestamp       TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON connection_audit_log(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_profile ON connection_audit_log(profile_id);
"""

_DDL_SQLITE = """
CREATE TABLE IF NOT EXISTS connection_audit_log (
    id              TEXT PRIMARY KEY,
    event_type      TEXT NOT NULL,
    profile_id      TEXT,
    performed_by    TEXT NOT NULL DEFAULT '',
    override_reason TEXT NOT NULL DEFAULT '',
    connection_ids  TEXT DEFAULT '[]',
    test_results    TEXT DEFAULT '{}',
    timestamp       TEXT DEFAULT (datetime('now'))
);
"""

_initialized = False


def _ts(): return datetime.now(timezone.utc).isoformat()
def _is_pg(): return bool(os.environ.get("DATABASE_URL", ""))


def _get_conn():
    if not _is_pg(): return None
    import psycopg2
    dsn = os.environ.get("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")
    return psycopg2.connect(dsn)


def init_audit_log() -> bool:
    global _initialized
    if _initialized: return True
    conn = _get_conn()
    if conn:
        try:
            conn.autocommit = True
            cur = conn.cursor()
            for stmt in _DDL_PG.strip().split(';'):
                stmt = stmt.strip()
                if stmt:
                    cur.execute(stmt)
            cur.close(); conn.close()
            _initialized = True
            log.info("connection_audit_log table ready (PG)")
            return True
        except Exception as e:
            log.warning("audit_log init (PG) failed: %s", e)
            try: conn.close()
            except Exception: pass
    try:
        from api.db.base import get_sync_engine
        from sqlalchemy import text as _t
        sa = get_sync_engine().connect()
        sa.execute(_t(_DDL_SQLITE)); sa.commit(); sa.close()
        _initialized = True
        log.info("connection_audit_log table ready (SQLite)")
        return True
    except Exception as e:
        log.warning("audit_log init (SQLite) failed: %s", e)
        return False


def write_audit_event(
    event_type: str,
    performed_by: str,
    profile_id: str | None = None,
    override_reason: str = "",
    connection_ids: list[str] | None = None,
    test_results: dict | None = None,
) -> str | None:
    """Write an audit event. Returns the new event id or None on failure.

    event_type values:
      rotation_test          — normal rotation test completed (all pass)
      rotation_override      — rotation saved despite test failures (admin override)
      profile_created        — new profile created
      profile_updated        — profile credentials updated without rotation test
      profile_deleted        — profile deleted
    """
    if not _initialized:
        init_audit_log()
    eid = str(uuid.uuid4())
    conn_ids = connection_ids or []
    results = test_results or {}

    conn = _get_conn()
    if conn:
        try:
            import psycopg2.extras
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO connection_audit_log "
                "(id, event_type, profile_id, performed_by, override_reason, connection_ids, test_results) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (eid, event_type, profile_id, performed_by, override_reason,
                 conn_ids, json.dumps(results)),
            )
            conn.commit(); cur.close(); conn.close()
            return eid
        except Exception as e:
            log.warning("write_audit_event (PG) failed: %s", e)
            try: conn.close()
            except Exception: pass

    try:
        from api.db.base import get_sync_engine
        from sqlalchemy import text as _t
        sa = get_sync_engine().connect()
        sa.execute(_t(
            "INSERT INTO connection_audit_log "
            "(id, event_type, profile_id, performed_by, override_reason, connection_ids, test_results) "
            "VALUES (:id, :et, :pid, :by, :reason, :cids, :results)"
        ), {
            "id": eid, "et": event_type, "pid": profile_id,
            "by": performed_by, "reason": override_reason,
            "cids": json.dumps(conn_ids), "results": json.dumps(results),
        })
        sa.commit(); sa.close()
        return eid
    except Exception as e:
        log.warning("write_audit_event (SQLite) failed: %s", e)
        return None


def list_audit_events(profile_id: str | None = None, limit: int = 50) -> list[dict]:
    """List recent audit events, optionally filtered by profile_id."""
    if not _initialized:
        init_audit_log()
    conn = _get_conn()
    if conn:
        try:
            cur = conn.cursor()
            if profile_id:
                cur.execute(
                    "SELECT * FROM connection_audit_log WHERE profile_id = %s "
                    "ORDER BY timestamp DESC LIMIT %s", (profile_id, limit)
                )
            else:
                cur.execute(
                    "SELECT * FROM connection_audit_log ORDER BY timestamp DESC LIMIT %s", (limit,)
                )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            cur.close(); conn.close()
            for r in rows:
                r['id'] = str(r.get('id', ''))
                if r.get('timestamp'):
                    try: r['timestamp'] = r['timestamp'].isoformat()
                    except Exception: pass
            return rows
        except Exception as e:
            log.warning("list_audit_events (PG) failed: %s", e)
    return []
