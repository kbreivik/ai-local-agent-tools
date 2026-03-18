"""Dynamic skill loading via importlib.util — no eval/exec."""
import importlib.util
import logging
import os
import shutil
from datetime import datetime, timezone

from mcp_server.tools.skills import registry, validator


log = logging.getLogger(__name__)

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
            return module.execute(**kwargs)
        except Exception as e:
            registry.record_error(skill_name, str(e))
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
    """Load one skill by name from the modules directory."""
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
        mcp_server.tool(name=name)(handler)

        meta = module.SKILL_META
        registry.register_skill(meta, filepath)

        log.info("Loaded skill: %s", name)
        return {"loaded": True, "name": name}

    except Exception as e:
        log.error("Failed to load skill %s: %s", name, e)
        return {"loaded": False, "name": name, "error": str(e)}


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
