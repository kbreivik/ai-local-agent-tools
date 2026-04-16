# CC PROMPT — v2.31.1 — fix(security): crypto boot-safety + key fingerprint + canary

## What this does
Prevents silent data corruption when `SETTINGS_ENCRYPTION_KEY` is missing on restart.
Today `api/crypto.py` generates a new ephemeral Fernet key when the env var is unset —
every subsequent decrypt of existing data returns empty and every stored credential
becomes unrecoverable garbage. Fix: (1) refuse to boot if the DB already has encrypted
rows but the env var is missing, (2) log the key fingerprint (SHA-256 first 8 chars) on
startup so operators can detect drift across restarts, (3) persist a decryptable canary
row so `/api/health/crypto` can verify the current key still decrypts existing data.

Three changes across three files. Version bump: v2.31.0 → v2.31.1

---

## Change 1 — api/crypto.py — add fingerprint, canary, boot-safety check

**Append** the following block to the end of `api/crypto.py`. Do not modify the existing
`_get_fernet`, `encrypt_value`, `decrypt_value`, or `is_encrypted` functions — the
existing fallback stays intact for first-run bootstrap (fresh install, empty DB).

```python
# ─── Boot-safety, fingerprint, canary ─────────────────────────────────────────

import hashlib

_CANARY_TABLE_DDL_PG = """
CREATE TABLE IF NOT EXISTS crypto_canary (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    encrypted_value TEXT NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
"""
_CANARY_TABLE_DDL_SQLITE = """
CREATE TABLE IF NOT EXISTS crypto_canary (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    encrypted_value TEXT NOT NULL,
    created_at      TEXT DEFAULT (datetime('now'))
);
"""

_CANARY_PLAINTEXT = "DEATHSTAR_CRYPTO_CANARY_v1"

# Tables that may contain Fernet-encrypted values. Used to detect whether
# the DB already has encrypted data before allowing a boot without the key.
_ENCRYPTED_TABLES = [
    ("connections",          "credentials"),
    ("credential_profiles",  "credentials"),
]


def _pg_dsn() -> str:
    return os.environ.get("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")


def key_fingerprint() -> str:
    """First 8 hex chars of SHA-256 of the current Fernet key — safe to log.

    Gives operators a stable identifier for the active key so drift across
    restarts is visible without exposing the key itself. Returns 'no-key'
    if SETTINGS_ENCRYPTION_KEY is unset.
    """
    key = os.environ.get("SETTINGS_ENCRYPTION_KEY", "")
    if not key:
        return "no-key"
    return hashlib.sha256(key.encode()).hexdigest()[:8]


def _has_encrypted_data_in_db() -> bool:
    """True if any known table has rows with the encryption prefix, OR if the
    crypto_canary row exists. Intentionally defensive — any error returns False
    (boot proceeds) because a brand-new DB has no tables yet."""
    dsn = _pg_dsn()
    if dsn:
        try:
            import psycopg2
            conn = psycopg2.connect(dsn)
            conn.autocommit = True
            cur = conn.cursor()
            for table, col in _ENCRYPTED_TABLES:
                try:
                    cur.execute(
                        f"SELECT 1 FROM {table} WHERE {col} LIKE %s LIMIT 1",
                        (f"{_PREFIX}%",),
                    )
                    if cur.fetchone():
                        cur.close(); conn.close()
                        return True
                except Exception:
                    continue  # table may not exist yet
            try:
                cur.execute("SELECT 1 FROM crypto_canary WHERE id = 1 LIMIT 1")
                if cur.fetchone():
                    cur.close(); conn.close()
                    return True
            except Exception:
                pass
            cur.close(); conn.close()
            return False
        except Exception:
            return False
    # SQLite fallback
    try:
        from sqlalchemy import text as _text
        from api.db.base import get_sync_engine
        with get_sync_engine().connect() as sa:
            for table, col in _ENCRYPTED_TABLES:
                try:
                    r = sa.execute(
                        _text(f"SELECT 1 FROM {table} WHERE {col} LIKE :p LIMIT 1"),
                        {"p": f"{_PREFIX}%"},
                    ).fetchone()
                    if r:
                        return True
                except Exception:
                    continue
            try:
                r = sa.execute(_text("SELECT 1 FROM crypto_canary WHERE id = 1 LIMIT 1")).fetchone()
                if r:
                    return True
            except Exception:
                pass
        return False
    except Exception:
        return False


def check_encryption_key_safe() -> None:
    """Refuse to start if SETTINGS_ENCRYPTION_KEY is missing AND the DB already
    contains encrypted values.

    Without this check, the app would silently generate a new Fernet key on
    startup and every stored credential would become permanently unrecoverable
    (decrypt_value returns "" for anything encrypted with the previous key).

    Called from the FastAPI lifespan AFTER init_db() but BEFORE any code that
    reads or writes encrypted data (settings migration, connections, collectors).

    Raises RuntimeError if unsafe — uvicorn will then exit non-zero. Safe to
    call multiple times.
    """
    key = os.environ.get("SETTINGS_ENCRYPTION_KEY", "")
    if key:
        log.info("Crypto: SETTINGS_ENCRYPTION_KEY present (fingerprint=%s)",
                 key_fingerprint())
        return
    if _has_encrypted_data_in_db():
        msg = (
            "REFUSING TO START — SETTINGS_ENCRYPTION_KEY is not set but the "
            "database already contains encrypted values. Starting with a "
            "freshly generated key would make every stored credential "
            "permanently unrecoverable. Set SETTINGS_ENCRYPTION_KEY in "
            "docker/.env to the correct persistent key and restart."
        )
        log.critical(msg)
        raise RuntimeError(msg)
    log.warning(
        "Crypto: SETTINGS_ENCRYPTION_KEY not set — DB has no encrypted data "
        "yet. A new key will be generated on first encrypt. Persist it in "
        "docker/.env before adding any connections or secrets."
    )


def _ensure_canary_table() -> bool:
    dsn = _pg_dsn()
    if dsn:
        try:
            import psycopg2
            conn = psycopg2.connect(dsn)
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute(_CANARY_TABLE_DDL_PG)
            cur.close(); conn.close()
            return True
        except Exception as e:
            log.warning("Crypto: canary table create failed (PG): %s", e)
            return False
    try:
        from sqlalchemy import text as _text
        from api.db.base import get_sync_engine
        with get_sync_engine().connect() as sa:
            sa.execute(_text(_CANARY_TABLE_DDL_SQLITE))
            sa.commit()
        return True
    except Exception as e:
        log.warning("Crypto: canary table create failed (SQLite): %s", e)
        return False


def ensure_crypto_canary() -> None:
    """Seed the canary row on first boot. Idempotent — no-op if already present."""
    if not _ensure_canary_table():
        return
    dsn = _pg_dsn()
    if dsn:
        try:
            import psycopg2
            conn = psycopg2.connect(dsn)
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute("SELECT encrypted_value FROM crypto_canary WHERE id = 1")
            row = cur.fetchone()
            if row and row[0]:
                cur.close(); conn.close()
                return
            encrypted = encrypt_value(_CANARY_PLAINTEXT)
            cur.execute(
                "INSERT INTO crypto_canary (id, encrypted_value) VALUES (1, %s) "
                "ON CONFLICT (id) DO NOTHING",
                (encrypted,),
            )
            cur.close(); conn.close()
            log.info("Crypto: canary seeded (fingerprint=%s)", key_fingerprint())
            return
        except Exception as e:
            log.warning("Crypto: canary seed failed (PG): %s", e)
            return
    try:
        from sqlalchemy import text as _text
        from api.db.base import get_sync_engine
        with get_sync_engine().connect() as sa:
            r = sa.execute(_text("SELECT encrypted_value FROM crypto_canary WHERE id = 1")).fetchone()
            if r and r[0]:
                return
            encrypted = encrypt_value(_CANARY_PLAINTEXT)
            sa.execute(
                _text("INSERT OR IGNORE INTO crypto_canary (id, encrypted_value) VALUES (1, :v)"),
                {"v": encrypted},
            )
            sa.commit()
        log.info("Crypto: canary seeded (fingerprint=%s)", key_fingerprint())
    except Exception as e:
        log.warning("Crypto: canary seed failed (SQLite): %s", e)


def verify_crypto_canary() -> dict:
    """Decrypt the canary and compare to the expected plaintext.

    Returns a dict suitable for a health endpoint:
      {status: ok|unseeded|mismatch|error, fingerprint: str, message: str}
    """
    fingerprint = key_fingerprint()
    stored = None
    dsn = _pg_dsn()
    if dsn:
        try:
            import psycopg2
            conn = psycopg2.connect(dsn)
            conn.autocommit = True
            cur = conn.cursor()
            try:
                cur.execute("SELECT encrypted_value FROM crypto_canary WHERE id = 1")
                row = cur.fetchone()
                stored = row[0] if row else None
            except Exception:
                stored = None
            cur.close(); conn.close()
        except Exception as e:
            return {"status": "error", "fingerprint": fingerprint, "message": str(e)}
    else:
        try:
            from sqlalchemy import text as _text
            from api.db.base import get_sync_engine
            with get_sync_engine().connect() as sa:
                try:
                    row = sa.execute(_text("SELECT encrypted_value FROM crypto_canary WHERE id = 1")).fetchone()
                    stored = row[0] if row else None
                except Exception:
                    stored = None
        except Exception as e:
            return {"status": "error", "fingerprint": fingerprint, "message": str(e)}

    if not stored:
        return {
            "status": "unseeded",
            "fingerprint": fingerprint,
            "message": "Canary not yet seeded (first boot or clean DB).",
        }
    try:
        decrypted = decrypt_value(stored)
    except Exception as e:
        return {"status": "error", "fingerprint": fingerprint, "message": str(e)}
    if decrypted == _CANARY_PLAINTEXT:
        return {
            "status": "ok",
            "fingerprint": fingerprint,
            "message": "Canary decrypted successfully — encryption key is valid.",
        }
    return {
        "status": "mismatch",
        "fingerprint": fingerprint,
        "message": (
            "Canary present but decrypt returned an unexpected value. "
            "SETTINGS_ENCRYPTION_KEY may have changed — existing encrypted "
            "data is likely unrecoverable with the current key."
        ),
    }
```

