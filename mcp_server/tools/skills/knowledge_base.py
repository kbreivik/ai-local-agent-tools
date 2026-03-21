"""
Knowledge & Compatibility layer — version tracking, compat checking, changelog parsing.
All functions are synchronous. No new packages.
"""
import json
import logging
import os
import re
from datetime import datetime, timezone

from mcp_server.tools.skills import registry

log = logging.getLogger(__name__)

_SETTINGS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "data", "agent_settings.json"
)
_EXPORTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "data", "skill_exports"
)

# Known vendor documentation URLs for common homelab services
VENDOR_DOCS = {
    "fortigate": {
        "changelog": "https://docs.fortinet.com/document/fortigate/{version}/fortios-release-notes/",
        "api_docs": "https://fndn.fortinet.net/index.php?/fortiapi/",
        "upgrade_guide": "https://docs.fortinet.com/document/fortigate/{version}/upgrade-guide/",
    },
    "fortiswitch": {
        "changelog": "https://docs.fortinet.com/document/fortiswitch/{version}/fortiswitchos-release-notes/",
        "api_docs": "https://docs.fortinet.com/document/fortiswitch/{version}/administration-guide/",
    },
    "proxmox": {
        "changelog": "https://pve.proxmox.com/wiki/Roadmap",
        "api_docs": "https://pve.proxmox.com/pve-docs/api-viewer/",
        "upgrade_guide": "https://pve.proxmox.com/wiki/Upgrade_from_{from_version}_to_{to_version}",
    },
    "truenas": {
        "api_docs": "https://www.truenas.com/docs/api/scale_rest_api.html",
        "changelog": "https://www.truenas.com/docs/scale/scalereleasenotes/",
    },
    "docker": {
        "changelog": "https://docs.docker.com/engine/release-notes/",
        "api_docs": "https://docs.docker.com/engine/api/v{version}/",
    },
    "elasticsearch": {
        "changelog": "https://www.elastic.co/guide/en/elasticsearch/reference/current/release-notes.html",
        "api_docs": "https://www.elastic.co/guide/en/elasticsearch/reference/current/rest-apis.html",
    },
}


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compare_versions(v1: str, v2: str) -> int:
    """Compare two version strings. Returns -1, 0, or 1."""
    def _parse(v):
        parts = re.split(r"[.\-]", v.strip())
        result = []
        for p in parts[:4]:
            try:
                result.append(int(p))
            except ValueError:
                result.append(0)
        while len(result) < 4:
            result.append(0)
        return result

    p1, p2 = _parse(v1), _parse(v2)
    if p1 < p2:
        return -1
    if p1 > p2:
        return 1
    return 0


def detect_version_from_skill_result(skill_name: str, result: dict) -> str | None:
    """
    Extract detected_version from a skill's result dict.
    Updates service_catalog if a version is found.
    Called automatically by loader's tool wrapper after every skill execution.
    """
    if not isinstance(result, dict):
        return None

    data = result.get("data")
    if not isinstance(data, dict):
        return None

    version = data.get("detected_version")
    if not version or not isinstance(version, str):
        return None

    # Find the skill's service_id from SKILL_META.compat
    skill = registry.get_skill(skill_name)
    if not skill:
        return version

    # compat is stored as part of SKILL_META but not in the DB directly
    # We'll try to load it from the module file
    try:
        import importlib.util
        modules_dir = os.path.join(os.path.dirname(__file__), "modules")
        filepath = os.path.join(modules_dir, f"{skill_name}.py")
        if os.path.exists(filepath):
            spec = importlib.util.spec_from_file_location(f"skill_{skill_name}", filepath)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                compat = getattr(module, "SKILL_META", {}).get("compat", {})
                service_id = compat.get("service", "")
                if service_id:
                    registry.update_service_version(service_id, version, source="skill_probe")
                    log.debug("Updated service '%s' version to %s via skill '%s'",
                              service_id, version, skill_name)
    except Exception as e:
        log.debug("detect_version_from_skill_result error for %s: %s", skill_name, e)

    return version


