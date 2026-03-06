"""GET/POST /api/settings — non-secret infrastructure settings."""
import os
import re
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

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
    """Update infrastructure settings in .env file."""
    path = _env_file()
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    updates = {
        "DOCKER_HOST":              body.dockerHost,
        "KAFKA_BOOTSTRAP_SERVERS":  body.kafkaBootstrapServers,
        "ELASTIC_URL":              body.elasticsearchUrl,
        "KIBANA_URL":               body.kibanaUrl,
        "MUNINN_URL":               body.muninndbUrl,
    }
    # Remove None entries
    updates = {k: v for k, v in updates.items() if v is not None}

    # Update existing lines or append
    existing_keys = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue
        if "=" in stripped:
            k = stripped.split("=", 1)[0].strip()
            if k in updates:
                new_lines.append(f'{k}={updates[k]}')
                existing_keys.add(k)
                continue
        new_lines.append(line)

    # Append keys not already in file
    for k, v in updates.items():
        if k not in existing_keys:
            new_lines.append(f"{k}={v}")

    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return {"status": "ok", "updated": list(updates.keys())}
