"""Agent-facing skill management tools."""
import os
from datetime import datetime, timezone

from mcp_server.tools.skills import registry, generator, loader
from mcp_server.tools import orchestration


def _ts():
    return datetime.now(timezone.utc).isoformat()


def _ok(data, message="OK"):
    return {"status": "ok", "data": data, "timestamp": _ts(), "message": message}


def _err(message, data=None):
    return {"status": "error", "data": data, "timestamp": _ts(), "message": message}


def skill_search(query: str, category: str = "") -> dict:
    """Search for skills by keyword."""
    skills = registry.search_skills(query, category)
    return _ok({"skills": skills, "count": len(skills)},
               f"Found {len(skills)} skill(s) matching '{query}'")


def skill_list(category: str = "", enabled_only: bool = True) -> dict:
    """List all registered skills."""
    skills = registry.list_skills(category, enabled_only)
    return _ok({"skills": skills, "count": len(skills)},
               f"{len(skills)} skill(s) registered")


def skill_info(name: str) -> dict:
    """Get full details about a skill."""
    skill = registry.get_skill(name)
    if not skill:
        return _err(f"Skill '{name}' not found")
    return _ok(skill, f"Skill '{name}' details")


def skill_create(
    mcp_server,
    description: str,
    category: str = "general",
    api_base: str = "",
    auth_type: str = "none",
    backend: str = "",
) -> dict:
    """Generate, validate, save, and load a new skill."""
    result = generator.generate_skill(
        description=description,
        category=category,
        api_base=api_base,
        auth_type=auth_type,
        backend=backend,
    )

    if result.get("status") != "ok":
        return result

    data = result.get("data", {})

    # Export path — no "code" key, just return the export info
    if "code" not in data:
        return _ok(data, result.get("message", "Export saved. Follow instructions in the file."))

    code = data["code"]
    name = data["name"]
    backend_used = data.get("backend_used", "unknown")

    # Save to modules directory
    dest = os.path.join(os.path.dirname(loader.__file__), "modules", f"{name}.py")
    with open(dest, "w", encoding="utf-8") as f:
        f.write(code)

    # Load into MCP server
    load_result = loader.load_single_skill(mcp_server, name)
    if not load_result.get("loaded"):
        return _err(
            f"Skill '{name}' generated but failed to load: {load_result.get('error')}",
            data={"code": code, "name": name},
        )

    # Audit log
    orchestration.audit_log(
        "skill_create",
        {"name": name, "backend": backend_used, "description": description[:100]},
    )

    return _ok({
        "name": name,
        "backend_used": backend_used,
        "file_path": dest,
    }, f"Skill '{name}' created and loaded via {backend_used}")


def skill_import(mcp_server) -> dict:
    """Scan data/skill_imports/ for .py skill files and load them."""
    result = loader.scan_imports(mcp_server)
    orchestration.audit_log("skill_import", result)
    imported = result.get("imported", [])
    failed = result.get("failed", [])
    return _ok(result,
               f"Import complete: {len(imported)} loaded, {len(failed)} failed")


def skill_disable(name: str) -> dict:
    """Disable a skill."""
    result = registry.disable_skill(name)
    orchestration.audit_log("skill_disable", {"name": name})
    return _ok(result, f"Skill '{name}' disabled")


def skill_enable(name: str) -> dict:
    """Enable a skill."""
    result = registry.enable_skill(name)
    orchestration.audit_log("skill_enable", {"name": name})
    return _ok(result, f"Skill '{name}' enabled")


def skill_export_prompt(
    description: str,
    category: str = "general",
    api_base: str = "",
    auth_type: str = "none",
) -> dict:
    """Save a self-contained skill generation prompt for offline use."""
    # Get existing skill names for collision avoidance
    existing_names = [s["name"] for s in registry.list_skills(enabled_only=False)]

    doc = generator.prompt_builder.build_export_document(
        description=description,
        category=category,
        api_base=api_base,
        auth_type=auth_type,
        existing_skills=existing_names,
    )

    result = generator._generate_export(doc, description)
    return result


def skill_generation_config() -> dict:
    """Show current skill generation configuration."""
    cfg = generator._get_backend_config()
    # Redact API keys
    if cfg.get("anthropic_api_key"):
        cfg["anthropic_api_key"] = cfg["anthropic_api_key"][:8] + "..."
    if cfg.get("lm_studio_api_key") and cfg["lm_studio_api_key"] != "lm-studio":
        cfg["lm_studio_api_key"] = cfg["lm_studio_api_key"][:8] + "..."
    return _ok(cfg, "Skill generation config")
