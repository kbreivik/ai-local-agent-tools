"""AdGuard Home — protection status, query stats, and filter lists."""
import os
from datetime import datetime, timezone

import httpx


SKILL_META = {
    "name": "adguard_status",
    "description": "Check AdGuard Home protection status, DNS query statistics, and active filter lists.",
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
            "action": {"type": "string", "description": "'status' (default), 'stats', or 'filters'"},
        },
        "required": [],
    },
    "auth_type": "basic",
    "config_keys": ["ADGUARD_HOST", "ADGUARD_USER", "ADGUARD_PASSWORD"],
    "compat": {
        "service": "adguard",
        "api_version_built_for": "0.107",
        "min_version": "0.100",
        "max_version": "",
        "version_endpoint": "/control/status",
        "version_field": "version",
    },
}


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()

def _ok(data, message="OK") -> dict:
    return {"status": "ok", "data": data, "timestamp": _ts(), "message": message}

def _err(message, data=None) -> dict:
    return {"status": "error", "data": data, "timestamp": _ts(), "message": message}


def _auth() -> tuple:
    user = os.environ.get("ADGUARD_USER", "")
    password = os.environ.get("ADGUARD_PASSWORD", "")
    return (user, password) if user else None


def execute(**kwargs) -> dict:
    host = os.environ.get("ADGUARD_HOST", "")
    action = kwargs.get("action", "status")
    if not host:
        return _err("ADGUARD_HOST not configured")
    auth = _auth()
    if not auth:
        return _err("ADGUARD_USER and ADGUARD_PASSWORD required")

    base = f"http://{host}:3000/control"
    try:
        if action == "stats":
            return _get_stats(base, auth)
        elif action == "filters":
            return _get_filters(base, auth)
        return _get_status(base, auth)
    except httpx.HTTPStatusError as e:
        return _err(f"AdGuard API error: HTTP {e.response.status_code}")
    except Exception as e:
        return _err(f"AdGuard connection failed: {e}")


def _get_status(base: str, auth) -> dict:
    r = httpx.get(f"{base}/status", auth=auth, timeout=10)
    r.raise_for_status()
    data = r.json()
    return _ok({
        "running": data.get("running", False),
        "protection_enabled": data.get("protection_enabled", False),
        "version": data.get("version", ""),
        "dns_addresses": data.get("dns_addresses", []),
        "dns_port": data.get("dns_port", 53),
    }, f"AdGuard v{data.get('version', '?')}: protection {'on' if data.get('protection_enabled') else 'off'}")


def _get_stats(base: str, auth) -> dict:
    r = httpx.get(f"{base}/stats", auth=auth, timeout=10)
    r.raise_for_status()
    data = r.json()
    return _ok({
        "num_dns_queries": data.get("num_dns_queries", 0),
        "num_blocked_filtering": data.get("num_blocked_filtering", 0),
        "num_replaced_safebrowsing": data.get("num_replaced_safebrowsing", 0),
        "num_replaced_parental": data.get("num_replaced_parental", 0),
        "avg_processing_time": data.get("avg_processing_time", 0),
        "top_queried_domains": list(data.get("top_queried_domains", [{}])[0].keys())[:5] if data.get("top_queried_domains") else [],
        "top_blocked_domains": list(data.get("top_blocked_domains", [{}])[0].keys())[:5] if data.get("top_blocked_domains") else [],
        "top_clients": list(data.get("top_clients", [{}])[0].keys())[:5] if data.get("top_clients") else [],
    }, f"AdGuard: {data.get('num_dns_queries', 0)} queries, {data.get('num_blocked_filtering', 0)} blocked")


def _get_filters(base: str, auth) -> dict:
    r = httpx.get(f"{base}/filtering/status", auth=auth, timeout=10)
    r.raise_for_status()
    data = r.json()
    filters = []
    for f in data.get("filters", []):
        filters.append({
            "name": f.get("name", ""),
            "url": f.get("url", ""),
            "enabled": f.get("enabled", False),
            "rules_count": f.get("rules_count", 0),
            "last_updated": f.get("last_updated", ""),
        })
    enabled = [f for f in filters if f["enabled"]]
    total_rules = sum(f["rules_count"] for f in enabled)
    return _ok({
        "filters": filters,
        "count": len(filters),
        "enabled": len(enabled),
        "total_rules": total_rules,
    }, f"AdGuard: {len(enabled)} filter(s), {total_rules} rule(s)")


def check_compat(**kwargs) -> dict:
    host = os.environ.get("ADGUARD_HOST", "")
    if not host:
        return _ok({"compatible": None, "detected_version": None, "reason": "Not configured"})
    auth = _auth()
    if not auth:
        return _ok({"compatible": None, "detected_version": None, "reason": "No credentials"})
    try:
        r = httpx.get(f"http://{host}:3000/control/status", auth=auth, timeout=10)
        version = r.json().get("version", "")
        return _ok({"compatible": True, "detected_version": version, "reason": f"AdGuard {version}"})
    except Exception as e:
        return _ok({"compatible": None, "detected_version": None, "reason": str(e)})
