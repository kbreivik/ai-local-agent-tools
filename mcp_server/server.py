"""FastMCP server exposing Swarm, Kafka, and Orchestration tools."""
import os
import sys

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastmcp import FastMCP

from mcp_server.tools import swarm, kafka, orchestration, elastic

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
def service_resolve_image(image: str) -> dict:
    """Resolve latest stable semver tag for an image from Docker Hub."""
    return swarm.service_resolve_image(image)


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


if __name__ == "__main__":
    mcp.run()
