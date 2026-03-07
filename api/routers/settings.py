"""GET/POST /api/settings — non-secret infrastructure settings."""
import logging
import os
import re
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])

# Keys that are safe to return (infrastructure, no secrets)
_SAFE_KEYS = {
    "DOCKER_HOST",
    "KAFKA_BOOTSTRAP_SERVERS",
    "ELASTIC_URL",
    "ELASTIC_INDEX_PATTERN",
    "MUNINN_URL",
    "API_HOST",
    "API_PORT",
    "LM_STUDIO_BASE_URL",
    "LM_STUDIO_MODEL",
}

# Keys that contain secrets — mask them
_SECRET_PATTERN = re.compile(r"key|secret|password|token", re.IGNORECASE)


def _env_file() -> Path:
    return Path(__file__).parent.parent.parent / ".env"


def _read_env() -> dict:
    """Read .env file as key→value dict. Returns {} if file not found."""
    path = _env_file()
    result = {}
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            result[k.strip()] = v.strip().strip('"').strip("'")
    return result


def _mask(key: str, value: str) -> str:
    if _SECRET_PATTERN.search(key):
        return value[:6] + "***" if len(value) > 6 else "***"
    return value


@router.get("")
async def get_settings():
    """Return current non-secret settings."""
    env = _read_env()
    # Merge .env with os.environ, .env takes priority for display
    result = {}
    for k in _SAFE_KEYS:
        v = env.get(k) or os.environ.get(k, "")
        if v:
            result[k] = _mask(k, v)
    return {"settings": result}


class SettingsBody(BaseModel):
    dockerHost:            str | None = None
    kafkaBootstrapServers: str | None = None
    elasticsearchUrl:      str | None = None
    kibanaUrl:             str | None = None
    muninndbUrl:           str | None = None
    swarmManagerIPs:       str | None = None
    swarmWorkerIPs:        str | None = None


@router.post("")
async def update_settings(body: SettingsBody):
    """
    Settings are read-only via API — edit .env directly to change them.

    This endpoint intentionally does NOT write to .env. Writing to .env from
    the API was the root cause of .env values being lost between restarts
    (partial rewrites discarded lines not in the known key set).

    To update settings: stop the server, edit .env, restart.
    """
    updates = {
        "DOCKER_HOST":              body.dockerHost,
        "KAFKA_BOOTSTRAP_SERVERS":  body.kafkaBootstrapServers,
        "ELASTIC_URL":              body.elasticsearchUrl,
        "KIBANA_URL":               body.kibanaUrl,
        "MUNINN_URL":               body.muninndbUrl,
    }
    updates = {k: v for k, v in updates.items() if v is not None}

    for k, v in updates.items():
        logger.warning(
            "POST /api/settings: would have written %s=%r to .env — skipped. "
            "Edit .env directly and restart the server.",
            k, v,
        )

    return {
        "status": "readonly",
        "message": "Settings are managed via .env. Edit .env and restart the server to apply changes.",
        "requested_updates": list(updates.keys()),
    }
