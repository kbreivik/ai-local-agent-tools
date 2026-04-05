"""Synology DSM — system info, storage volumes, and shared folders."""
import os
from datetime import datetime, timezone

import httpx


PLUGIN_META = {
    "name": "synology_dsm_status",
    "description": "Query Synology DSM system health, storage volumes/pools, and shared folders.",
    "platform": "synology",
    "category": "storage",
    "agent_types": ["observe", "investigate"],
    "requires_plan": False,
    "params": {
        "host": {"type": "string", "required": False, "description": "Synology host (default: env SYNOLOGY_HOST)"},
        "action": {"type": "string", "required": False, "description": "'system' (default), 'storage', or 'shares'"},
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


def _login(client: httpx.Client, host: str) -> str:
    """Authenticate to Synology DSM via SYNO.API.Auth. Returns session ID (sid)."""
    user = os.environ.get("SYNOLOGY_USER", "")
    password = os.environ.get("SYNOLOGY_PASSWORD", "")
    if not user or not password:
        return ""
    r = client.get(f"https://{host}:5001/webapi/entry.cgi", params={
        "api": "SYNO.API.Auth",
        "version": "6",
        "method": "login",
        "account": user,
        "passwd": password,
        "format": "sid",
    })
    if r.status_code == 200:
        data = r.json()
        if data.get("success"):
            return data.get("data", {}).get("sid", "")
    return ""


def _query(client: httpx.Client, host: str, sid: str, api: str, method: str, version: int = 1, **extra) -> dict:
    """Call a Synology API endpoint."""
    params = {"api": api, "version": str(version), "method": method, "_sid": sid, **extra}
    r = client.get(f"https://{host}:5001/webapi/entry.cgi", params=params)
    r.raise_for_status()
    data = r.json()
    if not data.get("success"):
        code = data.get("error", {}).get("code", "unknown")
        raise RuntimeError(f"Synology API error: code {code}")
    return data.get("data", {})


def validate(**kwargs) -> dict:
    host = kwargs.get("host") or os.environ.get("SYNOLOGY_HOST", "")
    if not host:
        return _err("SYNOLOGY_HOST not configured")
    client = httpx.Client(verify=False, timeout=10)
    try:
        sid = _login(client, host)
        client.close()
        if sid:
            return _ok({"reachable": True}, "Synology DSM reachable")
        return _err("Synology login failed — check SYNOLOGY_USER and SYNOLOGY_PASSWORD")
    except Exception as e:
        client.close()
        return _err(f"Synology connection failed: {e}")


def execute(**kwargs) -> dict:
    host = kwargs.get("host") or os.environ.get("SYNOLOGY_HOST", "")
    action = kwargs.get("action", "system")
    if not host:
        return _err("SYNOLOGY_HOST not configured")

    client = httpx.Client(verify=False, timeout=15)
    try:
        sid = _login(client, host)
        if not sid:
            return _err("Synology login failed — check SYNOLOGY_USER and SYNOLOGY_PASSWORD")

        if action == "storage":
            return _get_storage(client, host, sid)
        elif action == "shares":
            return _get_shares(client, host, sid)
        return _get_system(client, host, sid)
    except httpx.HTTPStatusError as e:
        return _err(f"Synology API error: HTTP {e.response.status_code}")
    except Exception as e:
        return _err(f"Synology connection failed: {e}")
    finally:
        client.close()


def _get_system(client: httpx.Client, host: str, sid: str) -> dict:
    data = _query(client, host, sid, "SYNO.DSM.Info", "getinfo", version=2)
    util = {}
    try:
        util = _query(client, host, sid, "SYNO.Core.System.Utilization", "get", version=1)
    except Exception:
        pass

    result = {
        "model": data.get("model", ""),
        "firmware": data.get("version_string", data.get("version", "")),
        "uptime": data.get("uptime_seconds", 0),
        "temperature": data.get("temperature", 0),
        "cpu_load": util.get("cpu", {}).get("system_load", 0) if util else 0,
        "ram_used_pct": util.get("memory", {}).get("real_usage", 0) if util else 0,
    }
    return _ok(result, f"Synology {result['model']} — firmware {result['firmware']}")


def _get_storage(client: httpx.Client, host: str, sid: str) -> dict:
    data = _query(client, host, sid, "SYNO.Storage.CGI.Storage", "load_info", version=1)

    volumes = []
    for v in data.get("volumes", []):
        total = int(v.get("size", {}).get("total", 0))
        used = int(v.get("size", {}).get("used", 0))
        pct = round(used / total * 100, 1) if total > 0 else 0
        volumes.append({
            "id": v.get("id", ""),
            "status": v.get("status", ""),
            "total_gb": round(total / (1024**3), 1),
            "used_gb": round(used / (1024**3), 1),
            "usage_pct": pct,
            "fs_type": v.get("fs_type", ""),
        })

    disks = []
    for d in data.get("disks", []):
        disks.append({
            "name": d.get("name", ""),
            "model": d.get("model", ""),
            "status": d.get("status", ""),
            "temp": d.get("temp", 0),
            "size_gb": round(int(d.get("size_total", 0)) / (1024**3), 1),
        })

    degraded = [v["id"] for v in volumes if v["status"] != "normal"]
    bad_disks = [d["name"] for d in disks if d["status"] != "normal"]
    result = {"volumes": volumes, "disks": disks}

    if degraded or bad_disks:
        msg = []
        if degraded:
            msg.append(f"volumes: {', '.join(degraded)}")
        if bad_disks:
            msg.append(f"disks: {', '.join(bad_disks)}")
        return _degraded(result, f"Synology storage degraded — {'; '.join(msg)}")
    return _ok(result, f"Synology: {len(volumes)} volume(s), {len(disks)} disk(s), all healthy")


def _get_shares(client: httpx.Client, host: str, sid: str) -> dict:
    data = _query(client, host, sid, "SYNO.FileStation.List", "list_share", version=2)
    shares = []
    for s in data.get("shares", []):
        shares.append({
            "name": s.get("name", ""),
            "path": s.get("path", ""),
            "is_dir": s.get("isdir", True),
        })
    return _ok({"shares": shares, "count": len(shares)},
               f"Synology: {len(shares)} shared folder(s)")