def check_skill_compatibility(skill_name: str) -> dict:
    """
    Check if a skill is compatible with the currently detected service version.
    Returns dict with: compatible, detected_version, built_for, warnings, breaking_changes
    """
    try:
        import importlib.util
        modules_dir = os.path.join(os.path.dirname(__file__), "modules")
        filepath = os.path.join(modules_dir, f"{skill_name}.py")

        if not os.path.exists(filepath):
            return {"compatible": None, "error": f"Skill file not found: {skill_name}"}

        spec = importlib.util.spec_from_file_location(f"skill_{skill_name}_compat", filepath)
        if not spec or not spec.loader:
            return {"compatible": None, "error": "Cannot load skill module"}
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        meta = getattr(module, "SKILL_META", {})
        compat = meta.get("compat", {})
        service_id = compat.get("service", "")
        built_for = compat.get("api_version_built_for", "")
        min_ver = compat.get("min_version", "")
        max_ver = compat.get("max_version", "")

        if not service_id:
            return {
                "compatible": None,
                "skill": skill_name,
                "detected_version": None,
                "built_for": built_for,
                "warnings": ["No compat.service defined in SKILL_META"],
                "breaking_changes": [],
            }

        # Get detected version from catalog
        service = registry.get_service(service_id)
        detected = service.get("detected_version", "") if service else ""

        warnings = []
        compatible = True

        # Check via skill's check_compat() if available
        check_compat_fn = getattr(module, "check_compat", None)
        check_method = "bounds_check"
        if callable(check_compat_fn):
            try:
                compat_result = check_compat_fn()
                if isinstance(compat_result, dict):
                    compat_data = compat_result.get("data") or {}
                    if compat_data.get("compatible") is False:
                        compatible = False
                        warnings.append(compat_result.get("message", "check_compat returned incompatible"))
                    if compat_data.get("detected_version"):
                        detected = compat_data["detected_version"]
                        registry.update_service_version(service_id, detected, source="version_probe")
                check_method = "version_probe"
            except Exception as e:
                warnings.append(f"check_compat() failed: {e}")

        # Version bounds check
        if detected and min_ver:
            if _compare_versions(detected, min_ver) < 0:
                compatible = False
                warnings.append(f"Detected version {detected} is below min_version {min_ver}")

        if detected and max_ver:
            if _compare_versions(detected, max_ver) > 0:
                compatible = False
                warnings.append(f"Detected version {detected} exceeds max_version {max_ver}")

        # Major version drift warning
        if detected and built_for:
            d_major = detected.split(".")[0]
            b_major = built_for.split(".")[0]
            if d_major != b_major:
                warnings.append(
                    f"Major version drift: built for {built_for}, detected {detected}"
                )
                if compatible:
                    compatible = None  # Unknown — warn but don't break

        # Check breaking changes table
        bc_list = registry.get_breaking_changes(service_id)
        relevant_bc = []
        for bc in bc_list:
            affected = bc.get("affected_skills", [])
            if skill_name in affected or not affected:
                # Only include if it's between built_for and detected
                relevant_bc.append({
                    "id": bc["id"],
                    "to_version": bc["to_version"],
                    "severity": bc["severity"],
                    "description": bc["description"],
                    "remediation": bc.get("remediation", ""),
                })
                if bc["severity"] == "breaking":
                    compatible = False

        # Log the check
        registry.log_compat_check(
            skill_name=skill_name,
            service_id=service_id,
            detected_version=detected,
            compatible=compatible,
            built_for_version=built_for,
            check_method=check_method,
            details="; ".join(warnings) if warnings else "OK",
        )

        return {
            "compatible": compatible,
            "skill": skill_name,
            "service_id": service_id,
            "detected_version": detected or None,
            "built_for": built_for,
            "warnings": warnings,
            "breaking_changes": relevant_bc,
        }

    except Exception as e:
        log.error("check_skill_compatibility error for %s: %s", skill_name, e)
        return {"compatible": None, "skill": skill_name, "error": str(e)}


def check_all_skills_compatibility() -> dict:
    """Run check_skill_compatibility for all enabled skills. Return summary."""
    skills = registry.list_skills(enabled_only=True)
    results = []
    summary = {"compatible": 0, "warning": 0, "incompatible": 0, "unknown": 0}

    for skill in skills:
        r = check_skill_compatibility(skill["name"])
        results.append(r)
        c = r.get("compatible")
        if c is True:
            summary["compatible"] += 1
        elif c is False:
            summary["incompatible"] += 1
        elif c is None and not r.get("error"):
            summary["warning"] += 1
        else:
            summary["unknown"] += 1

    return {"summary": summary, "skills": results, "total": len(results)}


