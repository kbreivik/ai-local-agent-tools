# CC PROMPT — v2.21.0 — Time-series metric_samples table

## What this does

Every collector stores only the latest snapshot — there is no historical record of
metrics over time. You cannot query "was disk growing?" or "was Kafka lag rising
before the broker failed?". This adds a `metric_samples` table in PostgreSQL and
writes key metrics on every collector poll. 30-day rolling retention via a cleanup
job. The agent gets a new `metric_trend` tool to query trends. No Elasticsearch
dependency — this works entirely within the existing PostgreSQL setup.

Version bump: 2.20.2 → 2.21.0

---

## Change 1 — NEW FILE: api/db/metric_samples.py

```python
"""Time-series metric samples — one row per collector poll per metric.

Stores numeric metrics from each collector poll. Rolling 30-day retention.
Used for: trend queries, rate-of-change, anomaly detection by the agent.

Schema:
  entity_id   — same as entity_changes (e.g. "ds-docker-worker-01", "kafka_cluster")
  metric_name — dot-separated path (e.g. "disk./.pct", "mem.pct", "kafka.lag.total")
  value       — float
  sampled_at  — timestamp
"""
import logging
import os
from datetime import datetime, timezone

log = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS metric_samples (
    id          BIGSERIAL PRIMARY KEY,
    entity_id   TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    value       DOUBLE PRECISION NOT NULL,
    sampled_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_metric_samples_entity_metric
    ON metric_samples(entity_id, metric_name, sampled_at DESC);
CREATE INDEX IF NOT EXISTS idx_metric_samples_time
    ON metric_samples(sampled_at DESC);
"""

_initialized = False


def _is_pg():
    return "postgres" in os.environ.get("DATABASE_URL", "")


def init_metric_samples():
    global _initialized
    if _initialized:
        return
    if not _is_pg():
        _initialized = True
        return
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        for stmt in _DDL.strip().split(";"):
            s = stmt.strip()
            if s:
                cur.execute(s)
        cur.close()
        conn.close()
        _initialized = True
        log.info("metric_samples table ready")
    except Exception as e:
        log.warning("metric_samples init failed: %s", e)


def write_samples(entity_id: str, metrics: dict[str, float]) -> None:
    """Write a batch of metric samples. Never raises.

    metrics: dict of metric_name → float value
    Example: {"mem.pct": 54.0, "disk./.pct": 29.0, "load.1": 0.48}
    """
    if not _is_pg() or not entity_id or not metrics:
        return
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        now = datetime.now(timezone.utc).isoformat()
        cur.executemany(
            "INSERT INTO metric_samples (entity_id, metric_name, value, sampled_at) "
            "VALUES (%s, %s, %s, %s)",
            [(entity_id, name, float(val), now) for name, val in metrics.items()
             if val is not None]
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        log.debug("write_samples failed (non-fatal): %s", e)


def query_trend(entity_id: str, metric_name: str, hours: int = 24,
                max_points: int = 50) -> list[dict]:
    """Return sampled values for one metric over the last N hours.

    Returns list of {sampled_at, value} dicts, oldest-first.
    Downsamples to max_points evenly if more samples exist.
    """
    if not _is_pg():
        return []
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT sampled_at, value
            FROM metric_samples
            WHERE entity_id = %s
              AND metric_name = %s
              AND sampled_at >= NOW() - INTERVAL '%s hours'
            ORDER BY sampled_at ASC
        """, (entity_id, metric_name, hours))
        rows = [{"sampled_at": r[0].isoformat(), "value": r[1]} for r in cur.fetchall()]
        cur.close()
        conn.close()
        # Downsample if needed
        if len(rows) > max_points:
            step = len(rows) / max_points
            rows = [rows[int(i * step)] for i in range(max_points)]
        return rows
    except Exception as e:
        log.debug("query_trend failed: %s", e)
        return []


def query_latest(entity_id: str, metric_name: str) -> float | None:
    """Return the most recent value for a metric."""
    if not _is_pg():
        return None
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT value FROM metric_samples
            WHERE entity_id = %s AND metric_name = %s
            ORDER BY sampled_at DESC LIMIT 1
        """, (entity_id, metric_name))
        row = cur.fetchone()
        cur.close()
        conn.close()
        return float(row[0]) if row else None
    except Exception as e:
        log.debug("query_latest failed: %s", e)
        return None


def compute_rate_of_change(entity_id: str, metric_name: str,
                           hours: int = 6) -> dict | None:
    """Compute rate of change per hour for a metric over the last N hours.

    Returns: {rate_per_hour, first_value, last_value, sample_count,
              trend: 'rising'|'falling'|'stable'}
    Returns None if fewer than 3 samples.
    """
    rows = query_trend(entity_id, metric_name, hours=hours, max_points=100)
    if len(rows) < 3:
        return None
    first_val = rows[0]["value"]
    last_val = rows[-1]["value"]
    # Approximate hours between first and last sample
    try:
        from datetime import datetime as _dt
        t0 = _dt.fromisoformat(rows[0]["sampled_at"])
        t1 = _dt.fromisoformat(rows[-1]["sampled_at"])
        elapsed_h = (t1 - t0).total_seconds() / 3600
    except Exception:
        elapsed_h = hours
    if elapsed_h < 0.01:
        return None
    rate = (last_val - first_val) / elapsed_h
    change = abs(last_val - first_val)
    trend = "stable" if change < 2 else ("rising" if rate > 0 else "falling")
    return {
        "rate_per_hour": round(rate, 3),
        "first_value": round(first_val, 2),
        "last_value": round(last_val, 2),
        "sample_count": len(rows),
        "trend": trend,
        "hours_covered": round(elapsed_h, 1),
    }


def cleanup_old_samples(days: int = 30) -> int:
    """Delete samples older than N days. Returns count deleted."""
    if not _is_pg():
        return 0
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM metric_samples WHERE sampled_at < NOW() - INTERVAL '%s days'",
            (days,)
        )
        n = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        return n
    except Exception as e:
        log.debug("cleanup_old_samples failed: %s", e)
        return 0
```

