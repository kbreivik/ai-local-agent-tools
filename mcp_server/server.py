"""FastMCP server exposing Swarm, Kafka, and Orchestration tools."""
import os
import sys

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastmcp import FastMCP

from api.constants import APP_NAME
from mcp_server.tools import swarm, kafka, orchestration, elastic
from mcp_server.tools.docker_engine import (
    docker_engine_version,
    docker_engine_check_update,
    docker_engine_update,
)
from mcp_server.tools import ingest as ingest_tools

mcp = FastMCP(APP_NAME)


# ── Docker Swarm tools ────────────────────────────────────────────────────────

@mcp.tool()
def swarm_status() -> dict:
    """Node health, manager/worker state."""
    return swarm.swarm_status()


@mcp.tool()
def service_list() -> dict:
    """All services, replicas, image versions."""
    return swarm.service_list()


@mcp.tool()
def service_health(name: str = "") -> dict:
    """Check service health. With no args, returns health summary of ALL services.
    With name, checks that specific service only.
    Examples:
      service_health()           # all services overview
      service_health(name="kafka")   # specific service
    """
    if not name:
        services = swarm.service_list()
        return services
    return swarm.service_health(name)


@mcp.tool()
def service_current_version(name: str) -> dict:
    """Currently running image tag for a service — call before deciding to upgrade."""
    return swarm.service_current_version(name)


@mcp.tool()
def service_resolve_image(image: str, resolve_previous: bool = True) -> dict:
    """
    Resolve latest stable semver tag for an image from Docker Hub.
    When resolve_previous=True also returns previous_major, previous_minor,
    and the full sorted all_stable list for downgrade target selection.
    """
    return swarm.service_resolve_image(image, resolve_previous)


@mcp.tool()
def service_version_history(image: str, count: int = 5) -> dict:
    """
    Return the last {count} stable semver versions for an image from Docker Hub,
    sorted descending. Use when downgrading — pick the version immediately below
    the current running version.
    """
    return swarm.service_version_history(image, count)


@mcp.tool()
def service_upgrade(name: str, image: str) -> dict:
    """Rolling upgrade with health gate."""
    return swarm.service_upgrade(name, image)


@mcp.tool()
def service_rollback(name: str) -> dict:
    """Revert service to previous image."""
    return swarm.service_rollback(name)


@mcp.tool()
def node_drain(node_id: str) -> dict:
    """Drain a Swarm node before maintenance. Requires plan_action() approval first.
    node_id accepts: Docker hex ID, hostname, or partial hostname.
    Reverse with: node_activate(node_id=<same value>)
    Examples:
      node_drain(node_id='tyimr0p3dsow')   # by hex ID
      node_drain(node_id='worker-01')       # by hostname
    """
    return swarm.node_drain(node_id)


@mcp.tool()
def node_activate(node_id: str) -> dict:
    """Re-activate a drained Swarm node.
    node_id accepts: Docker hex ID, hostname, or partial hostname.
    Examples:
      node_activate(node_id='yxm2ust947ch')   # by hex ID
      node_activate(node_id='manager-01')      # by hostname
    """
    return swarm.node_activate(node_id)


@mcp.tool()
def pre_upgrade_check() -> dict:
    """Full swarm readiness gate."""
    return swarm.pre_upgrade_check()


@mcp.tool()
def postgres_health() -> dict:
    """Check PostgreSQL database health: connection status, DB size, and key table row counts.
    Returns connected/error status. Uses DATABASE_URL env var or defaults to hp1-postgres:5432.
    Useful for verifying DB is reachable before/after container restarts.
    """
    return swarm.postgres_health()


@mcp.tool()
def service_logs(service_name: str, lines: int = 50, since_minutes: int = 10) -> dict:
    """Fetch recent logs from a Docker Swarm service or container.
    service_name: Docker service name (e.g. 'hp1_kafka1') or container name/ID
    lines: number of log lines to return (max 200, default 50)
    since_minutes: only return logs from last N minutes (default 10)
    Examples:
      service_logs(service_name="hp1_kafka1")
      service_logs(service_name="hp1_elasticsearch", lines=100, since_minutes=30)
    """
    return swarm.service_logs(service_name, lines, since_minutes)


