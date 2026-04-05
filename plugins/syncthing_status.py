"""Syncthing — sync status, folders, devices, and errors."""
import os
from datetime import datetime, timezone

import httpx


PLUGIN_META = {
    "name": "syncthing_status",
    "description": "Query Syncthing system status, folder sync state, connected devices, and errors.",
    "platform": "syncthing",
    "category": "storage",
    "agent_types": ["observe", "investigate"],
    "requires_plan": False,
    "params": {
        "host": {"type": "string", "required": False, "description": "Syncthing host (default: env SYNCTHING_HOST)"},
        "action": {"type": "string", "required": False, "description": "'status' (default), 'folders', 'devices', or 'errors'"},
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


def _headers() -> dict:
    key = os.environ.get("SYNCTHING_API_KEY", "")
    return {"X-API-Key": key} if key else {}


def validate(**kwargs) -> dict:
    host = kwargs.get("host") or os.environ.get("SYNCTHING_HOST", "")
    if not host:
        return _err("SYNCTHING_HOST not configured")
    headers = _headers()
    if not headers.get("X-API-Key"):
        return _err("SYNCTHING_API_KEY not configured")
    try:
        r = httpx.get(f"http://{host}:8384/rest/system/version", headers=headers, timeout=10)
        r.raise_for_status()
        return _ok(r.json(), "Syncthing reachable")
    except Exception as e:
        return _err(f"Syncthing connection failed: {e}")


def execute(**kwargs) -> dict:
    host = kwargs.get("host") or os.environ.get("SYNCTHING_HOST", "")
    action = kwargs.get("action", "status")
    if not host:
        return _err("SYNCTHING_HOST not configured")
    headers = _headers()
    if not headers.get("X-API-Key"):
        return _err("SYNCTHING_API_KEY not configured")

    base = f"http://{host}:8384/rest"
    try:
        if action == "folders":
            return _get_folders(base, headers)
        elif action == "devices":
            return _get_devices(base, headers)
        elif action == "errors":
            return _get_errors(base, headers)
        return _get_status(base, headers)
    except httpx.HTTPStatusError as e:
        return _err(f"Syncthing API error: HTTP {e.response.status_code}")
    except Exception as e:
        return _err(f"Syncthing connection failed: {e}")


def _get_status(base: str, headers: dict) -> dict:
    sr = httpx.get(f"{base}/system/status", headers=headers, timeout=10).json()
    vr = httpx.get(f"{base}/system/version", headers=headers, timeout=10).json()
    conns = httpx.get(f"{base}/system/connections", headers=headers, timeout=10).json()
    connected = len([c for c in conns.get("connections", {}).values() if c.get("connected")])
    return _ok({
        "my_id": sr.get("myID", "")[:12],
        "version": vr.get("version", ""),
        "uptime": sr.get("uptime", 0),
        "connected_devices": connected,
        "total_devices": len(conns.get("connections", {})),
    }, f"Syncthing v{vr.get('version', '?')}: {connected} device(s) connected")


def _get_folders(base: str, headers: dict) -> dict:
    cfg = httpx.get(f"{base}/config/folders", headers=headers, timeout=10).json()
    folders = []
    out_of_sync = []
    for f in cfg:
        fid = f.get("id", "")
        try:
            st = httpx.get(f"{base}/db/status", headers=headers, timeout=10, params={"folder": fid}).json()
        except Exception:
            st = {}
        state = st.get("state", "unknown")
        info = {
            "id": fid,
            "label": f.get("label", fid),
            "state": state,
            "global_files": st.get("globalFiles", 0),
            "need_files": st.get("needFiles", 0),
            "errors": st.get("errors", 0),
        }
        folders.append(info)
        if state not in ("idle", "scanning"):
            out_of_sync.append(fid)

    data = {"folders": folders, "count": len(folders)}
    if out_of_sync:
        return _degraded(data, f"Syncthing: {len(out_of_sync)} folder(s) not idle: {', '.join(out_of_sync)}")
    return _ok(data, f"Syncthing: {len(folders)} folder(s), all synced")


def _get_devices(base: str, headers: dict) -> dict:
    cfg = httpx.get(f"{base}/config/devices", headers=headers, timeout=10).json()
    conns = httpx.get(f"{base}/system/connections", headers=headers, timeout=10).json()
    conn_map = conns.get("connections", {})
    devices = []
    for d in cfg:
        did = d.get("deviceID", "")
        conn = conn_map.get(did, {})
        devices.append({
            "name": d.get("name", did[:12]),
            "id_short": did[:12],
            "connected": conn.get("connected", False),
            "address": conn.get("address", ""),
            "type": conn.get("type", ""),
        })
    return _ok({"devices": devices, "count": len(devices)},
               f"Syncthing: {len(devices)} device(s)")


def _get_errors(base: str, headers: dict) -> dict:
    r = httpx.get(f"{base}/system/error", headers=headers, timeout=10)
    r.raise_for_status()
    errors = r.json().get("errors", [])
    result = [{"when": e.get("when", ""), "message": e.get("message", "")} for e in errors[:20]]
    data = {"errors": result, "count": len(errors)}
    if errors:
        return _degraded(data, f"Syncthing: {len(errors)} error(s)")
    return _ok(data, "Syncthing: no errors")
