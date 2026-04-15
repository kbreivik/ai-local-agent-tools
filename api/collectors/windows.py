"""WindowsCollector — WinRM-based Windows host monitoring (stub).

Polls connections with platform='windows'. Auth via credential profile
(auth_type='windows'). Full implementation deferred; this stub provides
the collector skeleton so the platform registers in the manager.
"""
import asyncio
import logging
import os

from api.collectors.base import BaseCollector

log = logging.getLogger(__name__)


class WindowsCollector(BaseCollector):
    component = "windows"
    platforms = ["windows"]

    def __init__(self):
        super().__init__()
        self.interval = int(os.environ.get("WINDOWS_POLL_INTERVAL", "60"))

    async def poll(self) -> dict:
        return await asyncio.to_thread(self._collect_sync)

    def _collect_sync(self) -> dict:
        from api.connections import get_all_connections_for_platform
        conns = get_all_connections_for_platform("windows")
        if not conns:
            return {"health": "unconfigured", "hosts": []}

        hosts = []
        for conn in conns:
            label = conn.get("label") or conn.get("host", "?")
            hosts.append({
                "label":  label,
                "host":   conn.get("host", ""),
                "port":   conn.get("port", 5985),
                "dot":    "grey",
                "status": "stub — WinRM collector not yet implemented",
            })

        return {"health": "unconfigured", "hosts": hosts}

    def to_entities(self, state: dict):
        from api.collectors.base import Entity
        return [
            Entity(
                id=h.get("label", h.get("host", "unknown")),
                label=h.get("label", ""),
                component=self.component,
                platform="windows",
                section="COMPUTE",
                status="unknown",
                metadata={"host": h.get("host", ""), "port": h.get("port", 5985)},
            )
            for h in state.get("hosts", [])
        ] or super().to_entities(state)
