"""Proxmox Backup Server — datastore status, usage, and recent backup tasks."""
import os
from datetime import datetime, timezone

import httpx


PLUGIN_META = {
    "name": "pbs_backup_status",
    "description": "Check PBS datastore usage, last GC/verify, and recent backup task status.",
    "platform": "pbs",
    "category": "storage",
    "agent_types": ["observe", "investigate"],
    "requires_plan": False,
    "params": {
        "host": {"type": "string", "required": False, "description": "PBS host (default: env PBS_HOST)"},
        "detail": {"type": "string", "required": False, "description": "'summary' (default) or 'tasks'"},
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


def _auth_headers() -> dict:
    token_id = os.environ.get("PBS_TOKEN_ID", "")
    token_secret = os.environ.get("PBS_TOKEN_SECRET", "")
    if not token_id or not token_secret:
        return {}
    return {"Authorization": f"PBSAPIToken={token_id}:{token_secret}"}


def validate(**kwargs) -> dict:
    """Check connectivity to PBS API."""
    host = kwargs.get("host") or os.environ.get("PBS_HOST", "")
    if not host:
        return _err("PBS_HOST not configured")
    headers = _auth_headers()
    if not headers:
        return _err("PBS_TOKEN_ID and PBS_TOKEN_SECRET required")
    try:
        r = httpx.get(f"https://{host}:8007/api2/json/version", headers=headers,
                      verify=False, timeout=10)
        r.raise_for_status()
        return _ok(r.json().get("data", {}), "PBS reachable")
    except Exception as e:
        return _err(f"PBS connection failed: {e}")


def execute(**kwargs) -> dict:
    """Query PBS datastores or recent tasks."""
    host = kwargs.get("host") or os.environ.get("PBS_HOST", "")
    detail = kwargs.get("detail", "summary")
    if not host:
        return _err("PBS_HOST not configured")
    headers = _auth_headers()
    if not headers:
        return _err("PBS_TOKEN_ID and PBS_TOKEN_SECRET required")

    base = f"https://{host}:8007/api2/json"

    try:
        if detail == "tasks":
            return _get_tasks(base, headers)
        return _get_summary(base, headers)
    except httpx.HTTPStatusError as e:
        return _err(f"PBS API error: HTTP {e.response.status_code}")
    except Exception as e:
        return _err(f"PBS connection failed: {e}")


def _get_summary(base: str, headers: dict) -> dict:
    r = httpx.get(f"{base}/admin/datastore", headers=headers, verify=False, timeout=10)
    r.raise_for_status()
    stores = r.json().get("data", [])

    result = []
    degraded = []
    for ds in stores:
        name = ds.get("store", ds.get("name", "unknown"))
        # Get usage for this datastore
        try:
            ur = httpx.get(f"{base}/admin/datastore/{name}/status", headers=headers,
                          verify=False, timeout=10)
            usage = ur.json().get("data", {}) if ur.status_code == 200 else {}
        except Exception:
            usage = {}

        total = usage.get("total", 0)
        used = usage.get("used", 0)
        pct = round(used / total * 100, 1) if total > 0 else 0

        info = {
            "name": name,
            "usage_pct": pct,
            "total_gb": round(total / (1024**3), 1) if total else 0,
            "used_gb": round(used / (1024**3), 1) if used else 0,
            "gc_status": usage.get("gc-status", ""),
        }
        result.append(info)
        if pct > 90:
            degraded.append(name)

    data = {"datastores": result, "count": len(result)}
    if degraded:
        return _degraded(data, f"PBS: {len(degraded)} datastore(s) >90% full: {', '.join(degraded)}")
    return _ok(data, f"PBS: {len(result)} datastore(s), all healthy")


def _get_tasks(base: str, headers: dict) -> dict:
    r = httpx.get(f"{base}/nodes/localhost/tasks", headers=headers,
                  verify=False, timeout=10, params={"limit": 20})
    r.raise_for_status()
    tasks = r.json().get("data", [])

    result = []
    for t in tasks[:20]:
        result.append({
            "upid": t.get("upid", ""),
            "type": t.get("worker_type", ""),
            "status": t.get("status", ""),
            "starttime": t.get("starttime", 0),
            "endtime": t.get("endtime", 0),
            "user": t.get("user", ""),
        })

    failed = [t for t in result if t["status"] and t["status"] != "OK"]
    data = {"tasks": result, "count": len(result), "failed": len(failed)}
    if failed:
        return _degraded(data, f"PBS: {len(failed)} failed task(s) in recent history")
    return _ok(data, f"PBS: {len(result)} recent task(s), all OK")
