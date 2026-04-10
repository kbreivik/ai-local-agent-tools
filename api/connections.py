"""Connections manager — CRUD for platform connections with encrypted credentials.

Each connection stores host, port, auth type, encrypted credentials,
and platform-specific config. Plugins/skills resolve connections by
platform name instead of reading env vars directly.
"""
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from api.crypto import encrypt_value, decrypt_value

log = logging.getLogger(__name__)

_CONNECTIONS_DDL_PG = """
CREATE TABLE IF NOT EXISTS connections (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    platform    TEXT NOT NULL,
    label       TEXT NOT NULL,
    host        TEXT NOT NULL,
    port        INTEGER DEFAULT 443,
    auth_type   TEXT DEFAULT 'token',
    credentials TEXT DEFAULT '',
    enabled     BOOLEAN DEFAULT true,
    verified    BOOLEAN DEFAULT false,
    last_seen   TIMESTAMPTZ,
    config      JSONB DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(platform, label)
);
"""

_CONNECTIONS_DDL_SQLITE = """
CREATE TABLE IF NOT EXISTS connections (
    id          TEXT PRIMARY KEY,
    platform    TEXT NOT NULL,
    label       TEXT NOT NULL,
    host        TEXT NOT NULL,
    port        INTEGER DEFAULT 443,
    auth_type   TEXT DEFAULT 'token',
    credentials TEXT DEFAULT '',
    enabled     INTEGER DEFAULT 1,
    verified    INTEGER DEFAULT 0,
    last_seen   TEXT,
    config      TEXT DEFAULT '{}',
    created_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(platform, label)
);
"""

_initialized = False


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_postgres() -> bool:
    return bool(os.environ.get("DATABASE_URL", ""))


def _get_conn():
    """Get a psycopg2 connection for direct SQL. Returns None if not PostgreSQL."""
    if not _is_postgres():
        return None
    import psycopg2
    dsn = os.environ.get("DATABASE_URL", "")
    dsn = dsn.replace("postgresql+asyncpg://", "postgresql://")
    return psycopg2.connect(dsn)


def _get_sa_conn():
    """Get a SQLAlchemy sync connection (works with both PG and SQLite)."""
    try:
        from api.db.base import get_sync_engine
        return get_sync_engine().connect()
    except Exception:
        return None


def init_connections() -> bool:
    """Create the connections table. Works with both PostgreSQL and SQLite.

    Returns True if table is ready, False otherwise. Safe to call multiple times.
    """
    global _initialized
    if _initialized:
        return True

    # Try PostgreSQL first
    conn = _get_conn()
    if conn:
        try:
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute(_CONNECTIONS_DDL_PG)
            cur.close()
            conn.close()
            _initialized = True
            log.info("Connections table ready (PostgreSQL)")
            return True
        except Exception as e:
            log.warning("Connections table init failed (PG): %s", e)
            try:
                conn.close()
            except Exception:
                pass

    # SQLite fallback via SQLAlchemy
    sa_conn = _get_sa_conn()
    if not sa_conn:
        return False
    try:
        from sqlalchemy import text as _text
        sa_conn.execute(_text(_CONNECTIONS_DDL_SQLITE))
        sa_conn.commit()
        sa_conn.close()
        _initialized = True
        log.info("Connections table ready (SQLite)")
        return True
    except Exception as e:
        log.warning("Connections table init failed (SQLite): %s", e)
        try:
            sa_conn.close()
        except Exception:
            pass
        return False


