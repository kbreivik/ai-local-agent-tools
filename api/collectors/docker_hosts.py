"""
DockerHostsCollector — stub for multi-host Docker monitoring (Phase 2).

Registers the component in the collectors list immediately so it appears
in the UI. Full implementation will poll all docker_host connections.
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

    async def poll(self) -> dict:
        return await asyncio.to_thread(self._collect_sync)

    def _collect_sync(self) -> dict:
        # Phase 2: iterate all docker_host connections, poll each
        hosts = []
        try:
            from api.connections import get_all_connections_for_platform
            conns = get_all_connections_for_platform('docker_host')
            for conn in conns:
                hosts.append({
                    "label": conn.get("label", conn.get("host", "unknown")),
                    "host": conn.get("host", ""),
                    "port": conn.get("port", 2375),
                    "role": (conn.get("config") or {}).get("role", "unknown"),
                    "status": "configured",
                })
        except Exception as e:
            log.debug("docker_hosts: failed to read connections: %s", e)

        return {
            "health": "healthy" if hosts else "unconfigured",
            "hosts": hosts,
            "host_count": len(hosts),
        }
