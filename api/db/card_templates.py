"""card_templates — stores card layout templates per card type or per connection.

A template is a dict of ordered field-key arrays per section:
  {
    "header_sub": ["image"],          # max 1 field — shown below card name when collapsed
    "collapsed": ["running_version", "built_at", "version_status", "uptime"],  # max 10
    "expanded": ["endpoint", "volumes", "pull_date", "actions"],               # no limit
    "entity_only": ["ports", "networks", "ip_addresses"],                      # entity drawer only
    "hidden": []                                                                # not shown
  }

scope_type:
  'type'        — default template for all cards of a given card_type
  'connection'  — per-connection override (scope_id = connection UUID)
"""
import json
import logging
import os
import uuid
from datetime import datetime, timezone

log = logging.getLogger(__name__)

_DDL_PG = """
CREATE TABLE IF NOT EXISTS card_templates (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scope_type  TEXT NOT NULL DEFAULT 'type',
    scope_id    TEXT NOT NULL,
    template    JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(scope_type, scope_id)
);
"""

_DDL_SQLITE = """
CREATE TABLE IF NOT EXISTS card_templates (
    id          TEXT PRIMARY KEY,
    scope_type  TEXT NOT NULL DEFAULT 'type',
    scope_id    TEXT NOT NULL,
    template    TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(scope_type, scope_id)
);
"""

# Default templates — canonical field order for each card type.
# These ship as the initial DB state; user edits override per scope.
DEFAULT_TEMPLATES = {
    "container": {
        "header_sub":  ["image"],
        "collapsed":   ["running_version", "built_at", "version_status", "uptime"],
        "expanded":    ["endpoint", "volumes", "pull_date", "actions"],
        "entity_only": ["ports", "networks", "ip_addresses"],
        "hidden":      [],
    },
    "swarm_service": {
        "header_sub":  ["image"],
        "collapsed":   ["replicas", "uptime"],
        "expanded":    ["ports", "volumes", "actions"],
        "entity_only": ["networks", "ip_addresses"],
        "hidden":      [],
    },
    "proxmox_vm": {
        "header_sub":  ["node_type"],
        "collapsed":   ["cpu", "ram", "status"],
        "expanded":    ["disks", "actions"],
        "entity_only": [],
        "hidden":      [],
    },
}

_initialized = False


def _ts(): return datetime.now(timezone.utc).isoformat()
def _is_pg(): return bool(os.environ.get("DATABASE_URL", ""))


def _get_conn():
    if not _is_pg(): return None
    import psycopg2
    dsn = os.environ.get("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")
    return psycopg2.connect(dsn)


def init_card_templates() -> bool:
    global _initialized
    if _initialized: return True

    conn = _get_conn()
    if conn:
        try:
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute(_DDL_PG)
            cur.close()
            conn.autocommit = False
            _seed_defaults_pg(conn)
            conn.close()
            _initialized = True
            log.info("card_templates table ready (PG)")
            return True
        except Exception as e:
            log.warning("card_templates init (PG) failed: %s", e)
            try: conn.close()
            except Exception: pass

    try:
        from api.db.base import get_sync_engine
        from sqlalchemy import text as _t
        sa = get_sync_engine().connect()
        sa.execute(_t(_DDL_SQLITE))
        sa.commit()
        _seed_defaults_sqlite(sa)
        sa.close()
        _initialized = True
        log.info("card_templates table ready (SQLite)")
        return True
    except Exception as e:
        log.warning("card_templates init (SQLite) failed: %s", e)
        return False


def _seed_defaults_pg(conn) -> None:
    try:
        cur = conn.cursor()
        for card_type, template in DEFAULT_TEMPLATES.items():
            cur.execute(
                "INSERT INTO card_templates (scope_type, scope_id, template) "
                "VALUES ('type', %s, %s) ON CONFLICT (scope_type, scope_id) DO NOTHING",
                (card_type, json.dumps(template))
            )
        conn.commit()
        cur.close()
    except Exception as e:
        log.warning("_seed_defaults_pg failed: %s", e)
        try: conn.rollback()
        except Exception: pass


