"""Entity change and event tracking — append-only historical audit trail.

entity_changes: permanent record of field-level value changes.
  Written when a collector detects a field changed vs the prior snapshot.
  Never overwritten — full diff history preserved indefinitely.

entity_events: permanent discrete named events.
  Restarts, version changes, digest changes, threshold crossings.
  Severity-tagged for alert filtering.

Both tables are indexed for fast entity + time range queries.
Agent tools and GUI use these for "what changed" and "what happened" queries.
"""
import json
import logging
import os
import uuid
from datetime import datetime, timezone

log = logging.getLogger(__name__)

_DDL_PG = """
CREATE TABLE IF NOT EXISTS entity_changes (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id           TEXT NOT NULL,
    entity_type         TEXT NOT NULL,
    connection_id       TEXT,
    field_name          TEXT NOT NULL,
    old_value           TEXT,
    new_value           TEXT NOT NULL,
    detected_at         TIMESTAMPTZ DEFAULT NOW(),
    source_collector    TEXT,
    metadata            JSONB DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_entity_changes_entity  ON entity_changes(entity_id, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_entity_changes_field   ON entity_changes(field_name, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_entity_changes_time    ON entity_changes(detected_at DESC);

CREATE TABLE IF NOT EXISTS entity_events (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id           TEXT NOT NULL,
    entity_type         TEXT NOT NULL,
    connection_id       TEXT,
    event_type          TEXT NOT NULL,
    severity            TEXT NOT NULL DEFAULT 'info',
    description         TEXT NOT NULL,
    metadata            JSONB DEFAULT '{}',
    occurred_at         TIMESTAMPTZ DEFAULT NOW(),
    source_collector    TEXT
);
CREATE INDEX IF NOT EXISTS idx_entity_events_entity   ON entity_events(entity_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_entity_events_type     ON entity_events(event_type, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_entity_events_severity ON entity_events(severity, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_entity_events_time     ON entity_events(occurred_at DESC);
"""

_initialized = False


def _ts(): return datetime.now(timezone.utc).isoformat()
def _is_pg(): return "postgres" in os.environ.get("DATABASE_URL", "")


def init_entity_history() -> bool:
    """Create entity_changes and entity_events tables. Called from api/main.py."""
    global _initialized
    if _initialized: return True
    if not _is_pg():
        _initialized = True
        return True   # SQLite: skip, collectors will no-op gracefully
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
        log.info("entity_changes + entity_events tables ready")
        return True
    except Exception as e:
        log.warning("entity_history init failed: %s", e)
        return False


def write_change(
    *,
    entity_id: str,
    entity_type: str,
    field_name: str,
    old_value: str | None,
    new_value: str,
    connection_id: str = "",
    source_collector: str = "",
    metadata: dict | None = None,
) -> None:
    """Record a field-level change. Never raises."""
    if not _is_pg() or not entity_id or not field_name:
        return
    if old_value == new_value:
        return   # no-op if values are identical
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO entity_changes
                (id, entity_id, entity_type, connection_id, field_name,
                 old_value, new_value, detected_at, source_collector, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            str(uuid.uuid4()), entity_id, entity_type,
            connection_id or None, field_name,
            str(old_value) if old_value is not None else None,
            str(new_value),
            _ts(), source_collector or None,
            json.dumps(metadata or {}),
        ))
        conn.commit(); cur.close(); conn.close()
    except Exception as e:
        log.debug("write_change failed (non-fatal): %s", e)


def write_event(
    *,
    entity_id: str,
    entity_type: str,
    event_type: str,
    description: str,
    severity: str = "info",
    connection_id: str = "",
    source_collector: str = "",
    metadata: dict | None = None,
) -> None:
    """Record a discrete named event. Never raises.

    event_type examples:
      version_change, image_digest_change, container_restart,
      service_degraded, service_recovered, disk_threshold_crossed,
      new_ssh_host, config_change
    severity: info | warning | error | critical
    """
    if not _is_pg() or not entity_id or not event_type:
        return
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO entity_events
                (id, entity_id, entity_type, connection_id, event_type,
                 severity, description, metadata, occurred_at, source_collector)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            str(uuid.uuid4()), entity_id, entity_type,
            connection_id or None, event_type,
            severity, description[:500],
            json.dumps(metadata or {}),
            _ts(), source_collector or None,
        ))
        conn.commit(); cur.close(); conn.close()
    except Exception as e:
        log.debug("write_event failed (non-fatal): %s", e)


