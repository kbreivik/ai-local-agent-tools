"""
Documentation retrieval for skill generation.

Fetches relevant context from MuninnDB, the service catalog, the breaking
changes table, and local doc files. Used by generator.py to enrich LLM
prompts with real API documentation so generated skills are accurate.

Designed for airgapped environments — all sources are local.
"""
import json
import os
import re
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


# ── Config helpers ─────────────────────────────────────────────────────────────

def _api_base() -> str:
    return f"http://localhost:{os.environ.get('API_PORT', '8000')}"


def _project_root() -> Path:
    return Path(__file__).parent.parent.parent.parent


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ok(data: Any, message: str = "OK") -> dict:
    return {"status": "ok", "data": data, "timestamp": _ts(), "message": message}


def _err(message: str, data: Any = None) -> dict:
    return {"status": "error", "data": data, "timestamp": _ts(), "message": message}


# ── Keyword extraction ─────────────────────────────────────────────────────────

# Known service/product names the extractor should recognize as single tokens
KNOWN_SERVICES = {
    "fortigate", "fortiswitch", "fortianalyzer", "fortimanager", "fortios",
    "proxmox", "truenas", "synology", "unifi", "opnsense", "pfsense",
    "elasticsearch", "kibana", "logstash", "filebeat",
    "docker", "kubernetes", "k3s", "portainer",
    "grafana", "prometheus", "zabbix", "nagios",
    "nginx", "traefik", "haproxy", "caddy",
    "postgresql", "mysql", "mariadb", "redis", "mongodb",
    "kafka", "rabbitmq", "mosquitto", "nats",
    "minio", "ceph", "zfs", "btrfs",
    "wireguard", "tailscale", "zerotier",
    "pihole", "adguard", "bind9",
    "proxmoxer",  # python library
    "paramiko",   # python library
    "httpx",      # python library
}

# Protocol/tech keywords worth extracting
TECH_KEYWORDS = {
    "rest", "api", "graphql", "grpc", "ssh", "snmp", "http", "https",
    "websocket", "mqtt", "ssl", "tls", "jwt", "oauth", "ldap", "radius",
    "vlan", "ospf", "bgp", "lacp", "lldp", "stp", "ha", "cluster",
    "vm", "lxc", "container", "cgroup", "zpool", "dataset", "snapshot",
    "firmware", "upgrade", "backup", "restore", "config", "monitor",
    "health", "status", "metrics", "logs", "alerts",
}

# API path patterns — extract endpoint references
_API_PATH_RE = re.compile(r'(/api/[^\s"\']+|/v\d+/[^\s"\']+|/webapi/[^\s"\']+)')

# Version patterns — extract version references
_VERSION_RE = re.compile(r'\b(\d+\.\d+(?:\.\d+)?)\b')


def extract_keywords(description: str) -> dict:
    """
    Parse a skill description into structured search terms.

    Returns:
        {
            "services":   ["fortigate"],
            "tech":       ["rest", "api", "ha"],
            "endpoints":  ["/api/v2/monitor/system/status"],
            "versions":   ["7.4", "7.6"],
            "raw_terms":  ["fortigate", "system", "status", "health"],
        }
    """
    lower = description.lower()
    words = set(re.findall(r'[a-z][a-z0-9_-]+', lower))

    services = sorted(words & KNOWN_SERVICES)
    tech = sorted(words & TECH_KEYWORDS)
    endpoints = _API_PATH_RE.findall(description)
    versions = _VERSION_RE.findall(description)

    # Raw terms: all meaningful words >2 chars, excluding stopwords
    stopwords = {
        "the", "and", "for", "from", "with", "that", "this", "use", "via",
        "get", "set", "check", "should", "when", "will", "can", "also",
        "into", "not", "are", "has", "was", "been", "being", "does",
        "using", "used", "each", "which", "their", "them", "then",
        "need", "want", "like", "make", "just", "call", "return",
    }
    raw_terms = sorted(
        w for w in words
        if len(w) > 2 and w not in stopwords
        and not w.isdigit()
    )

    return {
        "services": services,
        "tech": tech,
        "endpoints": endpoints,
        "versions": versions,
        "raw_terms": raw_terms[:20],  # cap at 20 to avoid noise
    }


# ── MuninnDB retrieval ─────────────────────────────────────────────────────────