---

## Change 2 — api/main.py

Init the table and schedule daily cleanup. Find where `init_vm_action_log()` is called
(or any other init call in the lifespan) and add:

```python
from api.db.metric_samples import init_metric_samples
init_metric_samples()
```

Also schedule cleanup in the lifespan. Find where the scheduler or startup tasks run
(look for `start_auto_update()` or similar) and add after startup:

```python
# Schedule daily metric cleanup
import asyncio as _asyncio
async def _daily_metric_cleanup():
    import asyncio
    while True:
        await asyncio.sleep(86400)
        try:
            from api.db.metric_samples import cleanup_old_samples
            n = cleanup_old_samples(days=30)
            if n:
                log.info("metric_samples cleanup: deleted %d rows older than 30d", n)
        except Exception as _e:
            log.debug("metric_samples cleanup failed: %s", _e)
_asyncio.create_task(_daily_metric_cleanup())
```

---

## Change 3 — api/collectors/vm_hosts.py

In `_poll_one_vm()`, after the entity_history change detection block, add metric samples:

Find the comment:
```python
        # ── Change detection ──────────────────────────────────────────────────
```

After the entire change detection `try/except` block, add:

```python
        # ── Metric samples (time-series) ──────────────────────────────────────
        try:
            from api.db.metric_samples import write_samples
            metrics: dict = {}
            if result.get("mem_pct") is not None:
                metrics["mem.pct"] = float(result["mem_pct"])
            if result.get("load_1") is not None:
                metrics["load.1m"] = float(result["load_1"])
            if result.get("load_5") is not None:
                metrics["load.5m"] = float(result["load_5"])
            for disk in result.get("disks", []):
                mp = disk.get("mountpoint", "").replace("/", "_").strip("_") or "root"
                if disk.get("usage_pct") is not None:
                    metrics[f"disk.{mp}.pct"] = float(disk["usage_pct"])
                if disk.get("used_bytes") is not None:
                    metrics[f"disk.{mp}.used_gb"] = round(disk["used_bytes"] / 1e9, 3)
            if metrics:
                write_samples(label, metrics)
        except Exception as _me:
            log.debug("metric_samples write failed (non-fatal): %s", _me)
```

---

## Change 4 — api/collectors/kafka.py

In `_collect_sync()`, before the final `return` statement, add metric samples.

Find the last `return {` in `_collect_sync` and before it add:

```python
            # ── Metric samples (time-series) ──────────────────────────────────
            try:
                from api.db.metric_samples import write_samples
                kafka_metrics: dict = {
                    "brokers.alive": float(alive),
                    "brokers.expected": float(expected),
                    "partitions.under_replicated": float(under_replicated_total),
                }
                # Total consumer lag across all groups
                total_lag = sum(v.get("total_lag", 0) for v in group_lag.values())
                kafka_metrics["consumer.lag.total"] = float(total_lag)
                write_samples("kafka_cluster", kafka_metrics)
            except Exception as _me:
                log.debug("kafka metric_samples write failed: %s", _me)
```

