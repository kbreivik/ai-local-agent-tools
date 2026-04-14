"""
UniFi Network collector — device status and client count.
Two auth modes:
  - API key (UniFi OS consoles only): X-API-KEY header, port 443, /proxy/network prefix
  - Cookie session (classic controllers): POST /api/login, port 8443
Reads connection from DB (platform='unifi'); env var fallback.
"""
import asyncio
import logging
import os
import time

import httpx

from api.collectors.base import BaseCollector

log = logging.getLogger(__name__)

DEVICE_TYPE_LABEL = {
    "uap": "AP", "usw": "Switch", "ugw": "Gateway",
    "udm": "UDM", "uxg": "Gateway", "usp": "SmartPower",
}


class UniFiCollector(BaseCollector):
    component = "unifi"
    platforms = ["unifi"]
    interval = int(os.environ.get("UNIFI_POLL_INTERVAL", "60"))

    def __init__(self):
        super().__init__()

    def mock(self) -> dict:
        return {
            "health": "healthy", "auth_mode": "apikey",
            "connection_label": "mock-unifi", "connection_id": "mock-unifi-id",
            "site": "default",
            "devices": [
                {"name": "Living Room AP", "mac": "aa:bb:cc:dd:ee:ff", "model": "U6-Lite",
                 "type": "uap", "type_label": "AP", "state": "connected",
                 "clients": 8, "uptime": 86400, "version": "6.5.28"},
                {"name": "Core Switch", "mac": "11:22:33:44:55:66", "model": "USW-24-PoE",
                 "type": "usw", "type_label": "Switch", "state": "connected",
                 "clients": 12, "uptime": 1209600, "version": "6.5.28"},
            ],
            "device_count": 2, "devices_up": 2, "devices_down": 0,
            "client_count": 20, "wired_clients": 12, "wireless_clients": 8,
        }

    def to_entities(self, state: dict) -> list:
        from api.collectors.base import Entity

        label = state.get("connection_label", "unifi")
        health_map = {"healthy": "healthy", "degraded": "degraded",
                      "critical": "error", "error": "error", "unconfigured": "unknown"}
        base_status = health_map.get(state.get("health", "unknown"), "unknown")
        last_error = state.get("error") if base_status == "error" else None

        devices = state.get("devices", [])
        entities = []

        for dev in devices:
            name = dev.get("name") or dev.get("mac", "unknown")
            connected = dev.get("state") == "connected"
            type_label = dev.get("type_label", dev.get("type", "device"))
            entities.append(Entity(
                id=f"unifi:{label}:device:{dev.get('mac', name)}",
                label=f"{label}/{name}",
                component=self.component, platform="unifi", section="NETWORK",
                status="healthy" if connected else "degraded",
                last_error=f"{type_label} {name} disconnected" if not connected else None,
                metadata={
                    "name": name, "type": type_label, "model": dev.get("model", ""),
                    "clients": dev.get("clients", 0), "state": dev.get("state", "unknown"),
                    "uptime": dev.get("uptime", 0), "version": dev.get("version", ""),
                    "auth_mode": state.get("auth_mode", "unknown"), "connection": label,
                },
            ))

        # Summary entity — total client count always present
        entities.append(Entity(
            id=f"unifi:{label}:clients",
            label=f"{label}/clients",
            component=self.component, platform="unifi", section="NETWORK",
            status=base_status, last_error=last_error,
            metadata={
                "total_clients": state.get("client_count", 0),
                "wired": state.get("wired_clients", 0),
                "wireless": state.get("wireless_clients", 0),
                "device_count": state.get("device_count", 0),
                "devices_up": state.get("devices_up", 0),
                "devices_down": state.get("devices_down", 0),
                "auth_mode": state.get("auth_mode", "unknown"), "connection": label,
            },
        ))

        return entities[-1:] if not devices else entities

    async def poll(self) -> dict:
        return await asyncio.to_thread(self._collect_sync)

    def _collect_sync(self) -> dict:
        conn = None
        try:
            from api.connections import get_connection_for_platform
            conn = get_connection_for_platform("unifi")
        except Exception:
            pass

        if conn:
            host = conn.get("host", "")
            creds = conn.get("credentials", {}) if isinstance(conn.get("credentials"), dict) else {}
            api_key = creds.get("api_key", "")
            username = creds.get("username", "")
            password = creds.get("password", "")
            port = conn.get("port") or (443 if api_key else 8443)
            conn_label = conn.get("label", host)
            conn_id = conn.get("id", "")
        else:
            host = os.environ.get("UNIFI_HOST", "")
            api_key = os.environ.get("UNIFI_API_KEY", "")
            username = os.environ.get("UNIFI_USER", "")
            password = os.environ.get("UNIFI_PASSWORD", "")
            port = int(os.environ.get("UNIFI_PORT", "443" if api_key else "8443"))
            conn_label = host
            conn_id = ""

        if not host:
            return {"health": "unconfigured", "devices": [],
                    "message": "No UniFi connection configured"}

        site = os.environ.get("UNIFI_SITE", "default")

        if api_key:
            return _collect_apikey(host, port, api_key, site, conn_label, conn_id)
        elif username and password:
            return _collect_session(host, port, username, password, site, conn_label, conn_id)
        else:
            return {"health": "error", "devices": [],
                    "error": "UniFi: set api_key (recommended) OR username+password",
                    "connection_label": conn_label, "connection_id": conn_id}


