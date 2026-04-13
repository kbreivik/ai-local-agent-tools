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
