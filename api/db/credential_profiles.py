"""Credential profiles — named, encrypted auth sets shared across connections.

credential_profiles table:
  id          UUID PK
  name        TEXT UNIQUE NOT NULL        -- human label, e.g. "ubuntu-ssh-key"
  auth_type   TEXT NOT NULL               -- ssh_key | password | api_key | token
  credentials TEXT NOT NULL               -- Fernet-encrypted JSON
  created_at  TIMESTAMPTZ DEFAULT NOW()
  updated_at  TIMESTAMPTZ DEFAULT NOW()
"""
import json
import logging
import os
import uuid
from datetime import datetime, timezone

from api.crypto import encrypt_value, decrypt_value

log = logging.getLogger(__name__)

_DDL_PG = """
CREATE TABLE IF NOT EXISTS credential_profiles (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    auth_type   TEXT NOT NULL DEFAULT 'ssh_key',
    credentials TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(name)
);
"""

_DDL_SQLITE = """
CREATE TABLE IF NOT EXISTS credential_profiles (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    auth_type   TEXT NOT NULL DEFAULT 'ssh_key',
    credentials TEXT NOT NULL DEFAULT '',
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(name)
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


def init_credential_profiles() -> bool:
    global _initialized
    if _initialized: return True
    conn = _get_conn()
    if conn:
        try:
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute(_DDL_PG)
            cur.close(); conn.close()
            _initialized = True
            log.info("credential_profiles table ready (PG)")
            return True
        except Exception as e:
            log.warning("credential_profiles init (PG) failed: %s", e)
            try: conn.close()
            except Exception: pass
    try:
        from api.db.base import get_sync_engine
        from sqlalchemy import text as _t
        sa = get_sync_engine().connect()
        sa.execute(_t(_DDL_SQLITE)); sa.commit(); sa.close()
        _initialized = True
        log.info("credential_profiles table ready (SQLite)")
        return True
    except Exception as e:
        log.warning("credential_profiles init (SQLite) failed: %s", e)
        return False


def list_profiles() -> list[dict]:
    """List all profiles — credentials masked."""
    conn = _get_conn()
    rows = []
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("SELECT id, name, auth_type, created_at, updated_at FROM credential_profiles ORDER BY name")
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            cur.close(); conn.close()
        except Exception as e:
            log.warning("list_profiles failed: %s", e)
    else:
        try:
            from api.db.base import get_sync_engine
            from sqlalchemy import text as _t
            sa = get_sync_engine().connect()
            rows = [dict(r) for r in sa.execute(_t(
                "SELECT id, name, auth_type, created_at, updated_at FROM credential_profiles ORDER BY name"
            )).mappings().fetchall()]
            sa.close()
        except Exception:
            pass
    for r in rows:
        r['id'] = str(r['id'])
        if r.get('created_at'):
            try: r['created_at'] = r['created_at'].isoformat()
            except Exception: pass
    return rows


def get_profile(profile_id: str) -> dict | None:
    """Get a profile with decrypted credentials."""
    conn = _get_conn()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM credential_profiles WHERE id = %s", (profile_id,))
            cols = [d[0] for d in cur.description]
            row = cur.fetchone()
            cur.close(); conn.close()
            if not row: return None
            result = dict(zip(cols, row))
            result['id'] = str(result['id'])
            raw = result.get('credentials', '')
            if raw:
                dec = decrypt_value(raw)
                try: result['credentials'] = json.loads(dec)
                except Exception: result['credentials'] = dec
            return result
        except Exception as e:
            log.warning("get_profile failed: %s", e)
            return None
    return None


def create_profile(name: str, auth_type: str, credentials: dict) -> dict:
    conn = _get_conn()
    if not conn:
        return {"status": "error", "message": "No database connection"}
    try:
        pid = str(uuid.uuid4())
        enc = encrypt_value(json.dumps(credentials))
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO credential_profiles (id, name, auth_type, credentials) VALUES (%s, %s, %s, %s)",
            (pid, name, auth_type, enc)
        )
        conn.commit(); cur.close(); conn.close()
        return {"status": "ok", "id": pid, "message": f"Profile '{name}' created"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def update_profile(profile_id: str, name: str = None, credentials: dict = None) -> dict:
    conn = _get_conn()
    if not conn:
        return {"status": "error", "message": "No database connection"}
    try:
        sets, params = ["updated_at = NOW()"], []
        if name:
            sets.append("name = %s"); params.append(name)
        if credentials:
            existing = get_profile(profile_id)
            merged = {**(existing.get('credentials') or {}), **credentials}
            sets.append("credentials = %s"); params.append(encrypt_value(json.dumps(merged)))
        params.append(profile_id)
        cur = conn.cursor()
        cur.execute(f"UPDATE credential_profiles SET {', '.join(sets)} WHERE id = %s", params)
        conn.commit(); cur.close(); conn.close()
        return {"status": "ok", "message": "Profile updated"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def delete_profile(profile_id: str) -> dict:
    conn = _get_conn()
    if not conn:
        return {"status": "error", "message": "No database connection"}
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM credential_profiles WHERE id = %s", (profile_id,))
        deleted = cur.rowcount
        conn.commit(); cur.close(); conn.close()
        return {"status": "ok" if deleted else "error",
                "message": "Profile deleted" if deleted else "Not found"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def resolve_credentials_for_connection(connection: dict, all_connections: list[dict]) -> dict:
    """Return effective credentials for a connection.

    Priority:
    1. Connection's own inline credentials (if non-empty username or key)
    2. Linked credential profile (connection.config.credential_profile_id)
    3. Shared credential connection (existing shared_credentials fallback)
    """
    creds = connection.get('credentials') or {}
    if isinstance(creds, str):
        try: creds = json.loads(creds)
        except Exception: creds = {}

    # Has its own credentials
    if creds.get('username') or creds.get('private_key') or creds.get('password'):
        return creds

    # Linked profile
    cfg = connection.get('config') or {}
    if isinstance(cfg, str):
        try: cfg = json.loads(cfg)
        except Exception: cfg = {}
    profile_id = cfg.get('credential_profile_id')
    if profile_id:
        profile = get_profile(profile_id)
        if profile:
            return profile.get('credentials') or {}

    # Shared credential fallback (existing behaviour)
    for c in all_connections:
        if c['id'] == connection['id']: continue
        c_cfg = c.get('config') or {}
        if isinstance(c_cfg, str):
            try: c_cfg = json.loads(c_cfg)
            except Exception: c_cfg = {}
        if c_cfg.get('shared_credentials'):
            c_creds = c.get('credentials') or {}
            if isinstance(c_creds, str):
                try: c_creds = json.loads(c_creds)
                except Exception: c_creds = {}
            if c_creds.get('username') or c_creds.get('private_key'):
                return c_creds

    return creds
