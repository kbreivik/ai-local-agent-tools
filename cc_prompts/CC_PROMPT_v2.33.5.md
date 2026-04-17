# CC PROMPT — v2.33.5 — Prometheus /metrics endpoint

## What this does
Exposes DEATHSTAR internals as Prometheus metrics at `GET /metrics`. No auth
(bind same port, no sensitive values). Enables external alerting
("is agent-01 alive?") and trend analysis (collector latency, agent task
volume, escalation rate, Kafka ISR).

Version bump: 2.33.4 → 2.33.5

## Change 1 — requirements.txt

Ensure:
```
prometheus_client>=0.19.0
```

## Change 2 — api/metrics.py — new module

```python
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
```

## Change 3 — api/main.py — mount /metrics

```python
from fastapi import Response
from api.metrics import render_metrics, BUILD

# early in lifespan, set build info once
with open("VERSION") as f:
    BUILD.info({"version": f.read().strip()})

@app.get("/metrics")
async def metrics():
    body, ctype = render_metrics()
    return Response(content=body, media_type=ctype)
```

The route is intentionally unauthenticated (same pattern as healthchecks
in the existing codebase). If `agentHostIp` is set and the node is behind
a reverse proxy, document that the operator can restrict by IP at that layer.

## Change 4 — api/collectors/manager.py — instrument trigger_poll

Wrap `trigger_poll` (or the per-collector poll body) with the histogram:

```python
from api.metrics import COLLECTOR_POLL_SECONDS, COLLECTOR_POLL_FAILURES

async def trigger_poll(self, platform: str, *args, **kwargs):
    with COLLECTOR_POLL_SECONDS.labels(platform=platform).time():
        try:
            return await self._do_poll(platform, *args, **kwargs)
        except Exception as e:
            COLLECTOR_POLL_FAILURES.labels(
                platform=platform,
                reason=type(e).__name__
            ).inc()
            raise
```

## Change 5 — api/routers/agent.py — count tasks + tool calls + wall time

In the agent task lifecycle:

```python
from api.metrics import AGENT_TASKS, AGENT_TOOL_CALLS, AGENT_WALL_SECONDS
import time

# on task start:
_t0 = time.monotonic()

# on every tool call:
AGENT_TOOL_CALLS.labels(agent_type=agent_type, tool=tool_name).inc()

# on task end (all paths — success, escalated, budget_exhausted, failed):
AGENT_TASKS.labels(agent_type=agent_type, status=terminal_status).inc()
AGENT_WALL_SECONDS.labels(agent_type=agent_type).observe(time.monotonic() - _t0)
```

## Change 6 — api/routers/escalations.py — count escalations

```python
from api.metrics import ESCALATIONS
# on record_escalation:
ESCALATIONS.labels(reason=reason_code or "unspecified").inc()
```

## Change 7 — api/collectors/kafka hook — update kafka gauges

If a kafka collector (or kafka_overview cache) exists, after each refresh:

```python
from api.metrics import KAFKA_UNDER_REPLICATED, KAFKA_BROKERS_UP
for topic, n_ur in per_topic_under_replicated.items():
    KAFKA_UNDER_REPLICATED.labels(topic=topic).set(n_ur)
KAFKA_BROKERS_UP.set(len(reachable_brokers))
```

If no kafka collector exists yet, defer this change and leave gauges at 0 — they
will be populated by cycle 8's Kafka tab backend.

## Version bump
Update `VERSION`: 2.33.4 → 2.33.5

## Commit
```
git add -A
git commit -m "feat(ops): v2.33.5 Prometheus /metrics endpoint"
git push origin main
```

## How to test after push
1. Redeploy.
2. `curl -s http://192.168.199.10:8000/metrics | grep deathstar_` → expect several families.
3. Trigger a collector poll → `deathstar_collector_poll_seconds_bucket{platform="proxmox"}` counts increment.
4. Run an agent task → `deathstar_agent_tasks_total{agent_type="observe", status="success"}` ticks.
5. Optional: point a local Prometheus at the endpoint and confirm a 5-min scrape stream.
