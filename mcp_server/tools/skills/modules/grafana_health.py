"""Grafana — health status, dashboards, and firing alert rules."""
import os
from datetime import datetime, timezone

import httpx


SKILL_META = {
    "name": "grafana_health",
    "description": "Check Grafana health, list dashboards, and query firing alert rules.",
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
            "action": {"type": "string", "description": "'health' (default), 'dashboards', or 'alerts'"},
        },
        "required": [],
    },
    "auth_type": "bearer",
    "config_keys": ["GRAFANA_HOST", "GRAFANA_API_KEY"],
    "compat": {
        "service": "grafana",
        "api_version_built_for": "10.0",
        "min_version": "9.0",
        "max_version": "",
        "version_endpoint": "/api/health",
        "version_field": "version",
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
    api_key = os.environ.get("GRAFANA_API_KEY", "")
    if not api_key:
        return {}
    return {"Authorization": f"Bearer {api_key}"}


def execute(**kwargs) -> dict:
    """Query Grafana health, dashboards, or alerts."""
    host = os.environ.get("GRAFANA_HOST", "")
    action = kwargs.get("action", "health")
    if not host:
        return _err("GRAFANA_HOST not configured")

    headers = _headers()
    if not headers:
        return _err("GRAFANA_API_KEY not configured")

    base = f"http://{host}:3000/api"

    try:
        if action == "dashboards":
            return _get_dashboards(base, headers)
        elif action == "alerts":
            return _get_alerts(base, headers)
        return _get_health(base, headers)
    except httpx.HTTPStatusError as e:
        return _err(f"Grafana API error: HTTP {e.response.status_code}")
    except Exception as e:
        return _err(f"Grafana connection failed: {e}")


def _get_health(base: str, headers: dict) -> dict:
    r = httpx.get(f"{base}/health", headers=headers, timeout=10)
    r.raise_for_status()
    data = r.json()

    # Get org info
    org = {}
    try:
        or_r = httpx.get(f"{base}/org", headers=headers, timeout=10)
        if or_r.status_code == 200:
            org = or_r.json()
    except Exception:
        pass

    result = {
        "version": data.get("version", ""),
        "database": data.get("database", ""),
        "commit": data.get("commit", ""),
        "org_name": org.get("name", ""),
    }
    db_ok = data.get("database", "") == "ok"
    if not db_ok:
        return _degraded(result, f"Grafana v{result['version']}: database {data.get('database', 'unknown')}")
    return _ok(result, f"Grafana v{result['version']}: healthy")


def _get_dashboards(base: str, headers: dict) -> dict:
    r = httpx.get(f"{base}/search", headers=headers, timeout=10,
                  params={"type": "dash-db", "limit": 50})
    r.raise_for_status()
    dashboards = r.json()
    result = []
    for d in dashboards:
        result.append({
            "uid": d.get("uid", ""),
            "title": d.get("title", ""),
            "folder": d.get("folderTitle", ""),
            "url": d.get("url", ""),
            "tags": d.get("tags", []),
        })
    return _ok({"dashboards": result, "count": len(result)},
               f"Grafana: {len(result)} dashboard(s)")


def _get_alerts(base: str, headers: dict) -> dict:
    r = httpx.get(f"{base}/alertmanager/grafana/api/v2/alerts",
                  headers=headers, timeout=10)
    if r.status_code == 404:
        # Fallback for older Grafana without unified alerting
        r = httpx.get(f"{base}/alerts", headers=headers, timeout=10)
    r.raise_for_status()
    alerts = r.json()
    if not isinstance(alerts, list):
        alerts = alerts.get("data", alerts.get("alerts", []))

    result = []
    for a in alerts[:20]:
        result.append({
            "name": a.get("labels", {}).get("alertname", a.get("name", "")),
            "state": a.get("status", {}).get("state", a.get("state", "")),
            "severity": a.get("labels", {}).get("severity", ""),
            "summary": a.get("annotations", {}).get("summary", ""),
        })

    firing = [a for a in result if a["state"] in ("firing", "alerting")]
    data = {"alerts": result, "count": len(result), "firing": len(firing)}
    if firing:
        return _degraded(data, f"Grafana: {len(firing)} alert(s) firing")
    return _ok(data, f"Grafana: {len(result)} alert(s), none firing")


def check_compat(**kwargs) -> dict:
    """Probe Grafana version."""
    host = os.environ.get("GRAFANA_HOST", "")
    if not host:
        return _ok({"compatible": None, "detected_version": None, "reason": "Not configured"})
    headers = _headers()
    if not headers:
        return _ok({"compatible": None, "detected_version": None, "reason": "No API key"})
    try:
        r = httpx.get(f"http://{host}:3000/api/health", headers=headers, timeout=10)
        version = r.json().get("version", "")
        return _ok({"compatible": True, "detected_version": version, "reason": f"Grafana {version}"})
    except Exception as e:
        return _ok({"compatible": None, "detected_version": None, "reason": str(e)})