def list_connections(platform: str = "") -> list[dict]:
    """List all connections, optionally filtered by platform. Credentials masked."""
    conn = _get_conn()
    if conn:
        try:
            cur = conn.cursor()
            if platform:
                cur.execute("SELECT * FROM connections WHERE platform = %s ORDER BY platform, label", (platform,))
            else:
                cur.execute("SELECT * FROM connections ORDER BY platform, label")
            cols = [desc[0] for desc in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
            cur.close()
            conn.close()
        except Exception as e:
            log.warning("list_connections (PG) failed: %s", e)
            rows = []
    else:
        # SQLite fallback
        try:
            from sqlalchemy import text as _text
            sa = _get_sa_conn()
            if not sa:
                return []
            q = "SELECT * FROM connections WHERE platform=:p ORDER BY platform, label" if platform else "SELECT * FROM connections ORDER BY platform, label"
            params = {"p": platform} if platform else {}
            rows = [dict(r) for r in sa.execute(_text(q), params).mappings().fetchall()]
            sa.close()
        except Exception:
            return []

    # Mask credentials in list view
    for r in rows:
        r["credentials"] = "***" if r.get("credentials") else ""
        if r.get("last_seen"):
            try:
                r["last_seen"] = r["last_seen"].isoformat()
            except AttributeError:
                pass  # already a string (SQLite)
        if r.get("created_at"):
            try:
                r["created_at"] = r["created_at"].isoformat()
            except AttributeError:
                pass
        r["id"] = str(r["id"])
    return rows


def get_connection(id_or_label: str) -> dict | None:
    """Get a single connection with decrypted credentials."""
    conn = _get_conn()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        # Try UUID first, then label
        try:
            uuid.UUID(id_or_label)
            cur.execute("SELECT * FROM connections WHERE id = %s", (id_or_label,))
        except ValueError:
            cur.execute("SELECT * FROM connections WHERE label = %s LIMIT 1", (id_or_label,))
        cols = [desc[0] for desc in cur.description]
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return None
        result = dict(zip(cols, row))
        # Decrypt credentials
        raw_creds = result.get("credentials", "")
        if raw_creds:
            decrypted = decrypt_value(raw_creds)
            try:
                result["credentials"] = json.loads(decrypted)
            except (json.JSONDecodeError, TypeError):
                result["credentials"] = decrypted
        result["id"] = str(result["id"])
        if result.get("last_seen"):
            result["last_seen"] = result["last_seen"].isoformat()
        if result.get("created_at"):
            result["created_at"] = result["created_at"].isoformat()
        return result
    except Exception as e:
        log.warning("get_connection failed: %s", e)
        return None


def create_connection(
    platform: str, label: str, host: str, port: int = 443,
    auth_type: str = "token", credentials: dict = None,
    config: dict = None, enabled: bool = True,
) -> dict:
    """Create a new connection. Credentials are encrypted."""
    conn = _get_conn()
    if not conn:
        return {"status": "error", "message": "No database connection"}
    try:
        creds_str = json.dumps(credentials or {})
        encrypted_creds = encrypt_value(creds_str) if creds_str else ""
        config_json = json.dumps(config or {})
        cid = str(uuid.uuid4())
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO connections (id, platform, label, host, port, auth_type, credentials, enabled, config)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (cid, platform, label, host, port, auth_type, encrypted_creds, enabled, config_json))
        conn.commit()
        cur.close()
        conn.close()
        log.info("Connection created: %s/%s → %s:%d", platform, label, host, port)
        return {"status": "ok", "id": cid, "message": f"Connection '{label}' created"}
    except Exception as e:
        log.warning("create_connection failed: %s", e)
        return {"status": "error", "message": str(e)}


