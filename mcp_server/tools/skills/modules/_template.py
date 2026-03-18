"""<One-line description of what this skill does.>"""
import httpx
from datetime import datetime, timezone


# ── Skill metadata ─────────────────────────────────────────────────────────────
SKILL_META = {
    "name": "service_action_name",          # snake_case, globally unique
    "description": "What this tool does and when to call it. Be specific.",
    "category": "monitoring",               # monitoring | networking | storage | compute | general
    "version": "1.0.0",
    "annotations": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
    "parameters": {                         # JSON Schema for tool inputs
        "type": "object",
        "properties": {
            "host": {"type": "string", "description": "Target host IP or hostname"},
        },
        "required": ["host"],
    },
    "auth_type": "api_key",                 # none | api_key | token | basic
    "config_keys": ["PROXMOX_HOST", "PROXMOX_TOKEN_ID", "PROXMOX_TOKEN_SECRET"],
}


# ── Response helpers (match existing project convention) ───────────────────────
def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()

def _ok(data, message="OK") -> dict:
    return {"status": "ok", "data": data, "timestamp": _ts(), "message": message}

def _err(message, data=None) -> dict:
    return {"status": "error", "data": data, "timestamp": _ts(), "message": message}

def _degraded(data, message) -> dict:
    return {"status": "degraded", "data": data, "timestamp": _ts(), "message": message}


# ── Main execute function ──────────────────────────────────────────────────────
def execute(**kwargs) -> dict:
    """
    Run this skill. Receives kwargs matching the parameters schema.
    MUST return a dict with {status, data, timestamp, message}.
    """
    host = kwargs.get("host", "")
    if not host:
        return _err("host is required")
    try:
        # ... do the work ...
        return _ok({"host": host, "result": "..."}, "Success message")
    except Exception as e:
        return _err(f"skill_name error: {e}")
