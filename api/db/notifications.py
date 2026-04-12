"""Notification config storage and delivery tracking.

notification_channels: configured delivery channels (email/webhook)
notification_rules:    which alert types route to which channels
notification_log:      sent notification history (rate limit + audit)
"""
import json
import logging
import os
import uuid
from datetime import datetime, timezone

log = logging.getLogger(__name__)

_DDL_PG = """
CREATE TABLE IF NOT EXISTS notification_channels (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    type        TEXT NOT NULL,
    config      JSONB NOT NULL,
    enabled     BOOLEAN DEFAULT true,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(name)
);

CREATE TABLE IF NOT EXISTS notification_rules (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    channel_id      UUID REFERENCES notification_channels(id) ON DELETE CASCADE,
    event_type      TEXT NOT NULL,
    min_severity    TEXT DEFAULT 'warning',
    enabled         BOOLEAN DEFAULT true
);

CREATE TABLE IF NOT EXISTS notification_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    channel_id      UUID,
    event_type      TEXT,
    subject         TEXT,
    sent_at         TIMESTAMPTZ DEFAULT NOW(),
    status          TEXT,
    error           TEXT
);
CREATE INDEX IF NOT EXISTS idx_notif_log_sent ON notification_log(sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_notif_log_type ON notification_log(event_type, sent_at DESC);
"""

_initialized = False


def _ts(): return datetime.now(timezone.utc).isoformat()
def _is_pg(): return "postgres" in os.environ.get("DATABASE_URL", "")


def init_notifications() -> bool:
    global _initialized
    if _initialized: return True
    if not _is_pg():
        _initialized = True
        return True
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        for stmt in _DDL_PG.strip().split(";"):
            stmt = stmt.strip()
            if stmt: cur.execute(stmt)
        cur.close(); conn.close()
        _initialized = True
        log.info("notification tables ready")
        return True
    except Exception as e:
        log.warning("notifications init failed: %s", e)
        return False


def should_notify(event_type: str, channel_id: str, rate_limit_hours: int = 1) -> bool:
    """Check rate limit: return False if same event_type was sent to this channel recently."""
    if not _is_pg(): return True
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM notification_log
            WHERE channel_id = %s AND event_type = %s
              AND status = 'sent'
              AND sent_at > NOW() - INTERVAL '%s hours'
        """, (channel_id, event_type, rate_limit_hours))
        count = cur.fetchone()[0]
        cur.close(); conn.close()
        return count == 0
    except Exception as e:
        log.debug("should_notify check failed: %s", e)
        return True


def log_notification(channel_id: str, event_type: str, subject: str,
                     status: str, error: str = "") -> None:
    """Record a notification attempt."""
    if not _is_pg(): return
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO notification_log (id, channel_id, event_type, subject, status, error)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (str(uuid.uuid4()), channel_id, event_type, subject[:200], status, error[:300] or None))
        conn.commit(); cur.close(); conn.close()
    except Exception as e:
        log.debug("log_notification failed: %s", e)


def list_channels() -> list[dict]:
    if not _is_pg(): return []
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("SELECT id, name, type, config, enabled, created_at FROM notification_channels ORDER BY name")
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.close(); conn.close()
        for r in rows:
            if hasattr(r.get("id"), "hex"): r["id"] = str(r["id"])
            if hasattr(r.get("created_at"), "isoformat"): r["created_at"] = r["created_at"].isoformat()
            if isinstance(r.get("config"), str):
                try: r["config"] = json.loads(r["config"])
                except Exception: pass
        return rows
    except Exception as e:
        log.debug("list_channels failed: %s", e)
        return []


def create_channel(name: str, ch_type: str, config: dict) -> str:
    """Create a channel, return its UUID."""
    if not _is_pg(): return ""
    cid = str(uuid.uuid4())
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO notification_channels (id, name, type, config)
            VALUES (%s, %s, %s, %s)
        """, (cid, name, ch_type, json.dumps(config)))
        conn.commit(); cur.close(); conn.close()
        return cid
    except Exception as e:
        log.debug("create_channel failed: %s", e)
        return ""


def delete_channel(channel_id: str) -> bool:
    if not _is_pg(): return False
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM notification_channels WHERE id = %s", (channel_id,))
        conn.commit(); cur.close(); conn.close()
        return True
    except Exception as e:
        log.debug("delete_channel failed: %s", e)
        return False


def list_rules() -> list[dict]:
    if not _is_pg(): return []
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT r.id, r.channel_id, c.name as channel_name, r.event_type, r.min_severity, r.enabled
            FROM notification_rules r
            JOIN notification_channels c ON c.id = r.channel_id
            ORDER BY r.event_type
        """)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.close(); conn.close()
        for r in rows:
            if hasattr(r.get("id"), "hex"): r["id"] = str(r["id"])
            if hasattr(r.get("channel_id"), "hex"): r["channel_id"] = str(r["channel_id"])
        return rows
    except Exception as e:
        log.debug("list_rules failed: %s", e)
        return []


def create_rule(channel_id: str, event_type: str, min_severity: str = "warning") -> str:
    if not _is_pg(): return ""
    rid = str(uuid.uuid4())
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO notification_rules (id, channel_id, event_type, min_severity)
            VALUES (%s, %s, %s, %s)
        """, (rid, channel_id, event_type, min_severity))
        conn.commit(); cur.close(); conn.close()
        return rid
    except Exception as e:
        log.debug("create_rule failed: %s", e)
        return ""


def get_log(limit: int = 50) -> list[dict]:
    if not _is_pg(): return []
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT l.id, c.name as channel_name, l.event_type, l.subject, l.sent_at, l.status, l.error
            FROM notification_log l
            LEFT JOIN notification_channels c ON c.id = l.channel_id
            ORDER BY l.sent_at DESC LIMIT %s
        """, (limit,))
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.close(); conn.close()
        for r in rows:
            if hasattr(r.get("id"), "hex"): r["id"] = str(r["id"])
            if hasattr(r.get("sent_at"), "isoformat"): r["sent_at"] = r["sent_at"].isoformat()
        return rows
    except Exception as e:
        log.debug("get_log failed: %s", e)
        return []
