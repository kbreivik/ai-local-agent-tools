"""GET/POST /api/settings — DB-backed settings with env-var seeding."""
import logging
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Body, HTTPException
from api.auth import get_current_user
from mcp_server.tools.skills.storage import get_backend

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])

# Registry: frontend key → {env_var, sensitive, default}
# "env_var" is used for seeding on first run only.
# "sensitive" = True means the GET response masks the value.
SETTINGS_KEYS: dict[str, dict] = {
    # Local AI
    "lmStudioUrl":           {"env": "LM_STUDIO_BASE_URL",      "sens": False, "default": ""},
    "lmStudioApiKey":        {"env": "LM_STUDIO_API_KEY",       "sens": True,  "default": ""},
    "modelName":             {"env": "LM_STUDIO_MODEL",         "sens": False, "default": ""},
    # External AI
    "externalProvider":      {"env": None,                      "sens": False, "default": "claude"},
    "externalApiKey":        {"env": "ANTHROPIC_API_KEY",       "sens": True,  "default": ""},
    "externalModel":         {"env": None,                      "sens": False, "default": "claude-sonnet-4-6"},
    # Escalation
    "autoEscalate":          {"env": None,                      "sens": False, "default": "both"},
    "requireConfirmation":   {"env": None,                      "sens": False, "default": True},
    # Infrastructure — Docker / Messaging
    "dockerHost":            {"env": "DOCKER_HOST",             "sens": False, "default": ""},
    "kafkaBootstrapServers": {"env": "KAFKA_BOOTSTRAP_SERVERS", "sens": False, "default": ""},
    "elasticsearchUrl":      {"env": "ELASTIC_URL",             "sens": False, "default": ""},
    "kibanaUrl":             {"env": "KIBANA_URL",              "sens": False, "default": ""},
    "muninndbUrl":           {"env": "MUNINN_URL",              "sens": False, "default": ""},
    "swarmManagerIPs":       {"env": "",                        "sens": False, "default": ""},
    "swarmWorkerIPs":        {"env": "",                        "sens": False, "default": ""},
    "ghcrToken":             {"env": "GHCR_TOKEN",             "sens": True,  "default": ""},
    "agentDockerHost":       {"env": "AGENT01_DOCKER_HOST",    "sens": False, "default": ""},
    "agentHostIp":           {"env": "AGENT01_IP",             "sens": False, "default": ""},
    # Infrastructure — Proxmox
    "proxmoxHost":           {"env": "PROXMOX_HOST",            "sens": False, "default": ""},
    "proxmoxTokenId":        {"env": "PROXMOX_TOKEN_ID",        "sens": False, "default": ""},
    "proxmoxTokenSecret":    {"env": "PROXMOX_TOKEN_SECRET",    "sens": True,  "default": ""},
    "proxmoxUser":           {"env": "PROXMOX_USER",           "sens": False, "default": ""},
    "proxmoxNodes":          {"env": "PROXMOX_NODES",          "sens": False, "default": ""},
    # Infrastructure — FortiGate
    "fortigateHost":         {"env": "FORTIGATE_HOST",          "sens": False, "default": ""},
    "fortigateApiKey":       {"env": "FORTIGATE_API_KEY",       "sens": True,  "default": ""},
    # Infrastructure — TrueNAS
    "truenasHost":           {"env": "TRUENAS_HOST",            "sens": False, "default": ""},
    "truenasApiKey":         {"env": "TRUENAS_API_KEY",         "sens": True,  "default": ""},
    # Auto-update
    "autoUpdate":               {"env": None,                   "sens": False, "default": False},
    # UI (stored server-side so they survive browser clears)
    "dashboardRefreshInterval": {"env": None,                   "sens": False, "default": 15000},
    # Data retention
    "opLogRetentionDays":       {"env": None,                   "sens": False, "default": 30},
    "opLogMaxLinesPerSession":  {"env": None,                   "sens": False, "default": 500},
    # Notifications
    "notificationWebhookUrl": {"env": None, "sens": False, "default": ""},
    "notifyOnRecovery":       {"env": None, "sens": False, "default": False},
}


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mask(value: Any) -> str:
    """Return a masked version of a sensitive value."""
    s = str(value)
    return (s[:4] + "***") if len(s) > 4 else "***"


