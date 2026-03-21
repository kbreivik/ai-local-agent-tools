# Skill Generation Export — 2026-03-20 21:22 UTC

## Instructions

1. Copy everything below the separator line into your LLM chat (ChatGPT, Claude, etc.).
2. Send the prompt. The LLM will output a single Python file.
3. Save the output as a .py file (use the skill name from SKILL_META as the filename).
4. Copy the .py file to the agent's `data/skill_imports/` directory.
5. In the agent chat, run: `skill_import` to load and validate the skill.
6. Verify with: `skill_list` to see the newly imported skill.

---

## Skill Contract (follow this exactly)

```python
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
    "config_keys": ["SERVICE_HOST", "SERVICE_API_KEY"],
    "compat": {                             # Compatibility tracking
        "service": "service_name",          # Service identifier (e.g. "proxmox", "fortigate")
        "api_version_built_for": "1.0",     # API version used when writing this skill
        "min_version": "",                  # Oldest version known to work (empty = unknown)
        "max_version": "",                  # Newest version known to work (empty = no upper bound)
        "version_endpoint": "",             # API path to check service version
        "version_field": "",                # Dot-path to extract version from response
    },
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


# ── Optional: compatibility check ─────────────────────────────────────────────
def check_compat(**kwargs) -> dict:
    """
    OPTIONAL. Probe the target service version and check against compat bounds.
    If not implemented, the loader skips compat checking via probe for this skill.
    Returns: _ok({"compatible": True/False/None, "detected_version": "...", "reason": "..."})
    """
    return _ok({"compatible": None, "detected_version": None}, "Compat check not implemented")


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
        return _ok({"host": host, "result": "...", "detected_version": "1.0.0"}, "Success message")
    except Exception as e:
        return _err(f"skill_name error: {e}")

```

## What to Build

- **Description**: check TrueNAS pool health
- **Category**: storage
- **Auth type**: none

## Existing Skills (avoid these names)

- fortigate_system_status
- http_health_check
- proxmox_vm_status

## Hard Constraints

1. Output ONLY valid Python — no markdown fences, no explanation text before or after.
2. SKILL_META name must be snake_case, descriptive, unique.
3. Use httpx for HTTP calls with explicit timeouts (default 10s).
4. Return _ok/_err/_degraded dicts exactly as shown in template.
5. Include _ts, _ok, _err, _degraded helpers in every skill.
6. NEVER import subprocess, os.system, eval, exec, __import__, importlib, shutil.
7. Set readOnlyHint: True by default unless skill explicitly modifies state.
8. Handle missing config: return _err("CONFIG_KEY not set. Configure via Settings or env var.")
9. No markdown fences in output.