# ── Kafka tools ───────────────────────────────────────────────────────────────

@mcp.tool()
def kafka_broker_status(broker_id: int = None, broker_name: str = "") -> dict:
    """Get Kafka broker health and controller status.
    Call with no args to check all 3 brokers (most common usage).
    broker_id and broker_name params are accepted but ignored — always returns all brokers.
    Key field to check: controller_id (None = no controller elected = broken cluster).
    Broker addresses come from KAFKA_BOOTSTRAP_SERVERS env var.
    Example: kafka_broker_status()
    """
    return kafka.kafka_broker_status()


@mcp.tool()
def kafka_consumer_lag(group: str) -> dict:
    """Lag per topic/partition for a consumer group."""
    return kafka.kafka_consumer_lag(group)


@mcp.tool()
def kafka_topic_health(topic: str) -> dict:
    """Partition count, replication, under-replicated check."""
    return kafka.kafka_topic_health(topic)


@mcp.tool()
def kafka_topic_list() -> dict:
    """List all Kafka topics with partition count and replication factor.
    Skips internal (__consumer_offsets, __transaction_state) topics by default.
    Use to inventory topics before/after operations or to verify topic creation.
    Example: kafka_topic_list()
    """
    return kafka.kafka_topic_list()


@mcp.tool()
def kafka_rolling_restart_safe() -> dict:
    """Checks ISR before each broker restart."""
    return kafka.kafka_rolling_restart_safe()


@mcp.tool()
def pre_kafka_check() -> dict:
    """Full Kafka readiness gate."""
    return kafka.pre_kafka_check()


# ── Orchestration tools ───────────────────────────────────────────────────────

@mcp.tool()
def agent_status() -> dict:
    """Check agent's own health and performance metrics.
    Returns: version, deploy_mode, ws_clients (active WebSocket connections),
    lm_studio connectivity, success_rate, total_operations.
    Use to verify the agent is healthy before long-running tasks.
    Example: agent_status()
    """
    return orchestration.agent_status()


@mcp.tool()
def checkpoint_save(label: str) -> dict:
    """Snapshot current state before risky ops."""
    return orchestration.checkpoint_save(label)


@mcp.tool()
def checkpoint_restore(label: str) -> dict:
    """Rollback to saved state."""
    return orchestration.checkpoint_restore(label)


@mcp.tool()
def audit_log(action: str, result: str, target: str = "", details: str = "") -> dict:
    """Log an agent action to the audit table.
    REQUIRED: action (verb) and result (outcome).
    action: what happened — upgrade | drain | restart | create | check | rollback
    result: outcome — ok | failed | escalated | skipped | error
    target: what was acted on — kafka | manager-01 | proxmox_vm_status (optional)
    details: extra context (optional)
    EXAMPLES (copy these patterns):
      audit_log(action="upgrade", result="ok", target="kafka")
      audit_log(action="health_check", result="ok")
      audit_log(action="drain", result="failed", target="worker-01", details="node unreachable")
    Note: only logged once per run — subsequent calls skipped automatically.
    """
    return orchestration.audit_log(action, result, target=target, details=details)


@mcp.tool()
def escalate(reason: str) -> dict:
    """Flag decision as high-risk, log and pause."""
    return orchestration.escalate(reason)


@mcp.tool()
def pre_upgrade_check_full(service: str = "") -> dict:
    """6-step pre-upgrade gate: swarm + kafka + elastic errors + log pattern + memory + checkpoint."""
    return orchestration.pre_upgrade_check(service)


@mcp.tool()
def post_upgrade_verify(service: str, operation_id: str = "") -> dict:
    """Post-upgrade verification: replicas + no new errors + log correlation + memory engram."""
    return orchestration.post_upgrade_verify(service, operation_id)


# ── Elasticsearch log tools ───────────────────────────────────────────────────

@mcp.tool()
def elastic_cluster_health() -> dict:
    """Full Elasticsearch cluster health: status, nodes, shards, indices."""
    return elastic.elastic_cluster_health()