def seed_defaults() -> int:
    """Populate settings table from env vars if the table is empty.

    Called once from api/main.py lifespan on startup.
    Returns number of keys seeded (0 if table already had data).
    """
    backend = get_backend()
    # Check if already seeded: if any key exists, skip.
    if backend.get_setting("lmStudioUrl") is not None:
        return 0

    seeded = 0
    for key, meta in SETTINGS_KEYS.items():
        env_var = meta["env"]
        value = os.environ.get(env_var, "") if env_var else meta["default"]
        if value is not None and value != "":  # Only seed non-empty values
            backend.set_setting(key, value)
            seeded += 1

    logger.info("Settings: seeded %d keys from environment", seeded)
    return seeded


def sync_env_from_db() -> int:
    """Mirror DB settings into os.environ so collectors see user-saved values.

    Called on startup after seed_defaults(). DB is the source of truth after
    first save — this ensures settings saved via the UI survive process restarts
    without requiring env var changes in .env / Ansible.
    Returns number of keys synced.
    """
    backend = get_backend()
    synced = 0
    for key, meta in SETTINGS_KEYS.items():
        env_var = meta["env"]
        if not env_var:
            continue
        db_value = backend.get_setting(key)
        if db_value is not None and str(db_value).strip():
            from api.crypto import decrypt_value
            os.environ[env_var] = decrypt_value(str(db_value))
            synced += 1
    logger.info("Settings: synced %d keys from DB into os.environ", synced)
    return synced


@router.get("")
def get_settings(_: str = Depends(get_current_user)):
    """Return all settings with source badges, categories, and encryption status."""
    try:
        from api.settings_manager import list_settings
        settings = list_settings(SETTINGS_KEYS)
        # Also return flat dict for backward compat with existing GUI
        flat = {s["key"]: s["value"] for s in settings}
        return {
            "status": "ok",
            "data": {"settings": flat, "detailed": settings},
            "timestamp": _ts(),
            "message": "OK",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("")
def update_settings(
    body: dict[str, Any] = Body(...),
    _: str = Depends(get_current_user),
):
    """Persist settings to DB. Sensitive keys are auto-encrypted. Returns updated values (masked)."""
    try:
        from api.settings_manager import set_setting as _set, SENSITIVE_KEYS
        updated = {}
        for key, value in body.items():
            if key not in SETTINGS_KEYS:
                continue
            # Don't overwrite real values with masked placeholders or empty secrets
            if isinstance(value, str) and "***" in value:
                continue
            if key in SENSITIVE_KEYS and (value == "" or value is None):
                continue
            _set(key, value, registry=SETTINGS_KEYS)
            updated[key] = _mask(value) if (key in SENSITIVE_KEYS and value) else value
        return {"status": "ok", "data": {"updated": updated}, "timestamp": _ts(), "message": f"Updated {len(updated)} setting(s)"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/seed")
def reseed_settings(_: str = Depends(get_current_user)):
    """Force re-seed settings from env vars (overwrites existing DB values)."""
    try:
        backend = get_backend()
        seeded = 0
        for key, meta in SETTINGS_KEYS.items():
            env_var = meta["env"]
            value = os.environ.get(env_var, "") if env_var else meta["default"]
            if value is not None and value != "":
                backend.set_setting(key, value)
                seeded += 1
        logger.info("Settings: force-reseeded %d keys", seeded)
        return {"status": "ok", "data": {"seeded": seeded}, "timestamp": _ts(), "message": f"Seeded {seeded} key(s)"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))
