"""Infra inventory — lightweight SOT for discovered hostnames, IPs, aliases.

Populated by collectors. Read by vm_exec, capability injection,
and the infra_lookup tool. No manual entry required — auto-discovered.
"""
import json
import logging
import os
from datetime import datetime, timezone

log = logging.getLogger(__name__)

_DDL_PG = """
CREATE TABLE IF NOT EXISTS infra_inventory (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    connection_id   TEXT NOT NULL,
    platform        TEXT NOT NULL,
    label           TEXT NOT NULL,
    hostname        TEXT DEFAULT '',
    ips             JSONB DEFAULT '[]',
    aliases         JSONB DEFAULT '[]',
    ports           JSONB DEFAULT '{}',
    meta            JSONB DEFAULT '{}',
    last_discovered TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(connection_id)
);
CREATE INDEX IF NOT EXISTS idx_infra_inventory_hostname ON infra_inventory(hostname);
CREATE INDEX IF NOT EXISTS idx_infra_inventory_platform ON infra_inventory(platform);
"""

_DDL_SQLITE = """
CREATE TABLE IF NOT EXISTS infra_inventory (
    id              TEXT PRIMARY KEY,
    connection_id   TEXT NOT NULL UNIQUE,
    platform        TEXT NOT NULL,
    label           TEXT NOT NULL,
    hostname        TEXT DEFAULT '',
    ips             TEXT DEFAULT '[]',
    aliases         TEXT DEFAULT '[]',
    ports           TEXT DEFAULT '{}',
    meta            TEXT DEFAULT '{}',
    last_discovered TEXT DEFAULT (datetime('now'))
);
"""


def _ts():
    return datetime.now(timezone.utc).isoformat()


def _is_pg():
    return "postgres" in os.environ.get("DATABASE_URL", "")


def init_inventory():
    """Create infra_inventory table if not exists. Called on startup."""
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
            log.info("infra_inventory table ready (PostgreSQL)")
            return True
        except Exception as e:
            log.warning("infra_inventory init (PG) failed: %s", e)
    try:
        from api.connections import _get_sa_conn
        from sqlalchemy import text as _text
        sa = _get_sa_conn()
        if sa:
            sa.execute(_text(_DDL_SQLITE))
            sa.commit()
            sa.close()
            log.info("infra_inventory table ready (SQLite)")
            return True
    except Exception as e:
        log.warning("infra_inventory init (SQLite) failed: %s", e)
    return False


def upsert_entity(connection_id, platform, label, hostname="",
                  ips=None, aliases=None, ports=None, meta=None):
    """Insert or update an inventory entry. Safe to call on every poll cycle."""
    import uuid
    ips = ips or []
    aliases = aliases or []
    ports = ports or {}
    meta = meta or {}

    if _is_pg():
        try:
            from api.connections import _get_conn
            conn = _get_conn()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO infra_inventory
                    (id, connection_id, platform, label, hostname, ips, aliases, ports, meta, last_discovered)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (connection_id) DO UPDATE SET
                    label=EXCLUDED.label, hostname=EXCLUDED.hostname, ips=EXCLUDED.ips,
                    aliases=EXCLUDED.aliases, ports=EXCLUDED.ports, meta=EXCLUDED.meta,
                    last_discovered=EXCLUDED.last_discovered
            """, (str(uuid.uuid4()), connection_id, platform, label, hostname,
                  json.dumps(ips), json.dumps(aliases), json.dumps(ports), json.dumps(meta), _ts()))
            conn.commit()
            cur.close()
            conn.close()
            return True
        except Exception as e:
            log.debug("upsert_entity (PG) failed: %s", e)
    return False


def resolve_host(query):
    """Resolve a hostname/alias/label/IP to an inventory entry.
    Returns first match or None."""
    if not query:
        return None
    q = query.lower().strip()

    if _is_pg():
        try:
            from api.connections import _get_conn
            conn = _get_conn()
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM infra_inventory
                WHERE lower(label) = %s OR lower(hostname) = %s
                   OR ips::jsonb @> %s::jsonb OR aliases::jsonb @> %s::jsonb
                   OR lower(label) LIKE %s
                ORDER BY CASE
                    WHEN lower(label) = %s THEN 1
                    WHEN lower(hostname) = %s THEN 2
                    WHEN lower(label) LIKE %s THEN 3
                    ELSE 4 END
                LIMIT 1
            """, (q, q, json.dumps([query]), json.dumps([query]), f"%{q}%", q, q, f"%{q}%"))
            cols = [d[0] for d in cur.description]
            row = cur.fetchone()
            cur.close()
            conn.close()
            if not row:
                return None
            r = dict(zip(cols, row))
            for f in ("ips", "aliases", "ports", "meta"):
                if isinstance(r.get(f), str):
                    try: r[f] = json.loads(r[f])
                    except Exception: pass
            return r
        except Exception as e:
            log.debug("resolve_host (PG) failed: %s", e)
    return None


def list_inventory(platform=""):
    """Return all inventory entries, optionally filtered by platform."""
    if _is_pg():
        try:
            from api.connections import _get_conn
            conn = _get_conn()
            cur = conn.cursor()
            if platform:
                cur.execute("SELECT * FROM infra_inventory WHERE platform = %s ORDER BY label", (platform,))
            else:
                cur.execute("SELECT * FROM infra_inventory ORDER BY platform, label")
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
            cur.close()
            conn.close()
            for r in rows:
                for f in ("ips", "aliases", "ports", "meta"):
                    if isinstance(r.get(f), str):
                        try: r[f] = json.loads(r[f])
                        except Exception: pass
            return rows
        except Exception as e:
            log.debug("list_inventory (PG) failed: %s", e)
    return []