@mcp.tool()
def elastic_search_logs(
    query: str = "",
    service: str = "",
    node: str = "",
    minutes_ago: int = 60,
    size: int = 50,
) -> dict:
    """Search infrastructure logs. Filter by service, node, time range, keyword."""
    return elastic.elastic_search_logs(query, service, node, minutes_ago, size)


@mcp.tool()
def elastic_error_logs(service: str = "", minutes_ago: int = 30) -> dict:
    """Recent error/critical logs. Returns status=degraded if errors found."""
    return elastic.elastic_error_logs(service, minutes_ago)


@mcp.tool()
def elastic_kafka_logs(broker_id: str = "", minutes_ago: int = 60) -> dict:
    """Kafka broker log analysis: leader elections, ISR changes, offline partitions."""
    return elastic.elastic_kafka_logs(broker_id, minutes_ago)


@mcp.tool()
def elastic_log_pattern(service: str, hours: int = 24) -> dict:
    """Error rate trend for a service. Flags anomaly if current hour > 2x average."""
    return elastic.elastic_log_pattern(service, hours)


@mcp.tool()
def elastic_index_stats() -> dict:
    """hp1-logs-* index stats and Filebeat freshness check."""
    return elastic.elastic_index_stats()


@mcp.tool()
def elastic_correlate_operation(operation_id: str) -> dict:
    """Correlate a PostgreSQL operation_id with contemporaneous Elasticsearch logs."""
    return elastic.elastic_correlate_operation(operation_id)


# ── Docker Engine tools ───────────────────────────────────────────────────────

@mcp.tool()
def docker_engine_version_tool() -> dict:
    """Get the current Docker Engine version on the remote Debian 12 host via SSH."""
    return docker_engine_version()


@mcp.tool()
def docker_engine_check_update_tool() -> dict:
    """Check if a Docker Engine update is available. Runs apt-get update then apt-cache policy docker-ce."""
    return docker_engine_check_update()


@mcp.tool()
def docker_engine_update_tool(dry_run: bool = True) -> dict:
    """
    Upgrade Docker Engine on the remote Debian 12 host via apt-get.
    DESTRUCTIVE — requires plan_action() approval before calling with dry_run=False.
    dry_run=True runs a simulation. dry_run=False performs the actual upgrade.
    """
    return docker_engine_update(dry_run)


# ── Ingest tools ──────────────────────────────────────────────────────────────

@mcp.tool()
def ingest_url(url: str, tags: list = None, label: str = "") -> dict:
    """
    Fetch a URL, store its content locally and in MuninnDB for long-term recall.
    IMPORTANT: This tool requires user approval via the GUI before the content is stored.
    Call this when you find relevant documentation, runbooks, or reference material at a URL.
    Returns preview of content and whether it's new or updated.
    """
    return ingest_tools.ingest_url(url, tags, label)


@mcp.tool()
def ingest_pdf(filename: str, tags: list = None) -> dict:
    """
    Ingest a PDF file that has already been uploaded to data/docs/.
    Stores content in MuninnDB for long-term recall.
    """
    return ingest_tools.ingest_pdf(filename, tags)


@mcp.tool()
def check_internet_connectivity() -> dict:
    """Check if the agent host has internet access."""
    return ingest_tools.check_internet_connectivity()


# ── Skill system ──────────────────────────────────────────────────────────────

from mcp_server.tools.skills import meta_tools as skill_tools
from mcp_server.tools.skills import loader as skill_loader
from mcp_server.tools.skills import registry as skill_registry

skill_registry.init_db()  # triggers auto-detect: PostgreSQL → SQLite fallback
_skill_load_result = skill_loader.load_all_skills(mcp)
_skill_import_result = skill_loader.scan_imports(mcp)

