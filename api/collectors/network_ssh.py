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


def _ssh_exec(host: str, port: int, username: str, password: str,
              device_type: str, cmd: str) -> str:
    """
    Execute a CLI command via SSH with wingpy -> netmiko -> paramiko fallback.
    Returns command output string. Raises RuntimeError if all methods fail.
    """
    last_exc = None

    # 1. wingpy (optional, fastest — silent skip if not installed)
    try:
        from wingpy import Device as WingDevice  # noqa
        dev = WingDevice(host=host, port=port, username=username, password=password,
                         device_type=device_type, timeout=10)
        with dev:
            return dev.send_command(cmd)
    except ImportError:
        pass
    except Exception as e:
        last_exc = e
        log.debug("wingpy failed for %s: %s", host, e)

    # 2. netmiko (primary / most compatible)
    try:
        from netmiko import ConnectHandler
        with ConnectHandler(
            device_type=device_type, host=host, port=port,
            username=username, password=password,
            timeout=10, session_timeout=15,
            conn_timeout=8, banner_timeout=8, fast_cli=True,
        ) as conn:
            return conn.send_command(cmd, read_timeout=8)
    except ImportError:
        pass
    except Exception as e:
        last_exc = e
        log.debug("netmiko failed for %s: %s", host, e)

    # 3. paramiko (last resort — raw SSH)
    try:
        import paramiko
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(host, port=port, username=username, password=password,
                    timeout=10, look_for_keys=False, allow_agent=False)
        try:
            _, stdout, _ = ssh.exec_command(cmd, timeout=10)
            output = stdout.read().decode("utf-8", errors="replace").strip()
        finally:
            ssh.close()
        if output:
            return output
        raise RuntimeError("paramiko exec_command returned empty output")
    except ImportError:
        pass
    except Exception as e:
        last_exc = e
        log.debug("paramiko failed for %s: %s", host, e)

    raise RuntimeError(f"All SSH methods failed for {host}: {last_exc}")


class NetworkSSHCollector(BaseCollector):
    component = "network_ssh"
    platforms = ["fortiswitch", "cisco", "juniper", "aruba"]

    def __init__(self):
        super().__init__()
        self.interval = int(os.environ.get("NETWORK_SSH_POLL_INTERVAL", "60"))

    def mock(self) -> dict:
        return {
            "health": "healthy",
            "devices": [
                {"id": "mock-fs", "label": "FortiSwitch-48E", "host": "192.168.1.10", "port": 22,
                 "platform": "fortiswitch", "device_type": "fortinet_fswitch",
                 "dot": "green", "status": "online", "output_snippet": "FortiSwitch-48E v7.4.1"},
            ],
        }

    def to_entities(self, state: dict) -> list:
        from api.collectors.base import Entity, PLATFORM_SECTION
        dot_to_status = {"green": "healthy", "amber": "degraded", "red": "error", "grey": "unknown"}
        entities = []
        for dev in state.get("devices", []):
            platform = dev.get("platform", "network")
            dot = dev.get("dot", "grey")
            entities.append(Entity(
                id=f"network_ssh:{dev.get('host', dev.get('id', 'unknown'))}",
                label=dev.get("label", dev.get("host", "unknown")),
                component=self.component, platform=platform,
                section=PLATFORM_SECTION.get(platform, "NETWORK"),
                status=dot_to_status.get(dot, "unknown"),
                last_error=dev.get("error") if dot == "red" else None,
                metadata={"host": dev.get("host"), "port": dev.get("port"),
                          "device_type": dev.get("device_type"),
                          "output_snippet": (dev.get("output_snippet") or "")[:100]},
            ))
        return entities if entities else super().to_entities(state)

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
                cmd = SHOW_CMDS.get(device_type, SHOW_CMDS["default"])
                output = _ssh_exec(host, port, username, password, device_type, cmd)

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
