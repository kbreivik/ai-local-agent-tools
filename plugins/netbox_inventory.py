"""NetBox DCIM/IPAM — devices, IP prefixes, VLANs, and search."""
import os
from datetime import datetime, timezone

import httpx


PLUGIN_META = {
    "name": "netbox_inventory",
    "description": "Query NetBox DCIM inventory: devices, IP prefixes, VLANs, and keyword search.",
    "platform": "netbox",
    "category": "networking",
    "agent_types": ["observe", "investigate"],
    "requires_plan": False,
    "params": {
        "host": {"type": "string", "required": False, "description": "NetBox host (default: env NETBOX_HOST)"},
        "action": {"type": "string", "required": False, "description": "'devices' (default), 'search', 'prefixes', or 'vlans'"},
        "query": {"type": "string", "required": False, "description": "Search keyword (for action=search)"},
    },
}


def _ts():
    return datetime.now(timezone.utc).isoformat()

def _ok(data, message="OK"):
    return {"status": "ok", "data": data, "timestamp": _ts(), "message": message}

def _err(message, data=None):
    return {"status": "error", "data": data, "timestamp": _ts(), "message": message}


def _headers() -> dict:
    token = os.environ.get("NETBOX_API_TOKEN", "")
    if not token:
        return {}
    return {"Authorization": f"Token {token}"}


def validate(**kwargs) -> dict:
    host = kwargs.get("host") or os.environ.get("NETBOX_HOST", "")
    if not host:
        return _err("NETBOX_HOST not configured")
    headers = _headers()
    if not headers:
        return _err("NETBOX_API_TOKEN not configured")
    try:
        r = httpx.get(f"https://{host}/api/status/", headers=headers, verify=False, timeout=10)
        r.raise_for_status()
        return _ok(r.json(), "NetBox reachable")
    except Exception as e:
        return _err(f"NetBox connection failed: {e}")


def execute(**kwargs) -> dict:
    host = kwargs.get("host") or os.environ.get("NETBOX_HOST", "")
    action = kwargs.get("action", "devices")
    if not host:
        return _err("NETBOX_HOST not configured")
    headers = _headers()
    if not headers:
        return _err("NETBOX_API_TOKEN not configured")

    base = f"https://{host}/api"
    try:
        if action == "search":
            return _search(base, headers, kwargs.get("query", ""))
        elif action == "prefixes":
            return _get_prefixes(base, headers)
        elif action == "vlans":
            return _get_vlans(base, headers)
        return _get_devices(base, headers)
    except httpx.HTTPStatusError as e:
        return _err(f"NetBox API error: HTTP {e.response.status_code}")
    except Exception as e:
        return _err(f"NetBox connection failed: {e}")


def _get_devices(base: str, headers: dict) -> dict:
    r = httpx.get(f"{base}/dcim/devices/", headers=headers, verify=False, timeout=10,
                  params={"limit": 50})
    r.raise_for_status()
    data = r.json()
    devices = []
    for d in data.get("results", []):
        devices.append({
            "name": d.get("name", ""),
            "role": (d.get("role") or d.get("device_role") or {}).get("name", ""),
            "site": (d.get("site") or {}).get("name", ""),
            "status": (d.get("status") or {}).get("value", ""),
            "primary_ip": (d.get("primary_ip") or {}).get("address", ""),
            "model": (d.get("device_type") or {}).get("model", ""),
            "manufacturer": (d.get("device_type") or {}).get("manufacturer", {}).get("name", ""),
        })
    return _ok({"devices": devices, "count": data.get("count", len(devices))},
               f"NetBox: {data.get('count', len(devices))} device(s)")


def _search(base: str, headers: dict, query: str) -> dict:
    if not query:
        return _err("query parameter required for action=search")
    results = {}
    # Search devices
    r = httpx.get(f"{base}/dcim/devices/", headers=headers, verify=False, timeout=10,
                  params={"q": query, "limit": 10})
    if r.status_code == 200:
        results["devices"] = [
            {"name": d.get("name", ""), "primary_ip": (d.get("primary_ip") or {}).get("address", "")}
            for d in r.json().get("results", [])
        ]
    # Search IPs
    r = httpx.get(f"{base}/ipam/ip-addresses/", headers=headers, verify=False, timeout=10,
                  params={"q": query, "limit": 10})
    if r.status_code == 200:
        results["ip_addresses"] = [
            {"address": ip.get("address", ""), "dns_name": ip.get("dns_name", "")}
            for ip in r.json().get("results", [])
        ]
    total = sum(len(v) for v in results.values())
    return _ok(results, f"NetBox search '{query}': {total} result(s)")


def _get_prefixes(base: str, headers: dict) -> dict:
    r = httpx.get(f"{base}/ipam/prefixes/", headers=headers, verify=False, timeout=10,
                  params={"limit": 50})
    r.raise_for_status()
    data = r.json()
    prefixes = []
    for p in data.get("results", []):
        prefixes.append({
            "prefix": p.get("prefix", ""),
            "status": (p.get("status") or {}).get("value", ""),
            "vlan": (p.get("vlan") or {}).get("vid", None),
            "site": (p.get("site") or {}).get("name", ""),
            "utilization": p.get("_depth", 0),
        })
    return _ok({"prefixes": prefixes, "count": data.get("count", len(prefixes))},
               f"NetBox: {data.get('count', len(prefixes))} prefix(es)")


def _get_vlans(base: str, headers: dict) -> dict:
    r = httpx.get(f"{base}/ipam/vlans/", headers=headers, verify=False, timeout=10,
                  params={"limit": 50})
    r.raise_for_status()
    data = r.json()
    vlans = []
    for v in data.get("results", []):
        vlans.append({
            "vid": v.get("vid", 0),
            "name": v.get("name", ""),
            "site": (v.get("site") or {}).get("name", ""),
            "tenant": (v.get("tenant") or {}).get("name", ""),
            "status": (v.get("status") or {}).get("value", ""),
        })
    return _ok({"vlans": vlans, "count": data.get("count", len(vlans))},
               f"NetBox: {data.get('count', len(vlans))} VLAN(s)")
