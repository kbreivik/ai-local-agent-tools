"""Traefik — overview, routers, services, and entrypoints."""
import os
from datetime import datetime, timezone

import httpx


PLUGIN_META = {
    "name": "traefik_status",
    "description": "Query Traefik overview, HTTP/TCP routers, backend services, and entrypoints.",
    "platform": "traefik",
    "category": "networking",
    "agent_types": ["observe", "investigate"],
    "requires_plan": False,
    "params": {
        "host": {"type": "string", "required": False, "description": "Traefik host (default: env TRAEFIK_HOST)"},
        "action": {"type": "string", "required": False, "description": "'overview' (default), 'routers', 'services', or 'entrypoints'"},
    },
}


def _ts():
    return datetime.now(timezone.utc).isoformat()

def _ok(data, message="OK"):
    return {"status": "ok", "data": data, "timestamp": _ts(), "message": message}

def _err(message, data=None):
    return {"status": "error", "data": data, "timestamp": _ts(), "message": message}

def _degraded(data, message):
    return {"status": "degraded", "data": data, "timestamp": _ts(), "message": message}


def _auth() -> tuple:
    user = os.environ.get("TRAEFIK_USER", "")
    password = os.environ.get("TRAEFIK_PASSWORD", "")
    return (user, password) if user else None


def validate(**kwargs) -> dict:
    host = kwargs.get("host") or os.environ.get("TRAEFIK_HOST", "")
    if not host:
        return _err("TRAEFIK_HOST not configured")
    try:
        r = httpx.get(f"http://{host}:8080/api/version", auth=_auth(), timeout=10)
        r.raise_for_status()
        return _ok(r.json(), "Traefik reachable")
    except Exception as e:
        return _err(f"Traefik connection failed: {e}")


def execute(**kwargs) -> dict:
    host = kwargs.get("host") or os.environ.get("TRAEFIK_HOST", "")
    action = kwargs.get("action", "overview")
    if not host:
        return _err("TRAEFIK_HOST not configured")

    base = f"http://{host}:8080/api"
    auth = _auth()
    try:
        if action == "routers":
            return _get_routers(base, auth)
        elif action == "services":
            return _get_services(base, auth)
        elif action == "entrypoints":
            return _get_entrypoints(base, auth)
        return _get_overview(base, auth)
    except httpx.HTTPStatusError as e:
        return _err(f"Traefik API error: HTTP {e.response.status_code}")
    except Exception as e:
        return _err(f"Traefik connection failed: {e}")


def _get_overview(base: str, auth) -> dict:
    r = httpx.get(f"{base}/overview", auth=auth, timeout=10)
    r.raise_for_status()
    data = r.json()
    http_info = data.get("http", {})
    tcp_info = data.get("tcp", {})
    return _ok({
        "http_routers": http_info.get("routers", {}).get("total", 0),
        "http_services": http_info.get("services", {}).get("total", 0),
        "http_middlewares": http_info.get("middlewares", {}).get("total", 0),
        "tcp_routers": tcp_info.get("routers", {}).get("total", 0),
        "tcp_services": tcp_info.get("services", {}).get("total", 0),
    }, f"Traefik: {http_info.get('routers', {}).get('total', 0)} HTTP router(s)")


def _get_routers(base: str, auth) -> dict:
    r = httpx.get(f"{base}/http/routers", auth=auth, timeout=10)
    r.raise_for_status()
    routers = r.json()
    result = []
    errors = []
    for rt in routers:
        status = rt.get("status", "")
        info = {
            "name": rt.get("name", ""),
            "rule": rt.get("rule", ""),
            "service": rt.get("service", ""),
            "tls": bool(rt.get("tls")),
            "status": status,
            "entryPoints": rt.get("entryPoints", []),
        }
        result.append(info)
        if status != "enabled":
            errors.append(info["name"])

    data = {"routers": result, "count": len(result)}
    if errors:
        return _degraded(data, f"Traefik: {len(errors)} router(s) not enabled: {', '.join(errors[:5])}")
    return _ok(data, f"Traefik: {len(result)} HTTP router(s)")


def _get_services(base: str, auth) -> dict:
    r = httpx.get(f"{base}/http/services", auth=auth, timeout=10)
    r.raise_for_status()
    services = r.json()
    result = []
    for svc in services:
        lb = svc.get("loadBalancer", {})
        servers = lb.get("servers", [])
        result.append({
            "name": svc.get("name", ""),
            "type": svc.get("type", ""),
            "status": svc.get("status", ""),
            "servers": [s.get("url", "") for s in servers],
            "server_count": len(servers),
        })
    return _ok({"services": result, "count": len(result)},
               f"Traefik: {len(result)} HTTP service(s)")


def _get_entrypoints(base: str, auth) -> dict:
    r = httpx.get(f"{base}/entrypoints", auth=auth, timeout=10)
    r.raise_for_status()
    eps = r.json()
    result = []
    for ep in eps:
        result.append({
            "name": ep.get("name", ""),
            "address": ep.get("address", ""),
        })
    return _ok({"entrypoints": result, "count": len(result)},
               f"Traefik: {len(result)} entrypoint(s)")
