"""UniFi Network — devices, clients, and alerts via UniFi Controller API."""
import os
from datetime import datetime, timezone

import httpx


PLUGIN_META = {
    "name": "unifi_network_status",
    "description": "Query UniFi Network devices (APs, switches, gateways), connected clients, and alerts.",
    "platform": "unifi",
    "category": "networking",
    "agent_types": ["observe", "investigate"],
    "requires_plan": False,
    "params": {
        "host": {"type": "string", "required": False, "description": "UniFi host (default: env UNIFI_HOST)"},
        "action": {"type": "string", "required": False, "description": "'devices' (default), 'clients', or 'alerts'"},
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


def _login(client: httpx.Client, host: str) -> bool:
    """Authenticate to UniFi Controller. Returns True on success."""
    user = os.environ.get("UNIFI_USER", "")
    password = os.environ.get("UNIFI_PASSWORD", "")
    if not user or not password:
        return False
    r = client.post(f"https://{host}:8443/api/login",
                    json={"username": user, "password": password})
    return r.status_code == 200


def validate(**kwargs) -> dict:
    """Check connectivity to UniFi Controller."""
    host = kwargs.get("host") or os.environ.get("UNIFI_HOST", "")
    if not host:
        return _err("UNIFI_HOST not configured")
    try:
        client = httpx.Client(verify=False, timeout=10)
        if _login(client, host):
            client.close()
            return _ok({"reachable": True}, "UniFi Controller reachable")
        client.close()
        return _err("UniFi login failed — check UNIFI_USER and UNIFI_PASSWORD")
    except Exception as e:
        return _err(f"UniFi connection failed: {e}")


def execute(**kwargs) -> dict:
    """Query UniFi devices, clients, or alerts."""
    host = kwargs.get("host") or os.environ.get("UNIFI_HOST", "")
    action = kwargs.get("action", "devices")
    site = os.environ.get("UNIFI_SITE", "default")
    if not host:
        return _err("UNIFI_HOST not configured")

    client = httpx.Client(verify=False, timeout=15, follow_redirects=True)
    try:
        if not _login(client, host):
            return _err("UniFi login failed — check UNIFI_USER and UNIFI_PASSWORD")

        base = f"https://{host}:8443/api/s/{site}"

        if action == "clients":
            return _get_clients(client, base)
        elif action == "alerts":
            return _get_alerts(client, base)
        return _get_devices(client, base)
    except httpx.HTTPStatusError as e:
        return _err(f"UniFi API error: HTTP {e.response.status_code}")
    except Exception as e:
        return _err(f"UniFi connection failed: {e}")
    finally:
        client.close()


def _get_devices(client: httpx.Client, base: str) -> dict:
    r = client.get(f"{base}/stat/device")
    r.raise_for_status()
    devices = r.json().get("data", [])
    result = []
    disconnected = []
    for d in devices:
        name = d.get("name", d.get("mac", "unknown"))
        state = "connected" if d.get("state", 0) == 1 else "disconnected"
        info = {
            "name": name,
            "mac": d.get("mac", ""),
            "model": d.get("model", ""),
            "type": d.get("type", ""),
            "version": d.get("version", ""),
            "state": state,
            "uptime": d.get("uptime", 0),
            "clients": d.get("num_sta", 0),
        }
        result.append(info)
        if state != "connected":
            disconnected.append(name)

    data = {"devices": result, "count": len(result)}
    if disconnected:
        return _degraded(data, f"UniFi: {len(disconnected)} disconnected: {', '.join(disconnected)}")
    return _ok(data, f"UniFi: {len(result)} device(s), all connected")


def _get_clients(client: httpx.Client, base: str) -> dict:
    r = client.get(f"{base}/stat/sta")
    r.raise_for_status()
    clients = r.json().get("data", [])
    result = []
    for c in clients[:50]:
        result.append({
            "hostname": c.get("hostname", c.get("name", "")),
            "ip": c.get("ip", ""),
            "mac": c.get("mac", ""),
            "network": c.get("network", ""),
            "vlan": c.get("vlan", 0),
            "signal": c.get("signal", None),
            "experience": c.get("satisfaction", None),
            "is_wired": c.get("is_wired", False),
        })
    return _ok({"clients": result, "count": len(clients), "shown": len(result)},
               f"UniFi: {len(clients)} client(s) connected")


def _get_alerts(client: httpx.Client, base: str) -> dict:
    r = client.get(f"{base}/stat/alarm", params={"_limit": 20})
    r.raise_for_status()
    alerts = r.json().get("data", [])
    result = []
    for a in alerts[:20]:
        result.append({
            "type": a.get("key", ""),
            "message": a.get("msg", ""),
            "datetime": a.get("datetime", ""),
            "archived": a.get("archived", False),
        })
    return _ok({"alerts": result, "count": len(alerts)},
               f"UniFi: {len(alerts)} alert(s)")
