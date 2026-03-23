"""Dynamic skill loading via importlib.util — no eval/exec.

Skills are loaded into _SKILL_HANDLERS dict and dispatched via skill_execute().
Individual skills are NOT registered as separate MCP tools — one dispatcher handles all.
"""
import importlib.util
import logging
import os
import shutil
from datetime import datetime, timezone

from mcp_server.tools.skills import registry, validator


log = logging.getLogger(__name__)

# Single dispatcher registry: skill name → callable handler
_SKILL_HANDLERS: dict = {}

# Known services for auto-seeding the service catalog when starter skills load
_KNOWN_SERVICES: dict = {
    "proxmox":       {"display_name": "Proxmox VE",        "service_type": "hypervisor"},
    "fortigate":     {"display_name": "FortiGate Firewall", "service_type": "firewall"},
    "fortiswitch":   {"display_name": "FortiSwitch",        "service_type": "switch"},
    "truenas":       {"display_name": "TrueNAS SCALE",      "service_type": "storage"},
    "docker":        {"display_name": "Docker Engine",      "service_type": "container_runtime"},
    "elasticsearch": {"display_name": "Elasticsearch",      "service_type": "search"},
}


def _seed_service(service_id: str) -> None:
    """Upsert a service into the catalog with known display name / type (no-op if already present)."""
    known = _KNOWN_SERVICES.get(service_id, {})
    display_name = known.get("display_name", service_id.replace("_", " ").title())
    service_type = known.get("service_type", "")
    try:
        registry.upsert_service(service_id, display_name, service_type=service_type)
    except Exception as e:
        log.debug("Service catalog seed failed for %s: %s", service_id, e)

_MODULES_DIR = os.path.join(os.path.dirname(__file__), "modules")
_IMPORTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "data", "skill_imports"
)
_IMPORTS_PROCESSED_DIR = os.path.join(_IMPORTS_DIR, "processed")

# Public constant — imported by meta_tools and tests
GENERATED_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "data", "skill_modules"
)


def _make_tool_handler(module, skill_name: str):
    """Create a tool handler function wrapping a skill's execute()."""
    def handler(**kwargs) -> dict:
        try:
            registry.increment_call(skill_name)
            result = module.execute(**kwargs)

            # Passive version tracking and error-based compat detection
            try:
                from mcp_server.tools.skills import knowledge_base
                if isinstance(result, dict):
                    if result.get("status") == "ok" and result.get("data"):
                        knowledge_base.detect_version_from_skill_result(skill_name, result)
                    elif result.get("status") == "error" and result.get("message"):
                        registry.record_error(skill_name, result["message"])
                        compat_issue = knowledge_base.analyze_skill_errors_for_compat(
                            skill_name, result["message"])
                        if compat_issue:
                            result["data"] = result.get("data") or {}
                            result["data"]["compat_warning"] = compat_issue
                            result["message"] = (
                                result["message"]
                                + f" [COMPAT WARNING: This may be caused by a version change in "
                                f"{compat_issue.get('service_id', 'the service')}. "
                                f"Run skill_compat_check('{skill_name}') for details.]"
                            )
            except Exception:
                pass

            return result
        except Exception as e:
            error_str = str(e)
            registry.record_error(skill_name, error_str)

            try:
                from mcp_server.tools.skills import knowledge_base
                knowledge_base.analyze_skill_errors_for_compat(skill_name, error_str)
            except Exception:
                pass

            return {
                "status": "error", "data": None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "message": f"Skill '{skill_name}' error: {e}"
            }
    handler.__name__ = skill_name
    handler.__doc__ = module.SKILL_META["description"]
    return handler


def _load_module_from_file(filepath: str, module_name: str):
    """Load a Python module from a file path using importlib.util."""
    spec = importlib.util.spec_from_file_location(module_name, filepath)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot create module spec for {filepath}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_single_skill(mcp_server, name: str) -> dict:
    """Load one skill by name from the modules directory.

    Stores handler in _SKILL_HANDLERS for dispatch via skill_execute().
    Does NOT register individual MCP tools — the single dispatcher handles all skills.
    mcp_server parameter is kept for API compatibility but no longer used for per-skill registration.
    """
    filepath = os.path.join(_MODULES_DIR, f"{name}.py")
    if not os.path.exists(filepath):
        filepath = os.path.join(GENERATED_DIR, f"{name}.py")
    if not os.path.exists(filepath):
        return {"loaded": False, "name": name, "error": f"File not found in modules/ or GENERATED_DIR"}

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            code = f.read()

        result = validator.validate_skill_code(code)
        if not result["valid"]:
            return {"loaded": False, "name": name, "error": result["error"]}

        module = _load_module_from_file(filepath, f"skill_{name}")
        handler = _make_tool_handler(module, name)

        # Store in dispatcher registry (not registered as individual MCP tool)
        _SKILL_HANDLERS[name] = handler

        meta = module.SKILL_META
        registry.register_skill(meta, filepath)

        # Seed service catalog from SKILL_META.compat.service
        service_id = meta.get("compat", {}).get("service", "")
        if service_id:
            _seed_service(service_id)

        log.info("Loaded skill: %s", name)
        return {"loaded": True, "name": name}

    except Exception as e:
        log.error("Failed to load skill %s: %s", name, e)
        return {"loaded": False, "name": name, "error": str(e)}


