"""
Elasticsearch log access tools — agent reads real infrastructure logs.

All queries use httpx + hand-built ES query DSL (no elasticsearch-py).
Returns {status: "unavailable"} gracefully when ES not configured.
Never called inline during agent execution — each call is independently async.
"""
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Sequence, Union


_LEVEL_FIELDS = ("log.level", "level", "severity")


def _norm_levels(level: Union[str, Sequence[str], None]) -> list[str]:
    """Normalise level inputs to a flat, deduped list of lowercase strings.

    Accepts single string, list/tuple of strings, or None.
    Expands common synonyms: warn↔warning, err↔error, crit↔critical↔fatal.
    """
    if level is None:
        return []
    if isinstance(level, str):
        vals = [level]
    else:
        vals = list(level)
    out: list[str] = []
    for v in vals:
        if not v:
            continue
        s = str(v).strip().lower()
        if s in ("warn", "warning"):
            out.extend(["warn", "warning"])
        elif s in ("err", "error"):
            out.extend(["err", "error"])
        elif s in ("crit", "critical", "fatal"):
            out.extend(["crit", "critical", "fatal"])
        else:
            out.append(s)
    seen: set[str] = set()
    ordered: list[str] = []
    for v in out:
        if v not in seen:
            seen.add(v)
            ordered.append(v)
    return ordered


def _es_url() -> str:
    return os.environ.get("ELASTIC_URL", "").rstrip("/")


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ok(data: Any, message: str = "OK") -> dict:
    return {"status": "ok", "data": data, "timestamp": _ts(), "message": message}


def _err(message: str, data: Any = None) -> dict:
    return {"status": "error", "data": data, "timestamp": _ts(), "message": message}


def _unavailable(reason: str = "") -> dict:
    msg = reason or (
        "Elasticsearch not configured — set ELASTIC_URL env var to enable log queries"
    )
    return {"status": "degraded", "data": None, "timestamp": _ts(), "message": msg}


def _index() -> str:
    return os.environ.get("ELASTIC_INDEX_PATTERN", "hp1-logs-*")


def _time_range(minutes_ago: int) -> dict:
    since = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()
    return {"range": {"@timestamp": {"gte": since}}}


def _get(path: str, params: dict | None = None) -> dict:
    import httpx
    url = _es_url()
    try:
        r = httpx.get(f"{url}{path}", params=params, timeout=10.0)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        raise RuntimeError(f"ES GET {path} failed: {e}") from e


def _post(path: str, body: dict) -> dict:
    import httpx
    url = _es_url()
    try:
        r = httpx.post(f"{url}{path}", json=body, timeout=15.0)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        raise RuntimeError(f"ES POST {path} failed: {e}") from e


