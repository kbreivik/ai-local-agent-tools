"""Central constants for HP1-AI-Agent.

Single source of truth for values used across multiple modules.
Change here to update everywhere.
"""

# ── Application identity ──────────────────────────────────────────────────────

APP_NAME = "HP1-AI-Agent"

# ── Version management ───────────────────────────────────────────────────────

from pathlib import Path as _Path

def _read_version() -> str:
    try:
        return _Path(__file__).parent.parent.joinpath("VERSION").read_text().strip()
    except OSError:
        import logging as _logging
        _logging.getLogger(__name__).warning("VERSION file not found — defaulting to 'unknown'")
        return "unknown"

APP_VERSION = _read_version()

# ── Network ports ─────────────────────────────────────────────────────────────

DEFAULT_API_PORT = 8000   # FastAPI backend
DEFAULT_GUI_PORT = 5173   # Vite dev server (CORS origin, proxy target)

# ── LM Studio defaults ────────────────────────────────────────────────────────

DEFAULT_LM_STUDIO_URL   = "http://localhost:1234/v1"
DEFAULT_LM_STUDIO_MODEL = "lmstudio-community/qwen3-coder-30b-a3b-instruct"
DEFAULT_LM_STUDIO_KEY   = "lm-studio"

# ── Kafka defaults ────────────────────────────────────────────────────────────

DEFAULT_KAFKA_BOOTSTRAP   = "localhost:9092,localhost:9093,localhost:9094"
DEFAULT_KAFKA_LAG_THRESHOLD = 1000  # consumer group lag before alert fires
