"""Kibana — status, spaces, and saved dashboards."""
import os
from datetime import datetime, timezone

import httpx


SKILL_META = {
    "name": "kibana_status",
    "description": "Check Kibana health, list spaces, and browse saved dashboards.",
    "category": "monitoring",
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
            "action": {"type": "string", "description": "'status' (default), 'spaces', or 'dashboards'"},
        },
        "required": [],
    },
    "auth_type": "basic",
    "config_keys": ["KIBANA_HOST", "KIBANA_USER", "KIBANA_PASSWORD"],
    "compat": {
        "service": "kibana",
        "api_version_built_for": "8.12",
        "min_version": "7.10",
        "max_version": "",
        "version_endpoint": "/api/status",
        "version_field": "version.number",
    },
}


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()

def _ok(data, message="OK") -> dict:
    return {"status": "ok", "data": data, "timestamp": _ts(), "message": message}

def _err(message, data=None) -> dict:
    return {"status": "error", "data": data, "timestamp": _ts(), "message": message}

def _degraded(data, message) -> dict:
    return {"status": "degraded", "data": data, "timestamp": _ts(), "message": message}


def _client_and_base() -> tuple:
    """Return (httpx.Client, base_url) with auth configured."""
    host = os.environ.get("KIBANA_HOST", "")
    if not host:
        return None, ""
    user = os.environ.get("KIBANA_USER", "")
    password = os.environ.get("KIBANA_PASSWORD", "")
    auth = (user, password) if user else None
    base = f"http://{host}:5601"
    client = httpx.Client(verify=False, timeout=10, auth=auth,
                          headers={"kbn-xsrf": "true"})
    return client, base


def execute(**kwargs) -> dict:
    host = os.environ.get("KIBANA_HOST", "")
    action = kwargs.get("action", "status")
    if not host:
        return _err("KIBANA_HOST not configured")

    client, base = _client_and_base()
    if not client:
        return _err("KIBANA_HOST not configured")

    try:
        if action == "spaces":
            return _get_spaces(client, base)
        elif action == "dashboards":
            return _get_dashboards(client, base)
        return _get_status(client, base)
    except httpx.HTTPStatusError as e:
        return _err(f"Kibana API error: HTTP {e.response.status_code}")
    except Exception as e:
        return _err(f"Kibana connection failed: {e}")
    finally:
        client.close()


def _get_status(client: httpx.Client, base: str) -> dict:
    r = client.get(f"{base}/api/status")
    r.raise_for_status()
    data = r.json()
    version = data.get("version", {}).get("number", "")
    overall = data.get("status", {}).get("overall", {}).get("state", "unknown")
    result = {
        "version": version,
        "status": overall,
        "name": data.get("name", ""),
        "uuid": data.get("uuid", ""),
    }
    if overall != "green":
        return _degraded(result, f"Kibana v{version}: status {overall}")
    return _ok(result, f"Kibana v{version}: healthy")


def _get_spaces(client: httpx.Client, base: str) -> dict:
    r = client.get(f"{base}/api/spaces/space")
    r.raise_for_status()
    spaces = r.json()
    result = []
    for s in spaces:
        result.append({
            "id": s.get("id", ""),
            "name": s.get("name", ""),
            "description": s.get("description", ""),
        })
    return _ok({"spaces": result, "count": len(result)},
               f"Kibana: {len(result)} space(s)")


def _get_dashboards(client: httpx.Client, base: str) -> dict:
    r = client.get(f"{base}/api/saved_objects/_find",
                   params={"type": "dashboard", "per_page": 50})
    r.raise_for_status()
    data = r.json()
    dashboards = []
    for obj in data.get("saved_objects", []):
        attrs = obj.get("attributes", {})
        dashboards.append({
            "id": obj.get("id", ""),
            "title": attrs.get("title", ""),
            "description": attrs.get("description", ""),
            "namespace": obj.get("namespaces", ["default"])[0] if obj.get("namespaces") else "default",
        })
    return _ok({"dashboards": dashboards, "count": data.get("total", len(dashboards))},
               f"Kibana: {data.get('total', len(dashboards))} dashboard(s)")


def check_compat(**kwargs) -> dict:
    host = os.environ.get("KIBANA_HOST", "")
    if not host:
        return _ok({"compatible": None, "detected_version": None, "reason": "Not configured"})
    client, base = _client_and_base()
    if not client:
        return _ok({"compatible": None, "detected_version": None, "reason": "Not configured"})
    try:
        r = client.get(f"{base}/api/status")
        version = r.json().get("version", {}).get("number", "")
        client.close()
        return _ok({"compatible": True, "detected_version": version, "reason": f"Kibana {version}"})
    except Exception as e:
        client.close()
        return _ok({"compatible": None, "detected_version": None, "reason": str(e)})
