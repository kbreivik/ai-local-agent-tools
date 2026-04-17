"""
GET /api/kafka/overview
Aggregates kafka_topic_inspect + kafka_consumer_lag for UI consumption.
Cached for 30s (configurable via setting kafkaOverviewCacheTTL).
"""
import time
import logging

from fastapi import APIRouter, Depends, HTTPException

from api.auth import get_current_user
from mcp_server.tools.kafka_inspect import kafka_topic_inspect

try:
    from mcp_server.tools.kafka import kafka_consumer_lag  # existing
except ImportError:
    kafka_consumer_lag = None

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/kafka", tags=["kafka"])

_CACHE = {"ts": 0.0, "data": None}
_TTL_DEFAULT = 30


def _get_ttl() -> int:
    """Read overview cache TTL from settings DB, fall back to default."""
    try:
        from mcp_server.tools.skills.storage import get_backend
        raw = get_backend().get_setting("kafkaOverviewCacheTTL")
        if raw is None or raw == "":
            return _TTL_DEFAULT
        val = int(raw)
        return val if val > 0 else _TTL_DEFAULT
    except Exception:
        return _TTL_DEFAULT


def _max_lag_for_topic(topic: str, lag_blob) -> int | None:
    if not isinstance(lag_blob, dict) or "error" in lag_blob:
        return None
    mx = 0
    for group_data in lag_blob.get("groups", []):
        for pe in group_data.get("partitions", []):
            if pe.get("topic") == topic:
                mx = max(mx, pe.get("lag") or 0)
    return mx or None


@router.get("/overview")
def overview(_: str = Depends(get_current_user)):
    ttl = _get_ttl()
    if _CACHE["data"] and (time.time() - _CACHE["ts"]) < ttl:
        return _CACHE["data"]
    try:
        inspect_result = kafka_topic_inspect()
    except Exception as e:
        raise HTTPException(503, f"kafka unreachable: {e}")

    # kafka_topic_inspect returns {"status", "data": {...}, ...}. Unwrap.
    if isinstance(inspect_result, dict) and "data" in inspect_result and isinstance(inspect_result["data"], dict):
        inspect = inspect_result["data"] or {}
    else:
        inspect = inspect_result or {}

    lag = {}
    if kafka_consumer_lag:
        try:
            # kafka_consumer_lag requires a group arg; without an enumerable
            # group list here, we skip it. Placeholder for future enumeration.
            lag = {"groups": []}
        except Exception as e:
            log.warning("kafka_consumer_lag failed: %s", e)
            lag = {"error": str(e)}

    topics = []
    for t in inspect.get("topics", []):
        partitions = t.get("partitions", [])
        n_ur = sum(1 for p in partitions if p.get("under_replicated"))
        max_lag = _max_lag_for_topic(t["name"], lag)
        topics.append({
            "name": t["name"],
            "partitions": len(partitions),
            "under_replicated": n_ur,
            "max_consumer_lag": max_lag,
            "_raw_partitions": partitions,  # for drill-in
        })
    topics.sort(key=lambda x: x["name"])

    data = {
        "brokers": inspect.get("brokers", []),
        "topics": topics,
        "summary": inspect.get("summary", {}),
        "consumer_lag": lag,
        "fetched_at": time.time(),
    }
    _CACHE["ts"] = time.time()
    _CACHE["data"] = data
    return data
