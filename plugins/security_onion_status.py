"""Security Onion — grid status, alerts, and node health."""
import os
from datetime import datetime, timezone

import httpx


PLUGIN_META = {
    "name": "security_onion_status",
    "description": "Query Security Onion grid status, recent security alerts, and SOC node health.",
    "platform": "security_onion",
    "category": "monitoring",
    "agent_types": ["observe", "investigate"],
    "requires_plan": False,
    "params": {
        "host": {"type": "string", "required": False, "description": "Security Onion host (default: env SECONION_HOST)"},
        "action": {"type": "string", "required": False, "description": "'status' (default), 'alerts', or 'nodes'"},
        "hours": {"type": "integer", "required": False, "description": "Alert lookback hours (default: 24)"},
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


def _get_auth(host: str) -> dict:
    """Get auth headers for Security Onion SOC API."""
    api_key = os.environ.get("SECONION_API_KEY", "")
    if api_key:
        return {"Authorization": f"Bearer {api_key}"}
    # Try username/password login
    user = os.environ.get("SECONION_USER", "")
    password = os.environ.get("SECONION_PASSWORD", "")
    if user and password:
        try:
            r = httpx.post(f"https://{host}/api/auth/login",
                          json={"username": user, "password": password},
                          verify=False, timeout=10)
            if r.status_code == 200:
                token = r.json().get("token", r.json().get("access_token", ""))
                if token:
                    return {"Authorization": f"Bearer {token}"}
        except Exception:
            pass
    return {}


def validate(**kwargs) -> dict:
    host = kwargs.get("host") or os.environ.get("SECONION_HOST", "")
    if not host:
        return _err("SECONION_HOST not configured")
    headers = _get_auth(host)
    if not headers:
        return _err("SECONION_API_KEY or SECONION_USER/PASSWORD required")
    try:
        r = httpx.get(f"https://{host}/api/info", headers=headers, verify=False, timeout=10)
        r.raise_for_status()
        return _ok(r.json(), "Security Onion reachable")
    except Exception as e:
        return _err(f"Security Onion connection failed: {e}")


def execute(**kwargs) -> dict:
    host = kwargs.get("host") or os.environ.get("SECONION_HOST", "")
    action = kwargs.get("action", "status")
    hours = int(kwargs.get("hours", 24))
    if not host:
        return _err("SECONION_HOST not configured")

    headers = _get_auth(host)
    if not headers:
        return _err("SECONION_API_KEY or SECONION_USER/PASSWORD required")

    base = f"https://{host}/api"
    try:
        if action == "alerts":
            return _get_alerts(base, headers, hours)
        elif action == "nodes":
            return _get_nodes(base, headers)
        return _get_status(base, headers)
    except httpx.HTTPStatusError as e:
        return _err(f"Security Onion API error: HTTP {e.response.status_code}")
    except Exception as e:
        return _err(f"Security Onion connection failed: {e}")


def _get_status(base: str, headers: dict) -> dict:
    r = httpx.get(f"{base}/grid", headers=headers, verify=False, timeout=10)
    r.raise_for_status()
    data = r.json()
    result = {
        "status": data.get("status", "unknown"),
        "nodes": data.get("node_count", 0),
        "version": data.get("version", ""),
    }
    if result["status"] != "ok":
        return _degraded(result, f"Security Onion grid: {result['status']}")
    return _ok(result, f"Security Onion: {result['nodes']} node(s), grid healthy")


def _get_alerts(base: str, headers: dict, hours: int) -> dict:
    params = {"hours": hours, "limit": 50}
    r = httpx.get(f"{base}/alerts", headers=headers, verify=False, timeout=15, params=params)
    # Fallback: try events endpoint
    if r.status_code == 404:
        r = httpx.get(f"{base}/events", headers=headers, verify=False, timeout=15, params=params)
    r.raise_for_status()
    alerts = r.json() if isinstance(r.json(), list) else r.json().get("data", r.json().get("alerts", []))

    result = []
    for a in alerts[:50]:
        result.append({
            "severity": a.get("severity", a.get("rule", {}).get("severity", "")),
            "description": a.get("description", a.get("rule", {}).get("name", "")),
            "source_ip": a.get("source_ip", a.get("src_ip", "")),
            "dest_ip": a.get("dest_ip", a.get("dst_ip", "")),
            "timestamp": a.get("timestamp", ""),
        })

    high = [a for a in result if str(a.get("severity", "")).lower() in ("high", "critical", "3", "4")]
    data = {"alerts": result, "count": len(result), "high_severity": len(high)}
    if high:
        return _degraded(data, f"Security Onion: {len(high)} high-severity alert(s) in last {hours}h")
    return _ok(data, f"Security Onion: {len(result)} alert(s) in last {hours}h")


def _get_nodes(base: str, headers: dict) -> dict:
    r = httpx.get(f"{base}/grid/members", headers=headers, verify=False, timeout=10)
    # Fallback
    if r.status_code == 404:
        r = httpx.get(f"{base}/nodes", headers=headers, verify=False, timeout=10)
    r.raise_for_status()
    nodes = r.json() if isinstance(r.json(), list) else r.json().get("data", r.json().get("nodes", []))

    result = []
    unhealthy = []
    for n in nodes:
        status = n.get("status", "unknown")
        info = {
            "name": n.get("name", n.get("hostname", "")),
            "role": n.get("role", ""),
            "status": status,
            "ip": n.get("ip", n.get("address", "")),
        }
        result.append(info)
        if status not in ("ok", "running", "active"):
            unhealthy.append(info["name"])

    data = {"nodes": result, "count": len(result)}
    if unhealthy:
        return _degraded(data, f"Security Onion: {len(unhealthy)} unhealthy node(s): {', '.join(unhealthy)}")
    return _ok(data, f"Security Onion: {len(result)} node(s), all healthy")
