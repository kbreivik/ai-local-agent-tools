"""entity_maintenance — per-entity maintenance flag.

Stored in DB. When an entity is in maintenance:
  - Its dot is overridden to "grey" (no red/amber)
  - It is excluded from section health aggregation
  - The collector reports problem=None and maintenance=True on the card

Table schema:
  entity_id   TEXT PK   — e.g. "proxmox_vms:pve1:vm:100"
  reason      TEXT      — optional operator note
  set_by      TEXT      — username who set it
  set_at      TIMESTAMPTZ
  expires_at  TIMESTAMPTZ NULL — None = no expiry
"""
import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS entity_maintenance (
    entity_id  TEXT PRIMARY KEY,
    reason     TEXT    NOT NULL DEFAULT '',
    set_by     TEXT    NOT NULL DEFAULT 'operator',
    set_at     TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ NULL
);
CREATE INDEX IF NOT EXISTS idx_maint_expires ON entity_maintenance(expires_at);
"""

_initialized = False


def init_maintenance():
    """Create table if absent. Called on startup."""
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
        cur.close(); conn.close()
        _initialized = True
        log.info("entity_maintenance table ready")
    except Exception as e:
        log.warning("entity_maintenance init failed: %s", e)


def get_maintenance_set() -> set[str]:
    """Return set of entity_ids currently in maintenance (excluding expired)."""
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT entity_id FROM entity_maintenance "
            "WHERE expires_at IS NULL OR expires_at > NOW()"
        )
        rows = {r[0] for r in cur.fetchall()}
        cur.close(); conn.close()
        return rows
    except Exception as e:
        log.debug("get_maintenance_set failed: %s", e)
        return set()


def set_maintenance(entity_id: str, reason: str = "", set_by: str = "operator",
                    expires_at=None) -> dict:
    """Set an entity in maintenance. Upserts."""
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO entity_maintenance (entity_id, reason, set_by, set_at, expires_at)
               VALUES (%s, %s, %s, NOW(), %s)
               ON CONFLICT (entity_id) DO UPDATE SET
                 reason=EXCLUDED.reason, set_by=EXCLUDED.set_by,
                 set_at=NOW(), expires_at=EXCLUDED.expires_at""",
            (entity_id, reason, set_by, expires_at)
        )
        conn.commit(); cur.close(); conn.close()
        log.info("entity_maintenance: SET %s by %s", entity_id, set_by)
        return {"ok": True, "entity_id": entity_id}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def clear_maintenance(entity_id: str) -> dict:
    """Remove an entity from maintenance."""
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM entity_maintenance WHERE entity_id = %s", (entity_id,))
        deleted = cur.rowcount
        conn.commit(); cur.close(); conn.close()
        log.info("entity_maintenance: CLEAR %s (deleted=%d)", entity_id, deleted)
        return {"ok": True, "entity_id": entity_id, "was_set": deleted > 0}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def list_maintenance() -> list[dict]:
    """Return all active maintenance entries."""
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT entity_id, reason, set_by, set_at, expires_at "
            "FROM entity_maintenance "
            "WHERE expires_at IS NULL OR expires_at > NOW() "
            "ORDER BY set_at DESC"
        )
        cols = [d[0] for d in cur.description]
        rows = []
        for r in cur.fetchall():
            row = dict(zip(cols, r))
            for k in ("set_at", "expires_at"):
                if row.get(k) and hasattr(row[k], "isoformat"):
                    row[k] = row[k].isoformat()
            rows.append(row)
        cur.close(); conn.close()
        return rows
    except Exception as e:
        log.debug("list_maintenance failed: %s", e)
        return []
