"""
BaseCollector — abstract async polling loop.

Subclass this, set `component` and `interval`, implement `poll()`.
The loop calls `poll()` every `interval` seconds, catches all exceptions,
writes snapshots via the logger, and triggers alert checks.
Never crashes the API on infra unavailability.
"""
from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)


def _index_snapshot_to_es(component: str, state: dict) -> None:
    """POST a flattened collector snapshot to Elasticsearch deathstar-metrics-* index.

    Non-blocking (called in background thread via asyncio.to_thread by caller).
    Silently no-ops if ELASTIC_URL is not set.
    Only indexes components that have useful numeric metrics.
    """
    import os
    import json as _json
    from datetime import datetime, timezone

    elastic_url = os.environ.get("ELASTIC_URL", "").rstrip("/")
    if not elastic_url:
        return

    # Only index components with useful metrics — skip unconfigured
    health = state.get("health", "unknown")
    if health == "unconfigured":
        return

    # Build a flat document from the state
    now_iso = datetime.now(timezone.utc).isoformat()
    doc: dict = {
        "@timestamp": now_iso,
        "component": component,
        "health": health,
        "deathstar.source": "collector",
    }

    # Component-specific field extraction
    if component == "kafka_cluster":
        doc["kafka.brokers.alive"] = state.get("broker_count", 0)
        doc["kafka.brokers.expected"] = state.get("expected_brokers", 0)
        doc["kafka.partitions.under_replicated"] = state.get("under_replicated_partitions", 0)
        total_lag = sum(
            v.get("total_lag", 0)
            for v in (state.get("consumer_lag") or {}).values()
        )
        doc["kafka.consumer.lag.total"] = total_lag

    elif component == "swarm":
        doc["swarm.nodes.total"] = state.get("node_count", 0)
        doc["swarm.managers.active"] = state.get("active_managers", 0)
        doc["swarm.services.total"] = state.get("service_count", 0)
        doc["swarm.services.degraded"] = len(state.get("degraded_services") or [])
        doc["swarm.services.failed"] = len(state.get("failed_services") or [])

    elif component == "elasticsearch":
        doc["es.nodes"] = state.get("nodes", 0)
        doc["es.shards.active"] = (state.get("shards") or {}).get("active", 0)
        doc["es.shards.unassigned"] = (state.get("shards") or {}).get("unassigned", 0)

    elif component == "vm_hosts":
        # Aggregate across all VMs
        vms = state.get("vms") or []
        doc["vm_hosts.total"] = len(vms)
        doc["vm_hosts.ok"] = state.get("ok", 0)
        doc["vm_hosts.issues"] = state.get("issues", 0)

    elif component == "external_services":
        svcs = state.get("services") or []
        doc["external.total"] = len(svcs)
        doc["external.reachable"] = sum(1 for s in svcs if s.get("reachable"))
        doc["external.unreachable"] = sum(1 for s in svcs if not s.get("reachable"))

    else:
        # Skip components with no useful numeric fields
        return

    try:
        import httpx
        index = f"deathstar-metrics-{datetime.now(timezone.utc).strftime('%Y.%m')}"
        httpx.post(
            f"{elastic_url}/{index}/_doc",
            content=_json.dumps(doc),
            headers={"Content-Type": "application/json"},
            timeout=3.0,
        )
    except Exception:
        pass  # never let ES failure affect the collector loop