def _extract_hits(resp: dict) -> list[dict]:
    """Flatten ES hits into simple log records."""
    hits = resp.get("hits", {}).get("hits", [])
    results = []
    for h in hits:
        src = h.get("_source", {})
        results.append({
            "id": h.get("_id"),
            "index": h.get("_index"),
            "timestamp": src.get("@timestamp"),
            "message": src.get("message", ""),
            "level": src.get("log", {}).get("level") or src.get("log.level", "info"),
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


# ── Tool functions ────────────────────────────────────────────────────────────

def elastic_cluster_health() -> dict:
    """Full Elasticsearch cluster health: status, nodes, shards, indices."""
    if not _es_url():
        return _unavailable()
    try:
        health = _get("/_cluster/health")
        stats = _get("/_cluster/stats", {"filter_path": "nodes.count,indices.count,indices.docs,indices.store"})
        return _ok({
            "cluster_name": health.get("cluster_name"),
            "status": health.get("status"),
            "nodes": health.get("number_of_nodes", 0),
            "data_nodes": health.get("number_of_data_nodes", 0),
            "active_shards": health.get("active_shards", 0),
            "unassigned_shards": health.get("unassigned_shards", 0),
            "indices_count": stats.get("indices", {}).get("count", 0),
            "docs_count": stats.get("indices", {}).get("docs", {}).get("count", 0),
            "store_size": stats.get("indices", {}).get("store", {}).get("size_in_bytes", 0),
        }, f"Cluster '{health.get('cluster_name')}': {health.get('status')}")
    except Exception as e:
        return _err(str(e))


def elastic_search_logs(
    query: str = "",
    service: str = "",
    node: str = "",
    minutes_ago: int = 60,
    size: int = 50,
    level: Union[str, Sequence[str], None] = None,
    # Silent aliases — models guess these names frequently:
    severity: Union[str, Sequence[str], None] = None,
    log_level: Union[str, Sequence[str], None] = None,
    host: str = "",
    **_ignored,
) -> dict:
    """
    Search infrastructure logs. Filter by service name, node, time range, level.

    Parameters:
      query: Optional free-text query. Empty = match_all in time window.
      service: Container/service name substring filter.
      node: Host.name substring filter (alias: host).
      minutes_ago: Lookback window (default 60).
      size: Max hits to return (default 50, cap 500).
      level: Log level filter. "error" | "warn" | "info" | "critical" or list.
             Aliases warn↔warning, err↔error, crit↔critical↔fatal are normalised.
             Synonyms `severity=` and `log_level=` accepted silently.

    Returns _ok({total, returned, logs, total_in_window, applied_filters}).
    """
    if not _es_url():
        return _unavailable(
            "elastic_search_logs unavailable: ELASTIC_URL not set. "
            "Configure Elasticsearch to enable log search."
        )
    try:
        # Merge aliased level parameters
        merged_levels = _norm_levels(level) + _norm_levels(severity) + _norm_levels(log_level)
        seen: set[str] = set()
        merged_levels = [v for v in merged_levels if not (v in seen or seen.add(v))]

        # Allow `host=` as an alias for `node=` (models guess this name).
        node_filter = node or host

        time_filter = _time_range(minutes_ago)
        must = [time_filter]
        if query:
            must.append({"match": {"message": {"query": query, "operator": "or"}}})
        if service:
            must.append({"wildcard": {
                "docker.container.labels.com.docker.swarm.service.name": f"*{service}*"
            }})
        if node_filter:
            must.append({"wildcard": {"host.name": f"*{node_filter}*"}})
        if merged_levels:
            level_should = []
            for field in _LEVEL_FIELDS:
                level_should.append({"terms": {f"{field}.keyword": merged_levels}})
                level_should.append({"terms": {field: merged_levels}})
            must.append({"bool": {"should": level_should, "minimum_should_match": 1}})

        body = {
            "query": {"bool": {"must": must}},
            "sort": [{"@timestamp": {"order": "desc"}}],
            "size": min(int(size), 500),
            "_source": [
                "@timestamp", "message", "log.level", "level", "severity",
                "host.name", "container.name", "hp1_node_role",
                "docker.container.labels.com.docker.swarm.service.name",
            ],
        }
        resp = _post(f"/{_index()}/_search", body)
        hits = _extract_hits(resp)
        total = resp.get("hits", {}).get("total", {}).get("value", len(hits))

        # Compute total_in_window for narrow-filter false-negative reasoning.
        total_in_window = total
        try:
            window_resp = _post(f"/{_index()}/_search", {
                "query": {"bool": {"must": [time_filter]}},
                "size": 0,
            })
            total_in_window = (
                window_resp.get("hits", {}).get("total", {}).get("value", total)
            )
        except Exception:
            pass

        applied_filters = {
            "level":       merged_levels,
            "service":     service or None,
            "host":        node_filter or None,
            "query":       query or None,
            "minutes_ago": int(minutes_ago),
        }

        return _ok({
            "total":           total,
            "returned":        len(hits),
            "logs":            hits,
            "total_in_window": total_in_window,
            "applied_filters": applied_filters,
            "index":           _index(),
        }, f"Found {total} log entries (window: {total_in_window})")
    except Exception as e:
        return _err(str(e))


def elastic_error_logs(service: str = "", minutes_ago: int = 30) -> dict:
    """
    Recent error and critical log lines. Called as part of pre_upgrade_check().
    Returns errors grouped by service.
    """
    if not _es_url():
        return _unavailable()
    try:
        must = [
            _time_range(minutes_ago),
            {"terms": {"log.level": ["error", "critical", "ERROR", "CRITICAL", "FATAL"]}},
        ]
        if service:
            must.append({"wildcard": {
                "docker.container.labels.com.docker.swarm.service.name": f"*{service}*"
            }})

        body = {
            "query": {"bool": {"must": must}},
            "sort": [{"@timestamp": {"order": "desc"}}],
            "size": 50,
            "aggs": {
                "by_service": {
                    "terms": {
                        "field": "docker.container.labels.com.docker.swarm.service.name",
                        "size": 20,
                    }
                }
            },
            "_source": ["@timestamp", "message", "log.level", "host.name", "container.name",
                        "docker.container.labels.com.docker.swarm.service.name"],
        }
        resp = _post(f"/{_index()}/_search", body)
        hits = _extract_hits(resp)
        total = resp.get("hits", {}).get("total", {}).get("value", len(hits))
        service_counts = {
            b["key"]: b["doc_count"]
            for b in resp.get("aggregations", {}).get("by_service", {}).get("buckets", [])
        }
        ok = total == 0
        return {
            "status": "ok" if ok else "degraded",
            "data": {"error_count": total, "errors": hits, "by_service": service_counts},
            "timestamp": _ts(),
            "message": f"No errors" if ok else f"{total} error(s) in last {minutes_ago}min",
        }
    except Exception as e:
        return _err(str(e))


def elastic_kafka_logs(broker_id: str = "", minutes_ago: int = 60) -> dict:
    """
    Kafka broker log analysis — leader elections, ISR changes, offline partitions.
    Returns structured events, not raw log lines.
    """
    if not _es_url():
        return _unavailable(
            "elastic_kafka_logs unavailable: ELASTIC_URL not set. "
            "Configure Elasticsearch to enable Kafka log analysis."
        )
    try:
        kafka_patterns = [
            "LeaderElection", "ISR", "OfflinePartitions", "UnderReplicated",
            "ReplicaManager", "ControllerEpoch", "ERROR", "WARN",
        ]
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

        should_patterns = [{"match_phrase": {"message": p}} for p in kafka_patterns]

        body = {
            "query": {"bool": {
                "must": must,
                "should": should_patterns,
            }},
            "sort": [{"@timestamp": {"order": "desc"}}],
            "size": 100,
            "_source": ["@timestamp", "message", "log.level", "host.name", "container.name"],
        }
        resp = _post(f"/{_index()}/_search", body)
        hits = _extract_hits(resp)

        # Classify events
        events = []
        for h in hits:
            msg = h.get("message", "")
            kind = "general"
            if "LeaderElection" in msg or "leader" in msg.lower():
                kind = "leader_election"
            elif "ISR" in msg:
                kind = "isr_change"
            elif "OfflinePartitions" in msg or "offline" in msg.lower():
                kind = "offline_partitions"
            elif "UnderReplicated" in msg or "under-replicated" in msg.lower():
                kind = "under_replicated"
            elif h.get("level", "").lower() in ("error", "critical"):
                kind = "error"
            events.append({**h, "event_type": kind})

        total = resp.get("hits", {}).get("total", {}).get("value", len(hits))
        errors = [e for e in events if e["event_type"] == "error"]
        isr = [e for e in events if e["event_type"] == "isr_change"]
        offline = [e for e in events if e["event_type"] == "offline_partitions"]

        return _ok({
            "total": total,
            "events": events,
            "summary": {
                "errors": len(errors),
                "isr_changes": len(isr),
                "offline_partition_events": len(offline),
            }
        }, f"{total} Kafka log events; {len(errors)} errors, {len(isr)} ISR changes")
    except Exception as e:
        return _err(str(e))


def elastic_log_pattern(service: str, hours: int = 24) -> dict:
    """
    Error rate over time for a service (hourly buckets).
    Returns anomaly flag if current hour rate > 2x average.
    Agent uses this to detect degradation trends.
    """
    if not _es_url():
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
                                "terms": {"log.level": ["error", "critical", "ERROR", "CRITICAL"]}
                            }
                        }
                    },
                },
                "top_errors": {
                    "filter": {
                        "terms": {"log.level": ["error", "critical", "ERROR", "CRITICAL"]}
                    },
                    "aggs": {
                        "messages": {
                            "terms": {"field": "message.keyword", "size": 5}
                        }
                    }
                }
            }
        }
        resp = _post(f"/{_index()}/_search", body)
        buckets = resp.get("aggregations", {}).get("by_hour", {}).get("buckets", [])
        hourly = [
            {
                "hour": b["key_as_string"],
                "total": b["doc_count"],
                "errors": b["errors"]["doc_count"],
            }
            for b in buckets
        ]

        # Anomaly detection
        error_rates = [h["errors"] for h in hourly if h["total"] > 0]
        anomaly = False
        anomaly_reason = ""
        if len(error_rates) >= 2:
            avg = sum(error_rates[:-1]) / len(error_rates[:-1])
            current = error_rates[-1]
            if avg > 0 and current > 2 * avg:
                anomaly = True
                anomaly_reason = f"Current hour: {current} errors vs avg {avg:.1f}"

        top_errors = [
            b["key"] for b in
            resp.get("aggregations", {}).get("top_errors", {})
                .get("messages", {}).get("buckets", [])
        ]

        return _ok({
            "service": service,
            "hours": hours,
            "hourly": hourly,
            "total_errors": sum(h["errors"] for h in hourly),
            "anomaly": anomaly,
            "anomaly_reason": anomaly_reason,
            "top_error_messages": top_errors,
        }, f"{'ANOMALY DETECTED: ' + anomaly_reason if anomaly else 'Log pattern normal'}")
    except Exception as e:
        return _err(str(e))