---

## Change 2 — api/main.py — wire safety check + canary seed into lifespan

Two small insertions in the `lifespan` async context manager.

**2a.** Immediately after `await init_db()` and BEFORE `check_secrets()`. This must run
before any code that touches encrypted values (settings migration, connections init).

Find:
```python
    await init_db()
    check_secrets()
```

Replace with:
```python
    await init_db()
    # Crypto boot-safety: refuse to start if env key is missing but encrypted data exists
    from api.crypto import check_encryption_key_safe
    check_encryption_key_safe()
    check_secrets()
```

**2b.** After the existing `migrate_plaintext_secrets(SETTINGS_KEYS)` try/except block.
Find:
```python
    # Encrypt any plaintext secrets in settings table (one-time migration)
    try:
        from api.settings_manager import migrate_plaintext_secrets
        from api.routers.settings import SETTINGS_KEYS
        migrate_plaintext_secrets(SETTINGS_KEYS)
    except Exception as e:
        _log.debug("Secret encryption migration skipped: %s", e)
```

Add immediately after that block (still inside the lifespan):
```python
    # Seed crypto canary row for future key-drift detection
    try:
        from api.crypto import ensure_crypto_canary
        ensure_crypto_canary()
    except Exception as e:
        _log.debug("Crypto canary seed skipped: %s", e)
```

