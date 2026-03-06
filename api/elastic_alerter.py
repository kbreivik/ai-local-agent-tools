"""
ElasticAlerter — runs after each ElasticCollector poll.
Derives log-based alerts from Elasticsearch that the health collector cannot see.

Called from ElasticCollector._safe_poll() via the base collector hook.
All alerts go through api/alerts.py → AlertToast GUI + audit_log + MuninnDB.
"""
import logging
import os
from datetime import datetime, timedelta, timezone

import httpx

log = logging.getLogger(__name__)

_STALE_MIN = lambda: int(os.environ.get("ELASTIC_FILEBEAT_STALE_MINUTES", "10"))
_ERROR_THRESHOLD = lambda: int(os.environ.get("ELASTIC_ERROR_RATE_THRESHOLD", "10"))


def _es_url() -> str:
    return os.environ.get("ELASTIC_URL", "").rstrip("/")


def _index() -> str:
    return os.environ.get("ELASTIC_INDEX_PATTERN", "hp1-logs-*")


def _post_sync(path: str, body: dict) -> dict:
    """Synchronous ES query (called from async context via thread executor)."""
    url = _es_url()
    if not url:
        return {}
    try:
        r = httpx.post(f"{url}{path}", json=body, timeout=10.0)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.debug("ElasticAlerter ES POST failed: %s", e)
        return {}


def _check_sync() -> list[dict]:
    """
    Run all elastic alert checks synchronously.
    Returns list of (component, severity, message) alert dicts.
    """
    if not _es_url():
        return []

    alerts = []
    now = datetime.now(timezone.utc)
    stale_min = _STALE_MIN()
    error_threshold = _ERROR_THRESHOLD()

    # ── Check 1: Filebeat stale ──────────────────────────────────────────────
    try:
        resp = _post_sync(f"/{_index()}/_search", {
            "query": {"match_all": {}},
            "sort": [{"@timestamp": {"order": "desc"}}],
            "size": 1,
            "_source": ["@timestamp"],
        })
        hits = resp.get("hits", {}).get("hits", [])
        if hits:
            last_ts = hits[0].get("_source", {}).get("@timestamp")
            if last_ts:
                last_dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
                age_min = (now - last_dt).total_seconds() / 60
                if age_min > stale_min:
                    alerts.append({
                        "component": "filebeat",
                        "severity": "warning",
                        "message": f"Filebeat stale: last log {age_min:.0f}min ago (threshold {stale_min}min)",
                    })
        elif resp.get("hits", {}).get("total", {}).get("value", 0) == 0:
            # No documents at all — Filebeat may not be running
            pass
    except Exception as e:
        log.debug("Filebeat stale check failed: %s", e)

    # ── Check 2: Error rate in last 5min ────────────────────────────────────
    try:
        since = (now - timedelta(minutes=5)).isoformat()
        resp = _post_sync(f"/{_index()}/_search", {
            "query": {"bool": {"must": [
                {"range": {"@timestamp": {"gte": since}}},
                {"terms": {"log.level": ["error", "critical", "ERROR", "CRITICAL", "FATAL"]}},
            ]}},
            "size": 0,
            "aggs": {
                "by_service": {
                    "terms": {
                        "field": "docker.container.labels.com.docker.swarm.service.name",
                        "size": 10,
                    }
                }
            },
        })
        total_errors = resp.get("hits", {}).get("total", {}).get("value", 0)
        if total_errors > error_threshold:
            by_service = {
                b["key"]: b["doc_count"]
                for b in resp.get("aggregations", {}).get("by_service", {}).get("buckets", [])
                if b["key"]
            }
            svc_str = ", ".join(f"{k}:{v}" for k, v in list(by_service.items())[:5])
            alerts.append({
                "component": "elasticsearch",
                "severity": "warning",
                "message": f"High error rate: {total_errors} errors in last 5min. Services: {svc_str or 'various'}",
            })
    except Exception as e:
        log.debug("Error rate check failed: %s", e)

    # ── Check 3: Critical logs in last 5min ─────────────────────────────────
    try:
        since = (now - timedelta(minutes=5)).isoformat()
        resp = _post_sync(f"/{_index()}/_search", {
            "query": {"bool": {"must": [
                {"range": {"@timestamp": {"gte": since}}},
                {"terms": {"log.level": ["critical", "CRITICAL", "FATAL"]}},
            ]}},
            "sort": [{"@timestamp": {"order": "desc"}}],
            "size": 3,
            "_source": ["@timestamp", "message", "container.name",
                        "docker.container.labels.com.docker.swarm.service.name"],
        })
        crits = resp.get("hits", {}).get("hits", [])
        for h in crits:
            src = h.get("_source", {})
            svc = (
                src.get("docker", {}).get("container", {}).get("labels", {})
                   .get("com.docker.swarm.service.name", "")
                or src.get("container.name", "unknown")
            )
            msg = src.get("message", "")[:120]
            alerts.append({
                "component": svc or "infrastructure",
                "severity": "critical",
                "message": f"CRITICAL log: {msg}",
            })
    except Exception as e:
        log.debug("Critical log check failed: %s", e)

    # ── Check 4: Kafka offline partitions ────────────────────────────────────
    try:
        since = (now - timedelta(minutes=5)).isoformat()
        resp = _post_sync(f"/{_index()}/_search", {
            "query": {"bool": {"must": [
                {"range": {"@timestamp": {"gte": since}}},
                {"match_phrase": {"message": "OfflinePartitions"}},
            ]}},
            "size": 1,
            "_source": ["@timestamp", "message"],
        })
        if resp.get("hits", {}).get("total", {}).get("value", 0) > 0:
            msg = resp["hits"]["hits"][0]["_source"].get("message", "")[:100]
            alerts.append({
                "component": "kafka",
                "severity": "critical",
                "message": f"Kafka offline partitions detected: {msg}",
            })
    except Exception as e:
        log.debug("Kafka offline partition check failed: %s", e)

    return alerts


async def run_elastic_alerts() -> None:
    """
    Async entry point — run alert checks in thread executor, fire any alerts found.
    Called from ElasticCollector after each poll.
    """
    import asyncio
    from api.alerts import fire_alert
    from api.memory.hooks import _fire

    try:
        loop = asyncio.get_event_loop()
        found_alerts = await loop.run_in_executor(None, _check_sync)

        for a in found_alerts:
            fire_alert(a["component"], a["severity"], a["message"], source="elastic")

            # Store notable alerts in MuninnDB
            if a["severity"] in ("critical", "warning"):
                from api.memory.client import get_client
                async def _store_alert(alert=a):
                    try:
                        client = get_client()
                        await client.store(
                            f"alert:{alert['component']}",
                            alert["message"],
                            ["alert", alert["severity"], alert["component"]],
                        )
                    except Exception:
                        pass
                asyncio.create_task(_store_alert())

    except Exception as e:
        log.debug("ElasticAlerter run failed: %s", e)
