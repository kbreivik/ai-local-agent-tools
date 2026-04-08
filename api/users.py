"""User and API token management — Postgres tables + CRUD operations.

Users: multi-user auth with bcrypt passwords and roles.
Tokens: API tokens with SHA256 hash lookup and expiry.
"""
import hashlib
import logging
import os
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any

import bcrypt

log = logging.getLogger(__name__)

_USERS_DDL = """
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'stormtrooper',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_login TIMESTAMPTZ
);
"""

_TOKENS_DDL = """
CREATE TABLE IF NOT EXISTS api_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'droid',
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_used TIMESTAMPTZ,
    enabled BOOLEAN NOT NULL DEFAULT TRUE
);
"""

_initialized = False


def _get_conn():
    dsn = os.environ.get("DATABASE_URL", "")
    if not dsn:
        return None
    import psycopg2
    return psycopg2.connect(dsn.replace("postgresql+asyncpg://", "postgresql://"))


def init_users_tables() -> bool:
    """Create users + api_tokens tables. Returns True if ready."""
    global _initialized
    if _initialized:
        return True
    conn = _get_conn()
    if not conn:
        return False
    try:
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(_USERS_DDL)
        cur.execute(_TOKENS_DDL)
        cur.close()
        # Seed admin user if table is empty
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM users")
        if cur.fetchone()[0] == 0:
            admin_user = os.environ.get("ADMIN_USER", "admin")
            admin_pass = os.environ.get("ADMIN_PASSWORD", "changeme")
            pw_hash = bcrypt.hashpw(admin_pass.encode(), bcrypt.gensalt()).decode()
            cur.execute(
                "INSERT INTO users (id, username, password_hash, role) VALUES (%s, %s, %s, %s)",
                (str(uuid.uuid4()), admin_user, pw_hash, "sith_lord"),
            )
            log.info("Users: seeded admin user '%s' as sith_lord", admin_user)
        cur.close()
        conn.close()
        _initialized = True
        log.info("Users + API tokens tables ready")
        return True
    except Exception as e:
        log.warning("Users table init failed: %s", e)
        return False


# ── User CRUD ────────────────────────────────────────────────────────────────

def list_users() -> list[dict]:
    conn = _get_conn()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, username, role, enabled, created_at, last_login FROM users ORDER BY created_at")
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.close()
        conn.close()
        for r in rows:
            r["id"] = str(r["id"])
            for k in ("created_at", "last_login"):
                if r.get(k):
                    try:
                        r[k] = r[k].isoformat()
                    except AttributeError:
                        pass
        return rows
    except Exception as e:
        log.warning("list_users failed: %s", e)
        return []


def create_user(username: str, password: str, role: str = "stormtrooper") -> dict:
    conn = _get_conn()
    if not conn:
        return {"status": "error", "message": "No database"}
    try:
        pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        uid = str(uuid.uuid4())
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (id, username, password_hash, role) VALUES (%s, %s, %s, %s)",
            (uid, username, pw_hash, role),
        )
        conn.commit()
        cur.close()
        conn.close()
        return {"status": "ok", "id": uid}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def update_user(user_id: str, role: str = None, enabled: bool = None, password: str = None) -> dict:
    conn = _get_conn()
    if not conn:
        return {"status": "error", "message": "No database"}
    try:
        sets, params = [], []
        if role is not None:
            sets.append("role = %s")
            params.append(role)
        if enabled is not None:
            sets.append("enabled = %s")
            params.append(enabled)
        if password:
            sets.append("password_hash = %s")
            params.append(bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode())
        if not sets:
            return {"status": "ok", "message": "Nothing to update"}
        params.append(user_id)
        cur = conn.cursor()
        cur.execute(f"UPDATE users SET {', '.join(sets)} WHERE id = %s", params)
        conn.commit()
        cur.close()
        conn.close()
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def delete_user(user_id: str) -> dict:
    conn = _get_conn()
    if not conn:
        return {"status": "error", "message": "No database"}
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
        deleted = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        return {"status": "ok"} if deleted else {"status": "error", "message": "User not found"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def authenticate_user(username: str, password: str) -> dict | None:
    """Check users table. Returns user dict or None."""
    conn = _get_conn()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, username, password_hash, role, enabled FROM users WHERE username = %s", (username,))
        row = cur.fetchone()
        if not row:
            cur.close()
            conn.close()
            return None
        uid, uname, pw_hash, role, enabled = row
        if not enabled:
            cur.close()
            conn.close()
            return None
        if bcrypt.checkpw(password.encode(), pw_hash.encode()):
            cur.execute("UPDATE users SET last_login = NOW() WHERE id = %s", (uid,))
            conn.commit()
            cur.close()
            conn.close()
            return {"id": str(uid), "username": uname, "role": role}
        cur.close()
        conn.close()
        return None
    except Exception:
        return None


# ── API Token CRUD ───────────────────────────────────────────────────────────

def create_api_token(name: str, role: str = "droid", user_id: str = None, expires_at: str = None) -> dict:
    """Create an API token. Returns the raw token ONCE — it's not stored."""
    conn = _get_conn()
    if not conn:
        return {"status": "error", "message": "No database"}
    try:
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        tid = str(uuid.uuid4())
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO api_tokens (id, name, token_hash, role, user_id, expires_at) VALUES (%s, %s, %s, %s, %s, %s)",
            (tid, name, token_hash, role, user_id, expires_at),
        )
        conn.commit()
        cur.close()
        conn.close()
        return {"status": "ok", "id": tid, "name": name, "token": raw_token, "role": role}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def list_api_tokens(user_id: str = None) -> list[dict]:
    conn = _get_conn()
    if not conn:
        return []
    try:
        cur = conn.cursor()
        if user_id:
            cur.execute("SELECT id, name, role, user_id, expires_at, created_at, last_used, enabled FROM api_tokens WHERE user_id = %s ORDER BY created_at", (user_id,))
        else:
            cur.execute("SELECT id, name, role, user_id, expires_at, created_at, last_used, enabled FROM api_tokens ORDER BY created_at")
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.close()
        conn.close()
        for r in rows:
            r["id"] = str(r["id"])
            if r.get("user_id"):
                r["user_id"] = str(r["user_id"])
            for k in ("expires_at", "created_at", "last_used"):
                if r.get(k):
                    try:
                        r[k] = r[k].isoformat()
                    except AttributeError:
                        pass
        return rows
    except Exception:
        return []


def revoke_api_token(token_id: str) -> dict:
    conn = _get_conn()
    if not conn:
        return {"status": "error", "message": "No database"}
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM api_tokens WHERE id = %s", (token_id,))
        conn.commit()
        cur.close()
        conn.close()
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def authenticate_token(raw_token: str) -> dict | None:
    """Check api_tokens table by SHA256 hash. Returns {role, name} or None."""
    conn = _get_conn()
    if not conn:
        return None
    try:
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, role, enabled, expires_at FROM api_tokens WHERE token_hash = %s",
            (token_hash,),
        )
        row = cur.fetchone()
        if not row:
            cur.close()
            conn.close()
            return None
        tid, name, role, enabled, expires_at = row
        if not enabled:
            cur.close()
            conn.close()
            return None
        if expires_at and expires_at < datetime.now(timezone.utc):
            cur.close()
            conn.close()
            return None
        cur.execute("UPDATE api_tokens SET last_used = NOW() WHERE id = %s", (tid,))
        conn.commit()
        cur.close()
        conn.close()
        return {"role": role, "name": name, "username": f"token:{name}"}
    except Exception:
        return None