def _activate_memory(cues: list[str], timeout: float = 5.0) -> list[dict]:
    """
    Send activation cues to MuninnDB and return engram results.
    Each engram has: concept, content, tags, activation_score, etc.
    Returns empty list on failure (MuninnDB down, timeout, etc.).
    """
    try:
        import httpx
        r = httpx.post(
            f"{_api_base()}/api/memory/activate",
            json=cues,
            timeout=timeout,
        )
        if r.status_code == 200:
            return r.json().get("activations", [])
    except Exception as e:
        log.debug("MuninnDB activation failed: %s", e)
    return []


def _query_muninndb_multi(keywords: dict) -> list[dict]:
    """
    Run multiple activation queries with different cue strategies.
    Deduplicates by concept name and sorts by activation score.

    Strategy:
      1. Service-specific cues: "fortigate api", "fortigate rest", "fortigate documentation"
      2. Endpoint cues:         "/api/v2/monitor/system/status"
      3. Task-level cues:       "system status health monitoring"
      4. Broad tech cues:       "rest api authentication firewall"
    """
    all_engrams: dict[str, dict] = {}  # keyed by concept for dedup

    cue_batches = []

    # Strategy 1: service + context combinations
    for svc in keywords["services"]:
        cue_batches.append([
            f"{svc} api",
            f"{svc} documentation",
            f"{svc} rest api",
            f"{svc} configuration",
        ])

    # Strategy 2: exact endpoint strings (high signal)
    if keywords["endpoints"]:
        cue_batches.append(keywords["endpoints"][:5])

    # Strategy 3: task-level — combine service + tech terms
    task_cues = []
    for svc in keywords["services"][:2]:
        for tech in keywords["tech"][:3]:
            task_cues.append(f"{svc} {tech}")
    if task_cues:
        cue_batches.append(task_cues[:5])

    # Strategy 4: broad — raw terms combined
    if keywords["raw_terms"]:
        # Group into chunks of 3-4 terms
        terms = keywords["raw_terms"]
        for i in range(0, min(len(terms), 12), 3):
            chunk = " ".join(terms[i:i+3])
            if chunk not in task_cues:
                task_cues.append(chunk)
        if task_cues:
            cue_batches.append(task_cues[:5])

    # Execute each batch
    for cues in cue_batches:
        if not cues:
            continue
        engrams = _activate_memory(cues)
        for e in engrams:
            concept = e.get("concept", "")
            if concept and concept not in all_engrams:
                all_engrams[concept] = e
            elif concept in all_engrams:
                # Keep the higher activation score
                existing_score = all_engrams[concept].get("activation", 0)
                new_score = e.get("activation", 0)
                if new_score > existing_score:
                    all_engrams[concept] = e

    # Sort by activation score descending
    results = sorted(
        all_engrams.values(),
        key=lambda x: x.get("activation", 0),
        reverse=True,
    )
    return results


# ── Content classification and prioritization ──────────────────────────────────

# Tags and concept patterns that indicate document type
_DOC_TYPE_SIGNALS = {
    "api_reference": {
        "tags": {"api", "reference", "endpoint", "rest", "swagger", "openapi"},
        "concept_patterns": [r"api", r"endpoint", r"reference", r"swagger"],
        "priority": 1,  # highest
    },
    "config_guide": {
        "tags": {"configuration", "config", "setup", "settings", "admin"},
        "concept_patterns": [r"config", r"setup", r"admin.*guide", r"settings"],
        "priority": 2,
    },
    "changelog": {
        "tags": {"changelog", "release", "release-notes", "breaking", "migration"},
        "concept_patterns": [r"changelog", r"release.?note", r"what.?s.?new", r"migration"],
        "priority": 3,
    },
    "tutorial": {
        "tags": {"tutorial", "guide", "howto", "getting-started", "quickstart"},
        "concept_patterns": [r"tutorial", r"getting.?started", r"how.?to", r"quickstart"],
        "priority": 4,
    },
    "general": {
        "tags": set(),
        "concept_patterns": [],
        "priority": 5,  # lowest
    },
}