# Register promoted skills as first-class @mcp.tool() wrappers
try:
    from mcp_server.tools.skills.registry import list_skills as _ls_promoted
    for _ps in _ls_promoted(enabled_only=True):
        if _ps.get("lifecycle_state") != "promoted":
            continue
        _pname = _ps["name"]
        _pdesc = _ps.get("description", _pname)
        def _make_promoted_tool(_n: str, _d: str):
            def _promoted_fn(**kwargs) -> dict:
                """Promoted skill wrapper."""
                from mcp_server.tools.skills.loader import dispatch_skill
                return dispatch_skill(_n, **kwargs)
            _promoted_fn.__name__ = _n
            _promoted_fn.__doc__ = _d
            try:
                return mcp.tool()(_promoted_fn)
            except Exception as _reg_e:
                import logging as _reg_log
                _reg_log.getLogger(__name__).warning(
                    "Promoted skill '%s' registration skipped: %s", _n, _reg_e
                )
                return None
        _make_promoted_tool(_pname, _pdesc)
except Exception as _e:
    import logging as _logging
    _logging.getLogger(__name__).warning("Promoted skill registration failed: %s", _e)


@mcp.tool()
def skill_search(query: str, category: str = "") -> dict:
    """Search for dynamic skills by keyword. Call this when you need a capability
    not in the built-in tools (swarm, kafka, elastic, docker_engine, etc.)."""
    return skill_tools.skill_search(query, category)


@mcp.tool()
def skill_list(category: str = "", enabled_only: bool = True) -> dict:
    """List all dynamic skills. Categories: monitoring, networking, storage, compute, general."""
    return skill_tools.skill_list(category, enabled_only)


@mcp.tool()
def skill_info(name: str) -> dict:
    """Get details about a dynamic skill: parameters, call count, errors, generation mode."""
    return skill_tools.skill_info(name)


@mcp.tool()
def skill_create(
    description: str,
    category: str = "general",
    api_base: str = "",
    auth_type: str = "none",
    backend: str = "",
) -> dict:
    """Generate a new tool when no existing skill fits. Call skill_search FIRST.
    backend='local' (default) uses LM Studio. backend='cloud' uses Anthropic API.
    backend='export' saves a prompt file for offline generation (airgapped workflow).
    The description should name the service, API, and what data to return."""
    return skill_tools.skill_create(mcp, description, category, api_base, auth_type, backend)


@mcp.tool()
def skill_import() -> dict:
    """Scan data/skill_imports/ for .py skill files (sneakernet/offline workflow).
    Validates and loads any valid skills found. Call after operator drops files there."""
    return skill_tools.skill_import(mcp)


@mcp.tool()
def skill_export_prompt(
    description: str,
    category: str = "general",
    api_base: str = "",
    auth_type: str = "none",
) -> dict:
    """Save a self-contained skill generation prompt to data/skill_exports/.
    Use for airgapped environments. The export file contains full instructions
    for the operator to generate the skill on another machine."""
    return skill_tools.skill_export_prompt(description, category, api_base, auth_type)


@mcp.tool()
def skill_disable(name: str) -> dict:
    """Disable a broken dynamic skill."""
    return skill_tools.skill_disable(name)


@mcp.tool()
def skill_enable(name: str) -> dict:
    """Re-enable a disabled dynamic skill."""
    return skill_tools.skill_enable(name)


@mcp.tool()
def skill_generation_config() -> dict:
    """Show current skill generation config: backend, model, LM Studio URL."""
    return skill_tools.skill_generation_config()


# ── Skill v2: Service catalog, compat, knowledge tools ──────────────────────

@mcp.tool()
def service_catalog_list() -> dict:
    """List all known infrastructure services with detected versions and doc coverage."""
    return skill_tools.service_catalog_list()


@mcp.tool()
def service_catalog_update(service_id: str, detected_version: str = "", known_latest: str = "", notes: str = "") -> dict:
    """Update service catalog entry with detected or known version info.
    service_id: identifier string — must match an existing catalog entry.
    Existing catalog entries: 'kafka', 'proxmox', 'elasticsearch', 'generic', 'fortigate'
    EXAMPLES:
      service_catalog_update(service_id="kafka", detected_version="3.7.0", known_latest="3.7.0")
      service_catalog_update(service_id="proxmox", detected_version="8.3.2")
      service_catalog_update(service_id="elasticsearch", notes="Single node, hp1-logs cluster")
    """
    return skill_tools.service_catalog_update(service_id, detected_version, known_latest, notes)


@mcp.tool()
def skill_compat_check(name: str) -> dict:
    """Check if a skill is compatible with the current service version."""
    return skill_tools.skill_compat_check(name)


