"""
NetworkSSHCollector — polls SSH-based network gear (FortiSwitch, Cisco, Juniper)
via netmiko CLI commands every 60s.

Reads connections with auth_type='ssh' from the connections DB.
Writes component="network_ssh" to status_snapshots.
State shape: { health, devices: [DeviceCard], ok, total }
"""
import asyncio
import logging
import os

from api.collectors.base import BaseCollector

log = logging.getLogger(__name__)

SSH_PLATFORMS = {"fortiswitch", "cisco", "juniper", "aruba"}

# Map device_type to a show command that returns version/hostname
SHOW_CMDS = {
    "fortinet":      "get system status",
    "cisco_ios":     "show version | include Version",
    "cisco_xe":      "show version | include Version",
    "cisco_nxos":    "show version | include NXOS",
    "juniper_junos": "show version | match Junos",
    "aruba_os":      "show version",
    "default":       "show version",
}


class NetworkSSHCollector(BaseCollector):
    component = "network_ssh"

    def __init__(self):
        super().__init__()
        self.interval = int(os.environ.get("NETWORK_SSH_POLL_INTERVAL", "60"))

    async def poll(self) -> dict:
        return await asyncio.to_thread(self._collect_sync)

    def _collect_sync(self) -> dict:
        # Get decrypted connections per SSH platform
        ssh_conns = []
        try:
            from api.connections import get_connection_for_platform
            for platform in SSH_PLATFORMS:
                conn = get_connection_for_platform(platform)
                if conn and conn.get("host"):
                    ssh_conns.append(conn)
        except Exception as e:
            return {"health": "error", "devices": [], "error": str(e)}

        if not ssh_conns:
            return {"health": "unconfigured", "devices": [], "message": "No SSH connections configured"}

        devices = []
        errors = 0

        for c in ssh_conns:
            host = c.get("host", "")
            port = c.get("port") or 22
            creds = c.get("credentials", {}) if isinstance(c.get("credentials"), dict) else {}
            username = creds.get("username", "admin")
            password = creds.get("password", "")
            device_type = creds.get("device_type", "autodetect")
            label = c.get("label") or host

            try:
                from netmiko import ConnectHandler
                cmd = SHOW_CMDS.get(device_type, SHOW_CMDS["default"])
                device_params = {
                    "device_type": device_type,
                    "host": host,
                    "port": port,
                    "username": username,
                    "password": password,
                    "timeout": 10,
                    "session_timeout": 15,
                    "conn_timeout": 8,
                    "banner_timeout": 8,
                    "fast_cli": True,
                }
                with ConnectHandler(**device_params) as net_conn:
                    output = net_conn.send_command(cmd, read_timeout=8)

                devices.append({
                    "id": c.get("id"),
                    "label": label,
                    "host": host,
                    "port": port,
                    "platform": c.get("platform"),
                    "device_type": device_type,
                    "dot": "green",
                    "status": "online",
                    "output_snippet": output[:200] if output else "",
                })

            except Exception as e:
                log.warning("NetworkSSHCollector: %s (%s) failed: %s", label, host, e)
                errors += 1
                devices.append({
                    "id": c.get("id"),
                    "label": label,
                    "host": host,
                    "port": port,
                    "platform": c.get("platform"),
                    "device_type": device_type,
                    "dot": "red",
                    "status": "error",
                    "error": str(e)[:120],
                })

        total = len(devices)
        ok = total - errors
        if errors == 0:
            health = "healthy"
        elif ok == 0:
            health = "error"
        else:
            health = "degraded"

        return {"health": health, "devices": devices, "ok": ok, "total": total}
