"""
GET /api/elastic — Elasticsearch log access endpoints.
All endpoints gracefully return {available: false} when ELASTIC_URL not set.
Correlation endpoint bridges PostgreSQL operations ↔ Elasticsearch logs.
"""
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, HTTPException, Query

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/elastic", tags=["elastic"])

_ES_URL = lambda: os.environ.get("ELASTIC_URL", "").rstrip("/")
_INDEX = lambda: os.environ.get("ELASTIC_INDEX_PATTERN", "hp1-logs-*")
_STALE_MIN = lambda: int(os.environ.get("ELASTIC_FILEBEAT_STALE_MINUTES", "10"))


def _unavailable():
    return {"available": False, "message": "ELASTIC_URL not configured"}


async def _get(path: str, params: dict | None = None) -> dict:
    url = _ES_URL()
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(f"{url}{path}", params=params)
        r.raise_for_status()
        return r.json()


async def _post(path: str, body: dict) -> dict:
    url = _ES_URL()
    async with httpx.AsyncClient(timeout=15.0) as c:
        r = await c.post(f"{url}{path}", json=body)
        r.raise_for_status()
        return r.json()


def _time_range(minutes_ago: int) -> dict:
    since = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()
    return {"range": {"@timestamp": {"gte": since}}}


def _extract_hits(resp: dict) -> list[dict]:
    hits = resp.get("hits", {}).get("hits", [])
    results = []
    for h in hits:
        src = h.get("_source", {})
        results.append({
            "id": h.get("_id"),
            "index": h.get("_index"),
            "timestamp": src.get("@timestamp"),
            "message": src.get("message", ""),
            "level": (
                src.get("log", {}).get("level")
                or src.get("log.level", "info")
            ),
            "hostname": src.get("host", {}).get("name", src.get("host.name", "")),
            "container": src.get("container", {}).get("name", src.get("container.name", "")),
            "service": (
                src.get("docker", {}).get("container", {}).get("labels", {})
                   .get("com.docker.swarm.service.name", "")
                or src.get("container.labels", {}).get("com.docker.swarm.service.name", "")
            ),
            "node_role": src.get("hp1_node_role", ""),
        })
    return results


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/health")
async def elastic_health():
    """Elasticsearch cluster health summary."""
    if not _ES_URL():
        return _unavailable()
    try:
        health = await _get("/_cluster/health")
        stats = await _get("/_cluster/stats", {
            "filter_path": "nodes.count,indices.count,indices.docs,indices.store"
        })
        return {
            "available": True,
            "cluster_name": health.get("cluster_name"),
            "status": health.get("status"),
            "nodes": health.get("number_of_nodes", 0),
            "active_shards": health.get("active_shards", 0),
            "unassigned_shards": health.get("unassigned_shards", 0),
            "indices_count": stats.get("indices", {}).get("count", 0),
            "docs_count": stats.get("indices", {}).get("docs", {}).get("count", 0),
        }
    except Exception as e:
        return {"available": False, "error": str(e)}


@router.get("/logs")
async def elastic_logs(
    service: str = Query(""),
    node: str = Query(""),
    level: str = Query(""),
    q: str = Query(""),
    minutes_ago: int = Query(5, ge=1, le=10080),
    size: int = Query(100, ge=1, le=500),
):
    """Recent log lines from Elasticsearch. Filters: service, node, level, keyword."""
    if not _ES_URL():
        return _unavailable()
    try:
        must = [_time_range(minutes_ago)]
        if q:
            must.append({"match": {"message": {"query": q, "operator": "or"}}})
        if service:
            must.append({"bool": {"should": [
                {"wildcard": {
                    "docker.container.labels.com.docker.swarm.service.name": f"*{service}*"
                }},
                {"wildcard": {"container.name": f"*{service}*"}},
            ], "minimum_should_match": 1}})
        if node:
            must.append({"wildcard": {"host.name": f"*{node}*"}})
        if level:
            must.append({"term": {"log.level": level}})

        body = {
            "query": {"bool": {"must": must}},
            "sort": [{"@timestamp": {"order": "desc"}}],
            "size": size,
            "_source": [
                "@timestamp", "message", "log.level", "host.name", "container.name",
                "hp1_node_role",
                "docker.container.labels.com.docker.swarm.service.name",
            ],
        }
        resp = await _post(f"/{_INDEX()}/_search", body)
        hits = _extract_hits(resp)
        total = resp.get("hits", {}).get("total", {}).get("value", len(hits))
        return {"available": True, "total": total, "returned": len(hits), "logs": hits}
    except Exception as e:
        raise HTTPException(502, f"Elasticsearch error: {e}")


