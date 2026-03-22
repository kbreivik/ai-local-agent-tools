"""
Shim that exposes skill meta-tools to tool_registry.py.

tool_registry.py scans mcp_server/tools/*.py (top-level only).
The real implementations live in mcp_server/tools/skills/meta_tools.py.
This file wraps every public function so they are auto-discovered.

Functions that take mcp_server as first arg receive None — loader.py
documents that parameter as unused ("kept for API compatibility").
"""
import json

from mcp_server.tools.skills import meta_tools as _mt


# ── Read-only skill tools ─────────────────────────────────────────────────────

def skill_search(query: str, category: str = "") -> dict:
    """Search for dynamic skills by keyword. Call before skill_create to avoid duplicates."""
    return _mt.skill_search(query, category)


def skill_list(category: str = "", enabled_only: bool = True) -> dict:
    """List all dynamic skills. Categories: monitoring, networking, storage, compute, general."""
    return _mt.skill_list(category, enabled_only)


def skill_info(name: str) -> dict:
    """Get full details about a dynamic skill: parameters, call count, error rate, generation backend."""
    return _mt.skill_info(name)


def skill_generation_config() -> dict:
    """Show current skill generation config: backend, model, LM Studio URL."""
    return _mt.skill_generation_config()


def skill_health_summary() -> dict:
    """Full skill system health: compat status, error rates, stale checks, actions needed."""
    return _mt.skill_health_summary()


def skill_compat_check(name: str) -> dict:
    """Check if a skill is compatible with the current detected service version."""
    return _mt.skill_compat_check(name)


def skill_compat_check_all() -> dict:
    """Compat-check all enabled skills. Run after any infrastructure upgrade."""
    return _mt.skill_compat_check_all()


def skill_recommend_updates(service_id: str = "") -> dict:
    """List skills that need updating based on breaking changes and version drift."""
    return _mt.skill_recommend_updates(service_id)


def validate_skill_live(name: str) -> dict:
    """Run 3-layer validation on a skill: AST checks, live endpoint probe, LLM critic review."""
    return _mt.validate_skill_live(name)


# ── Mutating skill tools ──────────────────────────────────────────────────────

def skill_create(
    description: str,
    service: str = "",
    backend: str = "local",
) -> dict:
    """Generate and load a new skill from a description. Call skill_search FIRST to avoid duplicates.

    Args:
        description: What the skill should do. Include the service name, API/protocol type,
            authentication method, and what data to return.
            Example: 'Check Proxmox VM status via REST API using token auth'.
        service: Skill category hint. One of: monitoring, networking, storage, compute, general.
        backend: Generation backend. 'local' uses LM Studio, 'cloud' uses Anthropic API,
            'export' writes a prompt file for airgapped environments.
    """
    return _mt.skill_create(None, description, category=service or "general", backend=backend)


def skill_disable(name: str) -> dict:
    """Disable a broken dynamic skill so it stops being offered to the LLM."""
    return _mt.skill_disable(name)


def skill_enable(name: str) -> dict:
    """Re-enable a previously disabled dynamic skill."""
    return _mt.skill_enable(name)


def skill_import() -> dict:
    """Scan data/skill_imports/ for .py skill files and load them (sneakernet workflow)."""
    return _mt.skill_import(None)


def skill_export_prompt(
    description: str,
    category: str = "general",
    api_base: str = "",
    auth_type: str = "none",
) -> dict:
    """Save a self-contained skill generation prompt to data/skill_exports/ for airgapped use."""
    return _mt.skill_export_prompt(description, category, api_base, auth_type)


def skill_regenerate(name: str, backend: str = "") -> dict:
    """Regenerate a skill using current docs and version info. Backs up the old version."""
    return _mt.skill_regenerate(None, name, backend)


# ── Service catalog / knowledge tools ────────────────────────────────────────

def service_catalog_list() -> dict:
    """List all known infrastructure services with detected versions and doc coverage."""
    return _mt.service_catalog_list()


def service_catalog_update(
    service_id: str,
    detected_version: str = "",
    known_latest: str = "",
    notes: str = "",
) -> dict:
    """Update a service's version info in the catalog after a firmware upgrade or discovery."""
    return _mt.service_catalog_update(service_id, detected_version, known_latest, notes)


def knowledge_ingest_changelog(
    service_id: str,
    content: str = "",
    from_version: str = "",
    to_version: str = "",
) -> dict:
    """Parse a changelog or release notes to detect breaking changes affecting skills."""
    return _mt.knowledge_ingest_changelog(service_id, content, from_version, to_version)


def knowledge_export_request(service_id: str, request_type: str = "changelog") -> dict:
    """Export a structured documentation request for airgapped environments."""
    return _mt.knowledge_export_request(service_id, request_type)


# ── Discovery + execution ─────────────────────────────────────────────────────

def discover_environment(hosts: list) -> dict:
    """Scan hosts and auto-identify services via deterministic fingerprinting.
    Each host: {"address": "192.168.1.1"} or {"address": "...", "port": 8006}.
    Returns identified services, skill coverage gaps, and skill_create recommendations."""
    return _mt.discover_environment(hosts)


def skill_execute(name: str, kwargs_json: str = "") -> dict:
    """Execute a dynamic skill by name. Call skill_search first to find available skills.
    Pass skill parameters as a JSON object string in kwargs_json.
    Example: skill_execute(name='proxmox_vm_status', kwargs_json='{"node": "pve1"}')"""
    kwargs = {}
    if kwargs_json:
        try:
            kwargs = json.loads(kwargs_json)
        except (json.JSONDecodeError, ValueError):
            pass
    return _mt.skill_execute(name, **kwargs)
