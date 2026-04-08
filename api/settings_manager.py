"""Unified settings manager — single source of truth for all configuration.

Priority: DB → env var → hardcoded default.
Sensitive values auto-encrypted on write, auto-decrypted on read, masked on API response.
"""
import logging
import os
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)

# Keys that contain secrets — auto-encrypted in DB, masked in API responses
SENSITIVE_KEYS = frozenset({
    "lmStudioApiKey", "externalApiKey", "proxmoxTokenSecret",
    "ghcrToken", "fortigateApiKey", "truenasApiKey",
})

# Keys that come from .env only — read-only in GUI
ENV_ONLY_KEYS = frozenset({
    "adminPassword", "databaseUrl", "settingsEncryptionKey",
})

# Category mapping for GUI grouping
CATEGORIES = {
    # LLM
    "lmStudioUrl": "llm", "lmStudioApiKey": "llm", "modelName": "llm",
    "externalProvider": "llm", "externalApiKey": "llm", "externalModel": "llm",
    # Agent behavior
    "autoEscalate": "agent", "requireConfirmation": "agent", "autoUpdate": "agent",
    # Infrastructure
    "dockerHost": "infrastructure", "kafkaBootstrapServers": "infrastructure",
    "elasticsearchUrl": "infrastructure", "kibanaUrl": "infrastructure",
    "muninndbUrl": "infrastructure", "agentDockerHost": "infrastructure",
    "swarmManagerIPs": "infrastructure", "swarmWorkerIPs": "infrastructure",
    "ghcrToken": "infrastructure",
    # Proxmox
    "proxmoxHost": "proxmox", "proxmoxTokenId": "proxmox",
    "proxmoxTokenSecret": "proxmox", "proxmoxUser": "proxmox", "proxmoxNodes": "proxmox",
    # FortiGate
    "fortigateHost": "fortigate", "fortigateApiKey": "fortigate",
    # TrueNAS
    "truenasHost": "truenas", "truenasApiKey": "truenas",
    # UI
    "dashboardRefreshInterval": "ui",
    # Notifications
    "notificationWebhookUrl": "notifications",
    "notifyOnRecovery":       "notifications",
}


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mask(value: Any) -> str:
    """Return a masked version of a sensitive value."""
    s = str(value)
    return (s[:4] + "***") if len(s) > 4 else "***"


def get_setting(key: str, registry: dict | None = None) -> dict:
    """Get a setting value with source tracking.

    Returns: {"value": ..., "source": "db"|"env"|"default", "encrypted": bool}
    """
    from api.crypto import decrypt_value, is_encrypted

    meta = (registry or {}).get(key, {})
    env_var = meta.get("env", "")
    default = meta.get("default", "")

    # 1. Check DB
    try:
        from mcp_server.tools.skills.storage import get_backend
        db_val = get_backend().get_setting(key)
        if db_val is not None:
            # Only stringify for encryption check — preserve original type otherwise
            if isinstance(db_val, str):
                encrypted = is_encrypted(db_val)
                plaintext = decrypt_value(db_val) if encrypted else db_val
                return {"value": plaintext, "source": "db", "encrypted": encrypted}
            return {"value": db_val, "source": "db", "encrypted": False}
    except Exception:
        pass

    # 2. Check env var
    if env_var:
        env_val = os.environ.get(env_var, "")
        if env_val:
            return {"value": env_val, "source": "env", "encrypted": False}

    # 3. Hardcoded default
    return {"value": default, "source": "default", "encrypted": False}


def set_setting(key: str, value: Any, registry: dict | None = None) -> None:
    """Write a setting to DB. Auto-encrypts if key is in SENSITIVE_KEYS."""
    from api.crypto import encrypt_value
    from mcp_server.tools.skills.storage import get_backend

    store_value = value
    if key in SENSITIVE_KEYS and value and not str(value).endswith("***"):
        store_value = encrypt_value(str(value))

    get_backend().set_setting(key, store_value)

    # Mirror to os.environ for collectors/tools
    meta = (registry or {}).get(key, {})
    env_var = meta.get("env", "")
    if env_var and value is not None:
        # Store plaintext in env (encrypted is DB-only)
        plain = str(value)
        os.environ[env_var] = plain


def list_settings(registry: dict) -> list[dict]:
    """Return all settings with source badges, categories, and masked values."""
    result = []
    for key, meta in registry.items():
        info = get_setting(key, registry)
        is_secret = key in SENSITIVE_KEYS
        is_env_only = key in ENV_ONLY_KEYS
        entry = {
            "key": key,
            "value": _mask(info["value"]) if (is_secret and info["value"]) else info["value"],
            "source": info["source"],
            "category": CATEGORIES.get(key, "general"),
            "encrypted": info["encrypted"],
            "sensitive": is_secret,
            "readonly": is_env_only,
        }
        result.append(entry)
    return result


def migrate_plaintext_secrets(registry: dict) -> int:
    """One-time migration: encrypt any plaintext secrets found in DB.

    Called on startup. Idempotent — skips already-encrypted values.
    Returns count of values encrypted.
    """
    from api.crypto import encrypt_value, is_encrypted
    from mcp_server.tools.skills.storage import get_backend

    backend = get_backend()
    migrated = 0
    for key in SENSITIVE_KEYS:
        if key not in registry:
            continue
        try:
            raw = backend.get_setting(key)
            if raw is None:
                continue
            raw_str = str(raw) if not isinstance(raw, str) else raw
            if raw_str and not is_encrypted(raw_str) and not raw_str.endswith("***"):
                encrypted = encrypt_value(raw_str)
                backend.set_setting(key, encrypted)
                migrated += 1
                log.info("Encrypted plaintext secret: %s", key)
        except Exception as e:
            log.warning("Failed to migrate %s: %s", key, e)

    if migrated:
        log.info("Settings migration: encrypted %d plaintext secret(s)", migrated)
    return migrated
