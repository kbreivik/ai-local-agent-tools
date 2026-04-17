"""
Elasticsearch log access tools — agent reads real infrastructure logs.

All queries use httpx + hand-built ES query DSL (no elasticsearch-py).
Returns {status: "unavailable"} gracefully when ES not configured.
Never called inline during agent execution — each call is independently async.
"""
import json as _json
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Sequence, Union


_LEVEL_FIELDS = ("log.level", "level", "severity")

# Heuristic patterns for schema discovery when filters miss.
_SCHEMA_SERVICE_PATTERNS = (
    "service.name",
    "container.name",
    "kubernetes.labels.app",
    "docker.container.name",
    "fields.service",
    "beat.name",
    "docker.container.labels.com.docker.swarm.service.name",
)
_SCHEMA_HOST_PATTERNS = (
    "host.name",
    "host.hostname",
    "agent.hostname",
    "kubernetes.node.name",
    "beat.hostname",
)
_SCHEMA_LEVEL_PATTERNS = (
    "log.level",
    "level",
    "severity",
    "log_level",
    "fields.level",
    "loglevel",
)


def _compact_doc(source: dict, max_string_len: int = 160) -> dict:
    """Shallow-trim a doc: truncate long strings, cap list preview at 5 items."""
    out: dict = {}
    if not isinstance(source, dict):
        return source
    for k, v in source.items():
        if isinstance(v, str):
            out[k] = v[:max_string_len] + ("…" if len(v) > max_string_len else "")
        elif isinstance(v, dict):
            out[k] = _compact_doc(v, max_string_len)
        elif isinstance(v, list) and v and isinstance(v[0], (str, int, float)):
            out[k] = v[:5]
        else:
            out[k] = v
    return out


def _flatten_dict(d: dict, parent: str = "", sep: str = ".") -> dict:
    items: dict = {}
    if not isinstance(d, dict):
        return items
    for k, v in d.items():
        new_key = f"{parent}{sep}{k}" if parent else k
        if isinstance(v, dict):
            items.update(_flatten_dict(v, new_key, sep))
        else:
            items[new_key] = v
    return items


def _truncate_value(v):
    if isinstance(v, str):
        return v[:60] + ("…" if len(v) > 60 else "")
    if isinstance(v, (list, dict)):
        s = str(v)
        return s[:60] + ("…" if len(s) > 60 else "")
    return v


def _suggest_filter_fields(available_fields: dict) -> list:
    """Match known shipper field patterns against discovered fields."""
    def match(patterns, category):
        hits = [f for f in available_fields if f in patterns]
        if hits:
            first = hits[0]
            return {
                "category": category,
                "field": first,
                "example": available_fields[first].get("example"),
            }
        return None
    return [r for r in [
        match(_SCHEMA_SERVICE_PATTERNS, "service"),
        match(_SCHEMA_HOST_PATTERNS, "host"),
        match(_SCHEMA_LEVEL_PATTERNS, "level"),
    ] if r]


def _schema_discovery_enabled() -> bool:
    """Check the elasticSchemaDiscoveryOnMiss setting. Defaults True on any error."""
    try:
        from mcp_server.tools.skills.storage import get_backend
        v = get_backend().get_setting("elasticSchemaDiscoveryOnMiss")
    except Exception:
        return True
    if v is None:
        return True
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() not in ("false", "0", "no", "off")


def _enrich_with_schema_sample(time_filter: dict) -> dict:
    """Run an unfiltered sample over the same time window and extract schema metadata.

    Returns a dict to merge into the response envelope:
      - sample_docs: up to 3 compacted real docs
      - available_fields: top 20 flattened field names, with count + example
      - suggested_filters: heuristic mapping to {service, host, level}
      - schema_discovery_hint: human-readable explanation
    On error, returns {"schema_sample_error": str}.
    On empty window, returns {"schema_sample": None}.
    """
    try:
        sample_body = {
            "query": {"bool": {"filter": [time_filter]}},
            "size": 3,
            "sort": [{"@timestamp": {"order": "desc"}}],
        }
        resp = _post(f"/{_index()}/_search", sample_body)
    except Exception as e:
        return {"schema_sample_error": str(e)}

    hits = resp.get("hits", {}).get("hits", []) or []
    if not hits:
        return {"schema_sample": None}

    compact_hits = [_compact_doc(h.get("_source", {}) or {}) for h in hits]

    field_counts: dict = {}
    field_examples: dict = {}
    for doc in compact_hits:
        for key, val in _flatten_dict(doc).items():
            field_counts[key] = field_counts.get(key, 0) + 1
            if key not in field_examples and val is not None:
                field_examples[key] = _truncate_value(val)

    top_fields = sorted(field_counts.items(), key=lambda x: (-x[1], x[0]))[:20]
    available_fields = {
        k: {"count": c, "example": field_examples.get(k)}
        for k, c in top_fields
    }
    suggested_filters = _suggest_filter_fields(available_fields)

    return {
        "sample_docs": compact_hits,
        "available_fields": available_fields,
        "suggested_filters": suggested_filters,
        "schema_discovery_hint": (
            "Your previous filter returned 0 hits. Here are up to 3 real docs "
            "from the same window without filters. Pick a field from "
            "suggested_filters that matches what you want to filter on, "
            "then retry."
        ),
    }


