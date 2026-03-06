"""
BaseCollector — abstract async polling loop.

Subclass this, set `component` and `interval`, implement `poll()`.
The loop calls `poll()` every `interval` seconds, catches all exceptions,
writes snapshots via the logger, and triggers alert checks.
Never crashes the API on infra unavailability.
"""
import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone

log = logging.getLogger(__name__)


class BaseCollector(ABC):
    component: str = "base"
    interval: int = 30  # seconds

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
            self.last_health = state.get("health", "unknown")
            self.last_error = None

            is_healthy = self.last_health in (
                "healthy", "ok", "green", "active", "unconfigured"
            )

            import api.logger as logger_mod
            await logger_mod.log_status_snapshot(self.component, state, is_healthy)

            # Trigger alert check (late import avoids circular)
            from api.alerts import check_transition
            await check_transition(self.component, self.last_health)

            # Memory hooks — health transition + semantic triggers
            from api.memory.hooks import after_status_snapshot
            from api.memory.triggers import evaluate_triggers
            after_status_snapshot(self.component, state)
            await evaluate_triggers(self.component, state)

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