class BaseCollector(ABC):
    component: str = "base"
    interval: int = 30  # seconds
    platforms: list[str] = []  # connection platform types that trigger this collector

    def __init__(self):
        self._task: asyncio.Task | None = None
        self._running = False
        self.last_poll: datetime | None = None
        self.last_error: str | None = None
        self.last_health: str = "unknown"

    @abstractmethod
    async def poll(self) -> dict:
        """
        Collect data and return a state dict.
        Must include a 'health' key: healthy/degraded/critical/error/unconfigured
        Must never raise — handle exceptions internally.
        """
        ...

    async def _safe_poll(self) -> None:
        try:
            state = await self.poll()
            self._last_state = state
            self.last_health = state.get("health", "unknown")
            self.last_error = None

            is_healthy = self.last_health in (
                "healthy", "ok", "green", "active", "unconfigured"
            )

            import api.logger as logger_mod
            await logger_mod.log_status_snapshot(self.component, state, is_healthy)

            # Trigger alert check — pass connection metadata if available
            from api.alerts import check_transition
            await check_transition(
                self.component, self.last_health,
                connection_label=state.get("connection_label", ""),
                connection_id=state.get("connection_id", ""),
            )

            # Memory hooks — health transition + semantic triggers
            from api.memory.hooks import after_status_snapshot
            from api.memory.triggers import evaluate_triggers
            after_status_snapshot(self.component, state)
            await evaluate_triggers(self.component, state)

            # Index snapshot to Elasticsearch (non-blocking, best-effort)
            import asyncio as _asyncio
            _asyncio.create_task(
                _asyncio.to_thread(_index_snapshot_to_es, self.component, state)
            )

        except Exception as e:
            self.last_error = str(e)
            self.last_health = "error"
            log.error("Collector %s unhandled error: %s", self.component, e, exc_info=True)
            try:
                import api.logger as logger_mod
                await logger_mod.log_status_snapshot(
                    self.component,
                    {"health": "error", "error": str(e), "message": str(e)},
                    is_healthy=False,
                )
            except Exception:
                pass
        finally:
            self.last_poll = datetime.now(timezone.utc)

    async def _loop(self) -> None:
        self._running = True
        log.info("Collector %s started (interval=%ds)", self.component, self.interval)
        # Poll immediately on start, then on interval
        await self._safe_poll()
        while self._running:
            await asyncio.sleep(self.interval)
            if self._running:
                await self._safe_poll()

    def start(self) -> asyncio.Task:
        self._running = True
        self._task = asyncio.create_task(self._loop(), name=f"collector:{self.component}")
        return self._task

    def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()

    @property
    def is_running(self) -> bool:
        return self._running and self._task is not None and not self._task.done()

    def status(self) -> dict:
        return {
            "component": self.component,
            "running": self.is_running,
            "last_poll": self.last_poll.isoformat() if self.last_poll else None,
            "last_error": self.last_error,
            "last_health": self.last_health,
            "interval_s": self.interval,
        }

    def mock(self) -> dict:
        """Return fixture data in the same shape as poll(). No network calls."""
        raise NotImplementedError(f"{self.__class__.__name__} must implement mock()")

    def to_entities(self, state: dict) -> list[Entity]:
        """Convert a poll() state dict to canonical Entity objects."""
        status_map = {
            "healthy": "healthy", "ok": "healthy", "green": "healthy", "active": "healthy",
            "degraded": "degraded", "warn": "degraded", "amber": "degraded",
            "error": "error", "critical": "error", "red": "error",
            "unconfigured": "unknown",
        }
        raw = state.get("health", "unknown")
        status = status_map.get(str(raw).lower(), "unknown")
        last_error = state.get("error") or state.get("message") if status == "error" else None
        platform = self.platforms[0] if self.platforms else self.component
        return [Entity(
            id=self.component,
            label=self.component.replace("_", " ").title(),
            component=self.component,
            platform=platform,
            section=PLATFORM_SECTION.get(platform, "PLATFORM"),
            status=status,
            last_error=last_error,
            metadata={k: v for k, v in state.items()
                      if k not in ("health", "error", "message")},
        )]


PLATFORM_SECTION: dict[str, str] = {
    "proxmox": "COMPUTE", "pbs": "COMPUTE",
    "fortigate": "NETWORK", "fortiswitch": "NETWORK", "opnsense": "NETWORK",
    "cisco": "NETWORK", "juniper": "NETWORK", "aruba": "NETWORK",
    "unifi": "NETWORK", "pihole": "NETWORK", "technitium": "NETWORK",
    "nginx": "NETWORK", "caddy": "NETWORK", "traefik": "NETWORK",
    "truenas": "STORAGE", "synology": "STORAGE", "syncthing": "STORAGE",
    "security_onion": "SECURITY", "wazuh": "SECURITY",
    "grafana": "SECURITY", "kibana": "SECURITY",
    "portainer": "COMPUTE", "netbox": "NETWORK",
    "adguard": "NETWORK", "bookstack": "PLATFORM",
    "trilium": "PLATFORM",
    "lm_studio": "PLATFORM",
    "docker_host": "CONTAINERS",
    "vm_host": "COMPUTE",
    "elasticsearch": "SECURITY",
    "logstash": "SECURITY",
}


@dataclass
class Entity:
    id: str
    label: str
    component: str
    platform: str
    section: str
    status: str
    last_seen: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    latency_ms: int | None = None
    last_error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)
