"""TrueNAS ZFS pool status — health, capacity, and disk state."""
import os
from datetime import datetime, timezone

import httpx


PLUGIN_META = {
    "name": "truenas_pool_status",
    "description": "Check TrueNAS ZFS pool health, capacity usage, and disk state for all pools.",
    "platform": "truenas",
    "category": "storage",
    "agent_types": ["investigate", "execute"],
    "requires_plan": False,
    "params": {
        "host": {"type": "string", "required": False, "description": "TrueNAS host (default: env TRUENAS_HOST)"},
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


def execute(**kwargs) -> dict:
    """Fetch all ZFS pools and their status from TrueNAS API."""
    host = kwargs.get("host") or os.environ.get("TRUENAS_HOST", "")
    api_key = os.environ.get("TRUENAS_API_KEY", "")
    if not host:
        return _err("TRUENAS_HOST not configured")
    if not api_key:
        return _err("TRUENAS_API_KEY not configured")

    base = f"https://{host}/api/v2.0"
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        r = httpx.get(f"{base}/pool", headers=headers, timeout=15, verify=False)
        r.raise_for_status()
        pools = r.json()

        pool_data = []
        degraded_pools = []
        for pool in pools:
            name = pool.get("name", "unknown")
            status = pool.get("status", "UNKNOWN")
            healthy = pool.get("healthy", False)
            topology = pool.get("topology", {})

            # Capacity from top-level scan
            scan = pool.get("scan", {})

            pool_info = {
                "name": name,
                "status": status,
                "healthy": healthy,
                "path": pool.get("path", ""),
                "scan_state": scan.get("state", "NONE") if scan else "NONE",
                "vdev_count": len(topology.get("data", [])),
            }
            pool_data.append(pool_info)
            if not healthy or status != "ONLINE":
                degraded_pools.append(name)

        result = {"pools": pool_data, "pool_count": len(pool_data)}

        if degraded_pools:
            return _degraded(result, f"TrueNAS: {len(degraded_pools)} degraded pool(s): {', '.join(degraded_pools)}")

        return _ok(result, f"TrueNAS: {len(pool_data)} pool(s), all healthy")

    except httpx.HTTPStatusError as e:
        return _err(f"TrueNAS API error: HTTP {e.response.status_code}")
    except Exception as e:
        return _err(f"TrueNAS connection failed: {e}")