@mcp.tool()
def skill_compat_check_all() -> dict:
    """Compat check all enabled skills. Run after any infrastructure upgrade."""
    return skill_tools.skill_compat_check_all()


@mcp.tool()
def skill_health_summary() -> dict:
    """Full skill system health: compat status, error rates, stale checks, actions needed."""
    return skill_tools.skill_health_summary()


@mcp.tool()
def knowledge_ingest_changelog(service_id: str, content: str = "", from_version: str = "", to_version: str = "") -> dict:
    """Parse ingested changelog/release notes to find breaking changes affecting skills."""
    return skill_tools.knowledge_ingest_changelog(service_id, content, from_version, to_version)


@mcp.tool()
def knowledge_export_request(service_id: str, request_type: str = "changelog") -> dict:
    """Export a structured documentation request for airgapped environments.
    Tells the operator exactly which docs to get and where to find them."""
    return skill_tools.knowledge_export_request(service_id, request_type)


@mcp.tool()
def skill_recommend_updates(service_id: str = "") -> dict:
    """List skills that need updating based on breaking changes and version drift."""
    return skill_tools.skill_recommend_updates(service_id)


@mcp.tool()
def skill_regenerate(name: str, backend: str = "") -> dict:
    """Regenerate a skill with current docs and version info. Backs up the old version."""
    return skill_tools.skill_regenerate(mcp, name, backend)


# ── Skill v3: Discovery, dispatcher, live validation ─────────────────────────

def _load_default_hosts() -> list:
    """Load discovery hosts from DISCOVER_DEFAULT_HOSTS env var (JSON array) or empty list."""
    import json as _json
    raw = os.environ.get("DISCOVER_DEFAULT_HOSTS", "")
    if raw:
        try:
            return _json.loads(raw)
        except (ValueError, TypeError):
            pass
    return []

_HP1_HOSTS = _load_default_hosts()

@mcp.tool()
def discover_environment(hosts: list = None, hosts_json: str = "") -> dict:
    """Scan hosts for services via deterministic fingerprinting. No LLM calls.
    If called with no arguments, scans hosts from DISCOVER_DEFAULT_HOSTS env var.
    hosts: list of {"address": "...", "port": N} dicts (optional)
    hosts_json: JSON string alternative to hosts param (optional)
    Examples:
      discover_environment()
      discover_environment(hosts=[{"address": "10.0.0.1"}])
    """
    import json as _json
    if hosts_json:
        try:
            hosts = _json.loads(hosts_json)
        except Exception:
            pass
    resolved = hosts or _HP1_HOSTS
    if not resolved:
        from mcp_server.tools.skills.discovery import _err
        return _err("No hosts provided. Set DISCOVER_DEFAULT_HOSTS env var or pass hosts/hosts_json.")
    return skill_tools.discover_environment(resolved)


@mcp.tool()
def skill_execute(name: str, params_json: str = "{}") -> dict:
    """Execute a skill by name. Pass parameters as JSON string, e.g. params_json='{"host": "pve01"}'.
    Call skill_search() first to find available skills.
    Examples:
      skill_execute(name='proxmox_vm_status', params_json='{"host": "pve01"}')
      skill_execute(name='http_health_check', params_json='{"url": "http://127.0.0.1:8000/api/health"}')
      skill_execute(name='kafka_broker_status')
    """
    import json as _json
    try:
        kwargs = _json.loads(params_json) if params_json else {}
    except (ValueError, TypeError):
        kwargs = {}
    return skill_tools.skill_execute(name, **kwargs)


