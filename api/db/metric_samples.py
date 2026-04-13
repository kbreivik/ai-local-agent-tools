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
