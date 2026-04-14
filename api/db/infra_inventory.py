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


# ── Cross-system reference storage ─────────────────────────────────────────────

def write_cross_reference(connection_id: str, platform: str, label: str,
                          aliases: list = None, ips: list = None,
                          hostname: str = "", meta: dict = None):
    """Write a cross-system reference to infra_inventory.

    Called by collectors to record entity identities from their perspective.
    For example, the Proxmox collector writes VM name, vmid, node so the
    vm_hosts collector's entry for the same physical host can be linked.

    Uses connection_id as the primary key — same host discovered by two collectors
    will have separate rows (one per collector's connection). The resolve_entity
    function merges them by IP overlap.
    """
    upsert_entity(
        connection_id=connection_id,
        platform=platform,
        label=label,
        hostname=hostname,
        ips=ips or [],
        aliases=aliases or [],
        meta=meta or {},
    )


def resolve_entity(query: str) -> dict:
    """Resolve any entity name across all known infrastructure systems.

    Search order and sources:
    1. infra_inventory: label exact, hostname exact, IP match, alias match, label partial
    2. connections table: label search across all platforms
    3. Cross-inventory: when a match is found, find other entries with overlapping IPs
       to build a complete cross-system identity map.

    Returns a merged dict with all known identities for the entity, or None.
    """
    if not query:
        return None
    q = query.lower().strip()

    if not _is_pg():
        return None  # Only supported on PostgreSQL

    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()

        # Step 1: Search infra_inventory
        cur.execute("""
            SELECT * FROM infra_inventory
            WHERE lower(label) = %(q)s
               OR lower(hostname) = %(q)s
               OR lower(label) LIKE %(like)s
               OR ips::text ILIKE %(iplike)s
               OR aliases::text ILIKE %(iplike)s
            ORDER BY CASE
                WHEN lower(label) = %(q)s THEN 1
                WHEN lower(hostname) = %(q)s THEN 2
                WHEN lower(label) LIKE %(like)s THEN 3
                ELSE 4 END
            LIMIT 5
        """, {"q": q, "like": f"%{q}%", "iplike": f"%{q}%"})
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]

        # Step 2: Search connections table (labels, hosts)
        cur.execute("""
            SELECT id::text, platform, label, host,
                   COALESCE(config::text, '{}') as config_raw
            FROM connections
            WHERE lower(label) ILIKE %(like)s
               OR host = %(q)s
            LIMIT 10
        """, {"q": q, "like": f"%{q}%"})
        conn_cols = [d[0] for d in cur.description]
        conn_rows = [dict(zip(conn_cols, r)) for r in cur.fetchall()]

        # Deserialize JSONB fields
        for r in rows:
            for f in ("ips", "aliases", "ports", "meta"):
                if isinstance(r.get(f), str):
                    try:
                        import json as _json
                        r[f] = _json.loads(r[f])
                    except Exception:
                        pass

        if not rows and not conn_rows:
            cur.close()
            conn.close()
            return None

        # Step 3: Collect all IPs from primary matches to find related entries
        all_ips = set()
        for r in rows:
            for ip in (r.get("ips") or []):
                all_ips.add(ip)
        for c in conn_rows:
            if c.get("host"):
                all_ips.add(c["host"])

        # Find other inventory entries that share IPs (same physical host)
        related_rows = []
        if all_ips:
            ip_conditions = " OR ".join(["ips::text ILIKE %s"] * len(all_ips))
            cur.execute(f"""
                SELECT * FROM infra_inventory
                WHERE {ip_conditions}
            """, [f"%{ip}%" for ip in all_ips])
            related_cols = [d[0] for d in cur.description]
            all_related = [dict(zip(related_cols, r)) for r in cur.fetchall()]
            for r in all_related:
                for f in ("ips", "aliases", "ports", "meta"):
                    if isinstance(r.get(f), str):
                        try:
                            import json as _json
                            r[f] = _json.loads(r[f])
                        except Exception:
                            pass
            related_rows = [r for r in all_related
                            if not any(r["id"] == row["id"] for row in rows)]

        cur.close()
        conn.close()

        # Merge into a unified identity dict
        primary = rows[0] if rows else None
        result = {
            "query": query,
            "found": bool(primary or conn_rows),
            "canonical_label": primary["label"] if primary else (conn_rows[0].get("label") if conn_rows else query),
            "hostname": primary["hostname"] if primary else "",
            "ips": list(all_ips),
            # All system-specific identities grouped by platform
            "identities": {},
            # Raw entries from each source
            "inventory_matches": rows,
            "connection_matches": conn_rows,
            "related_entries": related_rows,
        }

        # Build identities map: platform → what that system calls this entity
        for r in rows + related_rows:
            plat = r.get("platform", "unknown")
            meta = r.get("meta") or {}
            identity = {
                "label": r.get("label", ""),
                "hostname": r.get("hostname", ""),
                "ips": r.get("ips", []),
                "connection_id": r.get("connection_id", ""),
                "aliases": r.get("aliases", []),
            }
            identity.update({k: v for k, v in meta.items()
                             if k in ("vmid", "node", "role", "os_type", "swarm_node_id",
                                      "kafka_broker_id", "proxmox_connection_id")})
            result["identities"][plat] = result["identities"].get(plat, [])
            result["identities"][plat].append(identity)

        for c in conn_rows:
            plat = c.get("platform", "connection")
            identity = {
                "label": c.get("label", ""),
                "host": c.get("host", ""),
                "connection_id": c.get("id", ""),
            }
            result["identities"][plat] = result["identities"].get(plat, [])
            result["identities"][plat].append(identity)

        return result

    except Exception as e:
        log.debug("resolve_entity failed: %s", e)
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