---

## Change 3 — api/routers/status.py — add /api/health/crypto endpoint

Append this new route to `api/routers/status.py` (the existing status router).

```python

@router.get("/health/crypto")
def health_crypto(_: str = Depends(get_current_user)):
    """Verify the crypto canary decrypts with the current SETTINGS_ENCRYPTION_KEY.
    Returns {status, fingerprint, message}. status: ok|unseeded|mismatch|error."""
    from api.crypto import verify_crypto_canary
    return verify_crypto_canary()
```

If `get_current_user` or `Depends` is not already imported in this file, add at the
top of the imports:
```python
from fastapi import Depends
from api.auth import get_current_user
```
(Leave any existing imports untouched — just add these if missing.)

---

## Version bump
- Update `VERSION` in `api/constants.py`: `v2.31.0` → `v2.31.1`
- Update root `/VERSION` file: `2.31.0` → `2.31.1`

## Commit
```
git add -A
git commit -m "fix(security): v2.31.1 crypto boot-safety + key fingerprint + canary"
git push origin main
```

---

## How to test after deploy

Run after `docker compose ... up -d hp1_agent`:

1. **Normal restart logs** — `docker compose logs hp1_agent | grep -i crypto` should show
   `Crypto: SETTINGS_ENCRYPTION_KEY present (fingerprint=XXXXXXXX)` and on first run
   also `Crypto: canary seeded (fingerprint=XXXXXXXX)`. The fingerprint must stay
   stable across restarts.

2. **Health endpoint** — authenticated GET `https://192.168.199.10:8000/api/health/crypto`
   → `{"status":"ok","fingerprint":"XXXXXXXX","message":"Canary decrypted successfully — encryption key is valid."}`

3. **Drift detection (destructive test — do last)** — temporarily comment out
   `SETTINGS_ENCRYPTION_KEY` in `/opt/hp1-agent/docker/.env` and restart. The container
   should exit non-zero. Logs must contain the `REFUSING TO START` message. Restore
   the line and restart — service comes back healthy.

4. **Login + connection CRUD still work** — confirm existing Proxmox / PBS / vm_host
   connections still decrypt and the collectors still poll them normally. No
   regression in credential retrieval.
