"""GET/POST /api/settings — DB-backed settings with env-var seeding."""
import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, Body
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
    # Infrastructure
    "kafkaBootstrapServers": {"env": "KAFKA_BOOTSTRAP_SERVERS", "sens": False, "default": ""},
    "elasticsearchUrl":      {"env": "ELASTIC_URL",             "sens": False, "default": ""},
    "kibanaUrl":             {"env": "KIBANA_URL",              "sens": False, "default": ""},
    "muninndbUrl":           {"env": "MUNINN_URL",              "sens": False, "default": ""},
    "dockerHost":            {"env": "DOCKER_HOST",             "sens": False, "default": ""},
    "swarmManagerIPs":       {"env": None,                      "sens": False, "default": ""},
    "swarmWorkerIPs":        {"env": None,                      "sens": False, "default": ""},
    # UI (stored server-side so they survive browser clears)
    "dashboardRefreshInterval": {"env": None,                   "sens": False, "default": 15000},
}


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


@router.get("")
def get_settings(_: str = Depends(get_current_user)):
    """Return all server-managed settings. Sensitive values are masked."""
    backend = get_backend()
    result = {}
    for key, meta in SETTINGS_KEYS.items():
        val = backend.get_setting(key)
        if val is None:
            # Fall back to env var then hardcoded default
            env_var = meta["env"]
            val = os.environ.get(env_var, meta["default"]) if env_var else meta["default"]
        result[key] = _mask(val) if (meta["sens"] and val) else val
    return {"settings": result}


@router.post("")
def update_settings(
    body: dict = Body(...),
    _: str = Depends(get_current_user),
):
    """Persist settings to DB. Only recognised keys are saved. Returns updated values (masked)."""
    backend = get_backend()
    updated = {}
    for key, value in body.items():
        if key not in SETTINGS_KEYS:
            continue
        backend.set_setting(key, value)
        meta = SETTINGS_KEYS[key]
        updated[key] = _mask(value) if (meta["sens"] and value) else value
    return {"status": "ok", "updated": updated}


@router.post("/seed")
def reseed_settings(_: str = Depends(get_current_user)):
    """Force re-seed settings from env vars (overwrites existing DB values)."""
    backend = get_backend()
    seeded = 0
    for key, meta in SETTINGS_KEYS.items():
        env_var = meta["env"]
        value = os.environ.get(env_var, "") if env_var else ""
        if value:
            backend.set_setting(key, value)
            seeded += 1
    logger.info("Settings: force-reseeded %d keys", seeded)
    return {"status": "ok", "seeded": seeded}
