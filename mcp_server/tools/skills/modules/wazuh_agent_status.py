"""Wazuh SIEM — agent status and recent security alerts."""
import os
from datetime import datetime, timezone

import httpx


SKILL_META = {
    "name": "wazuh_agent_status",
    "description": "Query Wazuh agent list with status and recent security alerts by severity.",
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
            "action": {"type": "string", "description": "'agents' (default) or 'alerts'"},
        },
        "required": [],
    },
    "auth_type": "basic",
    "config_keys": ["WAZUH_HOST", "WAZUH_API_USER", "WAZUH_API_PASSWORD"],
    "compat": {
        "service": "wazuh",
        "api_version_built_for": "4.7",
        "min_version": "4.3",
        "max_version": "",
        "version_endpoint": "/",
        "version_field": "data.api_version",
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


def _authenticate(host: str) -> str:
    """Authenticate to Wazuh API, return JWT token."""
    user = os.environ.get("WAZUH_API_USER", "")
    password = os.environ.get("WAZUH_API_PASSWORD", "")
    if not user or not password:
        return ""
    r = httpx.post(
        f"https://{host}:55000/security/user/authenticate",
        auth=(user, password),
        verify=False, timeout=10,
    )
    r.raise_for_status()
    return r.json().get("data", {}).get("token", "")


def execute(**kwargs) -> dict:
    """Query Wazuh agents or alerts."""
    host = os.environ.get("WAZUH_HOST", "")
    action = kwargs.get("action", "agents")
    if not host:
        return _err("WAZUH_HOST not configured")

    try:
        token = _authenticate(host)
        if not token:
            return _err("WAZUH_API_USER and WAZUH_API_PASSWORD required")
        headers = {"Authorization": f"Bearer {token}"}

        if action == "alerts":
            return _get_alerts(host, headers)
        return _get_agents(host, headers)

    except httpx.HTTPStatusError as e:
        return _err(f"Wazuh API error: HTTP {e.response.status_code}")
    except Exception as e:
        return _err(f"Wazuh connection failed: {e}")


def _get_agents(host: str, headers: dict) -> dict:
    r = httpx.get(f"https://{host}:55000/agents",
                  headers=headers, verify=False, timeout=10,
                  params={"limit": 50, "select": "id,name,ip,os.name,os.version,status,lastKeepAlive"})
    r.raise_for_status()
    agents = r.json().get("data", {}).get("affected_items", [])

    result = []
    disconnected = []
    for a in agents:
        status = a.get("status", "unknown")
        info = {
            "id": a.get("id", ""),
            "name": a.get("name", ""),
            "ip": a.get("ip", ""),
            "os": f"{a.get('os', {}).get('name', '')} {a.get('os', {}).get('version', '')}".strip(),
            "status": status,
            "last_keepalive": a.get("lastKeepAlive", ""),
        }
        result.append(info)
        if status != "active":
            disconnected.append(info["name"])

    data = {"agents": result, "count": len(result)}
    if disconnected:
        return _degraded(data, f"Wazuh: {len(disconnected)} inactive agent(s): {', '.join(disconnected[:5])}")
    return _ok(data, f"Wazuh: {len(result)} agent(s), all active")


def _get_alerts(host: str, headers: dict) -> dict:
    r = httpx.get(f"https://{host}:55000/security/events",
                  headers=headers, verify=False, timeout=10,
                  params={"limit": 20, "sort": "-timestamp"})
    # Fallback to /alerts if security/events not available
    if r.status_code == 404:
        r = httpx.get(f"https://{host}:55000/alerts",
                      headers=headers, verify=False, timeout=10,
                      params={"limit": 20, "sort": "-timestamp"})
    r.raise_for_status()
    alerts = r.json().get("data", {}).get("affected_items", [])

    result = []
    for a in alerts[:20]:
        result.append({
            "rule_id": a.get("rule", {}).get("id", ""),
            "description": a.get("rule", {}).get("description", ""),
            "level": a.get("rule", {}).get("level", 0),
            "agent": a.get("agent", {}).get("name", ""),
            "timestamp": a.get("timestamp", ""),
        })

    critical = [a for a in result if a["level"] >= 12]
    data = {"alerts": result, "count": len(result), "critical": len(critical)}
    if critical:
        return _degraded(data, f"Wazuh: {len(critical)} critical alert(s)")
    return _ok(data, f"Wazuh: {len(result)} recent alert(s)")


def check_compat(**kwargs) -> dict:
    """Probe Wazuh API version."""
    host = os.environ.get("WAZUH_HOST", "")
    if not host:
        return _ok({"compatible": None, "detected_version": None, "reason": "Not configured"})
    try:
        token = _authenticate(host)
        if not token:
            return _ok({"compatible": None, "detected_version": None, "reason": "Auth failed"})
        r = httpx.get(f"https://{host}:55000/", headers={"Authorization": f"Bearer {token}"},
                      verify=False, timeout=10)
        version = r.json().get("data", {}).get("api_version", "")
        return _ok({"compatible": True, "detected_version": version, "reason": f"Wazuh API: {version}"})
    except Exception as e:
        return _ok({"compatible": None, "detected_version": None, "reason": str(e)})
