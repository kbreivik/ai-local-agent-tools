"""Fernet encryption for secrets in the settings table.

Key source: SETTINGS_ENCRYPTION_KEY env var (base64 Fernet key).
If not set on first startup, generates one and logs a warning.
The key MUST be persisted in .env via Ansible — never stored in DB.
"""
import base64
import logging
import os

from cryptography.fernet import Fernet, InvalidToken

log = logging.getLogger(__name__)

_fernet: Fernet | None = None
_PREFIX = "enc::"  # prefix to identify encrypted values in DB


def _get_fernet() -> Fernet:
    """Return cached Fernet instance. Creates key on first call if missing."""
    global _fernet
    if _fernet is not None:
        return _fernet

    key = os.environ.get("SETTINGS_ENCRYPTION_KEY", "")
    if not key:
        key = Fernet.generate_key().decode()
        os.environ["SETTINGS_ENCRYPTION_KEY"] = key
        log.warning(
            "SETTINGS_ENCRYPTION_KEY not set — generated ephemeral key. "
            "Add this to docker/.env to persist across restarts:\n"
            "  SETTINGS_ENCRYPTION_KEY=%s", key
        )
    _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet


def encrypt_value(plaintext: str) -> str:
    """Encrypt a plaintext string. Returns prefixed ciphertext."""
    if not plaintext or is_encrypted(plaintext):
        return plaintext
    f = _get_fernet()
    ct = f.encrypt(plaintext.encode()).decode()
    return f"{_PREFIX}{ct}"


def decrypt_value(ciphertext: str) -> str:
    """Decrypt a prefixed ciphertext string. Returns plaintext.

    If value is not encrypted (no prefix), returns as-is.
    If decryption fails (wrong key), returns empty string + logs warning.
    """
    if not ciphertext or not is_encrypted(ciphertext):
        return ciphertext
    raw = ciphertext[len(_PREFIX):]
    try:
        f = _get_fernet()
        return f.decrypt(raw.encode()).decode()
    except InvalidToken:
        log.warning("Failed to decrypt value — key may have changed. Returning empty.")
        return ""
    except Exception as e:
        log.warning("Decryption error: %s", e)
        return ""


def is_encrypted(value: str) -> bool:
    """Check if a value has the encryption prefix."""
    return isinstance(value, str) and value.startswith(_PREFIX)


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


# ─── Key-parameterised helpers (for rotation tooling) ────────────────────────

def _fernet_from_key(key: str) -> Fernet:
    """Build a Fernet instance from a raw base64 key string."""
    if not key:
        raise ValueError("encryption key is empty")
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as e:
        raise ValueError(f"invalid Fernet key: {e}") from e


def encrypt_with_key(plaintext: str, key: str) -> str:
    """Encrypt using an explicit key. Returns prefixed ciphertext. Idempotent:
    if input is already encrypted, returns as-is."""
    if not plaintext or is_encrypted(plaintext):
        return plaintext
    f = _fernet_from_key(key)
    return f"{_PREFIX}{f.encrypt(plaintext.encode()).decode()}"


def decrypt_with_key(ciphertext: str, key: str) -> str:
    """Decrypt using an explicit key. Raises InvalidToken on failure (unlike
    decrypt_value() which swallows the error and returns '')."""
    if not ciphertext or not is_encrypted(ciphertext):
        return ciphertext
    raw = ciphertext[len(_PREFIX):]
    f = _fernet_from_key(key)
    return f.decrypt(raw.encode()).decode()


def fingerprint_of_key(key: str) -> str:
    """SHA-256 first 8 hex chars of an arbitrary key string."""
    if not key:
        return "no-key"
    return hashlib.sha256(key.encode()).hexdigest()[:8]