def analyze_skill_errors_for_compat(skill_name: str, error: str) -> dict | None:
    """
    Called when a skill returns _err(). Pattern-match for version compat issues.
    If a pattern matches, auto-creates a breaking_change entry. Returns it or None.
    """
    if not error:
        return None

    # Load service_id from skill meta
    service_id = ""
    try:
        import importlib.util
        modules_dir = os.path.join(os.path.dirname(__file__), "modules")
        filepath = os.path.join(modules_dir, f"{skill_name}.py")
        if os.path.exists(filepath):
            spec = importlib.util.spec_from_file_location(f"skill_{skill_name}_err", filepath)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                service_id = getattr(module, "SKILL_META", {}).get("compat", {}).get("service", "")
    except Exception:
        pass

    if not service_id:
        return None

    # Pattern matching
    severity = "warning"
    description = None

    error_lower = error.lower()

    if "404" in error or "http 404" in error_lower or "not found" in error_lower:
        severity = "breaking"
        description = f"Skill '{skill_name}' got HTTP 404 — API endpoint may have been removed or renamed."
    elif "400" in error and ("deprecated" in error_lower or "unknown parameter" in error_lower):
        severity = "warning"
        description = f"Skill '{skill_name}' got HTTP 400 with deprecated/unknown parameter — API may have changed."
    elif ("401" in error or "403" in error) and "auth" in error_lower:
        severity = "warning"
        description = f"Skill '{skill_name}' got auth error — authentication scheme may have changed."
    elif "json" in error_lower and ("decode" in error_lower or "parse" in error_lower):
        severity = "warning"
        description = f"Skill '{skill_name}' got JSON parse error — response format may have changed."
    elif "command not found" in error_lower:
        severity = "breaking"
        description = f"Skill '{skill_name}' CLI command not found — may have been renamed in newer version."
    elif "connection refused" in error_lower:
        # Don't auto-flag connection refused — could be service down, not version issue
        return None

    if not description:
        return None

    # Get detected version from service catalog for context
    service = registry.get_service(service_id)
    to_version = service.get("detected_version", "unknown") if service else "unknown"

    bc = registry.add_breaking_change(
        service_id=service_id,
        to_version=to_version,
        description=description,
        severity=severity,
        affected_skills=[skill_name],
        source="error_detection",
    )

    log.warning("Auto-detected possible breaking change for %s (service: %s): %s",
                skill_name, service_id, description)
    return bc


def parse_changelog_for_breaking_changes(
    service_id: str,
    content: str = "",
    from_version: str = "",
    to_version: str = "",
) -> dict:
    """
    Parse changelog text to extract breaking changes using the local LLM.
    If content is empty, queries MuninnDB for ingested changelogs.
    Returns dict with extracted changes or an export prompt for offline use.
    """
    # If no content provided, try MuninnDB
    if not content:
        content = _fetch_changelog_from_muninndb(service_id, from_version, to_version)

    if not content:
        return {
            "status": "error",
            "message": (
                f"No changelog content found for '{service_id}'. "
                "Please ingest the changelog first: ingest_pdf() or ingest_url(), "
                "then call this function again."
            )
        }

    # Try local LLM
    cfg = _get_llm_config()
    if not cfg.get("base_url"):
        return _export_changelog_analysis(service_id, content, from_version, to_version)

    prompt = _build_changelog_prompt(service_id, content, from_version, to_version)

    try:
        import httpx
        resp = httpx.post(
            f"{cfg['base_url']}/chat/completions",
            json={
                "model": cfg.get("model") or "local",
                "temperature": 0.1,
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "Extract breaking changes as a JSON array now."},
                ],
            },
            headers={"Authorization": f"Bearer {cfg.get('api_key', 'lm-studio')}"},
            timeout=120.0,
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()
        # Try to extract JSON array
        changes = _parse_llm_changelog_response(raw)
    except Exception as e:
        log.warning("LLM changelog parsing failed: %s — falling back to export", e)
        return _export_changelog_analysis(service_id, content, from_version, to_version)

    # Store extracted changes
    stored = []
    for change in changes:
        try:
            bc = registry.add_breaking_change(
                service_id=service_id,
                to_version=change.get("to_version", to_version or "unknown"),
                description=change.get("description", ""),
                severity=change.get("severity", "warning"),
                affected_endpoints=change.get("affected_endpoints", []),
                remediation=change.get("remediation", ""),
                source="changelog",
                from_version=from_version,
            )
            # Cross-reference affected skills
            endpoints = change.get("affected_endpoints", [])
            if endpoints:
                _cross_reference_skills(service_id, bc["id"], endpoints)
            stored.append(bc)
        except Exception as e:
            log.error("Failed to store breaking change: %s", e)

    return {
        "status": "ok",
        "service_id": service_id,
        "changes_found": len(stored),
        "changes": stored,
    }


