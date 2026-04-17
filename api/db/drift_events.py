"""Drift events — config_hash changed without a sanctioned agent_action.

A drift event is declared when:
  * entity_snapshots.config_hash != prev_config_hash
  * No agent_actions row for the same entity with was_planned=TRUE exists
    within ±60 seconds of the snapshot timestamp.

Surfaces as a ⚠ DRIFT badge on the affected card; one-click escalates to
the `investigate_drift` agent template.

The view is recreated on every startup so schema changes flow in without a
manual migration. Queries are intentionally cheap — the partial index on
entity_snapshots(entity_id, snapshot_at) WHERE hash changed keeps the
scan narrow even over months of poll history.
"""
import logging
import os

log = logging.getLogger(__name__)


# Postgres CREATE OR REPLACE VIEW only permits appending new columns at the
# end of the SELECT list — existing columns must keep their position, name and
# type. So recorded_at / suppressed_by_maintenance / acknowledged are tacked
# on after metadata.
_VIEW_SQL = """
CREATE OR REPLACE VIEW drift_events AS
SELECT
    es.entity_id,
    es.snapshot_at,
    es.config_hash,
    es.prev_config_hash,
    es.metadata,
    es.snapshot_at                AS recorded_at,
    (em.entity_id IS NOT NULL)    AS suppressed_by_maintenance,
    FALSE                         AS acknowledged
FROM entity_snapshots es
LEFT JOIN entity_maintenance em
  ON em.entity_id = es.entity_id
 AND em.set_at    <= es.snapshot_at
 AND (em.expires_at IS NULL OR em.expires_at > es.snapshot_at)
WHERE es.config_hash IS NOT NULL
  AND es.prev_config_hash IS NOT NULL
  AND es.config_hash <> es.prev_config_hash
  AND NOT EXISTS (
    SELECT 1
      FROM agent_actions aa
     WHERE aa.args_redacted ->> 'entity_id' = es.entity_id
       AND aa.was_planned = TRUE
       AND aa.timestamp BETWEEN es.snapshot_at - INTERVAL '60 seconds'
                             AND es.snapshot_at + INTERVAL '60 seconds'
  );
"""


def _is_pg() -> bool:
    return "postgres" in os.environ.get("DATABASE_URL", "")


def _get_conn():
    from api.connections import _get_conn as _c
    return _c()


_initialized = False


def init_drift_view() -> bool:
    """Create or replace the drift_events view. Idempotent.

    Depends on entity_snapshots (Change 1) and agent_actions (v2.31.2) both
    existing. If either is missing, returns False and the feature simply
    degrades — cards won't show a badge.
    """
    global _initialized
    if _initialized:
        return True
    if not _is_pg():
        _initialized = True
        return True  # SQLite: drift reconciliation is PG-only for now
    try:
        conn = _get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(_VIEW_SQL)
        cur.close(); conn.close()
        _initialized = True
        log.info("drift_events view ready")
        return True
    except Exception as e:
        log.warning("drift_events view init failed: %s", e)
        return False


def get_drift_for_entity(entity_id: str, limit: int = 10) -> list[dict]:
    """Return the most recent drift events for one entity."""
    if not _is_pg() or not entity_id:
        return []
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT snapshot_at, config_hash, prev_config_hash, metadata
              FROM drift_events
             WHERE entity_id = %s
             ORDER BY snapshot_at DESC
             LIMIT %s
            """,
            (entity_id, int(limit or 10)),
        )
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.close(); conn.close()
        for r in rows:
            if hasattr(r.get("snapshot_at"), "isoformat"):
                r["snapshot_at"] = r["snapshot_at"].isoformat()
        return rows
    except Exception as e:
        log.debug("get_drift_for_entity failed: %s", e)
        return []


def recent_drift(hours: int = 24, limit: int = 100) -> list[dict]:
    """Return all drift events across all entities in the last N hours."""
    if not _is_pg():
        return []
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT entity_id, snapshot_at, config_hash, prev_config_hash
              FROM drift_events
             WHERE snapshot_at > NOW() - (%s || ' hours')::interval
             ORDER BY snapshot_at DESC
             LIMIT %s
            """,
            (str(int(hours or 24)), int(limit or 100)),
        )
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.close(); conn.close()
        for r in rows:
            if hasattr(r.get("snapshot_at"), "isoformat"):
                r["snapshot_at"] = r["snapshot_at"].isoformat()
        return rows
    except Exception as e:
        log.debug("recent_drift failed: %s", e)
        return []


def entities_with_drift(hours: int = 24) -> set[str]:
    """Return the set of entity_ids with any drift event in the last N hours.

    Used by the dashboard summary to tag entities with has_drift=True without
    an N+1 per-card query.
    """
    if not _is_pg():
        return set()
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT DISTINCT entity_id
              FROM drift_events
             WHERE snapshot_at > NOW() - (%s || ' hours')::interval
            """,
            (str(int(hours or 24)),),
        )
        rows = cur.fetchall()
        cur.close(); conn.close()
        return {r[0] for r in rows if r and r[0]}
    except Exception as e:
        log.debug("entities_with_drift failed: %s", e)
        return set()
