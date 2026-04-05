"""NGINX — active connections and request stats via stub_status module."""
import os
import re
from datetime import datetime, timezone

import httpx


SKILL_META = {
    "name": "nginx_status",
    "description": "Query NGINX active connections, request rates, and accept/handled counts via stub_status.",
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
        "properties": {
            "action": {"type": "string", "description": "'status' (default)"},
        },
        "required": [],
    },
    "auth_type": "none",
    "config_keys": ["NGINX_HOST"],
    "compat": {
        "service": "nginx",
        "api_version_built_for": "1.25",
        "min_version": "1.0",
        "max_version": "",
        "version_endpoint": "/nginx_status",
        "version_field": "",
    },
}


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()

def _ok(data, message="OK") -> dict:
    return {"status": "ok", "data": data, "timestamp": _ts(), "message": message}

def _err(message, data=None) -> dict:
    return {"status": "error", "data": data, "timestamp": _ts(), "message": message}


def _auth() -> tuple | None:
    user = os.environ.get("NGINX_USER", "")
    password = os.environ.get("NGINX_PASSWORD", "")
    return (user, password) if user else None


def execute(**kwargs) -> dict:
    host = os.environ.get("NGINX_HOST", "")
    if not host:
        return _err("NGINX_HOST not configured")

    auth = _auth()

    # Try common stub_status paths
    for path in ("/nginx_status", "/status", "/stub_status", "/basic_status"):
        try:
            r = httpx.get(f"http://{host}{path}", auth=auth, timeout=10)
            if r.status_code == 200 and "Active connections" in r.text:
                return _parse_stub_status(r.text)
        except Exception:
            continue

    return _err(
        "NGINX stub_status not found. Tried /nginx_status, /status, /stub_status, /basic_status. "
        "Enable stub_status module: location /nginx_status { stub_status; allow 127.0.0.1; deny all; }"
    )


def _parse_stub_status(text: str) -> dict:
    """Parse nginx stub_status output.

    Format:
        Active connections: 3
        server accepts handled requests
         12345 12345 67890
        Reading: 0 Writing: 1 Waiting: 2
    """
    result = {}

    m = re.search(r"Active connections:\s*(\d+)", text)
    if m:
        result["active_connections"] = int(m.group(1))

    m = re.search(r"(\d+)\s+(\d+)\s+(\d+)", text)
    if m:
        result["accepts"] = int(m.group(1))
        result["handled"] = int(m.group(2))
        result["requests"] = int(m.group(3))
        result["dropped"] = result["accepts"] - result["handled"]

    m = re.search(r"Reading:\s*(\d+)\s+Writing:\s*(\d+)\s+Waiting:\s*(\d+)", text)
    if m:
        result["reading"] = int(m.group(1))
        result["writing"] = int(m.group(2))
        result["waiting"] = int(m.group(3))

    active = result.get("active_connections", 0)
    dropped = result.get("dropped", 0)
    return _ok(result, f"NGINX: {active} active connection(s), {dropped} dropped")


def check_compat(**kwargs) -> dict:
    host = os.environ.get("NGINX_HOST", "")
    if not host:
        return _ok({"compatible": None, "detected_version": None, "reason": "Not configured"})
    try:
        r = httpx.get(f"http://{host}/nginx_status", auth=_auth(), timeout=10)
        if r.status_code == 200 and "Active connections" in r.text:
            return _ok({"compatible": True, "detected_version": "stub_status enabled", "reason": "NGINX stub_status reachable"})
        return _ok({"compatible": None, "detected_version": None, "reason": "stub_status not enabled"})
    except Exception as e:
        return _ok({"compatible": None, "detected_version": None, "reason": str(e)})
