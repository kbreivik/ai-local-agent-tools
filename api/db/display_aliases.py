"""display_aliases — user-editable display name overrides for entities.

Each entry maps an entity_id to a user-set alias. The `origin` field stores
the original auto-derived name so it can be restored when alias is cleared.

entity_id format: 'docker:<container_name>' | 'swarm:<service_name>' | 'connection:<uuid>'
"""
import logging
import os
import uuid
from datetime import datetime, timezone

log = logging.getLogger(__name__)

_DDL_PG = """
CREATE TABLE IF NOT EXISTS display_aliases (
    entity_id   TEXT PRIMARY KEY,
    alias       TEXT NOT NULL,
    origin      TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_display_aliases_origin ON display_aliases(origin);
"""

_DDL_SQLITE = """
CREATE TABLE IF NOT EXISTS display_aliases (
    entity_id   TEXT PRIMARY KEY,
    alias       TEXT NOT NULL,
    origin      TEXT NOT NULL DEFAULT '',
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now'))
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


def init_display_aliases() -> bool:
    global _initialized
    if _initialized: return True
    conn = _get_conn()
    if conn:
        try:
            conn.autocommit = True
            cur = conn.cursor()
            for stmt in _DDL_PG.strip().split(';'):
                stmt = stmt.strip()
                if stmt: cur.execute(stmt)
            cur.close(); conn.close()
            _initialized = True
            log.info("display_aliases table ready (PG)")
            return True
        except Exception as e:
            log.warning("display_aliases init (PG) failed: %s", e)
            try: conn.close()
            except Exception: pass
    try:
        from api.db.base import get_sync_engine
        from sqlalchemy import text as _t
        sa = get_sync_engine().connect()
        sa.execute(_t(_DDL_SQLITE)); sa.commit(); sa.close()
        _initialized = True
        log.info("display_aliases table ready (SQLite)")
        return True
    except Exception as e:
        log.warning("display_aliases init (SQLite) failed: %s", e)
        return False


def list_aliases() -> list[dict]:
    if not _initialized: init_display_aliases()
    conn = _get_conn()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("SELECT entity_id, alias, origin, updated_at FROM display_aliases ORDER BY entity_id")
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            cur.close(); conn.close()
            for r in rows:
                try: r['updated_at'] = r['updated_at'].isoformat()
                except Exception: pass
            return rows
        except Exception: return []
    try:
        from api.db.base import get_sync_engine
        from sqlalchemy import text as _t
        sa = get_sync_engine().connect()
        rows = [dict(r) for r in sa.execute(_t(
            "SELECT entity_id, alias, origin, updated_at FROM display_aliases ORDER BY entity_id"
        )).mappings().fetchall()]
        sa.close()
        return rows
    except Exception: return []


def get_alias(entity_id: str) -> str | None:
    """Return alias for entity_id, or None if not set."""
    if not _initialized: init_display_aliases()
    conn = _get_conn()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("SELECT alias FROM display_aliases WHERE entity_id = %s", (entity_id,))
            row = cur.fetchone(); cur.close(); conn.close()
            return row[0] if row else None
        except Exception: return None
    try:
        from api.db.base import get_sync_engine
        from sqlalchemy import text as _t
        sa = get_sync_engine().connect()
        row = sa.execute(_t("SELECT alias FROM display_aliases WHERE entity_id = :id"), {"id": entity_id}).fetchone()
        sa.close()
        return row[0] if row else None
    except Exception: return None


def get_all_aliases() -> dict[str, str]:
    """Return {entity_id: alias} map — efficient for bulk lookups."""
    rows = list_aliases()
    return {r['entity_id']: r['alias'] for r in rows}


def set_alias(entity_id: str, alias: str, origin: str = "") -> bool:
    """Create or update an alias. origin is stored on first create, not overwritten on update."""
    if not _initialized: init_display_aliases()
    conn = _get_conn()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO display_aliases (entity_id, alias, origin) VALUES (%s, %s, %s) "
                "ON CONFLICT (entity_id) DO UPDATE SET alias = EXCLUDED.alias, updated_at = NOW()",
                (entity_id, alias, origin)
            )
            conn.commit(); cur.close(); conn.close()
            return True
        except Exception as e:
            log.warning("set_alias (PG) failed: %s", e)
            return False
    try:
        from api.db.base import get_sync_engine
        from sqlalchemy import text as _t
        sa = get_sync_engine().connect()
        existing = sa.execute(_t(
            "SELECT entity_id FROM display_aliases WHERE entity_id = :id"
        ), {"id": entity_id}).fetchone()
        if existing:
            sa.execute(_t(
                "UPDATE display_aliases SET alias = :alias, updated_at = datetime('now') WHERE entity_id = :id"
            ), {"alias": alias, "id": entity_id})
        else:
            sa.execute(_t(
                "INSERT INTO display_aliases (entity_id, alias, origin) VALUES (:id, :alias, :origin)"
            ), {"id": entity_id, "alias": alias, "origin": origin})
        sa.commit(); sa.close()
        return True
    except Exception as e:
        log.warning("set_alias (SQLite) failed: %s", e)
        return False


def delete_alias(entity_id: str) -> bool:
    """Remove alias — display falls back to origin."""
    if not _initialized: init_display_aliases()
    conn = _get_conn()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM display_aliases WHERE entity_id = %s", (entity_id,))
            conn.commit(); cur.close(); conn.close()
            return True
        except Exception: return False
    try:
        from api.db.base import get_sync_engine
        from sqlalchemy import text as _t
        sa = get_sync_engine().connect()
        sa.execute(_t("DELETE FROM display_aliases WHERE entity_id = :id"), {"id": entity_id})
        sa.commit(); sa.close()
        return True
    except Exception: return False
