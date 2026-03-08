"""Host network info tool."""
import socket
from datetime import datetime, timezone


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_host_network() -> dict:
    """Get the host machine IP addresses and network connectivity info.
    Call this tool when asked about IP addresses, hostnames, which addresses
    can be used to connect to this agent, or how to reach this agent from
    other machines on the network."""
    try:
        hostname = socket.gethostname()
        try:
            all_ips = socket.gethostbyname_ex(hostname)[2]
        except Exception:
            all_ips = [socket.gethostbyname(hostname)]

        # Separate LAN IPs from loopback/docker bridge ranges
        lan_ips = [
            ip for ip in all_ips
            if not ip.startswith('127.')
            and not ip.startswith('172.')
            and not ip.startswith('169.')
        ]

        return {
            "status": "ok",
            "data": {
                "hostname":  hostname,
                "lan_ips":   lan_ips,
                "all_ips":   all_ips,
                "api_port":  8000,
                "gui_port":  5173,
                "api_urls":  [f"http://{ip}:8000" for ip in lan_ips],
                "gui_urls":  [f"http://{ip}:5173" for ip in lan_ips],
            },
            "timestamp": _ts(),
            "message": (
                f"Host: {hostname} | "
                f"LAN IPs: {', '.join(lan_ips) if lan_ips else 'none detected'} | "
                f"API: :{8000}  GUI: :{5173}"
            ),
        }
    except Exception as e:
        return {
            "status": "error",
            "data": None,
            "timestamp": _ts(),
            "message": f"get_host_network error: {e}",
        }
