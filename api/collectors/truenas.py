"""
TrueNAS pool status collector.
Polls ZFS pool health and capacity from TrueNAS API v2.
Reads connection from DB (platform='truenas'); falls back to env vars
TRUENAS_HOST / TRUENAS_API_KEY.
"""
import asyncio
import logging
import os
import time

import httpx

from api.collectors.base import BaseCollector

log = logging.getLogger(__name__)


class TrueNASCollector(BaseCollector):
    component = "truenas"
    platforms = ["truenas"]
    interval = int(os.environ.get("TRUENAS_POLL_INTERVAL", "60"))

    def __init__(self):
        super().__init__()

    def mock(self) -> dict:
        return {
            "health": "healthy",
            "connection_label": "mock-truenas",
            "connection_id": "mock-tn-id",
            "pools": [
                {
                    "name": "tank",
                    "status": "ONLINE",
                    "healthy": True,
                    "size_gb": 10000.0,
                    "allocated_gb": 4200.0,
                    "free_gb": 5800.0,
                    "usage_pct": 42.0,
                    "scan_state": "FINISHED",
                    "scan_errors": 0,
                    "vdev_count": 2,
                },
            ],
        }

    def to_entities(self, state: dict) -> list:
        from api.collectors.base import Entity

        label = state.get("connection_label", "truenas")
        health_map = {
            "healthy": "healthy", "degraded": "degraded",
            "critical": "error", "error": "error", "unconfigured": "unknown",
        }
        base_status = health_map.get(state.get("health", "unknown"), "unknown")
        last_error = state.get("error") if base_status == "error" else None

        pools = state.get("pools", [])
        entities = []

        for pool in pools:
            pool_name = pool.get("name", "unknown")
            pool_status = pool.get("status", "UNKNOWN")
            healthy = pool.get("healthy", False)
            pct = pool.get("usage_pct", 0)

            if not healthy or pool_status not in ("ONLINE",):
                status = "error"
            elif pct > 90:
                status = "degraded"
            else:
                status = "healthy"

            entities.append(Entity(
                id=f"truenas:{label}:pool:{pool_name}",
                label=f"{label}/{pool_name}",
                component=self.component,
                platform="truenas",
                section="STORAGE",
                status=status,
                last_error=None if status == "healthy" else f"Pool {pool_name}: {pool_status}",
                metadata={
                    "status": pool_status,
                    "healthy": healthy,
                    "usage_pct": pct,
                    "size_gb": pool.get("size_gb"),
                    "allocated_gb": pool.get("allocated_gb"),
                    "free_gb": pool.get("free_gb"),
                    "scan_state": pool.get("scan_state", ""),
                    "scan_errors": pool.get("scan_errors", 0),
                    "vdev_count": pool.get("vdev_count", 0),
                    "connection": label,
                },
            ))

        if not entities:
            entities.append(Entity(
                id=f"truenas:{label}",
                label=label,
                component=self.component,
                platform="truenas",
                section="STORAGE",
                status=base_status,
                last_error=last_error,
                metadata={"connection": label},
            ))

        return entities

    async def poll(self) -> dict:
        return await asyncio.to_thread(self._collect_sync)

    def _collect_sync(self) -> dict:
        conn = None
        try:
            from api.connections import get_connection_for_platform
            conn = get_connection_for_platform("truenas")
        except Exception:
            pass

        if conn:
            host = conn.get("host", "")
            creds = conn.get("credentials", {}) if isinstance(conn.get("credentials"), dict) else {}
            api_key = creds.get("api_key", "")
            port = conn.get("port") or 443
            conn_label = conn.get("label", host)
            conn_id = conn.get("id", "")
        else:
            host = os.environ.get("TRUENAS_HOST", "")
            api_key = os.environ.get("TRUENAS_API_KEY", "")
            port = int(os.environ.get("TRUENAS_PORT", "443"))
            conn_label = host
            conn_id = ""

        if not host:
            return {"health": "unconfigured", "pools": [],
                    "message": "No TrueNAS connection configured"}

        if not api_key:
            return {"health": "error", "pools": [],
                    "error": "TrueNAS API key not set",
                    "connection_label": conn_label, "connection_id": conn_id}

        base = f"https://{host}/api/v2.0" if port == 443 else f"https://{host}:{port}/api/v2.0"
        headers = {"Authorization": f"Bearer {api_key}"}

        try:
            t0 = time.monotonic()
            r = httpx.get(f"{base}/system/info", headers=headers, verify=False, timeout=8)
            latency_ms = round((time.monotonic() - t0) * 1000)

            if r.status_code == 401:
                return {"health": "error", "pools": [],
                        "error": "TrueNAS auth failed — check API key",
                        "connection_label": conn_label, "connection_id": conn_id}
            r.raise_for_status()

            pools = _collect_pools(base, headers)
            # Stamp entity_id using this connection's label
            for pool in pools:
                pool["entity_id"] = f"truenas:{conn_label}:pool:{pool['name']}"

            degraded = [p for p in pools if not p["healthy"] or p["status"] != "ONLINE"]
            high_usage = [p for p in pools if p["usage_pct"] > 90]

            if degraded:
                health = "critical"
            elif high_usage:
                health = "degraded"
            else:
                health = "healthy"

            return {
                "health": health,
                "pools": pools,
                "pool_count": len(pools),
                "latency_ms": latency_ms,
                "connection_label": conn_label,
                "connection_id": conn_id,
            }

        except httpx.HTTPStatusError as e:
            log.warning("TrueNASCollector HTTP error %s: %s", conn_label, e)
            return {"health": "error", "pools": [],
                    "error": f"HTTP {e.response.status_code}",
                    "connection_label": conn_label, "connection_id": conn_id}
        except Exception as e:
            log.error("TrueNASCollector error %s: %s", conn_label, e)
            return {"health": "error", "pools": [],
                    "error": f"Connection failed: {str(e)[:80]}",
                    "connection_label": conn_label, "connection_id": conn_id}


def _collect_pools(base: str, headers: dict) -> list:
    """Fetch all ZFS pools with capacity and scan data."""
    try:
        r = httpx.get(f"{base}/pool", headers=headers, verify=False, timeout=15)
        r.raise_for_status()
        pools = r.json()
    except Exception as e:
        log.debug("TrueNAS pool list failed: %s", e)
        return []

    result = []
    for pool in pools:
        size = pool.get("size", 0) or 0
        allocated = pool.get("allocated", 0) or 0
        free = pool.get("free", 0) or 0
        pct = round(allocated / size * 100, 1) if size > 0 else 0

        scan = pool.get("scan") or {}
        topology = pool.get("topology") or {}

        result.append({
            "name": pool.get("name", "unknown"),
            "status": pool.get("status", "UNKNOWN"),
            "healthy": pool.get("healthy", False),
            "size_gb": round(size / (1024 ** 3), 1) if size else 0,
            "allocated_gb": round(allocated / (1024 ** 3), 1) if allocated else 0,
            "free_gb": round(free / (1024 ** 3), 1) if free else 0,
            "usage_pct": pct,
            "scan_state": scan.get("state", "NONE"),
            "scan_errors": scan.get("errors", 0),
            "vdev_count": len(topology.get("data", [])),
        })
    return result