---

## Change 5 — api/collectors/swarm.py

In `_collect_sync()`, before the final `return` dict, add:

```python
            # ── Metric samples ────────────────────────────────────────────────
            try:
                from api.db.metric_samples import write_samples
                swarm_metrics: dict = {
                    "nodes.total": float(len(node_data)),
                    "nodes.active_managers": float(active_managers),
                    "services.total": float(len(svc_data)),
                    "services.degraded": float(len(degraded_services)),
                    "services.failed": float(len(failed_services)),
                }
                write_samples("swarm_cluster", swarm_metrics)
            except Exception as _me:
                log.debug("swarm metric_samples write failed: %s", _me)
```

---

## Change 6 — mcp_server/tools/ — NEW FILE: metric_tools.py

```python
"""Agent tools for querying time-series metric trends."""
from datetime import datetime, timezone


def _ts():
    return datetime.now(timezone.utc).isoformat()


def metric_trend(entity_id: str, metric_name: str, hours: int = 24) -> dict:
    """Query historical metric samples for an entity.

    Returns time-series values and trend analysis (rising/falling/stable).
    Use to answer: "is disk growing?", "was lag rising before the failure?",
    "is memory steadily climbing on worker-01?"

    Args:
        entity_id:   Entity label (e.g. "ds-docker-worker-01", "kafka_cluster",
                     "swarm_cluster")
        metric_name: Metric path (e.g. "disk.root.pct", "mem.pct", "load.1m",
                     "kafka.lag.total", "consumer.lag.total",
                     "partitions.under_replicated", "brokers.alive")
        hours:       Look-back window in hours (default 24, max 168)
    """
    hours = min(max(1, hours), 168)
    try:
        from api.db.metric_samples import query_trend, compute_rate_of_change
        samples = query_trend(entity_id, metric_name, hours=hours)
        rate = compute_rate_of_change(entity_id, metric_name, hours=min(hours, 6))

        if not samples:
            return {
                "status": "ok",
                "message": f"No samples for {entity_id}/{metric_name} in last {hours}h",
                "data": {"samples": [], "rate": None, "available_hours": 0},
                "timestamp": _ts(),
            }

        return {
            "status": "ok",
            "message": (
                f"{len(samples)} samples for {entity_id}/{metric_name} over {hours}h. "
                + (f"Trend: {rate['trend']} ({rate['rate_per_hour']:+.2f}/h)" if rate else "")
            ),
            "data": {
                "entity_id": entity_id,
                "metric_name": metric_name,
                "hours": hours,
                "sample_count": len(samples),
                "samples": samples[-20:],  # last 20 for context
                "first_value": samples[0]["value"] if samples else None,
                "last_value": samples[-1]["value"] if samples else None,
                "rate_of_change": rate,
            },
            "timestamp": _ts(),
        }
    except Exception as e:
        return {"status": "error", "message": f"metric_trend error: {e}",
                "data": None, "timestamp": _ts()}


def list_metrics(entity_id: str) -> dict:
    """List all available metric names for an entity.

    Args:
        entity_id: Entity label (blank to list all known entities)
    """
    try:
        from api.connections import _get_conn
        import os
        if "postgres" not in os.environ.get("DATABASE_URL", ""):
            return {"status": "ok", "message": "metrics not available (no postgres)",
                    "data": {"metrics": []}, "timestamp": _ts()}

        conn = _get_conn()
        cur = conn.cursor()
        if entity_id:
            cur.execute("""
                SELECT DISTINCT metric_name, MAX(sampled_at) as last_seen,
                       COUNT(*) as sample_count
                FROM metric_samples
                WHERE entity_id = %s AND sampled_at >= NOW() - INTERVAL '48 hours'
                GROUP BY metric_name
                ORDER BY metric_name
            """, (entity_id,))
        else:
            cur.execute("""
                SELECT DISTINCT entity_id, COUNT(DISTINCT metric_name) as metric_count,
                       MAX(sampled_at) as last_seen
                FROM metric_samples
                WHERE sampled_at >= NOW() - INTERVAL '48 hours'
                GROUP BY entity_id
                ORDER BY entity_id
            """)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.close()
        conn.close()
        for r in rows:
            for k in ("last_seen",):
                if r.get(k) and hasattr(r[k], "isoformat"):
                    r[k] = r[k].isoformat()
        return {
            "status": "ok",
            "message": f"{len(rows)} {'metrics' if entity_id else 'entities'} found",
            "data": {"metrics" if entity_id else "entities": rows},
            "timestamp": _ts(),
        }
    except Exception as e:
        return {"status": "error", "message": f"list_metrics error: {e}",
                "data": None, "timestamp": _ts()}
```