def get_skill_health_summary() -> dict:
    """High-level dashboard: compat status, error rates, stale skills."""
    skills = registry.list_skills(enabled_only=False)
    all_enabled = [s for s in skills if s["enabled"]]
    all_disabled = [s for s in skills if not s["enabled"]]
    services = registry.list_services()
    unresolved_bc = registry.get_unresolved_breaking_changes()

    # Compat status from recent compat log entries
    compat_summary = {"compatible": 0, "warning": 0, "incompatible": 0, "unknown": 0}
    error_skills = []

    for skill in all_enabled:
        history = registry.get_compat_history(skill["name"], limit=1)
        if history:
            c = history[0].get("compatible")
            if c == 1:
                compat_summary["compatible"] += 1
            elif c == 0:
                compat_summary["incompatible"] += 1
            else:
                compat_summary["warning"] += 1
        else:
            compat_summary["unknown"] += 1

        if skill.get("last_error") and skill.get("call_count", 0) > 0:
            error_skills.append({"name": skill["name"], "last_error": skill["last_error"]})

    return {
        "total_skills": len(skills),
        "enabled": len(all_enabled),
        "disabled": len(all_disabled),
        "compat_summary": compat_summary,
        "services_tracked": len(services),
        "unresolved_breaking_changes": len(unresolved_bc),
        "skills_with_errors": error_skills,
        "services": [
            {
                "id": s["service_id"],
                "display_name": s["display_name"],
                "detected_version": s.get("detected_version", ""),
                "known_latest": s.get("known_latest", ""),
            }
            for s in services
        ],
    }


# ── Internal helpers ────────────────────────────────────────────────────────────

def _get_llm_config() -> dict:
    """Load LM Studio config from agent_settings.json with env var overrides."""
    file_cfg = {}
    try:
        if os.path.exists(_SETTINGS_PATH):
            with open(_SETTINGS_PATH) as f:
                cfg = json.load(f)
                file_cfg = cfg.get("skill_generation", {}).get("local_llm", {})
    except Exception:
        pass
    return {
        "base_url": os.environ.get("LM_STUDIO_BASE_URL", file_cfg.get("base_url", "http://localhost:1234/v1")),
        "model": os.environ.get("LM_STUDIO_MODEL", file_cfg.get("model", "")),
        "api_key": os.environ.get("LM_STUDIO_API_KEY", file_cfg.get("api_key", "lm-studio")),
    }


