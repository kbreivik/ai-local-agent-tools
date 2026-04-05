"""FortiSwitch 424E — system status, port status, and VLAN configuration."""
import os
from datetime import datetime, timezone

import httpx


PLUGIN_META = {
    "name": "fortiswitch_status",
    "description": "Query FortiSwitch system status, port link/speed/PoE, and VLAN configuration.",
    "platform": "fortiswitch",
    "category": "networking",
    "agent_types": ["observe", "investigate"],
    "requires_plan": False,
    "params": {
        "host": {"type": "string", "required": False, "description": "FortiSwitch host (default: env FORTISWITCH_HOST)"},
        "action": {"type": "string", "required": False, "description": "'status' (default), 'ports', or 'vlans'"},
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


def _get_client(host: str) -> tuple[str, dict]:
    """Return (base_url, headers) for FortiSwitch API."""
    api_key = os.environ.get("FORTISWITCH_API_KEY", "")
    base = f"https://{host}/api/v2"
    if api_key:
        return base, {"Authorization": f"Bearer {api_key}"}
    # Fallback: try FortiGate managed mode (query through FortiGate)
    fg_host = os.environ.get("FORTIGATE_HOST", "")
    fg_key = os.environ.get("FORTIGATE_API_KEY", "")
    if fg_host and fg_key:
        return f"https://{fg_host}/api/v2", {}
    return base, {}


def validate(**kwargs) -> dict:
    """Check connectivity to FortiSwitch API."""
    host = kwargs.get("host") or os.environ.get("FORTISWITCH_HOST", "")
    if not host:
        return _err("FORTISWITCH_HOST not configured")
    base, headers = _get_client(host)
    api_key = os.environ.get("FORTISWITCH_API_KEY", "")
    try:
        r = httpx.get(f"{base}/monitor/system/status",
                      params={"access_token": api_key} if api_key else {},
                      headers=headers, verify=False, timeout=10)
        r.raise_for_status()
        return _ok({"reachable": True}, "FortiSwitch reachable")
    except Exception as e:
        return _err(f"FortiSwitch connection failed: {e}")


def execute(**kwargs) -> dict:
    """Query FortiSwitch status, ports, or VLANs."""
    host = kwargs.get("host") or os.environ.get("FORTISWITCH_HOST", "")
    action = kwargs.get("action", "status")
    if not host:
        return _err("FORTISWITCH_HOST not configured")

    api_key = os.environ.get("FORTISWITCH_API_KEY", "")
    if not api_key:
        return _err("FORTISWITCH_API_KEY not configured")

    base = f"https://{host}/api/v2"
    params = {"access_token": api_key}

    try:
        if action == "ports":
            return _get_ports(base, params)
        elif action == "vlans":
            return _get_vlans(base, params)
        return _get_status(base, params)
    except httpx.HTTPStatusError as e:
        return _err(f"FortiSwitch API error: HTTP {e.response.status_code}")
    except Exception as e:
        return _err(f"FortiSwitch connection failed: {e}")


def _get_status(base: str, params: dict) -> dict:
    r = httpx.get(f"{base}/monitor/system/status", params=params, verify=False, timeout=10)
    r.raise_for_status()
    data = r.json().get("results", r.json())
    return _ok({
        "hostname": data.get("hostname", ""),
        "serial": data.get("serial", ""),
        "version": data.get("version", ""),
        "build": data.get("build", ""),
        "uptime": data.get("uptime", 0),
    }, f"FortiSwitch: {data.get('hostname', '?')} v{data.get('version', '?')}")


def _get_ports(base: str, params: dict) -> dict:
    r = httpx.get(f"{base}/monitor/switch/port-statistics", params=params,
                  verify=False, timeout=10)
    r.raise_for_status()
    ports = r.json().get("results", [])
    port_list = []
    for p in ports:
        port_list.append({
            "name": p.get("name", ""),
            "link": p.get("link", "down"),
            "speed": p.get("speed", ""),
            "duplex": p.get("duplex", ""),
            "poe_status": p.get("poe_status", ""),
            "vlan": p.get("vlan", ""),
            "tx_bytes": p.get("tx_bytes", 0),
            "rx_bytes": p.get("rx_bytes", 0),
        })
    up = len([p for p in port_list if p["link"] == "up"])
    return _ok({"ports": port_list, "count": len(port_list), "up": up},
               f"FortiSwitch: {up}/{len(port_list)} ports up")


def _get_vlans(base: str, params: dict) -> dict:
    r = httpx.get(f"{base}/cmdb/switch/vlan", params=params, verify=False, timeout=10)
    r.raise_for_status()
    vlans = r.json().get("results", [])
    vlan_list = []
    for v in vlans:
        vlan_list.append({
            "id": v.get("id", 0),
            "description": v.get("description", ""),
            "member_ports": [m.get("member-name", "") for m in v.get("member", [])],
        })
    return _ok({"vlans": vlan_list, "count": len(vlan_list)},
               f"FortiSwitch: {len(vlan_list)} VLAN(s)")
