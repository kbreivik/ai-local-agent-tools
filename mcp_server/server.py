"""FastMCP server exposing Swarm, Kafka, and Orchestration tools."""
import os
import sys

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastmcp import FastMCP

from mcp_server.tools import swarm, kafka, orchestration, elastic
from mcp_server.tools.docker_engine import (
    docker_engine_version,
    docker_engine_check_update,
    docker_engine_update,
)
from mcp_server.tools import ingest as ingest_tools

mcp = FastMCP("HP1-AI-Agent")


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
def service_health(name: str) -> dict:
    """Specific service ready/degraded/failed state."""
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
    """Safe drain before maintenance."""
    return swarm.node_drain(node_id)


@mcp.tool()
def pre_upgrade_check() -> dict:
    """Full swarm readiness gate."""
    return swarm.pre_upgrade_check()


# ── Kafka tools ───────────────────────────────────────────────────────────────

@mcp.tool()
def kafka_broker_status() -> dict:
    """Broker health, leader election state."""
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
def kafka_rolling_restart_safe() -> dict:
    """Checks ISR before each broker restart."""
    return kafka.kafka_rolling_restart_safe()


@mcp.tool()
def pre_kafka_check() -> dict:
    """Full Kafka readiness gate."""
    return kafka.pre_kafka_check()


# ── Orchestration tools ───────────────────────────────────────────────────────

@mcp.tool()
def checkpoint_save(label: str) -> dict:
    """Snapshot current state before risky ops."""
    return orchestration.checkpoint_save(label)


@mcp.tool()
def checkpoint_restore(label: str) -> dict:
    """Rollback to saved state."""
    return orchestration.checkpoint_restore(label)


@mcp.tool()
def audit_log(action: str, result: str) -> dict:
    """Structured log of every agent decision."""
    return orchestration.audit_log(action, result)


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

skill_registry.init_db()
_skill_load_result = skill_loader.load_all_skills(mcp)
_skill_import_result = skill_loader.scan_imports(mcp)


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
    """Update a service's version info. Use after firmware upgrades or discoveries."""
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

@mcp.tool()
def discover_environment(hosts: list) -> dict:
    """Scan hosts and auto-identify services via deterministic fingerprinting.
    Each host: {"address": "192.168.1.1"} or {"address": "...", "port": 8006}.
    Runs 4-phase pipeline: ENUMERATE → IDENTIFY → CATALOG → RECOMMEND.
    Returns identified services, existing skill coverage, and skill_create recommendations.
    No LLM calls — pure HTTP probing against known service fingerprints."""
    return skill_tools.discover_environment(hosts)


@mcp.tool()
def skill_execute(name: str, **kwargs) -> dict:
    """Execute a dynamic skill by name. Call skill_search() first to discover available skills.
    Pass skill parameters as keyword arguments matching the skill's parameter schema.
    Example: skill_execute(name='proxmox_vm_status', node='pve1')"""
    return skill_tools.skill_execute(name, **kwargs)


@mcp.tool()
def validate_skill_live(name: str) -> dict:
    """Run 3-layer validation on a skill: deterministic AST checks (Layer 1),
    live endpoint probing (Layer 2, if api_base available), and LLM critic review
    (Layer 3, if LM Studio available). Use after skill_create or after service upgrades."""
    return skill_tools.validate_skill_live(name)


if __name__ == "__main__":
    mcp.run()