def update_connection(connection_id: str, **kwargs) -> dict:
    """Partial update of a connection. Credentials re-encrypted if changed."""
    conn = _get_conn()
    if not conn:
        return {"status": "error", "message": "No database connection"}
    try:
        sets = []
        params = []
        for field in ("label", "host", "port", "auth_type", "enabled", "verified"):
            if field in kwargs:
                sets.append(f"{field} = %s")
                params.append(kwargs[field])
        if "credentials" in kwargs:
            new_creds = kwargs["credentials"]
            if isinstance(new_creds, dict) and new_creds:
                # Merge with existing credentials — don't wipe keys the user didn't send
                existing = get_connection(connection_id)
                existing_creds = existing.get("credentials", {}) if existing else {}
                if isinstance(existing_creds, dict):
                    merged = {**existing_creds, **new_creds}
                else:
                    merged = new_creds
                creds_str = json.dumps(merged)
            else:
                creds_str = json.dumps(new_creds if isinstance(new_creds, dict) else {})
            sets.append("credentials = %s")
            params.append(encrypt_value(creds_str) if creds_str else "")
        if "config" in kwargs:
            sets.append("config = %s")
            params.append(json.dumps(kwargs["config"]))
        if "last_seen" in kwargs:
            sets.append("last_seen = %s")
            params.append(kwargs["last_seen"])
        if not sets:
            return {"status": "ok", "message": "Nothing to update"}
        params.append(connection_id)
        cur = conn.cursor()
        cur.execute(f"UPDATE connections SET {', '.join(sets)} WHERE id = %s", params)
        conn.commit()
        cur.close()
        conn.close()
        return {"status": "ok", "message": "Connection updated"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def delete_connection(connection_id: str) -> dict:
    """Delete a connection by ID."""
    conn = _get_conn()
    if not conn:
        return {"status": "error", "message": "No database connection"}
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM connections WHERE id = %s", (connection_id,))
        deleted = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        if deleted:
            return {"status": "ok", "message": "Connection deleted"}
        return {"status": "error", "message": "Connection not found"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def test_connection(connection_id: str) -> dict:
    """Test a connection by probing its platform health endpoint (same logic as
    ExternalServicesCollector) so auth, path, and scheme are always correct."""
    connection = get_connection(connection_id)
    if not connection:
        return {"status": "error", "message": "Connection not found"}

    platform = connection["platform"]
    now = _ts()

    # Use the platform-specific health check from ExternalServicesCollector
    try:
        from api.collectors.external_services import PLATFORM_HEALTH, ExternalServicesCollector
        health_cfg = PLATFORM_HEALTH.get(platform)
        if health_cfg:
            collector = ExternalServicesCollector()
            result = collector._probe_connection(connection, health_cfg)
            ok = result.get("dot") == "green"
            update_connection(connection_id, verified=ok, last_seen=now)
            return {
                "status": "ok" if ok else "error",
                "data": {
                    "reachable": result.get("reachable", False),
                    "latency_ms": result.get("latency_ms"),
                    "summary": result.get("summary", ""),
                    "dot": result.get("dot", "red"),
                },
                "timestamp": now,
                "message": result.get("summary") or result.get("problem") or "unreachable",
            }
    except Exception as e:
        log.warning("test_connection platform probe failed (%s): %s", platform, e)

    # Docker host — direct Docker API test
    if platform == 'docker_host':
        try:
            import docker
            host = connection["host"]
            port = connection.get("port", 2375)
            if host.startswith("unix://") or host.startswith("/"):
                url = host
            else:
                url = f"tcp://{host}:{port}"
            client = docker.DockerClient(base_url=url, timeout=5)
            info = client.info()
            client.close()
            is_swarm = info.get("Swarm", {}).get("LocalNodeState") == "active"
            update_connection(connection_id, verified=True, last_seen=now)
            return {
                "status": "ok",
                "data": {
                    "docker_version": info.get("ServerVersion"),
                    "is_swarm": is_swarm,
                    "containers": info.get("Containers", 0),
                    "swarm_role": "manager" if info.get("Swarm", {}).get("ControlAvailable") else "worker",
                },
                "timestamp": now,
                "message": f"Docker {info.get('ServerVersion')} — {'swarm manager' if is_swarm else 'standalone'}",
            }
        except Exception as e:
            update_connection(connection_id, verified=False, last_seen=now)
            return {"status": "error", "data": None, "timestamp": now, "message": str(e)}

    # Fallback for platforms not in PLATFORM_HEALTH: generic HTTPS reachability check
    try:
        import httpx
        host = connection["host"]
        port = connection.get("port", 443)
        # Treat any port that is known-HTTPS or >1024 and unknown as https
        https_ports = {443, 8443, 8006, 8007, 9443, 5001, 8001}
        scheme = "https" if port in https_ports else "http"
        r = httpx.get(f"{scheme}://{host}:{port}/", verify=False, timeout=10,
                      follow_redirects=True)
        ok = r.status_code < 500
        update_connection(connection_id, verified=ok, last_seen=now)
        return {
            "status": "ok" if ok else "error",
            "data": {"http_status": r.status_code},
            "timestamp": now,
            "message": f"HTTP {r.status_code}",
        }
    except Exception as e:
        update_connection(connection_id, verified=False, last_seen=now)
        return {"status": "error", "data": None, "timestamp": now, "message": str(e)}


def mark_connection_verified(connection_id: str, verified: bool) -> None:
    """Update verified status and last_seen after a probe."""
    if not connection_id:
        return
    now = datetime.now(timezone.utc).isoformat()
    try:
        update_connection(connection_id, verified=verified, last_seen=now)
    except Exception as e:
        log.debug("mark_connection_verified failed: %s", e)


def _decode_creds(result: dict) -> dict:
    """Decrypt and parse credentials field in a connection row."""
    raw_creds = result.get("credentials", "")
    if raw_creds:
        decrypted = decrypt_value(raw_creds)
        try:
            result["credentials"] = json.loads(decrypted)
        except (json.JSONDecodeError, TypeError):
            result["credentials"] = decrypted
    result["id"] = str(result.get("id", ""))
    return result


def get_connection_for_platform(platform: str) -> dict | None:
    """Get the first enabled connection for a platform. Decrypted credentials included.

    Used by plugins/skills to resolve connection details instead of env vars.
    Works with both PostgreSQL (psycopg2) and SQLite (SQLAlchemy).
    """
    # Try PostgreSQL first
    conn = _get_conn()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM connections WHERE platform = %s AND enabled = true AND host != '' ORDER BY created_at LIMIT 1",
                (platform,),
            )
            cols = [desc[0] for desc in cur.description]
            row = cur.fetchone()
            cur.close()
            conn.close()
            if not row:
                return None
            return _decode_creds(dict(zip(cols, row)))
        except Exception:
            return None

    # SQLite fallback via SQLAlchemy
    try:
        from sqlalchemy import text as _text
        sa = _get_sa_conn()
        if not sa:
            return None
        row = sa.execute(
            _text("SELECT * FROM connections WHERE platform=:p AND enabled=1 AND host!='' ORDER BY created_at LIMIT 1"),
            {"p": platform},
        ).mappings().fetchone()
        sa.close()
        if not row:
            return None
        return _decode_creds(dict(row))
    except Exception:
        return None


def get_all_connections_for_platform(platform: str) -> list[dict]:
    """Get ALL enabled connections for a platform with decrypted credentials.

    Used by collectors that support multiple connections (e.g. multiple
    Proxmox clusters). Works with both PostgreSQL and SQLite.
    """
    # PostgreSQL
    conn = _get_conn()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM connections WHERE platform = %s AND enabled = true "
                "AND host != '' ORDER BY created_at",
                (platform,),
            )
            cols = [desc[0] for desc in cur.description]
            rows = [dict(zip(cols, row)) for row in cur.fetchall()]
            cur.close()
            conn.close()
            return [_decode_creds(r) for r in rows]
        except Exception:
            return []

    # SQLite fallback
    try:
        from sqlalchemy import text as _text
        sa = _get_sa_conn()
        if not sa:
            return []
        rows = sa.execute(
            _text("SELECT * FROM connections WHERE platform=:p AND enabled=1 "
                  "AND host!='' ORDER BY created_at"),
            {"p": platform},
        ).mappings().fetchall()
        sa.close()
        return [_decode_creds(dict(r)) for r in rows]
    except Exception:
        return []
