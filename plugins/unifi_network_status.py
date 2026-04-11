"""UniFi Network — devices, clients, and alerts via UniFi Controller API.

Reads credentials from the registered UniFi connection in the DB.
Supports API key mode (UDM SE / UniFi OS) and session mode (classic).
"""
import os
from datetime import datetime, timezone

import httpx


PLUGIN_META = {
    "name": "unifi_network_status",
    "description": (
        "Query UniFi Network clients, devices, and alerts. "
        "Reads credentials from the registered UniFi connection in the DB. "
        "Actions: 'clients' (default — hostnames, IPs, MACs), "
        "'devices' (APs, switches, gateways), 'alerts'."
    ),
    "platform": "unifi",
    "category": "networking",
    "agent_types": ["observe", "investigate"],
    "requires_plan": False,
    "params": {
        "host": {"type": "string", "required": False,
                 "description": "UniFi host override. Default: uses registered connection."},
        "action": {"type": "string", "required": False,
                   "description": "'clients' (default), 'devices', or 'alerts'"},
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


def _resolve_connection(host_override=""):
    """Resolve UniFi connection: DB first, env var fallback."""
    try:
        from api.connections import get_connection_for_platform
        conn = get_connection_for_platform("unifi")
        if conn:
            host = host_override or conn.get("host", "")
            port = conn.get("port") or 443
            creds = conn.get("credentials") or {}
            if isinstance(creds, str):
                import json
                try: creds = json.loads(creds)
                except Exception: creds = {}
            return {
                "host": host, "port": port,
                "api_key": creds.get("api_key", ""),
                "username": creds.get("username", ""),
                "password": creds.get("password", ""),
                "conn_label": conn.get("label", host),
                "conn_id": str(conn.get("id", "")),
                "source": "db",
            }
    except Exception:
        pass
    host = host_override or os.environ.get("UNIFI_HOST", "")
    api_key = os.environ.get("UNIFI_API_KEY", "")
    username = os.environ.get("UNIFI_USER", "")
    password = os.environ.get("UNIFI_PASSWORD", "")
    port = int(os.environ.get("UNIFI_PORT", "443" if api_key else "8443"))
    return {"host": host, "port": port, "api_key": api_key,
            "username": username, "password": password,
            "conn_label": host, "conn_id": "", "source": "env"}


def validate(**kwargs):
    c = _resolve_connection(kwargs.get("host", ""))
    if not c["host"]:
        return _err("No UniFi host configured — add in Settings → Connections")
    if not c["api_key"] and not (c["username"] and c["password"]):
        return _err("No UniFi credentials — add api_key or username+password in connection")
    try:
        if c["api_key"]:
            r = httpx.get(f"https://{c['host']}/proxy/network/api/s/default/stat/health",
                          headers={"X-API-KEY": c["api_key"]}, verify=False, timeout=8)
            if r.status_code == 401:
                return _err("API key rejected")
            r.raise_for_status()
            return _ok({"reachable": True, "auth": "apikey", "source": c["source"]},
                       "UniFi reachable via API key")
        else:
            client = httpx.Client(verify=False, timeout=10)
            r = client.post(f"https://{c['host']}:{c['port']}/api/login",
                            json={"username": c["username"], "password": c["password"]})
            client.close()
            if r.status_code == 200:
                return _ok({"reachable": True, "auth": "session", "source": c["source"]},
                           "UniFi reachable via session")
            return _err("Login failed")
    except Exception as e:
        return _err(f"UniFi connection failed: {e}")


def execute(**kwargs):
    host_override = kwargs.get("host", "")
    action = kwargs.get("action", "clients")
    c = _resolve_connection(host_override)

    if not c["host"]:
        return _err("No UniFi connection configured — add in Settings → Connections")

    site = os.environ.get("UNIFI_SITE", "default")

    if c["api_key"]:
        return _execute_apikey(c, action, site)
    elif c["username"] and c["password"]:
        return _execute_session(c, action, site)
    else:
        return _err(f"No credentials for UniFi {c['conn_label']} — "
                    "add api_key (for UDM/UCG) or username+password in the connection")


def _execute_apikey(c, action, site):
    host, port = c["host"], c["port"]
    base = f"https://{host}" if port == 443 else f"https://{host}:{port}"
    api_base = f"{base}/proxy/network/api/s/{site}"
    headers = {"X-API-KEY": c["api_key"], "Accept": "application/json"}
    client = httpx.Client(verify=False, timeout=15, headers=headers)
    try:
        if action == "clients":
            r = client.get(f"{api_base}/stat/sta")
            r.raise_for_status()
            clients = r.json().get("data", [])
            result = [{"hostname": cl.get("hostname") or cl.get("name") or cl.get("mac", "?"),
                        "ip": cl.get("ip", ""), "mac": cl.get("mac", ""),
                        "type": "wireless" if not cl.get("is_wired") else "wired",
                        "ap_mac": cl.get("ap_mac", ""), "network": cl.get("network", ""),
                        "signal": cl.get("signal"), "uptime": cl.get("uptime", 0),
                        "tx_bytes": cl.get("tx_bytes", 0), "rx_bytes": cl.get("rx_bytes", 0)}
                       for cl in clients]
            return _ok({"connection": c["conn_label"], "action": "clients",
                        "count": len(result), "clients": result},
                       f"{len(result)} clients on {c['conn_label']}")

        elif action == "devices":
            r = client.get(f"{api_base}/stat/device")
            r.raise_for_status()
            devices = r.json().get("data", [])
            result = [{"name": d.get("name", d.get("mac", "?")), "mac": d.get("mac", ""),
                        "model": d.get("model", ""), "type": d.get("type", ""),
                        "state": "connected" if d.get("state", 0) == 1 else "disconnected",
                        "clients": int(d.get("num_sta", 0) or 0),
                        "uptime": int(d.get("uptime", 0) or 0),
                        "version": d.get("version", ""), "ip": d.get("ip", "")}
                       for d in devices]
            disconnected = [d["name"] for d in result if d["state"] != "connected"]
            data = {"connection": c["conn_label"], "action": "devices",
                    "count": len(result), "devices": result}
            if disconnected:
                return _degraded(data, f"{len(disconnected)} disconnected: {', '.join(disconnected)}")
            return _ok(data, f"{len(result)} devices on {c['conn_label']}")

        elif action == "alerts":
            r = client.get(f"{api_base}/stat/alarm?archived=false")
            if r.status_code == 404:
                r = client.get(f"{api_base}/stat/event?_limit=20")
            r.raise_for_status()
            alerts = r.json().get("data", [])[:20]
            return _ok({"connection": c["conn_label"], "action": "alerts",
                        "count": len(alerts), "alerts": alerts},
                       f"{len(alerts)} alert(s) on {c['conn_label']}")
        else:
            return _err(f"Unknown action {action!r}. Use: clients, devices, alerts")
    except Exception as e:
        if "401" in str(e) or "403" in str(e):
            return _err(f"UniFi API key rejected on {c['conn_label']} — "
                        "check key in Settings → Connections")
        return _err(f"UniFi API error: {e}")
    finally:
        client.close()


def _execute_session(c, action, site):
    host, port = c["host"], c["port"]
    base = f"https://{host}:{port}"
    api_base = f"{base}/api/s/{site}"
    client = httpx.Client(verify=False, timeout=15, follow_redirects=True)
    try:
        r = client.post(f"{base}/api/login",
                        json={"username": c["username"], "password": c["password"]})
        if r.status_code in (400, 401):
            return _err(f"UniFi login failed on {c['conn_label']} — "
                        "use a local admin account or switch to API key auth")
        r.raise_for_status()

        if action == "clients":
            r2 = client.get(f"{api_base}/stat/sta")
            r2.raise_for_status()
            clients = r2.json().get("data", [])
            result = [{"hostname": cl.get("hostname") or cl.get("mac", "?"),
                        "ip": cl.get("ip", ""), "mac": cl.get("mac", ""),
                        "type": "wireless" if not cl.get("is_wired") else "wired"}
                       for cl in clients]
            return _ok({"connection": c["conn_label"], "count": len(result), "clients": result},
                       f"{len(result)} clients")

        elif action == "devices":
            r2 = client.get(f"{api_base}/stat/device")
            r2.raise_for_status()
            devices = r2.json().get("data", [])
            result = [{"name": d.get("name", "?"), "mac": d.get("mac", ""),
                        "state": "connected" if d.get("state", 0) == 1 else "disconnected",
                        "clients": int(d.get("num_sta", 0) or 0)}
                       for d in devices]
            disconnected = [d["name"] for d in result if d["state"] != "connected"]
            data = {"connection": c["conn_label"], "count": len(result), "devices": result}
            if disconnected:
                return _degraded(data, f"{len(disconnected)} disconnected: {', '.join(disconnected)}")
            return _ok(data, f"{len(result)} devices")

        elif action == "alerts":
            r2 = client.get(f"{api_base}/stat/alarm", params={"_limit": 20})
            r2.raise_for_status()
            alerts = r2.json().get("data", [])[:20]
            return _ok({"connection": c["conn_label"], "count": len(alerts), "alerts": alerts},
                       f"{len(alerts)} alert(s)")
        else:
            return _err(f"Unknown action {action!r}. Use: clients, devices, alerts")
    except Exception as e:
        return _err(f"UniFi session error: {e}")
    finally:
        client.close()
