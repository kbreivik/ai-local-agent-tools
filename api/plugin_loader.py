"""Plugin scanner and loader — auto-discovers .py files from plugins/ directory.

Tier 2 tools: human-written, auto-discovered at startup, same contract as skills.
Each plugin must export PLUGIN_META (dict) and execute(**kwargs) (function).
"""
import importlib
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

PLUGINS_DIR = Path(__file__).parent.parent / "plugins"

_REQUIRED_META_KEYS = {"name", "description", "platform", "agent_types", "params"}


@dataclass
class PluginInfo:
    name: str
    description: str
    platform: str
    category: str
    agent_types: list[str]
    requires_plan: bool
    params: dict
    execute: Callable
    module_path: str
    errors: list[str] = field(default_factory=list)


_plugins: list[PluginInfo] = []
_plugin_map: dict[str, PluginInfo] = {}


def scan_plugins(path: str = "") -> list[PluginInfo]:
    """Scan plugins directory, validate contract, return list of PluginInfo.

    Each .py file must export PLUGIN_META (dict) and execute(**kwargs).
    Invalid plugins are logged as warnings but don't crash the agent.
    """
    global _plugins, _plugin_map
    plugins_dir = Path(path) if path else PLUGINS_DIR
    if not plugins_dir.is_dir():
        log.debug("Plugins directory not found: %s", plugins_dir)
        return []

    project_root = str(plugins_dir.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    loaded = []
    for py_file in sorted(plugins_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue

        module_name = f"plugins.{py_file.stem}"
        try:
            # Reload if already imported (hot-reload on rescan)
            if module_name in sys.modules:
                mod = importlib.reload(sys.modules[module_name])
            else:
                mod = importlib.import_module(module_name)
        except Exception as e:
            log.warning("Plugin %s failed to import: %s", py_file.name, e)
            continue

        # Validate PLUGIN_META
        meta = getattr(mod, "PLUGIN_META", None)
        if not isinstance(meta, dict):
            log.warning("Plugin %s: missing PLUGIN_META dict", py_file.name)
            continue

        missing = _REQUIRED_META_KEYS - set(meta.keys())
        if missing:
            log.warning("Plugin %s: PLUGIN_META missing keys: %s", py_file.name, missing)
            continue

        # Validate execute()
        execute_fn = getattr(mod, "execute", None)
        if not callable(execute_fn):
            log.warning("Plugin %s: missing execute() function", py_file.name)
            continue

        info = PluginInfo(
            name=meta["name"],
            description=meta["description"],
            platform=meta.get("platform", ""),
            category=meta.get("category", "general"),
            agent_types=meta.get("agent_types", ["investigate"]),
            requires_plan=meta.get("requires_plan", False),
            params=meta.get("params", {}),
            execute=execute_fn,
            module_path=str(py_file),
        )
        loaded.append(info)
        log.info("Plugin loaded: %s (platform=%s, agents=%s)",
                 info.name, info.platform, info.agent_types)

    _plugins = loaded
    _plugin_map = {p.name: p for p in loaded}
    log.info("Plugins: %d loaded from %s", len(loaded), plugins_dir)
    return loaded


def get_plugins() -> list[PluginInfo]:
    """Return cached plugin list (call scan_plugins first)."""
    return _plugins


def get_plugin(name: str) -> PluginInfo | None:
    """Look up a plugin by name."""
    return _plugin_map.get(name)


def invoke_plugin(name: str, params: dict[str, Any]) -> dict:
    """Execute a plugin by name. Returns _err if not found."""
    plugin = _plugin_map.get(name)
    if not plugin:
        return {"status": "error", "data": None, "timestamp": "",
                "message": f"Plugin '{name}' not found"}
    try:
        return plugin.execute(**params)
    except Exception as e:
        return {"status": "error", "data": None, "timestamp": "",
                "message": f"Plugin '{name}' error: {e}"}
