"""
FortiGate firewall collector.
Polls system status and interface health from FortiGate REST API.
Reads connection from DB (platform='fortigate'); falls back to env vars
FORTIGATE_HOST / FORTIGATE_API_KEY.
Auth: access_token query parameter (not header).
"""
import asyncio
import logging
import os
import time

import httpx

from api.collectors.base import BaseCollector

log = logging.getLogger(__name__)


class FortiGateCollector(BaseCollector):
    component = "fortigate"
    platforms = ["fortigate"]
    interval = int(os.environ.get("FORTIGATE_POLL_INTERVAL", "60"))

    def __init__(self):
        super().__init__()

    def mock(self) -> dict:
        return {
            "health": "healthy",
            "connection_label": "mock-fortigate",
            "connection_id": "mock-fg-id",
            "hostname": "FGT-600E",
            "version": "7.4.1",
            "serial": "FGT60E1234567890",
            "uptime": 864000,
            "ha_mode": "standalone",
            "interfaces": [
                {
                    "name": "wan1",
                    "alias": "WAN",
                    "link": True,
                    "speed": 1000,
                    "type": "physical",
                    "ip": "203.0.113.1/24",
                    "rx_bytes": 1234567890,
                    "tx_bytes": 987654321,
                    "rx_errors": 0,
                    "tx_errors": 0,
                },
                {
                    "name": "internal",
                    "alias": "LAN",
                    "link": True,
                    "speed": 1000,
                    "type": "physical",
                    "ip": "192.168.1.1/24",
                    "rx_bytes": 9876543210,
                    "tx_bytes": 1234567890,
                    "rx_errors": 0,
                    "tx_errors": 0,
                },
            ],
        }

    def to_entities(self, state: dict) -> list:
        from api.collectors.base import Entity

        label = state.get("connection_label", state.get("hostname", "fortigate"))
        health_map = {
            "healthy": "healthy", "degraded": "degraded",
            "critical": "error", "error": "error", "unconfigured": "unknown",
        }
        base_status = health_map.get(state.get("health", "unknown"), "unknown")
        last_error = state.get("error") if base_status == "error" else None

        interfaces = state.get("interfaces", [])
        entities = []

        for iface in interfaces:
            name = iface.get("name", "unknown")
            link = iface.get("link", False)
            rx_errors = iface.get("rx_errors", 0) or 0
            tx_errors = iface.get("tx_errors", 0) or 0
            has_errors = (rx_errors + tx_errors) > 0

            if not link:
                status = "degraded"
                iface_error = f"{name}: link down"
            elif has_errors:
                status = "degraded"
                iface_error = f"{name}: {rx_errors + tx_errors} errors"
            else:
                status = "healthy"
                iface_error = None

            alias = iface.get("alias", "")
            display = f"{label}/{alias or name}"

            entities.append(Entity(
                id=f"fortigate:{label}:iface:{name}",
                label=display,
                component=self.component,
                platform="fortigate",
                section="NETWORK",
                status=status,
                last_error=iface_error,
                metadata={
                    "interface": name,
                    "alias": alias,
                    "link": link,
                    "speed": iface.get("speed", 0),
                    "type": iface.get("type", ""),
                    "ip": iface.get("ip", ""),
                    "rx_bytes": iface.get("rx_bytes", 0),
                    "tx_bytes": iface.get("tx_bytes", 0),
                    "connection": label,
                },
            ))

        if not entities:
            entities.append(Entity(
                id=f"fortigate:{label}",
                label=label,
                component=self.component,
                platform="fortigate",
                section="NETWORK",
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
            conn = get_connection_for_platform("fortigate")
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
            host = os.environ.get("FORTIGATE_HOST", "")
            api_key = os.environ.get("FORTIGATE_API_KEY", "")
            port = int(os.environ.get("FORTIGATE_PORT", "443"))
            conn_label = host
            conn_id = ""

        if not host:
            return {"health": "unconfigured", "interfaces": [],
                    "message": "No FortiGate connection configured"}

        if not api_key:
            return {"health": "error", "interfaces": [],
                    "error": "FortiGate API key not set",
                    "connection_label": conn_label, "connection_id": conn_id}

        base = f"https://{host}" if port == 443 else f"https://{host}:{port}"
        params = {"access_token": api_key}

        try:
            # 1. System status — confirms reachability + auth + gets hostname/version
            t0 = time.monotonic()
            r = httpx.get(f"{base}/api/v2/monitor/system/status",
                          params=params, headers={}, verify=False, timeout=8)
            latency_ms = round((time.monotonic() - t0) * 1000)

            if r.status_code == 401 or r.status_code == 403:
                return {"health": "error", "interfaces": [],
                        "error": "FortiGate auth failed — check API key",
                        "connection_label": conn_label, "connection_id": conn_id}
            r.raise_for_status()

            sys_data = r.json().get("results", r.json())
            hostname = sys_data.get("hostname", conn_label)
            version = sys_data.get("version", "")
            serial = sys_data.get("serial", "")
            uptime = sys_data.get("uptime", 0)
            ha_mode = sys_data.get("ha_mode", "standalone")

            # 2. Interface status
            interfaces = _collect_interfaces(base, params)
            # Stamp entity_id using this connection's label
            for iface in interfaces:
                iface["entity_id"] = f"fortigate:{conn_label}:iface:{iface['name']}"

            # Determine health
            down_ifaces = [i for i in interfaces if not i["link"]]
            error_ifaces = [i for i in interfaces
                           if (i.get("rx_errors", 0) or 0) + (i.get("tx_errors", 0) or 0) > 0]

            if not interfaces:
                health = "healthy"  # No interface data yet
            elif down_ifaces:
                health = "degraded"
            elif error_ifaces:
                health = "degraded"
            else:
                health = "healthy"

            snapshot = {
                "health": health,
                "hostname": hostname,
                "version": version,
                "serial": serial,
                "uptime": uptime,
                "ha_mode": ha_mode,
                "interfaces": interfaces,
                "latency_ms": latency_ms,
                "connection_label": conn_label,
                "connection_id": conn_id,
            }

            # v2.39.1: best-effort fact extraction
            try:
                from api.facts.extractors import extract_facts_from_fortigate_snapshot
                from api.db.known_facts import batch_upsert_facts
                from api.metrics import FACTS_UPSERTED_COUNTER
                facts = extract_facts_from_fortigate_snapshot(snapshot, conn_label)
                result = batch_upsert_facts(facts, actor="collector")
                for action, count in result.items():
                    if count > 0:
                        FACTS_UPSERTED_COUNTER.labels(
                            source="fortigate_collector", action=action
                        ).inc(count)
            except Exception as _fe:
                log.warning("Fact extraction failed for fortigate: %s", _fe)

            return snapshot

        except httpx.HTTPStatusError as e:
            log.warning("FortiGateCollector HTTP error %s: %s", conn_label, e)
            return {"health": "error", "interfaces": [],
                    "error": f"HTTP {e.response.status_code}",
                    "connection_label": conn_label, "connection_id": conn_id}
        except Exception as e:
            log.error("FortiGateCollector error %s: %s", conn_label, e)
            return {"health": "error", "interfaces": [],
                    "error": f"Connection failed: {str(e)[:80]}",
                    "connection_label": conn_label, "connection_id": conn_id}


def _collect_interfaces(base: str, params: dict) -> list:
    """Fetch physical interface status and counters."""
    try:
        r = httpx.get(f"{base}/api/v2/monitor/system/interface",
                      params=params, headers={}, verify=False, timeout=10)
        r.raise_for_status()
        raw = r.json().get("results", [])
    except Exception as e:
        log.debug("FortiGate interface fetch failed: %s", e)
        return []

    result = []
    for iface in raw:
        # Only include physical and aggregate interfaces
        iface_type = iface.get("type", "")
        if iface_type not in ("physical", "aggregate", "redundant", "vlan", "hard-switch"):
            continue

        result.append({
            "name": iface.get("name", "unknown"),
            "alias": iface.get("alias", ""),
            "link": iface.get("link", False),
            "speed": iface.get("speed", 0),
            "type": iface_type,
            "ip": iface.get("ip", ""),
            "rx_bytes": iface.get("rx_bytes", 0),
            "tx_bytes": iface.get("tx_bytes", 0),
            "rx_errors": iface.get("rx_errors", 0),
            "tx_errors": iface.get("tx_errors", 0),
        })
    return result
