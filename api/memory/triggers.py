"""
Semantic memory triggers — watch for known bad patterns in infrastructure state
and store targeted engrams + fire alerts.

Registered via after_status_snapshot hook in collectors.
"""
import logging

from api.memory.client import get_client

log = logging.getLogger(__name__)

# ── Trigger definitions ───────────────────────────────────────────────────────
# Each trigger: (component, condition_fn, concept, content_fn, tags)

_KAFKA_LAG_THRESHOLD = 1000


def _kafka_triggers(state: dict) -> list[tuple[str, str, list[str]]]:
    """Kafka-specific triggers — lag and under-replicated partitions."""
    results = []
    lag_data = state.get("consumer_lag", {})
    for group, info in lag_data.items():
        total_lag = info.get("total_lag", 0) if isinstance(info, dict) else 0
        if total_lag > _KAFKA_LAG_THRESHOLD:
            results.append((
                f"kafka_lag:{group}",
                f"Consumer group '{group}' lag={total_lag} exceeds threshold {_KAFKA_LAG_THRESHOLD}. "
                f"Action: check consumer health, inspect topic throughput, consider scaling consumers.",
                ["kafka", "lag", "alert", group],
            ))
    urp = state.get("under_replicated_partitions", 0)
    if urp > 0:
        results.append((
            "kafka:under_replicated_partitions",
            f"Kafka cluster has {urp} under-replicated partition(s). "
            f"Action: check broker connectivity, disk space, and replication factor.",
            ["kafka", "replication", "alert"],
        ))
    return results


def _swarm_triggers(state: dict) -> list[tuple[str, str, list[str]]]:
    """Docker Swarm triggers — failed services, manager quorum loss."""
    results = []
    failed = state.get("failed_services", [])
    # failed_services may be a list of names or an integer count
    failed_list = failed if isinstance(failed, list) else []
    failed_count = len(failed_list) if isinstance(failed, list) else (failed if isinstance(failed, int) else 0)
    if failed_count > 0:
        results.append((
            "swarm:failed_services",
            f"{failed_count} Swarm service(s) not at desired replica count: {', '.join(failed_list[:5])}. "
            f"Action: inspect service logs, check node availability, consider drain/force-update.",
            ["swarm", "services", "alert"],
        ))
    active_mgr = state.get("active_managers", 0)
    mgr_count = state.get("manager_count", 0)
    if mgr_count > 1 and active_mgr < (mgr_count // 2 + 1):
        results.append((
            "swarm:manager_quorum_loss",
            f"Swarm manager quorum at risk: {active_mgr}/{mgr_count} managers active. "
            f"Raft consensus requires majority. Action: recover manager nodes immediately.",
            ["swarm", "managers", "critical"],
        ))
    return results


def _elastic_triggers(state: dict) -> list[tuple[str, str, list[str]]]:
    """Elasticsearch triggers — red cluster, unassigned shards."""
    results = []
    health = state.get("health", "unknown")
    if health == "critical":  # mapped from ES 'red'
        shards = state.get("shards", {})
        unassigned = shards.get("unassigned", 0)
        results.append((
            "elasticsearch:cluster_red",
            f"Elasticsearch cluster is RED with {unassigned} unassigned shard(s). "
            f"Action: check node availability, disk space, shard allocation settings.",
            ["elasticsearch", "shards", "critical"],
        ))
    return results


# ── Public interface ──────────────────────────────────────────────────────────

async def evaluate_triggers(component: str, state: dict) -> None:
    """
    Evaluate semantic triggers for the given component state.
    Stores matched patterns as engrams with remediation guidance.
    """
    if state.get("health") in ("unconfigured", "unknown"):
        return

    engrams: list[tuple[str, str, list[str]]] = []
    if component == "kafka_cluster":
        engrams = _kafka_triggers(state)
    elif component == "swarm":
        engrams = _swarm_triggers(state)
    elif component == "elasticsearch":
        engrams = _elastic_triggers(state)

    if not engrams:
        return

    client = get_client()
    for concept, content, tags in engrams:
        try:
            await client.store(concept, content, tags)
            log.debug("Memory trigger fired: %s", concept)
        except Exception as e:
            log.debug("Memory trigger store failed (%s): %s", concept, e)