@router.get("/errors")
async def elastic_errors(
    service: str = Query(""),
    minutes_ago: int = Query(30, ge=1, le=1440),
):
    """Error and critical log lines, grouped by service."""
    if not _ES_URL():
        return _unavailable()
    try:
        must = [
            _time_range(minutes_ago),
            {"terms": {"log.level": ["error", "critical", "ERROR", "CRITICAL", "FATAL"]}},
        ]
        if service:
            must.append({"bool": {"should": [
                {"wildcard": {
                    "docker.container.labels.com.docker.swarm.service.name": f"*{service}*"
                }},
                {"wildcard": {"container.name": f"*{service}*"}},
            ], "minimum_should_match": 1}})

        body = {
            "query": {"bool": {"must": must}},
            "sort": [{"@timestamp": {"order": "desc"}}],
            "size": 100,
            "aggs": {
                "by_service": {
                    "terms": {
                        "field": "docker.container.labels.com.docker.swarm.service.name",
                        "size": 20,
                    }
                }
            },
            "_source": [
                "@timestamp", "message", "log.level", "host.name", "container.name",
                "docker.container.labels.com.docker.swarm.service.name",
            ],
        }
        resp = await _post(f"/{_INDEX()}/_search", body)
        hits = _extract_hits(resp)
        total = resp.get("hits", {}).get("total", {}).get("value", len(hits))
        by_service = {
            b["key"]: b["doc_count"]
            for b in resp.get("aggregations", {}).get("by_service", {}).get("buckets", [])
        }
        return {
            "available": True,
            "error_count": total,
            "by_service": by_service,
            "errors": hits,
        }
    except Exception as e:
        raise HTTPException(502, f"Elasticsearch error: {e}")


@router.get("/pattern/{service}")
async def elastic_pattern(
    service: str,
    hours: int = Query(24, ge=1, le=168),
):
    """Error rate over time for a service (hourly buckets). Flags anomalies."""
    if not _ES_URL():
        return _unavailable()
    try:
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        must = [{"range": {"@timestamp": {"gte": since}}}]
        if service:
            must.append({"bool": {"should": [
                {"wildcard": {
                    "docker.container.labels.com.docker.swarm.service.name": f"*{service}*"
                }},
                {"wildcard": {"container.name": f"*{service}*"}},
            ], "minimum_should_match": 1}})

        body = {
            "query": {"bool": {"must": must}},
            "size": 0,
            "aggs": {
                "by_hour": {
                    "date_histogram": {
                        "field": "@timestamp",
                        "calendar_interval": "hour",
                    },
                    "aggs": {
                        "errors": {
                            "filter": {
                                "terms": {"log.level": [
                                    "error", "critical", "ERROR", "CRITICAL"
                                ]}
                            }
                        }
                    },
                }
            },
        }
        resp = await _post(f"/{_INDEX()}/_search", body)
        buckets = resp.get("aggregations", {}).get("by_hour", {}).get("buckets", [])
        hourly = [
            {
                "hour": b["key_as_string"],
                "total": b["doc_count"],
                "errors": b["errors"]["doc_count"],
            }
            for b in buckets
        ]

        error_rates = [h["errors"] for h in hourly if h["total"] > 0]
        anomaly = False
        anomaly_reason = ""
        if len(error_rates) >= 2:
            avg = sum(error_rates[:-1]) / len(error_rates[:-1])
            current = error_rates[-1]
            if avg > 0 and current > 2 * avg:
                anomaly = True
                anomaly_reason = f"Current hour {current} errors vs avg {avg:.1f}"

        return {
            "available": True,
            "service": service,
            "hours": hours,
            "hourly": hourly,
            "total_errors": sum(h["errors"] for h in hourly),
            "anomaly": anomaly,
            "anomaly_reason": anomaly_reason,
        }
    except Exception as e:
        raise HTTPException(502, f"Elasticsearch error: {e}")