def _classify_doc_type(engram: dict) -> tuple[str, int]:
    """
    Classify an engram by document type. Returns (type_name, priority).
    Lower priority number = more valuable for skill generation.
    """
    tags = set(t.lower() for t in engram.get("tags", []))
    concept = engram.get("concept", "").lower()

    for doc_type, signals in _DOC_TYPE_SIGNALS.items():
        if doc_type == "general":
            continue
        # Check tag overlap
        if tags & signals["tags"]:
            return doc_type, signals["priority"]
        # Check concept pattern match
        for pattern in signals["concept_patterns"]:
            if re.search(pattern, concept):
                return doc_type, signals["priority"]

    return "general", 5


def _prioritize_engrams(engrams: list[dict]) -> list[dict]:
    """
    Sort engrams by: doc_type priority first, then activation score.
    API references come before tutorials, etc.
    """
    scored = []
    for e in engrams:
        doc_type, type_priority = _classify_doc_type(e)
        activation = e.get("activation", 0)
        scored.append({
            **e,
            "_doc_type": doc_type,
            "_type_priority": type_priority,
            "_activation": activation,
        })

    scored.sort(key=lambda x: (x["_type_priority"], -x["_activation"]))
    return scored


# ── Token budgeting ────────────────────────────────────────────────────────────

