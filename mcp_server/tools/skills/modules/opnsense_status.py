"""OPNsense — system info, interfaces, and firewall rules."""
import os
from datetime import datetime, timezone

import httpx


SKILL_META = {
    "name": "opnsense_status",
    "description": "Query OPNsense system status, network interfaces, and firewall rule counts.",
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
            "action": {"type": "string", "description": "'system' (default), 'interfaces', or 'firewall'"},
        },
        "required": [],
    },
    "auth_type": "api_key",
    "config_keys": ["OPNSENSE_HOST", "OPNSENSE_API_KEY", "OPNSENSE_API_SECRET"],
    "compat": {
        "service": "opnsense",
        "api_version_built_for": "24.1",
        "min_version": "21.1",
        "max_version": "",
        "version_endpoint": "/api/core/firmware/status",
        "version_field": "product_version",
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


def _auth() -> tuple:
    key = os.environ.get("OPNSENSE_API_KEY", "")
    secret = os.environ.get("OPNSENSE_API_SECRET", "")
    return (key, secret) if key and secret else None


def execute(**kwargs) -> dict:
    host = os.environ.get("OPNSENSE_HOST", "")
    action = kwargs.get("action", "system")
    if not host:
        return _err("OPNSENSE_HOST not configured")
    auth = _auth()
    if not auth:
        return _err("OPNSENSE_API_KEY and OPNSENSE_API_SECRET required")

    base = f"https://{host}/api"
    try:
        if action == "interfaces":
            return _get_interfaces(base, auth)
        elif action == "firewall":
            return _get_firewall(base, auth)
        return _get_system(base, auth)
    except httpx.HTTPStatusError as e:
        return _err(f"OPNsense API error: HTTP {e.response.status_code}")
    except Exception as e:
        return _err(f"OPNsense connection failed: {e}")


def _get_system(base: str, auth) -> dict:
    # Firmware info (includes version)
    fr = httpx.get(f"{base}/core/firmware/status", auth=auth, verify=False, timeout=10)
    fr.raise_for_status()
    fw = fr.json()

    # System activity
    activity = {}
    try:
        ar = httpx.get(f"{base}/diagnostics/activity/getActivity", auth=auth, verify=False, timeout=10)
        if ar.status_code == 200:
            activity = ar.json()
    except Exception:
        pass

    updates_available = fw.get("status_msg", "").lower() != "up-to-date" if fw.get("status_msg") else False
    result = {
        "version": fw.get("product_version", ""),
        "product": fw.get("product_name", "OPNsense"),
        "updates_available": updates_available,
        "status_msg": fw.get("status_msg", ""),
    }
    if updates_available:
        return _degraded(result, f"OPNsense v{result['version']}: firmware update available")
    return _ok(result, f"OPNsense v{result['version']}: up to date")


def _get_interfaces(base: str, auth) -> dict:
    r = httpx.get(f"{base}/diagnostics/interface/getInterfaceStatistics",
                  auth=auth, verify=False, timeout=10)
    r.raise_for_status()
    data = r.json()
    interfaces = []
    for name, stats in data.get("statistics", data).items():
        if isinstance(stats, dict):
            interfaces.append({
                "name": name,
                "bytes_in": stats.get("bytes received", stats.get("received-bytes", 0)),
                "bytes_out": stats.get("bytes transmitted", stats.get("sent-bytes", 0)),
                "errors_in": stats.get("input errors", stats.get("received-errors", 0)),
                "errors_out": stats.get("output errors", stats.get("sent-errors", 0)),
            })

    errors = [i for i in interfaces if i.get("errors_in", 0) > 0 or i.get("errors_out", 0) > 0]
    result = {"interfaces": interfaces, "count": len(interfaces)}
    if errors:
        return _degraded(result, f"OPNsense: {len(errors)} interface(s) with errors")
    return _ok(result, f"OPNsense: {len(interfaces)} interface(s)")


def _get_firewall(base: str, auth) -> dict:
    # Get filter rules
    r = httpx.get(f"{base}/firewall/filter/searchRule", auth=auth, verify=False, timeout=10,
                  params={"current": 1, "rowCount": 5})
    r.raise_for_status()
    data = r.json()
    total_rules = data.get("total", 0)

    # Get recent log entries
    log_entries = []
    try:
        lr = httpx.get(f"{base}/diagnostics/firewall/log", auth=auth, verify=False, timeout=10,
                       params={"limit": 10})
        if lr.status_code == 200:
            for entry in lr.json()[:10]:
                log_entries.append({
                    "action": entry.get("action", ""),
                    "interface": entry.get("interface", ""),
                    "src": entry.get("src", ""),
                    "dst": entry.get("dst", ""),
                    "proto": entry.get("protoname", ""),
                })
    except Exception:
        pass

    return _ok({
        "total_rules": total_rules,
        "recent_blocks": log_entries,
        "recent_block_count": len(log_entries),
    }, f"OPNsense: {total_rules} firewall rule(s)")


def check_compat(**kwargs) -> dict:
    host = os.environ.get("OPNSENSE_HOST", "")
    if not host:
        return _ok({"compatible": None, "detected_version": None, "reason": "Not configured"})
    auth = _auth()
    if not auth:
        return _ok({"compatible": None, "detected_version": None, "reason": "No API key"})
    try:
        r = httpx.get(f"https://{host}/api/core/firmware/status", auth=auth, verify=False, timeout=10)
        version = r.json().get("product_version", "")
        return _ok({"compatible": True, "detected_version": version, "reason": f"OPNsense {version}"})
    except Exception as e:
        return _ok({"compatible": None, "detected_version": None, "reason": str(e)})