def _compute_hint(
    total: int,
    total_in_window: int | None,
    levels: list,
    service: str | None,
    host: str | None,
) -> str | None:
    """Return a short hint for the agent when results look suspicious."""
    if total == 0 and total_in_window and total_in_window > 0:
        filters = []
        if levels:
            filters.append(f"level={levels}")
        if service:
            filters.append(f"service={service!r}")
        if host:
            filters.append(f"host={host!r}")
        if filters:
            return (
                f"Filter may be too narrow: 0 hits matched but "
                f"{total_in_window} log entries exist in the same window. "
                f"Active filters: {', '.join(filters)}. "
                "Try dropping one filter or broadening."
            )
    return None


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

    Returns _ok({total, total_relation, returned, logs, total_in_window,
                 applied_filters, query_lucene, index, hint?}).
    `hint` is only present when results look suspicious (0 hits but the
    unfiltered window has data).
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

        query_body = {"bool": {"must": must}}
        body = {
            "query": query_body,
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
        total_val = resp.get("hits", {}).get("total", {})
        if isinstance(total_val, dict):
            total = total_val.get("value", len(hits))
            total_relation = total_val.get("relation", "eq")
        else:
            total = int(total_val)
            total_relation = "eq"

        # Compute total_in_window for narrow-filter false-negative reasoning.
        total_in_window: int | None = None
        try:
            window_resp = _post(f"/{_index()}/_search", {
                "query": {"bool": {"must": [time_filter]}},
                "size": 0,
            })
            window_total = window_resp.get("hits", {}).get("total", {})
            if isinstance(window_total, dict):
                total_in_window = window_total.get("value", 0)
            else:
                total_in_window = int(window_total)
        except Exception:
            total_in_window = None

        applied_filters = {
            "level":       merged_levels or None,
            "service":     service or None,
            "host":        node_filter or None,
            "query":       query or None,
            "minutes_ago": int(minutes_ago),
        }

        hint = _compute_hint(
            total=total,
            total_in_window=total_in_window,
            levels=merged_levels,
            service=service or None,
            host=node_filter or None,
        )

        data = {
            "total":           total,
            "total_relation": total_relation,
            "returned":        len(hits),
            "logs":            hits,
            "total_in_window": total_in_window,
            "applied_filters": applied_filters,
            "query_lucene":    _json.dumps(query_body, separators=(",", ":")),
            "index":           _index(),
        }
        if hint:
            data["hint"] = hint

        # Schema discovery on filter miss: 0 hits but window has data → sample.
        if (
            total == 0
            and total_in_window is not None
            and total_in_window > 0
            and _schema_discovery_enabled()
        ):
            try:
                data.update(_enrich_with_schema_sample(time_filter))
            except Exception as _e:
                data["schema_sample_error"] = str(_e)

        msg = f"Found {total} log entries (window: {total_in_window})"
        if hint:
            msg = f"{msg} — {hint}"
        return _ok(data, msg)
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
        time_filter = {"range": {"@timestamp": {"gte": since}}}
        must = [time_filter]
        if service:
            must.append({"bool": {"should": [
                {"wildcard": {
                    "docker.container.labels.com.docker.swarm.service.name": f"*{service}*"
                }},
                {"wildcard": {"container.name": f"*{service}*"}},
            ], "minimum_should_match": 1}})

        query_body = {"bool": {"must": must}}
        body = {
            "query": query_body,
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

        total_errors = sum(h["errors"] for h in hourly)
        total_in_window = sum(h["total"] for h in hourly)

        applied_filters = {
            "service": service or None,
            "hours":   int(hours),
        }

        pattern_data = {
            "service": service,
            "hours": hours,
            "hourly": hourly,
            "total_errors": total_errors,
            "total_in_window": total_in_window,
            "applied_filters": applied_filters,
            "query_lucene": _json.dumps(query_body, separators=(",", ":")),
            "index": _index(),
            "anomaly": anomaly,
            "anomaly_reason": anomaly_reason,
            "top_error_messages": top_errors,
        }

        # Schema discovery on filter miss: service filter set but no docs matched.
        if (
            service
            and total_in_window == 0
            and _schema_discovery_enabled()
        ):
            try:
                pattern_data.update(_enrich_with_schema_sample(time_filter))
            except Exception as _e:
                pattern_data["schema_sample_error"] = str(_e)

        return _ok(
            pattern_data,
            f"{'ANOMALY DETECTED: ' + anomaly_reason if anomaly else 'Log pattern normal'}",
        )
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
