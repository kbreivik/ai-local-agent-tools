# CC PROMPT — v2.26.9 — DB foundations: credential_profiles seq_id, audit_log, connections username_cache

## What this does
Three DB-layer additions that underpin the credential profile overhaul:
1. `credential_profiles`: add `seq_id` (human-readable serial ID), `discoverable` flag; seed
   a permanent dummy profile at seq_id=0 (no-auth placeholder for import/CSV)
2. New `connection_audit_log` table for rotation overrides, credential events
3. `connections`: add `username_cache` (non-secret derived field, keeps username visible
   without decrypting credentials)
Version bump: 2.26.8 → 2.26.9

---

## Change 1 — api/db/credential_profiles.py

### 1a — Replace PG DDL constant with full schema including new columns

FIND (exact):
```
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
```

REPLACE WITH:
```
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
```

### 1b — Replace SQLite DDL constant

FIND (exact):
```
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
```

REPLACE WITH:
```
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
```

### 1c — Replace init_credential_profiles to run migrations + seed dummy

FIND (exact):
```
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
```

REPLACE WITH:
```
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
```

### 1d — Update list_profiles to return seq_id + discoverable

FIND (exact):
```
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
```

REPLACE WITH:
```
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
```

---

## Change 2 — api/db/audit_log.py (NEW FILE — create it)

```python
"""connection_audit_log — records credential rotation events and admin overrides."""
import json
import logging
import os
import uuid
from datetime import datetime, timezone

log = logging.getLogger(__name__)

_DDL_PG = """
CREATE TABLE IF NOT EXISTS connection_audit_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type      TEXT NOT NULL,
    profile_id      TEXT,
    performed_by    TEXT NOT NULL DEFAULT '',
    override_reason TEXT NOT NULL DEFAULT '',
    connection_ids  TEXT[] DEFAULT '{}',
    test_results    JSONB DEFAULT '{}',
    timestamp       TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON connection_audit_log(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_profile ON connection_audit_log(profile_id);
"""

_DDL_SQLITE = """
CREATE TABLE IF NOT EXISTS connection_audit_log (
    id              TEXT PRIMARY KEY,
    event_type      TEXT NOT NULL,
    profile_id      TEXT,
    performed_by    TEXT NOT NULL DEFAULT '',
    override_reason TEXT NOT NULL DEFAULT '',
    connection_ids  TEXT DEFAULT '[]',
    test_results    TEXT DEFAULT '{}',
    timestamp       TEXT DEFAULT (datetime('now'))
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


def init_audit_log() -> bool:
    global _initialized
    if _initialized: return True
    conn = _get_conn()
    if conn:
        try:
            conn.autocommit = True
            cur = conn.cursor()
            for stmt in _DDL_PG.strip().split(';'):
                stmt = stmt.strip()
                if stmt:
                    cur.execute(stmt)
            cur.close(); conn.close()
            _initialized = True
            log.info("connection_audit_log table ready (PG)")
            return True
        except Exception as e:
            log.warning("audit_log init (PG) failed: %s", e)
            try: conn.close()
            except Exception: pass
    try:
        from api.db.base import get_sync_engine
        from sqlalchemy import text as _t
        sa = get_sync_engine().connect()
        sa.execute(_t(_DDL_SQLITE)); sa.commit(); sa.close()
        _initialized = True
        log.info("connection_audit_log table ready (SQLite)")
        return True
    except Exception as e:
        log.warning("audit_log init (SQLite) failed: %s", e)
        return False


def write_audit_event(
    event_type: str,
    performed_by: str,
    profile_id: str | None = None,
    override_reason: str = "",
    connection_ids: list[str] | None = None,
    test_results: dict | None = None,
) -> str | None:
    """Write an audit event. Returns the new event id or None on failure.

    event_type values:
      rotation_test          — normal rotation test completed (all pass)
      rotation_override      — rotation saved despite test failures (admin override)
      profile_created        — new profile created
      profile_updated        — profile credentials updated without rotation test
      profile_deleted        — profile deleted
    """
    if not _initialized:
        init_audit_log()
    eid = str(uuid.uuid4())
    conn_ids = connection_ids or []
    results = test_results or {}

    conn = _get_conn()
    if conn:
        try:
            import psycopg2.extras
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO connection_audit_log "
                "(id, event_type, profile_id, performed_by, override_reason, connection_ids, test_results) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (eid, event_type, profile_id, performed_by, override_reason,
                 conn_ids, json.dumps(results)),
            )
            conn.commit(); cur.close(); conn.close()
            return eid
        except Exception as e:
            log.warning("write_audit_event (PG) failed: %s", e)
            try: conn.close()
            except Exception: pass

    try:
        from api.db.base import get_sync_engine
        from sqlalchemy import text as _t
        sa = get_sync_engine().connect()
        sa.execute(_t(
            "INSERT INTO connection_audit_log "
            "(id, event_type, profile_id, performed_by, override_reason, connection_ids, test_results) "
            "VALUES (:id, :et, :pid, :by, :reason, :cids, :results)"
        ), {
            "id": eid, "et": event_type, "pid": profile_id,
            "by": performed_by, "reason": override_reason,
            "cids": json.dumps(conn_ids), "results": json.dumps(results),
        })
        sa.commit(); sa.close()
        return eid
    except Exception as e:
        log.warning("write_audit_event (SQLite) failed: %s", e)
        return None


def list_audit_events(profile_id: str | None = None, limit: int = 50) -> list[dict]:
    """List recent audit events, optionally filtered by profile_id."""
    if not _initialized:
        init_audit_log()
    conn = _get_conn()
    if conn:
        try:
            cur = conn.cursor()
            if profile_id:
                cur.execute(
                    "SELECT * FROM connection_audit_log WHERE profile_id = %s "
                    "ORDER BY timestamp DESC LIMIT %s", (profile_id, limit)
                )
            else:
                cur.execute(
                    "SELECT * FROM connection_audit_log ORDER BY timestamp DESC LIMIT %s", (limit,)
                )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            cur.close(); conn.close()
            for r in rows:
                r['id'] = str(r.get('id', ''))
                if r.get('timestamp'):
                    try: r['timestamp'] = r['timestamp'].isoformat()
                    except Exception: pass
            return rows
        except Exception as e:
            log.warning("list_audit_events (PG) failed: %s", e)
    return []
```

