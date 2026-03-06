"""
CollectorManager — auto-discovers and manages all BaseCollector subclasses.

Drop a new file in api/collectors/ that defines a BaseCollector subclass —
it will be loaded automatically on next API start. No registration needed.
"""
import importlib
import inspect
import logging
import pkgutil
from pathlib import Path

from api.collectors.base import BaseCollector

log = logging.getLogger(__name__)

_SKIP = {"base", "manager", "__init__"}


class CollectorManager:
    def __init__(self):
        self._collectors: dict[str, BaseCollector] = {}

    def _discover(self) -> list[BaseCollector]:
        """Import every module in api/collectors/ and collect BaseCollector subclasses."""
        collectors = []
        pkg_dir = Path(__file__).parent

        for mod_info in pkgutil.iter_modules([str(pkg_dir)]):
            if mod_info.name in _SKIP:
                continue
            full_name = f"api.collectors.{mod_info.name}"
            try:
                mod = importlib.import_module(full_name)
                for _, cls in inspect.getmembers(mod, inspect.isclass):
                    if (
                        issubclass(cls, BaseCollector)
                        and cls is not BaseCollector
                        and cls.__module__ == full_name
                    ):
                        collectors.append(cls())
                        log.debug("Discovered collector: %s (%s)", cls.__name__, cls.component)
            except Exception as e:
                log.warning("Failed to load collector from %s: %s", full_name, e)

        return collectors

    def start_all(self) -> None:
        """Start all discovered collectors as background asyncio tasks."""
        collectors = self._discover()
        for collector in collectors:
            self._collectors[collector.component] = collector
            collector.start()
            log.info("Started collector: %s (every %ds)", collector.component, collector.interval)
        log.info("CollectorManager: %d collectors running", len(collectors))

    def stop_all(self) -> None:
        """Cancel all collector tasks."""
        for collector in self._collectors.values():
            collector.stop()
        self._collectors.clear()
        log.info("CollectorManager: all collectors stopped")

    def status(self) -> dict:
        """Return status dict keyed by component name."""
        return {name: c.status() for name, c in self._collectors.items()}

    def get(self, component: str) -> BaseCollector | None:
        return self._collectors.get(component)

    @property
    def components(self) -> list[str]:
        return list(self._collectors.keys())


# Module-level singleton — imported by main.py lifespan and status router
manager = CollectorManager()