def _collect_apikey(host, port, api_key, site, conn_label, conn_id) -> dict:
    """UniFi OS API key mode — X-API-KEY header, /proxy/network prefix."""
    base_url = f"https://{host}" if port == 443 else f"https://{host}:{port}"
    api_base = f"{base_url}/proxy/network/api/s/{site}"
    headers = {"X-API-KEY": api_key, "Accept": "application/json"}

    try:
        t0 = time.monotonic()
        r = httpx.get(f"{base_url}/proxy/network/api/s/{site}/stat/health",
                      headers=headers, verify=False, timeout=8)
        latency_ms = round((time.monotonic() - t0) * 1000)
        if r.status_code == 401:
            return {"health": "error", "devices": [], "auth_mode": "apikey",
                    "error": "UniFi API key rejected — check key; API key only works on UniFi OS consoles (UDM/UCG/etc)",
                    "connection_label": conn_label, "connection_id": conn_id}
        r.raise_for_status()

        client = httpx.Client(verify=False, timeout=15, headers=headers)
        try:
            devices = _get_devices(client, api_base)
            client_count, wired, wireless = _get_clients(client, api_base)
        finally:
            client.close()

        return _build_result(devices, client_count, wired, wireless,
                             latency_ms, "apikey", site, conn_label, conn_id)
    except Exception as e:
        log.error("UniFi apikey error %s: %s", conn_label, e)
        return {"health": "error", "devices": [], "auth_mode": "apikey",
                "error": f"Connection failed: {str(e)[:80]}",
                "connection_label": conn_label, "connection_id": conn_id}


def _collect_session(host, port, username, password, site, conn_label, conn_id) -> dict:
    """Classic cookie session — POST /api/login, persist cookie via httpx.Client."""
    base_url = f"https://{host}:{port}"
    api_base = f"{base_url}/api/s/{site}"

    client = httpx.Client(verify=False, timeout=15, follow_redirects=True)
    try:
        t0 = time.monotonic()
        r = client.post(f"{base_url}/api/login",
                        json={"username": username, "password": password})
        latency_ms = round((time.monotonic() - t0) * 1000)
        if r.status_code == 400:
            return {"health": "error", "devices": [], "auth_mode": "session",
                    "error": "UniFi login failed — use a local admin account (cloud/UI.com accounts require MFA and will fail)",
                    "connection_label": conn_label, "connection_id": conn_id}
        r.raise_for_status()

        devices = _get_devices(client, api_base)
        client_count, wired, wireless = _get_clients(client, api_base)
        return _build_result(devices, client_count, wired, wireless,
                             latency_ms, "session", site, conn_label, conn_id)
    except Exception as e:
        log.error("UniFi session error %s: %s", conn_label, e)
        return {"health": "error", "devices": [], "auth_mode": "session",
                "error": f"Connection failed: {str(e)[:80]}",
                "connection_label": conn_label, "connection_id": conn_id}
    finally:
        client.close()


def _get_devices(client: httpx.Client, api_base: str) -> list:
    try:
        r = client.get(f"{api_base}/stat/device")
        r.raise_for_status()
        raw = r.json().get("data", [])
    except Exception as e:
        log.debug("UniFi device list failed: %s", e)
        return []
    result = []
    for d in raw:
        dev_type = d.get("type", "")
        result.append({
            "name": d.get("name", d.get("mac", "unknown")),
            "mac": d.get("mac", ""),
            "model": d.get("model", ""),
            "type": dev_type,
            "type_label": DEVICE_TYPE_LABEL.get(dev_type, dev_type.upper() or "Device"),
            "state": "connected" if d.get("state", 0) == 1 else "disconnected",
            "clients": int(d.get("num_sta", 0) or 0),
            "uptime": int(d.get("uptime", 0) or 0),
            "version": d.get("version", ""),
        })
    return result


def _get_clients(client: httpx.Client, api_base: str) -> tuple[int, int, int]:
    try:
        r = client.get(f"{api_base}/stat/sta")
        r.raise_for_status()
        clients = r.json().get("data", [])
    except Exception as e:
        log.debug("UniFi client list failed: %s", e)
        return 0, 0, 0
    wired = sum(1 for c in clients if c.get("is_wired", False))
    return len(clients), wired, len(clients) - wired


def _build_result(devices, client_count, wired, wireless,
                  latency_ms, auth_mode, site, conn_label, conn_id) -> dict:
    # Stamp entity_id onto each device so the frontend can open EntityDrawer
    for dev in devices:
        dev["entity_id"] = f"unifi:{conn_label}:device:{dev.get('mac') or dev.get('name', 'unknown')}"
    devices_up = sum(1 for d in devices if d["state"] == "connected")
    devices_down = len(devices) - devices_up
    health = ("critical" if devices_down == len(devices) > 0
              else "degraded" if devices_down > 0
              else "healthy")
    return {
        "health": health, "auth_mode": auth_mode, "site": site,
        "devices": devices, "device_count": len(devices),
        "devices_up": devices_up, "devices_down": devices_down,
        "client_count": client_count, "wired_clients": wired, "wireless_clients": wireless,
        "latency_ms": latency_ms, "connection_label": conn_label, "connection_id": conn_id,
    }