def dispatch_skill(name: str, **kwargs) -> dict:
    """Execute a loaded skill by name. Called by the skill_execute MCP tool."""
    handler = _SKILL_HANDLERS.get(name)
    if not handler:
        # Skill not in memory — check DB for state and try lazy load from disk
        skill = registry.get_skill(name)
        if skill:
            if not skill.get("enabled", True):
                return {
                    "status": "error", "data": None,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "message": f"Skill '{name}' is disabled. Use skill_enable('{name}') to re-enable.",
                }
            # Skill is enabled in DB but not in memory — try lazy load from modules/
            load_result = load_single_skill(None, name)
            if load_result.get("loaded"):
                log.info("Lazy-loaded skill '%s' on first execute", name)
                handler = _SKILL_HANDLERS.get(name)
        if not handler:
            return {
                "status": "error", "data": None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "message": (
                    f"Skill '{name}' not found. "
                    "Use skill_search() to discover available skills, "
                    "or skill_create() to generate a new one."
                ),
            }
    return handler(**kwargs)


def list_loaded_skills() -> list:
    """Return names of all currently loaded skills."""
    return list(_SKILL_HANDLERS.keys())


def load_all_skills(mcp_server) -> dict:
    """Scan modules/ and data/skill_modules/ for skill files. Returns summary."""
    loaded = []
    failed = []

    for scan_dir in [_MODULES_DIR, GENERATED_DIR]:
        if not os.path.isdir(scan_dir):
            os.makedirs(scan_dir, exist_ok=True)
            continue

        for fname in sorted(os.listdir(scan_dir)):
            if not fname.endswith(".py"):
                continue
            if fname.startswith("__") or fname.startswith("_template"):
                continue

            name = fname[:-3]  # strip .py
            if name in _SKILL_HANDLERS:
                continue  # Already loaded from higher-priority dir

            # load_single_skill normally looks only in _MODULES_DIR — pass filepath directly
            filepath = os.path.join(scan_dir, fname)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    code = f.read()
                result = validator.validate_skill_code(code)
                if not result["valid"]:
                    failed.append({"name": name, "error": result["error"]})
                    continue
                module = _load_module_from_file(filepath, f"skill_{name}")
                handler = _make_tool_handler(module, name)
                _SKILL_HANDLERS[name] = handler
                meta = module.SKILL_META
                registry.register_skill(meta, filepath)
                service_id = meta.get("compat", {}).get("service", "")
                if service_id:
                    _seed_service(service_id)
                log.info("Loaded skill: %s (from %s)", name, scan_dir)
                loaded.append(name)
            except Exception as e:
                log.error("Failed to load skill %s: %s", name, e)
                failed.append({"name": name, "error": str(e)})

    log.info("Skill loader: %d loaded, %d failed", len(loaded), len(failed))
    return {"loaded": loaded, "failed": failed, "total": len(loaded) + len(failed)}


def scan_imports(mcp_server) -> dict:
    """Scan data/skill_imports/ for .py files, validate, load, register."""
    os.makedirs(_IMPORTS_DIR, exist_ok=True)
    os.makedirs(_IMPORTS_PROCESSED_DIR, exist_ok=True)

    imported = []
    failed = []

    for fname in os.listdir(_IMPORTS_DIR):
        if not fname.endswith(".py"):
            continue
        fpath = os.path.join(_IMPORTS_DIR, fname)
        if not os.path.isfile(fpath):
            continue

        try:
            with open(fpath, "r", encoding="utf-8") as f:
                code = f.read()

            result = validator.validate_skill_code(code)
            if not result["valid"]:
                log.error("Import validation failed for %s: %s", fname, result["error"])
                failed.append({"filename": fname, "error": result["error"]})
                continue

            skill_name = result["name"]
            dest = os.path.join(_MODULES_DIR, f"{skill_name}.py")
            shutil.copy2(fpath, dest)

            load_result = load_single_skill(mcp_server, skill_name)
            if not load_result.get("loaded"):
                failed.append({"filename": fname, "error": load_result.get("error", "unknown")})
                # Clean up copied file on failure
                if os.path.exists(dest):
                    os.remove(dest)
                continue

            # Update generation mode to sneakernet
            meta = result.get("meta", {"name": skill_name})
            registry.register_skill(meta, dest, auto_generated=False, generation_mode="sneakernet")

            # Move original to processed
            shutil.move(fpath, os.path.join(_IMPORTS_PROCESSED_DIR, fname))
            imported.append(skill_name)
            log.info("Imported skill via sneakernet: %s", skill_name)

        except Exception as e:
            log.error("Import error for %s: %s", fname, e)
            failed.append({"filename": fname, "error": str(e)})

    return {"imported": imported, "failed": failed, "total": len(imported) + len(failed)}