@mcp.tool()
def search_docs(query: str, platform: str = "", doc_type: str = "") -> dict:
    """Search ingested documentation by semantic + keyword match.
    Returns ranked chunks from vendor docs, admin guides, API references.
    Use when you need specific CLI syntax, config examples, or API details.
    Examples:
      search_docs(query="add disk to VM", platform="proxmox")
      search_docs(query="OSPF configuration", platform="fortigate")
      search_docs(query="backup schedule", platform="pbs")
    """
    from datetime import datetime, timezone
    from api.rag.doc_search import search_docs as _search, format_doc_results
    doc_type_filter = [doc_type] if doc_type else None
    results = _search(query=query, platform=platform, doc_type_filter=doc_type_filter)
    return {
        "status": "ok",
        "data": {
            "chunks": [
                {"content": r["content"], "platform": r["platform"],
                 "doc_type": r["doc_type"], "source_label": r.get("source_label", ""),
                 "score": r.get("rrf_score", 0)}
                for r in results
            ],
            "count": len(results),
            "platform": platform or "(auto)",
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "message": f"{len(results)} doc chunk(s) found" + (f" for {platform}" if platform else ""),
    }


@mcp.tool()
def validate_skill_live(name: str) -> dict:
    """Run 3-layer validation on a skill: deterministic AST checks (Layer 1),
    live endpoint probing (Layer 2, if api_base available), and LLM critic review
    (Layer 3, if LM Studio available). Use after skill_create or after service upgrades."""
    return skill_tools.validate_skill_live(name)


# ── Storage health ────────────────────────────────────────────────────────────

@mcp.tool()
def storage_health() -> dict:
    """Show current storage configuration: which backend is active, connection status,
    and Redis cache status. Use to verify PostgreSQL auto-detection worked."""
    from mcp_server.tools.skills.storage import get_backend, get_cache
    from datetime import datetime, timezone

    db = get_backend()
    db_health = db.health_check()

    cache = get_cache()
    cache_health = (
        cache.health_check() if cache
        else {"ok": False, "backend": "none", "details": "not configured"}
    )

    return {
        "status": "ok",
        "data": {"database": db_health, "cache": cache_health},
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "message": (
            f"DB: {db_health['backend']} ({'ok' if db_health['ok'] else 'ERROR'}) | "
            f"Cache: {cache_health['backend']} ({'ok' if cache_health['ok'] else 'none'})"
        ),
    }


@mcp.tool()
def vm_exec(host: str, command: str) -> dict:
    """Execute a read-only command on a registered VM host via SSH.
    Resolves credentials and jump hosts automatically from the connections database.
    Use host='agent-01' (label) or IP.
    Useful for: disk usage (df -h), large files (find / -size +100M), memory (free -m),
    logs (journalctl -n 50), Docker storage (docker system df).
    Always call this instead of asking the user to SSH manually.
    """
    from mcp_server.tools.vm import vm_exec as _vm_exec
    return _vm_exec(host=host, command=command)


@mcp.tool()
def infra_lookup(query: str = "", platform: str = "") -> dict:
    """Look up infrastructure entities by hostname, IP, alias, or label.
    Searches the auto-populated infra_inventory. Use to resolve names,
    find IPs, or list all known hosts for a platform.
    Leave query blank to list all known entities.
    """
    from mcp_server.tools.vm import infra_lookup as _infra_lookup
    return _infra_lookup(query=query, platform=platform)


@mcp.tool()
def docker_df(host: str = "") -> dict:
    """Get Docker disk usage: images, containers, volumes, build cache.
    Returns structured breakdown with sizes. Use before/after prune to measure reclaimed space.
    Uses Docker SDK directly — faster and more accurate than 'docker system df' via SSH.
    """
    from mcp_server.tools.docker_api import docker_df as _docker_df
    return _docker_df(host=host)


@mcp.tool()
def docker_prune(host: str = "", target: str = "images", force: bool = True) -> dict:
    """Prune unused Docker resources and return before/after disk delta.
    ALWAYS call plan_action() before this tool.
    target: images, images_all, containers, volumes, cache, system.
    Returns exact bytes reclaimed with before/after snapshots.
    """
    from mcp_server.tools.docker_api import docker_prune as _docker_prune
    return _docker_prune(host=host, target=target, force=force)


@mcp.tool()
def docker_images(host: str = "", include_dangling: bool = True) -> dict:
    """List Docker images with sizes, tags, and age. Sorted by size descending.
    Useful before pruning to see what is present and what would be removed.
    """
    from mcp_server.tools.docker_api import docker_images as _docker_images
    return _docker_images(host=host, include_dangling=include_dangling)


if __name__ == "__main__":
    mcp.run()