---

## Change 3 — api/connections.py

### 3a — Add username_cache to PG DDL

FIND (exact):
```
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
```

REPLACE WITH:
```
_CONNECTIONS_DDL_PG = """
CREATE TABLE IF NOT EXISTS connections (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    platform       TEXT NOT NULL,
    label          TEXT NOT NULL,
    host           TEXT NOT NULL,
    port           INTEGER DEFAULT 443,
    auth_type      TEXT DEFAULT 'token',
    credentials    TEXT DEFAULT '',
    enabled        BOOLEAN DEFAULT true,
    verified       BOOLEAN DEFAULT false,
    last_seen      TIMESTAMPTZ,
    config         JSONB DEFAULT '{}',
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    username_cache TEXT NOT NULL DEFAULT '',
    UNIQUE(platform, label)
);
"""

_CONNECTIONS_MIGRATIONS_PG = [
    "ALTER TABLE connections ADD COLUMN IF NOT EXISTS username_cache TEXT NOT NULL DEFAULT ''",
]
```

### 3b — Add username_cache to SQLite DDL

FIND (exact):
```
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
```

REPLACE WITH:
```
_CONNECTIONS_DDL_SQLITE = """
CREATE TABLE IF NOT EXISTS connections (
    id             TEXT PRIMARY KEY,
    platform       TEXT NOT NULL,
    label          TEXT NOT NULL,
    host           TEXT NOT NULL,
    port           INTEGER DEFAULT 443,
    auth_type      TEXT DEFAULT 'token',
    credentials    TEXT DEFAULT '',
    enabled        INTEGER DEFAULT 1,
    verified       INTEGER DEFAULT 0,
    last_seen      TEXT,
    config         TEXT DEFAULT '{}',
    created_at     TEXT DEFAULT (datetime('now')),
    username_cache TEXT NOT NULL DEFAULT '',
    UNIQUE(platform, label)
);
"""

_CONNECTIONS_MIGRATIONS_SQLITE = [
    "ALTER TABLE connections ADD COLUMN username_cache TEXT NOT NULL DEFAULT ''",
]
```

