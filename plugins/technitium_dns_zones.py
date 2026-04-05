"""Technitium DNS Server — list zones and record counts."""
import os
from datetime import datetime, timezone

import httpx


PLUGIN_META = {
    "name": "technitium_dns_zones",
    "description": "List Technitium DNS Server zones with record counts and DNSSEC status.",
    "platform": "technitium",
    "category": "networking",
    "agent_types": ["investigate", "execute"],
    "requires_plan": False,
    "params": {
        "host": {"type": "string", "required": False, "description": "Technitium host (default: env TECHNITIUM_HOST)"},
        "zone": {"type": "string", "required": False, "description": "Specific zone to query (default: list all)"},
    },
}


def _ts():
    return datetime.now(timezone.utc).isoformat()

def _ok(data, message="OK"):
    return {"status": "ok", "data": data, "timestamp": _ts(), "message": message}

def _err(message, data=None):
    return {"status": "error", "data": data, "timestamp": _ts(), "message": message}


def execute(**kwargs) -> dict:
    """List DNS zones or query a specific zone."""
    host = kwargs.get("host") or os.environ.get("TECHNITIUM_HOST", "")
    api_key = os.environ.get("TECHNITIUM_API_KEY", "")
    if not host:
        return _err("TECHNITIUM_HOST not configured")
    if not api_key:
        return _err("TECHNITIUM_API_KEY not configured")

    base = f"http://{host}/api"
    zone_filter = kwargs.get("zone", "")

    try:
        r = httpx.get(
            f"{base}/zones/list",
            params={"token": api_key},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()

        if data.get("status") != "ok":
            return _err(f"Technitium API error: {data.get('errorMessage', 'unknown')}")

        zones = data.get("response", {}).get("zones", [])

        zone_list = []
        for z in zones:
            name = z.get("name", "")
            if zone_filter and name != zone_filter:
                continue
            zone_list.append({
                "name": name,
                "type": z.get("type", ""),
                "disabled": z.get("disabled", False),
                "dnssec": z.get("dnssecStatus", ""),
                "internal": z.get("internal", False),
            })

        result = {"zones": zone_list, "zone_count": len(zone_list)}

        if zone_filter:
            return _ok(result, f"Technitium: zone '{zone_filter}' — {len(zone_list)} match(es)")
        return _ok(result, f"Technitium: {len(zone_list)} zone(s)")

    except httpx.HTTPStatusError as e:
        return _err(f"Technitium API error: HTTP {e.response.status_code}")
    except Exception as e:
        return _err(f"Technitium connection failed: {e}")