def _fetch_changelog_from_muninndb(service_id: str, from_version: str, to_version: str) -> str:
    """Query MuninnDB for ingested changelog content."""
    try:
        import httpx
        api_port = os.environ.get("API_PORT", "8000")
        query = f"{service_id} changelog release notes {from_version} {to_version}".strip()
        resp = httpx.post(
            f"http://localhost:{api_port}/api/memory/activate",
            json={"query": query},
            timeout=10.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            engrams = data.get("engrams", data.get("activated", []))
            texts = [e.get("content", e.get("text", "")) for e in engrams if isinstance(e, dict)]
            combined = "\n\n".join(t for t in texts if t)
            return combined[:8000]  # Limit to 8KB
    except Exception:
        pass
    return ""


def _build_changelog_prompt(service_id: str, content: str, from_version: str, to_version: str) -> str:
    range_str = f"{from_version} → {to_version}" if from_version and to_version else to_version or from_version or "recent"
    return f"""You are a technical assistant analyzing {service_id} release notes / changelogs.
Extract ALL breaking changes between versions {range_str}.

A breaking change is anything that could cause existing API integrations or scripts to fail:
- Removed or renamed API endpoints/commands
- Changed request/response formats
- New required parameters
- Changed authentication methods
- Removed CLI commands or options
- Changed default behaviors

Output ONLY a JSON array. Each item must have these fields:
- "description": string — clear description of the change
- "to_version": string — version that introduced the change
- "severity": "breaking" | "warning" | "info"
- "affected_endpoints": array of strings — API paths or CLI commands affected
- "remediation": string — how to fix affected integrations

If no breaking changes found, output: []

Changelog content:
{content[:6000]}"""


def _parse_llm_changelog_response(raw: str) -> list:
    """Extract JSON array from LLM response."""
    # Strip markdown fences
    raw = re.sub(r"```(?:json)?\s*", "", raw)
    raw = re.sub(r"```\s*$", "", raw).strip()
    # Find JSON array
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except Exception:
            pass
    return []


def _cross_reference_skills(service_id: str, change_id: int, endpoints: list) -> None:
    """Find skills that use affected endpoints and update the breaking_change record."""
    affected = []
    try:
        modules_dir = os.path.join(os.path.dirname(__file__), "modules")
        for fname in os.listdir(modules_dir):
            if not fname.endswith(".py") or fname.startswith("_"):
                continue
            filepath = os.path.join(modules_dir, fname)
            with open(filepath, "r", encoding="utf-8") as f:
                source = f.read()
            for ep in endpoints:
                if ep in source:
                    skill_name = fname[:-3]
                    if skill_name not in affected:
                        affected.append(skill_name)
                    break
        if affected:
            registry.update_breaking_change_skills(change_id, affected)
    except Exception as e:
        log.debug("_cross_reference_skills error: %s", e)


def _export_changelog_analysis(service_id: str, content: str, from_version: str, to_version: str) -> dict:
    """Export a changelog analysis prompt for offline/sneakernet use."""
    os.makedirs(_EXPORTS_DIR, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"{service_id}_changelog_analysis_{ts}.md"
    filepath = os.path.join(_EXPORTS_DIR, filename)

    prompt = _build_changelog_prompt(service_id, content, from_version, to_version)

    doc = f"""# Changelog Analysis Request — {service_id.title()}
Generated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}

## Instructions
1. Copy everything below the separator line into an LLM (Claude, ChatGPT, etc.)
2. The LLM will output a JSON array of breaking changes
3. Save the JSON output as a .json file
4. Bring it back to the agent host
5. Tell the agent: "I have changelog analysis results for {service_id}" and paste the JSON

---

{prompt}
"""

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(doc)

    return {
        "status": "ok",
        "export_path": filepath,
        "filename": filename,
        "message": f"Changelog analysis prompt saved to {filename}. No local LLM available — use sneakernet workflow.",
    }


def build_knowledge_export_request(service_id: str, request_type: str = "changelog") -> dict:
    """
    Build and save a 'go fetch this document' request for airgapped environments.
    """
    os.makedirs(_EXPORTS_DIR, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"{service_id}_knowledge_request_{ts}.md"
    filepath = os.path.join(_EXPORTS_DIR, filename)

    vendor = VENDOR_DOCS.get(service_id, {})
    doc_url = vendor.get(request_type, vendor.get("api_docs", ""))

    # Find skills that use this service
    affected_skills = []
    try:
        import importlib.util
        modules_dir = os.path.join(os.path.dirname(__file__), "modules")
        for fname in os.listdir(modules_dir):
            if not fname.endswith(".py") or fname.startswith("_"):
                continue
            filepath_skill = os.path.join(modules_dir, fname)
            spec = importlib.util.spec_from_file_location(f"skill_probe_{fname}", filepath_skill)
            if spec and spec.loader:
                try:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    compat = getattr(module, "SKILL_META", {}).get("compat", {})
                    if compat.get("service") == service_id:
                        name = getattr(module, "SKILL_META", {}).get("name", fname[:-3])
                        version_endpoint = compat.get("version_endpoint", "")
                        affected_skills.append(f"  - {name}" + (f" (uses {version_endpoint})" if version_endpoint else ""))
                except Exception:
                    pass
    except Exception:
        pass

    service = registry.get_service(service_id)
    detected = service.get("detected_version", "") if service else ""
    known_latest = service.get("known_latest", "") if service else ""

    type_labels = {
        "changelog": "Release Notes / Changelog",
        "api_docs": "API Documentation",
        "upgrade_guide": "Upgrade Guide",
    }

    doc = f"""# Knowledge Request — {service_id.title()} {type_labels.get(request_type, request_type.title())}
Generated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}

## What We Need
{type_labels.get(request_type, request_type)} for {service_id.title()}
{"Current detected version: " + detected if detected else ""}
{"Known latest version: " + known_latest if known_latest else ""}

## Where to Find It
{("- " + doc_url) if doc_url else "- Check the vendor's official documentation site"}
{"".join(f"{chr(10)}- " + v for k, v in vendor.items() if k != request_type and v) if vendor else ""}

## Why We Need It
These skills may need updating:
{chr(10).join(affected_skills) if affected_skills else "  (no skills currently use this service)"}

## How to Bring It Back
**Option A** — Download the PDF:
1. Download the document on an internet-connected machine
2. Copy the PDF to: `data/docs/` on the agent host
3. Run: `ingest_pdf("{service_id}-{request_type}.pdf")`

**Option B** — Copy text content:
1. Copy the relevant section text
2. Save as a .txt file in `data/docs/`
3. Tell the agent to ingest it

After ingesting, run: `knowledge_ingest_changelog("{service_id}")`
to extract any breaking changes from the document.
"""

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(doc)

    return {
        "status": "ok",
        "export_path": filepath,
        "filename": filename,
        "service_id": service_id,
        "request_type": request_type,
        "doc_url": doc_url,
        "affected_skills": len(affected_skills),
    }


def recommend_skill_updates(service_id: str = "") -> dict:
    """
    Based on breaking_changes and compat log, return a prioritized list of
    skills needing regeneration. For each skill includes: why, built-for vs
    detected version, relevant doc snippets from MuninnDB, and whether
    auto-regeneration is feasible.
    """
    if service_id:
        bc_list = registry.get_breaking_changes(service_id)
    else:
        bc_list = registry.get_unresolved_breaking_changes()

    recommendations = []
    seen_skills: set = set()

    for bc in bc_list:
        for skill_name in bc.get("affected_skills", []):
            if skill_name in seen_skills:
                continue
            seen_skills.add(skill_name)

            skill = registry.get_skill(skill_name)
            if not skill:
                continue

            # Fetch relevant doc snippets from MuninnDB for context
            doc_snippets = []
            try:
                from mcp_server.tools.skills.doc_retrieval import fetch_relevant_docs
                result = fetch_relevant_docs(
                    skill.get("description", skill_name),
                    token_budget=500,
                )
                for doc in result.get("data", {}).get("context_docs", [])[:2]:
                    doc_snippets.append({
                        "concept": doc.get("concept", ""),
                        "excerpt": doc.get("content", "")[:300],
                    })
            except Exception:
                pass

            # Get built-for version from compat history
            history = registry.get_compat_history(skill_name, limit=1)
            built_for = history[0].get("built_for_version", "") if history else ""
            detected = history[0].get("detected_version", "") if history else ""

            recommendations.append({
                "skill": skill_name,
                "action": "NEEDS UPDATE" if bc["severity"] == "breaking" else "REVIEW",
                "reason": bc["description"],
                "breaking_change_id": bc["id"],
                "severity": bc["severity"],
                "remediation": bc.get("remediation", "Consider regenerating with current docs"),
                "built_for_version": built_for,
                "detected_version": detected,
                "can_auto_regenerate": bc["severity"] != "breaking" or bool(doc_snippets),
                "doc_snippets": doc_snippets,
            })

    # Also include skills with recent compat check failures
    skills = registry.list_skills(enabled_only=True)
    for skill in skills:
        if skill["name"] in seen_skills:
            continue
        history = registry.get_compat_history(skill["name"], limit=1)
        if history and history[0].get("compatible") == 0:
            seen_skills.add(skill["name"])
            recommendations.append({
                "skill": skill["name"],
                "action": "INCOMPATIBLE",
                "reason": history[0].get("details", "Compat check failed"),
                "breaking_change_id": None,
                "severity": "breaking",
                "remediation": f"Regenerate: skill_regenerate('{skill['name']}')",
                "built_for_version": history[0].get("built_for_version", ""),
                "detected_version": history[0].get("detected_version", ""),
                "can_auto_regenerate": True,
                "doc_snippets": [],
            })

    return {"recommendations": recommendations, "count": len(recommendations)}