def get_changes(
    entity_id: str,
    hours: int = 24,
    field_name: str = "",
    limit: int = 50,
) -> list[dict]:
    """Query entity_changes for an entity within the last N hours."""
    if not _is_pg(): return []
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        sql = """
            SELECT field_name, old_value, new_value, detected_at, source_collector, metadata
            FROM entity_changes
            WHERE entity_id = %s
              AND detected_at >= NOW() - INTERVAL '%s hours'
        """
        params = [entity_id, hours]
        if field_name:
            sql += " AND field_name = %s"
            params.append(field_name)
        sql += " ORDER BY detected_at DESC LIMIT %s"
        params.append(limit)
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.close(); conn.close()
        for r in rows:
            if hasattr(r.get("detected_at"), "isoformat"):
                r["detected_at"] = r["detected_at"].isoformat()
            if isinstance(r.get("metadata"), str):
                try: r["metadata"] = json.loads(r["metadata"])
                except Exception: pass
        return rows
    except Exception as e:
        log.debug("get_changes failed: %s", e)
        return []


def get_events(
    entity_id: str,
    hours: int = 24,
    event_type: str = "",
    severity: str = "",
    limit: int = 50,
) -> list[dict]:
    """Query entity_events for an entity within the last N hours."""
    if not _is_pg(): return []
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        sql = """
            SELECT event_type, severity, description, occurred_at,
                   source_collector, metadata
            FROM entity_events
            WHERE entity_id = %s
              AND occurred_at >= NOW() - INTERVAL '%s hours'
        """
        params = [entity_id, hours]
        if event_type:
            sql += " AND event_type = %s"; params.append(event_type)
        if severity:
            sql += " AND severity = %s"; params.append(severity)
        sql += " ORDER BY occurred_at DESC LIMIT %s"
        params.append(limit)
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.close(); conn.close()
        for r in rows:
            if hasattr(r.get("occurred_at"), "isoformat"):
                r["occurred_at"] = r["occurred_at"].isoformat()
            if isinstance(r.get("metadata"), str):
                try: r["metadata"] = json.loads(r["metadata"])
                except Exception: pass
        return rows
    except Exception as e:
        log.debug("get_events failed: %s", e)
        return []


def get_last_known_values(entity_id: str, fields: list[str]) -> dict[str, str | None]:
    """Return the most recent known value for each requested field.

    Used by collectors to check if a field changed since last poll.
    Queries entity_changes for the most recent new_value per field.
    Returns {field_name: last_value_or_None}.
    """
    if not _is_pg() or not entity_id or not fields:
        return {f: None for f in fields}
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        # Use DISTINCT ON for efficient latest-per-field query
        cur.execute("""
            SELECT DISTINCT ON (field_name) field_name, new_value
            FROM entity_changes
            WHERE entity_id = %s AND field_name = ANY(%s)
            ORDER BY field_name, detected_at DESC
        """, (entity_id, fields))
        result = {f: None for f in fields}
        for row in cur.fetchall():
            result[row[0]] = row[1]
        cur.close(); conn.close()
        return result
    except Exception as e:
        log.debug("get_last_known_values failed: %s", e)
        return {f: None for f in fields}


def get_recent_changes_summary(entity_id: str, hours: int = 24) -> str | None:
    """Return a compact one-line summary of recent changes for prompt injection.

    Example: "3 changes in 24h: os (12.6→12.7), docker_version (28.0→29.3.1)"
    Returns None if no changes found.
    """
    changes = get_changes(entity_id, hours=hours, limit=10)
    if not changes:
        return None
    parts = []
    for c in changes[:3]:
        old = c.get("old_value", "?")
        new = c.get("new_value", "?")
        field = c.get("field_name", "?")
        parts.append(f"{field} ({old}→{new})")
    n = len(changes)
    return f"{n} change{'s' if n > 1 else ''} in {hours}h: {', '.join(parts)}"