def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token for English text."""
    return len(text) // 4


def _truncate_content(content: str, max_tokens: int) -> str:
    """
    Truncate content intelligently — prefer cutting at paragraph or
    sentence boundaries rather than mid-sentence.
    """
    max_chars = max_tokens * 4
    if len(content) <= max_chars:
        return content

    # Try to cut at paragraph boundary
    truncated = content[:max_chars]
    last_para = truncated.rfind("\n\n")
    if last_para > max_chars * 0.6:
        return truncated[:last_para].rstrip() + "\n\n[... truncated]"

    # Try sentence boundary
    last_sentence = max(
        truncated.rfind(". "),
        truncated.rfind(".\n"),
        truncated.rfind("! "),
        truncated.rfind("? "),
    )
    if last_sentence > max_chars * 0.6:
        return truncated[:last_sentence + 1].rstrip() + "\n\n[... truncated]"

    # Hard cut
    return truncated.rstrip() + "\n\n[... truncated]"


def _budget_content(engrams: list[dict], total_token_budget: int) -> list[dict]:
    """
    Allocate token budget across engrams. Higher-priority docs get more space.
    Returns engrams with content trimmed to fit within total budget.
    """
    if not engrams:
        return []

    results = []
    remaining = total_token_budget

    # Tier 1: API references and config guides — up to 60% of budget
    # Tier 2: changelogs — up to 25%
    # Tier 3: everything else — remainder
    tier_budgets = {
        1: int(total_token_budget * 0.45),  # api_reference
        2: int(total_token_budget * 0.20),  # config_guide
        3: int(total_token_budget * 0.20),  # changelog
        4: int(total_token_budget * 0.10),  # tutorial
        5: int(total_token_budget * 0.05),  # general
    }

    # Group by priority tier
    by_tier: dict[int, list[dict]] = {}
    for e in engrams:
        tier = e.get("_type_priority", 5)
        by_tier.setdefault(tier, []).append(e)

    for tier in sorted(by_tier.keys()):
        tier_items = by_tier[tier]
        budget_for_tier = min(tier_budgets.get(tier, 100), remaining)
        if budget_for_tier <= 50:
            break

        per_item = max(150, budget_for_tier // len(tier_items))

        for e in tier_items:
            content = e.get("content", "")
            if not content:
                continue

            tokens_needed = _estimate_tokens(content)
            if tokens_needed <= per_item:
                trimmed = content
            else:
                trimmed = _truncate_content(content, per_item)

            actual_tokens = _estimate_tokens(trimmed)
            if actual_tokens > remaining:
                trimmed = _truncate_content(trimmed, remaining)
                actual_tokens = _estimate_tokens(trimmed)

            results.append({
                "concept": e.get("concept", ""),
                "content": trimmed,
                "doc_type": e.get("_doc_type", "general"),
                "tags": e.get("tags", []),
                "tokens": actual_tokens,
            })
            remaining -= actual_tokens
            if remaining <= 50:
                break

        if remaining <= 50:
            break

    return results


# ── Local file fallback ────────────────────────────────────────────────────────

def _scan_local_docs(keywords: dict, max_results: int = 3) -> list[dict]:
    """
    Fallback when MuninnDB is unavailable. Scan data/docs/ for files
    whose names match the service or keywords. Return file content snippets.
    """
    docs_dir = _project_root() / "data" / "docs"
    if not docs_dir.exists():
        return []

    results = []
    search_terms = keywords["services"] + keywords["raw_terms"][:5]

    for fpath in docs_dir.iterdir():
        if fpath.suffix.lower() not in (".txt", ".md", ".html", ".json", ".rst"):
            continue
        name_lower = fpath.stem.lower()
        if any(term in name_lower for term in search_terms):
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")[:8000]
                results.append({
                    "concept": f"local_doc:{fpath.name}",
                    "content": content,
                    "doc_type": "local_file",
                    "tags": ["local", fpath.suffix.lstrip(".")],
                    "tokens": _estimate_tokens(content),
                })
            except Exception:
                continue
        if len(results) >= max_results:
            break

    return results


# ── Service catalog integration ────────────────────────────────────────────────

def _get_service_context(service_id: str) -> dict | None:
    """
    Pull known info about a service from the service catalog and
    any relevant breaking changes. Returns a context dict or None.
    """
    try:
        from mcp_server.tools.skills import registry

        service = registry.get_service(service_id)
        if not service:
            return None

        breaking = registry.get_breaking_changes(service_id)
        unresolved = [b for b in breaking if not b.get("resolved")]

        return {
            "service_id": service_id,
            "display_name": service.get("display_name", service_id),
            "detected_version": service.get("detected_version", ""),
            "api_docs_ingested": bool(service.get("api_docs_ingested")),
            "api_docs_version": service.get("api_docs_version", ""),
            "notes": service.get("notes", ""),
            "breaking_changes": [
                {
                    "from": b.get("from_version", ""),
                    "to": b.get("to_version", ""),
                    "description": b.get("description", ""),
                    "affected_endpoints": json.loads(b.get("affected_endpoints", "[]")),
                    "remediation": b.get("remediation", ""),
                }
                for b in unresolved[:5]
            ],
        }
    except Exception as e:
        log.debug("Service catalog lookup failed: %s", e)
        return None


# ── Existing skill context ─────────────────────────────────────────────────────

def _get_existing_skill_context(service_id: str) -> list[dict]:
    """
    Find existing skills for the same service. The generator should know
    what already exists to avoid duplication and maintain consistency.
    """
    try:
        from mcp_server.tools.skills import registry
        skills = registry.search_skills(service_id)
        return [
            {
                "name": s.get("name"),
                "description": s.get("description"),
                "version": s.get("version"),
                "compat_built_for": json.loads(s.get("annotations", "{}"))
                    .get("api_version_built_for", ""),
            }
            for s in skills[:10]
        ]
    except Exception:
        return []


# ── Main entry point ───────────────────────────────────────────────────────────

def fetch_relevant_docs(
    description: str,
    category: str = "general",
    api_base: str = "",
    token_budget: int = 3000,
) -> dict:
    """
    Fetch documentation context for skill generation.

    Queries MuninnDB with multiple strategies, classifies results by doc type,
    allocates token budget by priority (API ref > config > changelog > tutorial),
    and enriches with service catalog data and breaking change context.

    Falls back to scanning data/docs/ when MuninnDB is unreachable.

    Args:
        description: Natural language description of the skill to generate
        category:    Skill category (monitoring, networking, etc.)
        api_base:    Optional API base URL hint
        token_budget: Max total tokens for documentation context (default 3000)

    Returns:
        {
            "status": "ok",
            "data": {
                "context_docs":     [{"concept", "content", "doc_type", "tokens"}, ...],
                "service_context":  {...} | None,
                "existing_skills":  [...],
                "total_tokens":     int,
                "sources_used":     ["muninndb"|"local_files"|"service_catalog"],
                "keywords":         {...},
            },
            "message": "Found 5 relevant doc sections (1842 tokens)"
        }
    """
    keywords = extract_keywords(description)

    # Also extract keywords from api_base if provided
    if api_base:
        api_keywords = extract_keywords(api_base)
        keywords["endpoints"].extend(api_keywords["endpoints"])
        keywords["services"] = sorted(set(keywords["services"] + api_keywords["services"]))

    sources_used = []
    context_docs = []
    service_context = None
    existing_skills = []

    # ── 1. Service catalog context (cheap, no MuninnDB needed) ──────────
    # Reserve ~200 tokens for this — it's structured metadata, not prose
    for svc in keywords["services"]:
        svc_ctx = _get_service_context(svc)
        if svc_ctx:
            service_context = svc_ctx
            sources_used.append("service_catalog")
            break

    # ── 2. Existing skills for this service ─────────────────────────────
    for svc in keywords["services"]:
        existing_skills = _get_existing_skill_context(svc)
        if existing_skills:
            break

    # ── 3. MuninnDB multi-query retrieval ───────────────────────────────
    engrams = _query_muninndb_multi(keywords)

    if engrams:
        sources_used.append("muninndb")
        prioritized = _prioritize_engrams(engrams)
        context_docs = _budget_content(prioritized, token_budget)
    else:
        # ── 4. Fallback: local file scan ────────────────────────────────
        local_docs = _scan_local_docs(keywords)
        if local_docs:
            sources_used.append("local_files")
            # Apply budget to local docs too
            for doc in local_docs:
                doc["_type_priority"] = 3
                doc["_doc_type"] = doc.get("doc_type", "local_file")
                doc["_activation"] = 0
            context_docs = _budget_content(local_docs, token_budget)

    total_tokens = sum(d.get("tokens", 0) for d in context_docs)

    return _ok(
        {
            "context_docs": context_docs,
            "service_context": service_context,
            "existing_skills": existing_skills,
            "total_tokens": total_tokens,
            "doc_count": len(context_docs),
            "sources_used": sources_used,
            "keywords": keywords,
        },
        f"Found {len(context_docs)} relevant doc sections ({total_tokens} tokens) "
        f"from {', '.join(sources_used) or 'no sources'}",
    )


# ── Prompt formatting ──────────────────────────────────────────────────────────

def format_docs_for_prompt(fetch_result: dict) -> str:
    """
    Format the output of fetch_relevant_docs() into a string that gets
    injected into the LLM generation prompt.

    Structure:
      ## Service Context          (if available)
      ## Reference Documentation  (from MuninnDB / local files)
      ## Existing Skills          (what already exists for this service)
      ## Known Breaking Changes   (if any)
    """
    data = fetch_result.get("data", {})
    sections = []

    # ── Service context ─────────────────────────────────────────────────
    svc = data.get("service_context")
    if svc:
        lines = [f"## Target Service: {svc['display_name']}"]
        if svc.get("detected_version"):
            lines.append(f"- Currently running version: {svc['detected_version']}")
        if svc.get("api_docs_version"):
            lines.append(f"- Ingested API docs cover version: {svc['api_docs_version']}")
        if svc.get("notes"):
            lines.append(f"- Notes: {svc['notes']}")
        sections.append("\n".join(lines))

    # ── Breaking changes ────────────────────────────────────────────────
    if svc and svc.get("breaking_changes"):
        lines = ["## Known Breaking Changes (unresolved)"]
        for bc in svc["breaking_changes"]:
            lines.append(f"- **{bc.get('from', '?')} → {bc['to']}**: {bc['description']}")
            if bc.get("affected_endpoints"):
                lines.append(f"  Affected endpoints: {', '.join(bc['affected_endpoints'])}")
            if bc.get("remediation"):
                lines.append(f"  Remediation: {bc['remediation']}")
        lines.append("")
        lines.append("IMPORTANT: The generated skill MUST account for these breaking changes.")
        sections.append("\n".join(lines))

    # ── Reference documentation ─────────────────────────────────────────
    docs = data.get("context_docs", [])
    if docs:
        lines = ["## Reference Documentation"]
        for i, doc in enumerate(docs, 1):
            doc_type = doc.get("doc_type", "general")
            concept = doc.get("concept", f"doc_{i}")
            lines.append(f"### [{doc_type}] {concept}")
            lines.append(doc.get("content", ""))
            lines.append("")
        sections.append("\n".join(lines))

    # ── Existing skills ─────────────────────────────────────────────────
    existing = data.get("existing_skills", [])
    if existing:
        lines = ["## Existing Skills for This Service (avoid duplicating these)"]
        for s in existing:
            lines.append(f"- `{s['name']}`: {s['description']}")
        sections.append("\n".join(lines))

    if not sections:
        return (
            "## Reference Documentation\n"
            "No documentation found for this service in the local knowledge base.\n"
            "The generated skill should include defensive error handling and\n"
            "clear error messages for unexpected API responses.\n"
            "Consider using skill_export_prompt() to request documentation\n"
            "from the operator for better results."
        )

    return "\n\n".join(sections)