def elastic_index_stats() -> dict:
    """
    hp1-logs-* index sizes, doc counts, Filebeat ingest freshness.
    Returns stale=True if last ingest > ELASTIC_FILEBEAT_STALE_MINUTES ago.
    """
    if not _es_url():
        return _unavailable()
    try:
        stale_minutes = int(os.environ.get("ELASTIC_FILEBEAT_STALE_MINUTES", "10"))

        # Index stats
        stats_resp = _get(f"/{_index()}/_stats/docs,store")
        indices_info = []
        all_indices = stats_resp.get("indices", {})
        total_docs = 0
        total_bytes = 0

        for idx_name, idx_data in all_indices.items():
            docs = idx_data.get("primaries", {}).get("docs", {}).get("count", 0)
            store = idx_data.get("primaries", {}).get("store", {}).get("size_in_bytes", 0)
            total_docs += docs
            total_bytes += store
            indices_info.append({"index": idx_name, "docs": docs, "size_bytes": store})

        indices_info.sort(key=lambda x: x["index"], reverse=True)

        # Last ingest timestamp
        last_doc_resp = _post(f"/{_index()}/_search", {
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
                    stale = age_min > stale_minutes
                except Exception:
                    pass

        return _ok({
            "indices": indices_info,
            "total_docs": total_docs,
            "total_size_bytes": total_bytes,
            "last_ingest": last_ts,
            "filebeat_active": not stale,
            "stale": stale,
        }, f"{'Filebeat stale' if stale else 'Filebeat active'}, {total_docs:,} total docs")
    except Exception as e:
        return _err(str(e))


def elastic_correlate_operation(operation_id: str) -> dict:
    """
    Find Elasticsearch log entries from the same time window as a PostgreSQL operation.
    Powerful for post-mortem analysis.
    """
    if not _es_url():
        return _unavailable()
    try:
        import httpx

        # Fetch operation record from API
        api_base = f"http://127.0.0.1:{os.environ.get('API_PORT', '8000')}"
        try:
            r = httpx.get(f"{api_base}/api/logs/operations/{operation_id}", timeout=5.0)
            r.raise_for_status()
            op = r.json()
        except Exception as e:
            return _err(f"Cannot fetch operation {operation_id}: {e}")

        started_at = op.get("started_at")
        completed_at = op.get("completed_at") or _ts()
        label = op.get("label", "")

        # Expand window by 30s on each side
        from datetime import timedelta
        try:
            start_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
        except Exception:
            return _err(f"Cannot parse operation timestamps")

        since = (start_dt - timedelta(seconds=30)).isoformat()
        until = (end_dt + timedelta(seconds=30)).isoformat()

        body = {
            "query": {"bool": {"must": [
                {"range": {"@timestamp": {"gte": since, "lte": until}}}
            ]}},
            "sort": [{"@timestamp": {"order": "asc"}}],
            "size": 200,
            "_source": ["@timestamp", "message", "log.level", "host.name",
                        "container.name", "hp1_node_role",
                        "docker.container.labels.com.docker.swarm.service.name"],
        }
        resp = _post(f"/{_index()}/_search", body)
        hits = _extract_hits(resp)
        total = resp.get("hits", {}).get("total", {}).get("value", len(hits))

        errors = [h for h in hits if h.get("level", "").lower() in ("error", "critical", "fatal")]
        warns = [h for h in hits if h.get("level", "").lower() == "warn"]

        return _ok({
            "operation_id": operation_id,
            "operation_label": label,
            "window": {"from": since, "to": until},
            "total_logs": total,
            "error_count": len(errors),
            "warn_count": len(warns),
            "errors": errors[:20],
            "logs": hits[:100],
        }, f"Correlated {total} log entries with operation, {len(errors)} errors")
    except Exception as e:
        return _err(str(e))