def _seed_defaults_sqlite(sa) -> None:
    try:
        from sqlalchemy import text as _t
        for card_type, template in DEFAULT_TEMPLATES.items():
            sa.execute(_t(
                "INSERT OR IGNORE INTO card_templates (id, scope_type, scope_id, template) "
                "VALUES (:id, 'type', :sid, :tmpl)"
            ), {"id": str(uuid.uuid4()), "sid": card_type, "tmpl": json.dumps(template)})
        sa.commit()
    except Exception as e:
        log.warning("_seed_defaults_sqlite failed: %s", e)


def _parse_template(raw) -> dict:
    """Parse template from DB (JSONB or JSON string) to dict."""
    if isinstance(raw, dict): return raw
    try: return json.loads(raw)
    except Exception: return {}


def get_template(scope_type: str, scope_id: str) -> dict | None:
    """Get template for given scope. Returns None if not found."""
    if not _initialized: init_card_templates()
    conn = _get_conn()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT template FROM card_templates WHERE scope_type = %s AND scope_id = %s",
                (scope_type, scope_id)
            )
            row = cur.fetchone()
            cur.close(); conn.close()
            return _parse_template(row[0]) if row else None
        except Exception: return None
    try:
        from api.db.base import get_sync_engine
        from sqlalchemy import text as _t
        sa = get_sync_engine().connect()
        row = sa.execute(_t(
            "SELECT template FROM card_templates WHERE scope_type = :st AND scope_id = :sid"
        ), {"st": scope_type, "sid": scope_id}).fetchone()
        sa.close()
        return _parse_template(row[0]) if row else None
    except Exception: return None


def upsert_template(scope_type: str, scope_id: str, template: dict) -> bool:
    """Create or update a template. Returns True on success."""
    if not _initialized: init_card_templates()
    conn = _get_conn()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO card_templates (scope_type, scope_id, template) "
                "VALUES (%s, %s, %s) ON CONFLICT (scope_type, scope_id) "
                "DO UPDATE SET template = EXCLUDED.template, updated_at = NOW()",
                (scope_type, scope_id, json.dumps(template))
            )
            conn.commit(); cur.close(); conn.close()
            return True
        except Exception as e:
            log.warning("upsert_template (PG) failed: %s", e)
            return False
    try:
        from api.db.base import get_sync_engine
        from sqlalchemy import text as _t
        sa = get_sync_engine().connect()
        existing = sa.execute(_t(
            "SELECT id FROM card_templates WHERE scope_type = :st AND scope_id = :sid"
        ), {"st": scope_type, "sid": scope_id}).fetchone()
        if existing:
            sa.execute(_t(
                "UPDATE card_templates SET template = :tmpl WHERE scope_type = :st AND scope_id = :sid"
            ), {"tmpl": json.dumps(template), "st": scope_type, "sid": scope_id})
        else:
            sa.execute(_t(
                "INSERT INTO card_templates (id, scope_type, scope_id, template) "
                "VALUES (:id, :st, :sid, :tmpl)"
            ), {"id": str(uuid.uuid4()), "st": scope_type, "sid": scope_id, "tmpl": json.dumps(template)})
        sa.commit(); sa.close()
        return True
    except Exception as e:
        log.warning("upsert_template (SQLite) failed: %s", e)
        return False


def delete_template(scope_type: str, scope_id: str) -> bool:
    """Delete a connection-scoped template override (reset to type default)."""
    if scope_type == 'type':
        log.warning("Refusing to delete type-level template for %s", scope_id)
        return False
    conn = _get_conn()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM card_templates WHERE scope_type = %s AND scope_id = %s",
                (scope_type, scope_id)
            )
            conn.commit(); cur.close(); conn.close()
            return True
        except Exception: return False
    try:
        from api.db.base import get_sync_engine
        from sqlalchemy import text as _t
        sa = get_sync_engine().connect()
        sa.execute(_t(
            "DELETE FROM card_templates WHERE scope_type = :st AND scope_id = :sid"
        ), {"st": scope_type, "sid": scope_id})
        sa.commit(); sa.close()
        return True
    except Exception: return False


def resolve_template(card_type: str, connection_id: str | None = None) -> dict:
    """Resolve effective template: per-connection override -> type default -> hardcoded default."""
    if connection_id:
        override = get_template('connection', connection_id)
        if override:
            return override
    type_tmpl = get_template('type', card_type)
    if type_tmpl:
        return type_tmpl
    return DEFAULT_TEMPLATES.get(card_type, {})
