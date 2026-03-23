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

    # Save to generated skills directory (persisted via data volume)
    os.makedirs(loader.GENERATED_DIR, exist_ok=True)
    dest = os.path.join(loader.GENERATED_DIR, f"{name}.py")
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


# ── v2: Service catalog, compat, knowledge tools ──────────────────────────────

def service_catalog_list() -> dict:
    """List all known infrastructure services."""
    services = registry.list_services()
    return _ok({"services": services, "count": len(services)},
               f"{len(services)} service(s) in catalog")


def service_catalog_update(
    service_id: str,
    detected_version: str = "",
    known_latest: str = "",
    notes: str = "",
) -> dict:
    """Update a service's version info in the catalog."""
    kwargs = {}
    if detected_version:
        kwargs["detected_version"] = detected_version
        kwargs["version_source"] = "manual"
    if known_latest:
        kwargs["known_latest"] = known_latest
    if notes:
        kwargs["notes"] = notes

    existing = registry.get_service(service_id)
    if existing:
        result = registry.upsert_service(service_id, existing.get("display_name", service_id), **kwargs)
    else:
        result = registry.upsert_service(
            service_id,
            service_id.replace("_", " ").title(),
            **kwargs
        )

    orchestration.audit_log("service_catalog_update", {"service_id": service_id, **kwargs})
    return _ok(result, f"Service '{service_id}' updated")


def skill_compat_check(name: str) -> dict:
    """Check compatibility of a single skill with detected service version."""
    from mcp_server.tools.skills import knowledge_base
    result = knowledge_base.check_skill_compatibility(name)
    return _ok(result, f"Compat check complete for '{name}'")


def skill_compat_check_all() -> dict:
    """Compat check all enabled skills."""
    from mcp_server.tools.skills import knowledge_base
    result = knowledge_base.check_all_skills_compatibility()
    s = result["summary"]
    msg = (f"Compat check complete: {s['compatible']} compatible, "
           f"{s['incompatible']} incompatible, {s['warning']} warnings, "
           f"{s['unknown']} unknown")
    orchestration.audit_log("skill_compat_check_all", result["summary"])
    return _ok(result, msg)


def skill_health_summary() -> dict:
    """Full skill system health dashboard."""
    from mcp_server.tools.skills import knowledge_base
    result = knowledge_base.get_skill_health_summary()
    return _ok(result, f"Health summary: {result['enabled']}/{result['total_skills']} skills enabled")


def knowledge_ingest_changelog(
    service_id: str,
    content: str = "",
    from_version: str = "",
    to_version: str = "",
) -> dict:
    """Parse ingested changelog/release notes to extract breaking changes."""
    from mcp_server.tools.skills import knowledge_base
    result = knowledge_base.parse_changelog_for_breaking_changes(
        service_id=service_id,
        content=content,
        from_version=from_version,
        to_version=to_version,
    )
    if result.get("status") == "ok":
        n = result.get("changes_found", 0)
        orchestration.audit_log("knowledge_ingest_changelog",
                                {"service_id": service_id, "changes_found": n})
        return _ok(result, f"Extracted {n} breaking change(s) for '{service_id}'")
    return _err(result.get("message", "Changelog analysis failed"), data=result)


def knowledge_export_request(service_id: str, request_type: str = "changelog") -> dict:
    """Export a structured request for documentation gathering (airgapped workflow)."""
    from mcp_server.tools.skills import knowledge_base
    result = knowledge_base.build_knowledge_export_request(service_id, request_type)
    if result.get("status") == "ok":
        return _ok(result,
                   f"Knowledge request saved to {result['filename']}. "
                   f"Take this file to a machine with internet access and follow the instructions.")
    return _err("Failed to create knowledge export request")


def skill_recommend_updates(service_id: str = "") -> dict:
    """List skills that need updating based on breaking changes and version drift."""
    from mcp_server.tools.skills import knowledge_base
    result = knowledge_base.recommend_skill_updates(service_id)
    return _ok(result, f"{result['count']} skill(s) need attention")


# ── v3: Environment discovery, skill dispatcher, live validation ──────────────

def discover_environment(hosts: list) -> dict:
    """Run 4-phase environment discovery pipeline on a list of hosts.

    Each host: {"address": "192.168.1.1"} or {"address": "...", "port": 443}
    """
    from mcp_server.tools.skills import discovery
    result = discovery.discover_environment(hosts)
    if result.get("status") == "ok":
        data = result["data"]
        orchestration.audit_log("discover_environment", {
            "hosts_probed": data["summary"]["hosts_probed"],
            "identified": data["summary"]["identified"],
            "recommendations": len(data.get("skill_recommendations", [])),
        })
    return result


def skill_execute(name: str, **kwargs) -> dict:
    """Execute a dynamic skill by name. Call skill_search() first to find skills."""
    return loader.dispatch_skill(name, **kwargs)


def validate_skill_live(name: str) -> dict:
    """Run 3-layer validation on a loaded skill (deterministic + live probe + LLM critic)."""
    from mcp_server.tools.skills import live_validator
    result = live_validator.validate_skill_live(name)
    orchestration.audit_log("validate_skill_live", {
        "name": name,
        "overall_valid": result.get("data", {}).get("overall_valid"),
    })
    return result


def skill_regenerate(mcp_server, name: str, backend: str = "") -> dict:
    """Regenerate a skill, backing up the old version first."""
    skill = registry.get_skill(name)
    if not skill:
        return _err(f"Skill '{name}' not found")

    # Back up old file
    import shutil as _shutil
    # Always regenerate into persistent dir
    _in_modules = os.path.join(os.path.dirname(loader.__file__), "modules", f"{name}.py")
    _in_generated = os.path.join(loader.GENERATED_DIR, f"{name}.py")
    os.makedirs(loader.GENERATED_DIR, exist_ok=True)
    skill_dir = loader.GENERATED_DIR
    old_path = os.path.join(skill_dir, f"{name}.py")
    bak_path = os.path.join(skill_dir, f"{name}.py.bak")

    # Source file for backup: prefer GENERATED_DIR copy, fall back to modules/ copy
    _source_path = _in_generated if os.path.exists(_in_generated) else _in_modules
    # If source is different from old_path (starter skill first regen), copy it first
    if _source_path != old_path and os.path.exists(_source_path):
        _shutil.copy2(_source_path, old_path)

    if os.path.exists(old_path):
        _shutil.copy2(old_path, bak_path)

    # Get description from skill registry
    description = skill.get("description", name)
    category = skill.get("category", "general")
    auth_type = skill.get("auth_type", "none")

    result = skill_create(mcp_server, description, category, "", auth_type, backend)

    if result.get("status") == "ok":
        orchestration.audit_log("skill_regenerate", {"name": name, "backed_up_to": bak_path})
        result_data = result.get("data", {})
        result_data["backed_up_old_version"] = bak_path
        return _ok(result_data, f"Skill '{name}' regenerated. Old version backed up.")

    # Restore backup on failure
    if os.path.exists(bak_path) and not os.path.exists(old_path):
        _shutil.copy2(bak_path, old_path)

    return result
