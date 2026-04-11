"""
DockerHostsCollector — polls all docker_host connections.
Uses auth-aware client builder supporting TCP, TLS, and SSH modes.
"""
import asyncio
import logging
import os

from api.collectors.base import BaseCollector

log = logging.getLogger(__name__)


class DockerHostsCollector(BaseCollector):
    component = "docker_hosts"

    def __init__(self):
        super().__init__()
        self.interval = int(os.environ.get("DOCKER_HOSTS_POLL_INTERVAL", "60"))

    async def poll(self):
        return await asyncio.to_thread(self._collect_sync)

    def _collect_sync(self):
        from api.connections import get_all_connections_for_platform
        from api.collectors.swarm import _build_docker_client_for_conn

        hosts = []
        try:
            conns = get_all_connections_for_platform("docker_host")
        except Exception as e:
            log.debug("docker_hosts: failed to read connections: %s", e)
            return {"health": "unconfigured", "hosts": [], "host_count": 0}

        for conn in conns:
            label = conn.get("label", conn.get("host", "unknown"))
            host_info = {
                "label": label,
                "host": conn.get("host", ""),
                "port": conn.get("port", 2375),
                "role": (conn.get("config") or {}).get("role", "unknown"),
                "auth_mode": conn.get("auth_type", "tcp"),
            }
            try:
                client = _build_docker_client_for_conn(conn)
                info = client.info()
                client.close()
                host_info["status"] = "ok"
                host_info["docker_version"] = info.get("ServerVersion")
                host_info["containers"] = info.get("Containers", 0)
                host_info["is_swarm"] = info.get("Swarm", {}).get("LocalNodeState") == "active"
                host_info["dot"] = "green"
            except Exception as e:
                host_info["status"] = "error"
                host_info["error"] = str(e)[:120]
                host_info["dot"] = "red"
            hosts.append(host_info)

        ok  = sum(1 for h in hosts if h.get("dot") == "green")
        red = sum(1 for h in hosts if h.get("dot") == "red")
        health = "healthy" if red == 0 and hosts else ("degraded" if ok > 0 else "error" if hosts else "unconfigured")

        return {"health": health, "hosts": hosts, "host_count": len(hosts), "ok": ok, "issues": red}
