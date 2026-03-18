"""Get FortiGate firewall system status including hostname, firmware version, uptime, and HA state."""
import json
import os

import httpx
from datetime import datetime, timezone


SKILL_META = {
    "name": "fortigate_system_status",
    "description": "Get FortiGate firewall system status including hostname, firmware version, uptime, and HA state.",
    "category": "networking",
    "version": "1.0.0",
    "annotations": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
    "auth_type": "api_key",
    "config_keys": ["FORTIGATE_HOST", "FORTIGATE_API_KEY"],
}


# ── Response helpers ───────────────────────────────────────────────────────────
def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()

def _ok(data, message="OK") -> dict:
    return {"status": "ok", "data": data, "timestamp": _ts(), "message": message}

def _err(message, data=None) -> dict:
    return {"status": "error", "data": data, "timestamp": _ts(), "message": message}

def _degraded(data, message) -> dict:
    return {"status": "degraded", "data": data, "timestamp": _ts(), "message": message}


# ── Config ─────────────────────────────────────────────────────────────────────
def _fortigate_config() -> dict:
    settings_path = os.path.join(
        os.path.dirname(
            os.path.dirname(
                os.path.dirname(
                    os.path.dirname(
                        os.path.dirname(__file__)
                    )
                )
            )
        ),
        "data", "agent_settings.json"
    )
    file_cfg = {}
    try:
        if os.path.exists(settings_path):
            with open(settings_path) as f:
                cfg = json.load(f)
                file_cfg = cfg.get("fortigate", {})
    except Exception:
        pass

    return {
        "host": os.environ.get("FORTIGATE_HOST", file_cfg.get("host", "")),
        "api_key": os.environ.get("FORTIGATE_API_KEY", file_cfg.get("api_key", "")),
    }


# ── Execute ────────────────────────────────────────────────────────────────────
def execute(**kwargs) -> dict:
    cfg = _fortigate_config()
    if not cfg["host"]:
        return _err("FORTIGATE_HOST not set. Configure via Settings or env var.")
    if not cfg["api_key"]:
        return _err("FORTIGATE_API_KEY not set. Configure via Settings or env var.")

    host = cfg["host"]
    api_key = cfg["api_key"]

    try:
        r = httpx.get(
            f"https://{host}/api/v2/monitor/system/status",
            params={"access_token": api_key},
            verify=False,
            timeout=10.0,
        )
        r.raise_for_status()
        data = r.json().get("results", r.json())

        result = {
            "hostname": data.get("hostname", "unknown"),
            "serial": data.get("serial", "unknown"),
            "version": data.get("version", "unknown"),
            "build": data.get("build", "unknown"),
            "uptime": data.get("uptime", 0),
        }

        # Check HA state
        ha_mode = data.get("ha_mode", "standalone")
        result["ha_mode"] = ha_mode

        if ha_mode != "standalone":
            ha_info = data.get("ha_info", {})
            result["ha_info"] = ha_info
            # Check sync status
            is_synced = ha_info.get("in_sync", True) if isinstance(ha_info, dict) else True
            if not is_synced:
                return _degraded(result,
                                 f"FortiGate '{result['hostname']}' HA not synced (mode: {ha_mode})")

        return _ok(result,
                   f"FortiGate '{result['hostname']}' v{result['version']} uptime {result['uptime']}s")

    except httpx.HTTPStatusError as e:
        return _err(f"FortiGate API error: HTTP {e.response.status_code}")
    except Exception as e:
        return _err(f"fortigate_system_status error: {e}")
