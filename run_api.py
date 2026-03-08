"""Start the FastAPI server with all required environment variables."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent

# Load .env if present (key=value lines, skip comments and blanks)
_env_file = ROOT / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _, _v = _line.partition("=")
        _k = _k.strip()
        if _k and not os.environ.get(_k):   # don't overwrite already-set env vars
            os.environ[_k] = _v.strip()

# Load API key from mcp.json if not set
if not os.environ.get("LM_STUDIO_API_KEY"):
    try:
        mcp = json.loads((ROOT / "mcp.json").read_text())
        for srv in mcp.get("mcpServers", {}).values():
            key = srv.get("env", {}).get("LM_STUDIO_API_KEY", "")
            if key:
                os.environ["LM_STUDIO_API_KEY"] = key
                break
    except Exception:
        pass

os.environ.setdefault("DOCKER_HOST",               "npipe:////./pipe/docker_engine")
os.environ.setdefault("KAFKA_BOOTSTRAP_SERVERS",   "localhost:9092,localhost:9093,localhost:9094")
os.environ.setdefault("AUDIT_LOG_PATH",            str(ROOT / "logs" / "audit.log"))
os.environ.setdefault("CHECKPOINT_PATH",           str(ROOT / "checkpoints"))
os.environ.setdefault("DB_PATH",                   str(ROOT / "data" / "hp1_agent.db"))
os.environ.setdefault("LM_STUDIO_BASE_URL",        "http://localhost:1234/v1")
os.environ.setdefault("LM_STUDIO_MODEL",
    "lmstudio-community/qwen3-coder-30b-a3b-instruct")
os.environ.setdefault("CORS_ALLOW_ALL", "true")

sys.path.insert(0, str(ROOT))

import uvicorn
uvicorn.run(
    "api.main:app",
    host=os.environ.get("API_HOST", "0.0.0.0"),
    port=int(os.environ.get("API_PORT", "8000")),
    reload=False,
    log_level="info",
)