---

## Change 7 — mcp_server/server.py

Register the two new tools. Add before the final `if __name__ == "__main__":` block:

```python
@mcp.tool()
def metric_trend(entity_id: str, metric_name: str, hours: int = 24) -> dict:
    """Query time-series metric history for infrastructure entities.
    Returns samples + trend analysis (rising/falling/stable, rate per hour).
    Entities: vm host labels, 'kafka_cluster', 'swarm_cluster'.
    Metrics: 'mem.pct', 'load.1m', 'disk.root.pct', 'consumer.lag.total',
             'brokers.alive', 'partitions.under_replicated'.
    Use to answer: 'is disk growing?', 'was lag rising before the failure?'
    Example: metric_trend('ds-docker-worker-01', 'mem.pct', hours=12)
    """
    from mcp_server.tools.metric_tools import metric_trend as _mt
    return _mt(entity_id=entity_id, metric_name=metric_name, hours=hours)


@mcp.tool()
def list_metrics(entity_id: str = "") -> dict:
    """List available time-series metrics for an entity (or all entities if blank).
    Use before metric_trend() to discover what metrics are available.
    Example: list_metrics('ds-docker-worker-01')
    """
    from mcp_server.tools.metric_tools import list_metrics as _lm
    return _lm(entity_id=entity_id)
```

---

## Change 8 — api/agents/router.py

Add `metric_trend` and `list_metrics` to OBSERVE_AGENT_TOOLS and INVESTIGATE_AGENT_TOOLS:

Find:
```python
    "swarm_node_status",
    "service_placement",
})
```
(closing of OBSERVE_AGENT_TOOLS)

Replace with:
```python
    "swarm_node_status",
    "service_placement",
    "metric_trend",
    "list_metrics",
})
```

Apply the same addition to INVESTIGATE_AGENT_TOOLS (find its closing `"service_placement",` and add the two tools after it).

Also add a METRIC TREND GUIDANCE section to STATUS_PROMPT and RESEARCH_PROMPT.

In STATUS_PROMPT, after the KAFKA INVESTIGATION section, add:

```
METRIC TREND QUERIES:
When asked if something is growing, rising, or trending:
  metric_trend(entity_id="ds-docker-worker-01", metric_name="disk.root.pct", hours=24)
  metric_trend(entity_id="kafka_cluster", metric_name="consumer.lag.total", hours=6)
  metric_trend(entity_id="swarm_cluster", metric_name="services.failed", hours=12)
Use list_metrics(entity_id="...") to see what metrics are available for an entity.
Available metrics by entity type:
  VM hosts: mem.pct, load.1m, load.5m, disk.<mount>.pct, disk.<mount>.used_gb
  kafka_cluster: brokers.alive, partitions.under_replicated, consumer.lag.total
  swarm_cluster: nodes.total, services.degraded, services.failed
```

Add the same section to RESEARCH_PROMPT after rule 5c.

---

## Do NOT touch

- Any frontend files
- Any other router

---

## Version bump

Update `VERSION`: `2.20.2` → `2.21.0`

---

## Commit

```bash
git add -A
git commit -m "feat(data): v2.21.0 time-series metric_samples table + metric_trend agent tool

- api/db/metric_samples.py: metric_samples table (entity_id, metric_name, value, sampled_at)
- vm_hosts collector: writes mem.pct, load.1m/5m, disk.*.pct/used_gb per host per poll
- kafka collector: writes brokers.alive, under_replicated, consumer.lag.total per poll
- swarm collector: writes nodes.total, services.degraded/failed per poll
- 30-day rolling retention via daily cleanup task in main.py lifespan
- mcp_server/tools/metric_tools.py: metric_trend() + list_metrics() tools
- metric_trend: returns samples + rate-of-change (rate/h, trend: rising/falling/stable)
- Both tools added to OBSERVE and INVESTIGATE agent allowlists
- STATUS_PROMPT + RESEARCH_PROMPT: METRIC TREND QUERIES guidance section
- Enables: 'is disk growing?', 'was lag rising before the failure?'"
git push origin main
```
