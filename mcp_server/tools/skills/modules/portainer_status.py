"""Portainer — environments, containers, and stacks."""
import os
from datetime import datetime, timezone

import httpx


SKILL_META = {
    "name": "portainer_status",
    "description": "Query Portainer environments, containers per endpoint, and deployed stacks.",
    "category": "compute",
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
            "action": {"type": "string", "description": "'environments' (default), 'containers', or 'stacks'"},
        },
        "required": [],
    },
    "auth_type": "api_key",
    "config_keys": ["PORTAINER_HOST", "PORTAINER_API_KEY"],
    "compat": {
        "service": "portainer",
        "api_version_built_for": "2.19",
        "min_version": "2.0",
        "max_version": "",
        "version_endpoint": "/api/status",
        "version_field": "Version",
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


def _headers() -> dict:
    api_key = os.environ.get("PORTAINER_API_KEY", "")
    if not api_key:
        return {}
    return {"X-API-Key": api_key}


def execute(**kwargs) -> dict:
    """Query Portainer environments, containers, or stacks."""
    host = os.environ.get("PORTAINER_HOST", "")
    action = kwargs.get("action", "environments")
    if not host:
        return _err("PORTAINER_HOST not configured")

    headers = _headers()
    if not headers:
        return _err("PORTAINER_API_KEY not configured")

    base = f"https://{host}:9443/api"

    try:
        if action == "containers":
            return _get_containers(base, headers)
        elif action == "stacks":
            return _get_stacks(base, headers)
        return _get_environments(base, headers)
    except httpx.HTTPStatusError as e:
        return _err(f"Portainer API error: HTTP {e.response.status_code}")
    except Exception as e:
        return _err(f"Portainer connection failed: {e}")


def _get_environments(base: str, headers: dict) -> dict:
    r = httpx.get(f"{base}/endpoints", headers=headers, verify=False, timeout=10)
    r.raise_for_status()
    endpoints = r.json()
    result = []
    unhealthy = []
    for ep in endpoints:
        status = "up" if ep.get("Status", 0) == 1 else "down"
        info = {
            "id": ep.get("Id", 0),
            "name": ep.get("Name", ""),
            "type": ep.get("Type", 0),
            "url": ep.get("URL", ""),
            "status": status,
            "snapshots": len(ep.get("Snapshots", [])),
        }
        result.append(info)
        if status != "up":
            unhealthy.append(info["name"])

    data = {"environments": result, "count": len(result)}
    if unhealthy:
        return _degraded(data, f"Portainer: {len(unhealthy)} environment(s) down: {', '.join(unhealthy)}")
    return _ok(data, f"Portainer: {len(result)} environment(s), all up")


def _get_containers(base: str, headers: dict) -> dict:
    # First get endpoints, then containers for each
    r = httpx.get(f"{base}/endpoints", headers=headers, verify=False, timeout=10)
    r.raise_for_status()
    endpoints = r.json()

    all_containers = []
    for ep in endpoints:
        ep_id = ep.get("Id", 0)
        ep_name = ep.get("Name", "")
        if ep.get("Status", 0) != 1:
            continue
        try:
            cr = httpx.get(f"{base}/endpoints/{ep_id}/docker/containers/json",
                          headers=headers, verify=False, timeout=10,
                          params={"all": "true"})
            if cr.status_code != 200:
                continue
            for c in cr.json():
                all_containers.append({
                    "environment": ep_name,
                    "name": (c.get("Names") or [""])[0].lstrip("/"),
                    "image": c.get("Image", ""),
                    "state": c.get("State", ""),
                    "status": c.get("Status", ""),
                })
        except Exception:
            continue

    return _ok({"containers": all_containers, "count": len(all_containers)},
               f"Portainer: {len(all_containers)} container(s) across {len(endpoints)} environment(s)")


def _get_stacks(base: str, headers: dict) -> dict:
    r = httpx.get(f"{base}/stacks", headers=headers, verify=False, timeout=10)
    r.raise_for_status()
    stacks = r.json()
    result = []
    for s in stacks:
        result.append({
            "id": s.get("Id", 0),
            "name": s.get("Name", ""),
            "type": s.get("Type", 0),
            "status": "active" if s.get("Status", 0) == 1 else "inactive",
            "endpoint_id": s.get("EndpointId", 0),
        })
    return _ok({"stacks": result, "count": len(result)},
               f"Portainer: {len(result)} stack(s)")


def check_compat(**kwargs) -> dict:
    """Probe Portainer version."""
    host = os.environ.get("PORTAINER_HOST", "")
    if not host:
        return _ok({"compatible": None, "detected_version": None, "reason": "Not configured"})
    headers = _headers()
    if not headers:
        return _ok({"compatible": None, "detected_version": None, "reason": "No API key"})
    try:
        r = httpx.get(f"https://{host}:9443/api/status", headers=headers, verify=False, timeout=10)
        version = r.json().get("Version", "")
        return _ok({"compatible": True, "detected_version": version, "reason": f"Portainer {version}"})
    except Exception as e:
        return _ok({"compatible": None, "detected_version": None, "reason": str(e)})
