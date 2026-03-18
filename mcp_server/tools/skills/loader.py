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

_MODULES_DIR = os.path.join(os.path.dirname(__file__), "modules")
_IMPORTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "data", "skill_imports"
)
_IMPORTS_PROCESSED_DIR = os.path.join(_IMPORTS_DIR, "processed")


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
        return {"loaded": False, "name": name, "error": f"File not found: {filepath}"}

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

        log.info("Loaded skill: %s", name)
        return {"loaded": True, "name": name}

    except Exception as e:
        log.error("Failed to load skill %s: %s", name, e)
        return {"loaded": False, "name": name, "error": str(e)}


def dispatch_skill(name: str, **kwargs) -> dict:
    """Execute a loaded skill by name. Called by the skill_execute MCP tool."""
    handler = _SKILL_HANDLERS.get(name)
    if not handler:
        # Check if skill exists but wasn't loaded
        skill = registry.get_skill(name)
        if skill and not skill.get("enabled", True):
            return {
                "status": "error", "data": None,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "message": f"Skill '{name}' is disabled. Use skill_enable('{name}') to re-enable.",
            }
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
    """Scan modules/ for skill files, load each, register in DB. Returns summary."""
    loaded = []
    failed = []

    if not os.path.isdir(_MODULES_DIR):
        return {"loaded": loaded, "failed": failed, "total": 0}

    for fname in sorted(os.listdir(_MODULES_DIR)):
        if not fname.endswith(".py"):
            continue
        if fname.startswith("__") or fname.startswith("_template"):
            continue

        name = fname[:-3]  # strip .py
        result = load_single_skill(mcp_server, name)
        if result.get("loaded"):
            loaded.append(name)
        else:
            failed.append({"name": name, "error": result.get("error", "unknown")})

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