@router.get("/kafka")
async def elastic_kafka(
    broker_id: str = Query(""),
    minutes_ago: int = Query(60, ge=1, le=1440),
):
    """Kafka broker log events — leader elections, ISR changes, offline partitions."""
    if not _ES_URL():
        return _unavailable()
    try:
        must = [
            _time_range(minutes_ago),
            {"bool": {"should": [
                {"wildcard": {"container.name": "*kafka*"}},
                {"wildcard": {
                    "docker.container.labels.com.docker.swarm.service.name": "*kafka*"
                }},
            ], "minimum_should_match": 1}},
        ]
        if broker_id:
            must.append({"match": {"message": broker_id}})

        body = {
            "query": {"bool": {"must": must}},
            "sort": [{"@timestamp": {"order": "desc"}}],
            "size": 100,
            "_source": ["@timestamp", "message", "log.level", "host.name", "container.name"],
        }
        resp = await _post(f"/{_INDEX()}/_search", body)
        hits = _extract_hits(resp)
        total = resp.get("hits", {}).get("total", {}).get("value", len(hits))

        events = []
        for h in hits:
            msg = h.get("message", "")
            kind = "general"
            if "LeaderElection" in msg:
                kind = "leader_election"
            elif "ISR" in msg:
                kind = "isr_change"
            elif "OfflinePartitions" in msg:
                kind = "offline_partitions"
            elif "UnderReplicated" in msg:
                kind = "under_replicated"
            elif h.get("level", "").lower() in ("error", "critical"):
                kind = "error"
            events.append({**h, "event_type": kind})

        return {
            "available": True,
            "total": total,
            "events": events,
        }
    except Exception as e:
        raise HTTPException(502, f"Elasticsearch error: {e}")


@router.get("/stats")
async def elastic_stats():
    """hp1-logs-* index sizes, doc counts, Filebeat ingest freshness."""
    if not _ES_URL():
        return _unavailable()
    try:
        stale_min = _STALE_MIN()
        stats_resp = await _get(f"/{_INDEX()}/_stats/docs,store")
        indices_info = []
        total_docs = 0
        total_bytes = 0

        for idx_name, idx_data in stats_resp.get("indices", {}).items():
            docs = idx_data.get("primaries", {}).get("docs", {}).get("count", 0)
            store = idx_data.get("primaries", {}).get("store", {}).get("size_in_bytes", 0)
            total_docs += docs
            total_bytes += store
            indices_info.append({"index": idx_name, "docs": docs, "size_bytes": store})

        indices_info.sort(key=lambda x: x["index"], reverse=True)

        # Last document timestamp
        last_doc_resp = await _post(f"/{_INDEX()}/_search", {
            "query": {"match_all": {}},
            "sort": [{"@timestamp": {"order": "desc"}}],
            "size": 1,
            "_source": ["@timestamp"],
        })
        last_hits = last_doc_resp.get("hits", {}).get("hits", [])
        last_ts = None
        stale = True
        if last_hits:
            last_ts = last_hits[0].get("_source", {}).get("@timestamp")
            if last_ts:
                try:
                    last_dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
                    age_min = (datetime.now(timezone.utc) - last_dt).total_seconds() / 60
                    stale = age_min > stale_min
                except Exception:
                    pass

        return {
            "available": True,
            "indices": indices_info,
            "total_docs": total_docs,
            "total_size_bytes": total_bytes,
            "last_ingest": last_ts,
            "filebeat_active": not stale,
            "stale": stale,
            "stale_threshold_minutes": stale_min,
        }
    except Exception as e:
        raise HTTPException(502, f"Elasticsearch error: {e}")


@router.get("/correlate/{operation_id}")
async def correlate_operation(operation_id: str):
    """Correlate a PostgreSQL operation with Elasticsearch log events."""
    try:
        from api.correlator import correlate, store_correlation
        result = await correlate(operation_id)
        # Store correlation as memory engram (non-blocking)
        asyncio.create_task(store_correlation(result))

        # Serialize dataclasses
        from dataclasses import asdict
        return asdict(result)
    except Exception as e:
        log.error("Correlation failed for %s: %s", operation_id, e)
        raise HTTPException(500, str(e))