### 3c — Run migrations in init_connections

FIND (exact):
```
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
```

REPLACE WITH:
```
    # Try PostgreSQL first
    conn = _get_conn()
    if conn:
        try:
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute(_CONNECTIONS_DDL_PG)
            cur.close()
            # Migrations
            conn.autocommit = False
            for stmt in _CONNECTIONS_MIGRATIONS_PG:
                try:
                    cur2 = conn.cursor()
                    cur2.execute(stmt)
                    conn.commit()
                    cur2.close()
                except Exception:
                    conn.rollback()
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
        for stmt in _CONNECTIONS_MIGRATIONS_SQLITE:
            try:
                sa_conn.execute(_text(stmt)); sa_conn.commit()
            except Exception:
                pass
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
```

### 3d — Populate username_cache in create_connection

FIND (exact):
```
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
```

REPLACE WITH:
```
    try:
        creds_dict = credentials or {}
        creds_str = json.dumps(creds_dict)
        encrypted_creds = encrypt_value(creds_str) if creds_str else ""
        config_json = json.dumps(config or {})
        cid = str(uuid.uuid4())
        username_cache = str(creds_dict.get('username', ''))
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO connections (id, platform, label, host, port, auth_type, credentials, enabled, config, username_cache)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (cid, platform, label, host, port, auth_type, encrypted_creds, enabled, config_json, username_cache))
        conn.commit()
        cur.close()
        conn.close()
        log.info("Connection created: %s/%s → %s:%d", platform, label, host, port)
        return {"status": "ok", "id": cid, "message": f"Connection '{label}' created"}
    except Exception as e:
        log.warning("create_connection failed: %s", e)
        return {"status": "error", "message": str(e)}
```

### 3e — Populate username_cache in update_connection (after credential merge)

FIND (exact):
```
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
```

REPLACE WITH:
```
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
                merged = new_creds if isinstance(new_creds, dict) else {}
                creds_str = json.dumps(merged)
            sets.append("credentials = %s")
            params.append(encrypt_value(creds_str) if creds_str else "")
            # Update username_cache whenever credentials change
            if isinstance(merged if 'merged' in dir() else (new_creds or {}), dict):
                cache_user = (merged if isinstance(merged, dict) else (new_creds or {})).get('username', '')
                if cache_user:
                    sets.append("username_cache = %s")
                    params.append(str(cache_user))
```

### 3f — Init audit_log on startup (at bottom of init_connections, after _initialized = True)

FIND (exact):
```
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
```

REPLACE WITH:
```
        _initialized = True
        log.info("Connections table ready (SQLite)")
        # Also ensure audit log table exists
        try:
            from api.db.audit_log import init_audit_log
            init_audit_log()
        except Exception as e:
            log.warning("audit_log init (via connections init) failed: %s", e)
        return True
    except Exception as e:
        log.warning("Connections table init failed (SQLite): %s", e)
        try:
            sa_conn.close()
        except Exception:
            pass
        return False
```

---

## Version bump
Update VERSION: 2.26.8 → 2.26.9

## Commit
```bash
git add -A
git commit -m "feat(db): v2.26.9 credential_profiles seq_id+discoverable, connection_audit_log, username_cache"
git push origin main
```
