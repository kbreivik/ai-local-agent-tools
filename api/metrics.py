"""
Central Prometheus metric definitions and /metrics exposition.
Keep naming stable: deathstar_<area>_<unit>_<suffix>.
"""
from prometheus_client import (
    Counter, Histogram, Gauge, Info,
    CONTENT_TYPE_LATEST, generate_latest, CollectorRegistry, REGISTRY,
)

# --- collectors ---
COLLECTOR_POLL_SECONDS = Histogram(
    "deathstar_collector_poll_seconds",
    "Collector poll duration",
    ["platform"],
    buckets=(0.1, 0.5, 1, 2, 5, 10, 20, 30, 60),
)
COLLECTOR_POLL_FAILURES = Counter(
    "deathstar_collector_poll_failures_total",
    "Collector poll failures",
    ["platform", "reason"],
)

# --- agent ---
AGENT_TASKS = Counter(
    "deathstar_agent_tasks_total",
    "Agent tasks by type and terminal status",
    ["agent_type", "status"],   # status: success, escalated, budget_exhausted, failed
)
AGENT_TOOL_CALLS = Counter(
    "deathstar_agent_tool_calls_total",
    "Tool calls made by agents",
    ["agent_type", "tool"],
)
AGENT_WALL_SECONDS = Histogram(
    "deathstar_agent_task_seconds",
    "Agent task wall-clock time",
    ["agent_type"],
    buckets=(1, 5, 10, 30, 60, 120, 300, 600),
)

# --- escalations ---
ESCALATIONS = Counter(
    "deathstar_escalations_total",
    "Escalations raised",
    ["reason"],
)

# --- kafka ---
KAFKA_UNDER_REPLICATED = Gauge(
    "deathstar_kafka_under_replicated_partitions",
    "Partitions where ISR != replicas",
    ["topic"],
)
KAFKA_BROKERS_UP = Gauge(
    "deathstar_kafka_brokers_up",
    "Reachable brokers in cluster",
)

# --- build info ---
BUILD = Info("deathstar_build", "Build metadata")


def render_metrics() -> tuple[bytes, str]:
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
