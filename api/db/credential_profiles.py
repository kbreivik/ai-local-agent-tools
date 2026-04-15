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
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    seq_id       BIGSERIAL UNIQUE,
    name         TEXT NOT NULL,
    auth_type    TEXT NOT NULL DEFAULT 'ssh',
    credentials  TEXT NOT NULL DEFAULT '',
    discoverable BOOLEAN NOT NULL DEFAULT false,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(name)
);
"""

# Migrations — safe to run on existing DB (IF NOT EXISTS / try-except per statement)
_MIGRATIONS_PG = [
    "ALTER TABLE credential_profiles ADD COLUMN IF NOT EXISTS seq_id BIGSERIAL",
    "ALTER TABLE credential_profiles ADD COLUMN IF NOT EXISTS discoverable BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE credential_profiles ADD CONSTRAINT IF NOT EXISTS credential_profiles_seq_id_key UNIQUE (seq_id)",
]

_DDL_SQLITE = """
CREATE TABLE IF NOT EXISTS credential_profiles (
    id           TEXT PRIMARY KEY,
    seq_id       INTEGER,
    name         TEXT NOT NULL,
    auth_type    TEXT NOT NULL DEFAULT 'ssh',
    credentials  TEXT NOT NULL DEFAULT '',
    discoverable INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT DEFAULT (datetime('now')),
    updated_at   TEXT DEFAULT (datetime('now')),
    UNIQUE(name),
    UNIQUE(seq_id)
);
"""

_MIGRATIONS_SQLITE = [
    "ALTER TABLE credential_profiles ADD COLUMN seq_id INTEGER",
    "ALTER TABLE credential_profiles ADD COLUMN discoverable INTEGER NOT NULL DEFAULT 0",
]

_initialized = False


def _ts(): return datetime.now(timezone.utc).isoformat()
def _is_pg(): return bool(os.environ.get("DATABASE_URL", ""))


def _get_conn():
    if not _is_pg(): return None
    import psycopg2
    dsn = os.environ.get("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")
    return psycopg2.connect(dsn)


def _seed_dummy_profile(conn_or_sa, is_pg: bool) -> None:
    """Ensure the seq_id=0 no-auth placeholder profile exists."""
    try:
        if is_pg:
            import psycopg2.extras
            cur = conn_or_sa.cursor()
            cur.execute(
                "INSERT INTO credential_profiles (seq_id, name, auth_type, credentials, discoverable) "
                "VALUES (0, '__no_credential__', 'none', '', false) "
                "ON CONFLICT (name) DO NOTHING"
            )
            conn_or_sa.commit()
            cur.close()
        else:
            from sqlalchemy import text as _t
            conn_or_sa.execute(_t(
                "INSERT OR IGNORE INTO credential_profiles (seq_id, name, auth_type, credentials, discoverable) "
                "VALUES (0, '__no_credential__', 'none', '', 0)"
            ))
            conn_or_sa.commit()
    except Exception as e:
        log.warning("Failed to seed dummy profile: %s", e)


def init_credential_profiles() -> bool:
    global _initialized
    if _initialized: return True

    conn = _get_conn()
    if conn:
        try:
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute(_DDL_PG)
            cur.close()
            # Run migrations (each wrapped — safe on fresh installs)
            conn.autocommit = False
            for stmt in _MIGRATIONS_PG:
                try:
                    cur2 = conn.cursor()
                    cur2.execute(stmt)
                    conn.commit()
                    cur2.close()
                except Exception:
                    conn.rollback()
            conn.autocommit = True
            conn.close()
            _initialized = True
            log.info("credential_profiles table ready (PG)")
            # Re-open for seeding
            conn2 = _get_conn()
            if conn2:
                conn2.autocommit = False
                _seed_dummy_profile(conn2, is_pg=True)
                conn2.close()
            return True
        except Exception as e:
            log.warning("credential_profiles init (PG) failed: %s", e)
            try: conn.close()
            except Exception: pass

    try:
        from api.db.base import get_sync_engine
        from sqlalchemy import text as _t
        sa = get_sync_engine().connect()
        sa.execute(_t(_DDL_SQLITE))
        sa.commit()
        for stmt in _MIGRATIONS_SQLITE:
            try:
                sa.execute(_t(stmt)); sa.commit()
            except Exception:
                pass
        _seed_dummy_profile(sa, is_pg=False)
        sa.close()
        _initialized = True
        log.info("credential_profiles table ready (SQLite)")
        return True
    except Exception as e:
        log.warning("credential_profiles init (SQLite) failed: %s", e)
        return False


def list_profiles() -> list[dict]:
    """List all profiles — credentials masked, safe fields included.

    Returns seq_id, name, auth_type, discoverable, linked_connections_count,
    and derived safe fields: username (non-secret), has_private_key, has_passphrase, has_password.
    """
    conn = _get_conn()
    rows = []
    if conn:
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, seq_id, name, auth_type, credentials, discoverable, created_at "
                "FROM credential_profiles ORDER BY COALESCE(seq_id, 999999), name"
            )
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
                "SELECT id, seq_id, name, auth_type, credentials, discoverable, created_at "
                "FROM credential_profiles ORDER BY COALESCE(seq_id, 999999), name"
            )).mappings().fetchall()]
            sa.close()
        except Exception:
            pass

    # Count linked connections per profile
    linked_counts = _count_linked_connections()

    for r in rows:
        r['id'] = str(r['id'])
        if r.get('created_at'):
            try: r['created_at'] = r['created_at'].isoformat()
            except Exception: pass
        # Derive safe fields from encrypted credentials
        raw = r.pop('credentials', '') or ''
        creds = {}
        if raw:
            try:
                dec = decrypt_value(raw)
                creds = json.loads(dec)
            except Exception:
                pass
        r['username']        = creds.get('username', '')
        r['has_private_key'] = bool(creds.get('private_key', ''))
        r['has_passphrase']  = bool(creds.get('passphrase', ''))
        r['has_password']    = bool(creds.get('password', ''))
        r['linked_connections_count'] = linked_counts.get(str(r['id']), 0)
        r['discoverable'] = bool(r.get('discoverable', False))
    return rows


def _count_linked_connections() -> dict:
    """Return {profile_id: count} of connections linked to each profile."""
    try:
        conn = _get_conn()
        if conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT config->>'credential_profile_id' AS pid, COUNT(*) "
                "FROM connections WHERE config->>'credential_profile_id' IS NOT NULL "
                "GROUP BY config->>'credential_profile_id'"
            )
            result = {str(r[0]): r[1] for r in cur.fetchall()}
            cur.close(); conn.close()
            return result
        from api.db.base import get_sync_engine
        from sqlalchemy import text as _t
        sa = get_sync_engine().connect()
        rows = sa.execute(_t(
            "SELECT json_extract(config,'$.credential_profile_id') AS pid, COUNT(*) AS cnt "
            "FROM connections WHERE json_extract(config,'$.credential_profile_id') IS NOT NULL "
            "GROUP BY pid"
        )).fetchall()
        sa.close()
        return {str(r[0]): r[1] for r in rows}
    except Exception:
        return {}


def get_profile_safe(profile_id: str) -> dict | None:
    """Get non-secret profile fields for UI display (no raw credentials)."""
    p = get_profile(profile_id)
    if not p:
        return None
    creds = p.get('credentials') or {}
    if isinstance(creds, str):
        try: creds = json.loads(creds)
        except Exception: creds = {}
    return {
        'id':              p['id'],
        'seq_id':          p.get('seq_id'),
        'name':            p['name'],
        'auth_type':       p['auth_type'],
        'discoverable':    bool(p.get('discoverable', False)),
        'username':        creds.get('username', ''),
        'has_private_key': bool(creds.get('private_key', '')),
        'has_passphrase':  bool(creds.get('passphrase', '')),
        'has_password':    bool(creds.get('password', '')),
    }


def get_profile_by_seq_id(seq_id: int) -> dict | None:
    """Get a profile by its seq_id (used for CSV import matching)."""
    conn = _get_conn()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM credential_profiles WHERE seq_id = %s", (seq_id,))
            cols = [d[0] for d in cur.description]
            row = cur.fetchone()
            cur.close(); conn.close()
            if not row: return None
            r = dict(zip(cols, row))
            r['id'] = str(r['id'])
            return r
        except Exception:
            return None
    try:
        from api.db.base import get_sync_engine
        from sqlalchemy import text as _t
        sa = get_sync_engine().connect()
        row = sa.execute(_t("SELECT * FROM credential_profiles WHERE seq_id = :s"), {"s": seq_id}).mappings().fetchone()
        sa.close()
        return dict(row) if row else None
    except Exception:
        return None


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
