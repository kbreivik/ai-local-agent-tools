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
