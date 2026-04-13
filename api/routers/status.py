"""
GET /api/status — live infrastructure status from DB snapshots.

All data comes from the status_snapshots table, written by background collectors.
Never calls Docker/Kafka/ES directly — that's the collectors' job.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text

from api.auth import get_current_user
from api.db.base import get_engine
from api.db import queries as q

router = APIRouter(prefix="/api/status", tags=["status"])


def _snap_state(snap: dict) -> dict:
    """Extract state from snapshot row, inject last_updated timestamp."""
    if not snap:
        return {"health": "unknown", "message": "No data yet — collector starting"}
    state = snap.get("state") or {}
    if isinstance(state, str):
        import json
        try:
            state = json.loads(state)
        except Exception:
            state = {}
    state["last_updated"] = snap.get("timestamp")
    return state


# ── Main status endpoint ───────────────────────────────────────────────────────

@router.get("")
async def get_status():
    """Latest snapshot per component + collector status."""
    from api.collectors import manager as coll_mgr

    async with get_engine().connect() as conn:
        swarm_snap     = await q.get_latest_snapshot(conn, "swarm")
        kafka_snap     = await q.get_latest_snapshot(conn, "kafka_cluster")
        elastic_snap   = await q.get_latest_snapshot(conn, "elasticsearch")

    swarm_state   = _snap_state(swarm_snap)
    kafka_state   = _snap_state(kafka_snap)
    elastic_state = _snap_state(elastic_snap)

    # Derive filebeat from elastic state
    filebeat_state = elastic_state.get("filebeat", {"status": "unconfigured"})

    return {
        "swarm":         swarm_state,
        "kafka":         kafka_state,
        "elasticsearch": elastic_state,
        "filebeat":      filebeat_state,
        "collectors":    coll_mgr.status(),
    }


# ── History / sparklines ───────────────────────────────────────────────────────

@router.get("/history/{component}")
async def get_history(
    component: str,
    hours: int = Query(24, ge=1, le=168),
):
    """Returns snapshot history for a component for the last N hours."""
    # Use space separator to match SQLite's storage format for string comparisons
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    async with get_engine().connect() as conn:
        rows = await q.get_snapshots_since(conn, component, since, limit=500)

    # Return slim records for sparkline rendering
    slim = []
    for r in rows:
        state = r.get("state") or {}
        if isinstance(state, str):
            import json
            try:
                state = json.loads(state)
            except Exception:
                state = {}
        slim.append({
            "timestamp": r.get("timestamp"),
            "health": state.get("health", "unknown"),
            "is_healthy": r.get("is_healthy", False),
        })
    return {"component": component, "hours": hours, "history": slim}


# ── Detailed endpoints ─────────────────────────────────────────────────────────

@router.get("/nodes")
async def get_nodes():
    """Swarm node detail from latest snapshot."""
    async with get_engine().connect() as conn:
        snap = await q.get_latest_snapshot(conn, "swarm")
    state = _snap_state(snap)
    return {
        "nodes": state.get("nodes", []),
        "node_count": state.get("node_count", 0),
        "health": state.get("health", "unknown"),
        "last_updated": state.get("last_updated"),
    }


@router.get("/services")
async def get_services():
    """Swarm service detail from latest snapshot."""
    async with get_engine().connect() as conn:
        snap = await q.get_latest_snapshot(conn, "swarm")
    state = _snap_state(snap)
    return {
        "services": state.get("services", []),
        "service_count": state.get("service_count", 0),
        "health": state.get("health", "unknown"),
        "last_updated": state.get("last_updated"),
    }


@router.get("/brokers")
async def get_brokers():
    """Kafka broker detail from latest snapshot."""
    async with get_engine().connect() as conn:
        snap = await q.get_latest_snapshot(conn, "kafka_cluster")
    state = _snap_state(snap)
    return {
        "brokers": state.get("brokers", []),
        "broker_count": state.get("broker_count", 0),
        "controller_id": state.get("controller_id"),
        "health": state.get("health", "unknown"),
        "last_updated": state.get("last_updated"),
    }


@router.get("/lag")
async def get_consumer_lag():
    """Consumer group lag from latest Kafka snapshot."""
    async with get_engine().connect() as conn:
        snap = await q.get_latest_snapshot(conn, "kafka_cluster")
    state = _snap_state(snap)
    return {
        "consumer_lag": state.get("consumer_lag", {}),
        "health": state.get("health", "unknown"),
        "last_updated": state.get("last_updated"),
    }


@router.get("/topics")
async def get_topics():
    """Kafka topic list from latest snapshot."""
    async with get_engine().connect() as conn:
        snap = await q.get_latest_snapshot(conn, "kafka_cluster")
    state = _snap_state(snap)
    return {
        "topics": state.get("topics", []),
        "topic_count": state.get("topic_count", 0),
        "under_replicated_partitions": state.get("under_replicated_partitions", 0),
        "last_updated": state.get("last_updated"),
    }


@router.get("/collectors/{component}/data")
async def collector_data(component: str):
    """Return the last collected state dict for a named collector."""
    from api.collectors import manager as coll_mgr
    collector = coll_mgr.get(component)
    if not collector:
        return {"status": "error", "data": None, "message": f"Collector '{component}' not found"}
    state = getattr(collector, '_last_state', None)
    if state is None:
        return {"status": "ok", "data": None, "message": "No data yet"}
    return {"status": "ok", "data": state}


@router.get("/collectors/{component}/debug")
async def collector_debug(component: str, _: str = Depends(get_current_user)):
    """
    Make a raw API call using the component's stored connection credentials
    and return the raw response. Used for diagnosing collector issues.
    Only works for pbs and proxmox.
    """
    if component not in ("pbs", "proxmox"):
        raise HTTPException(400, "Debug only supported for pbs and proxmox")

    import httpx
    from api.connections import get_connection_for_platform

    conn = get_connection_for_platform(component)
    if not conn:
        return {"status": "error", "message": f"No {component} connection configured"}

    host = conn.get("host", "")
    port = conn.get("port") or (8007 if component == "pbs" else 8006)
    creds = conn.get("credentials", {}) if isinstance(conn.get("credentials"), dict) else {}
    user = creds.get("user", "")
    token_name = creds.get("token_name", "")
    secret = creds.get("secret", "")

    if component == "pbs":
        auth_header = f"PBSAPIToken={user}!{token_name}:{secret}"
    else:
        auth_header = f"PVEAPIToken={user}!{token_name}={secret}"

    headers = {"Authorization": auth_header}
    base = f"https://{host}:{port}/api2/json"

    results = {}
    paths_to_test = (
        ["/version", "/config/datastore", "/system/tasks"]
        if component == "pbs"
        else ["/version", "/nodes"]
    )

    for path in paths_to_test:
        try:
            r = httpx.get(f"{base}{path}", headers=headers, verify=False, timeout=8)
            results[path] = {
                "status_code": r.status_code,
                "body_preview": r.text[:500],
            }
        except Exception as e:
            results[path] = {"error": str(e)[:200]}

    return {
        "status": "ok",
        "host": f"{host}:{port}",
        "user": user,
        "token_name": token_name,
        "secret_set": bool(secret),
        "results": results,
    }


@router.get("/pipeline")
async def get_pipeline_health(_: str = Depends(get_current_user)):
    """Consolidated data pipeline health — collector freshness, PG snapshot age, ES ingest."""
    from api.collectors import manager as coll_mgr
    import os
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)

    # ── Collector freshness from in-memory status ─────────────────────────────
    collectors_raw = coll_mgr.status()
    collector_rows = []
    for name, c in sorted(collectors_raw.items()):
        last_poll_str = c.get("last_poll")
        age_s = None
        stale = False
        if last_poll_str:
            try:
                lp = datetime.fromisoformat(last_poll_str.replace("Z", "+00:00"))
                age_s = int((now - lp).total_seconds())
                interval = c.get("interval_s", 60)
                stale = age_s > interval * 3  # stale if >3x interval since last poll
            except Exception:
                pass
        collector_rows.append({
            "name": name,
            "running": c.get("running", False),
            "health": c.get("last_health", "unknown"),
            "interval_s": c.get("interval_s", 0),
            "last_poll": last_poll_str,
            "age_s": age_s,
            "stale": stale,
            "error": c.get("last_error"),
        })

    # ── PostgreSQL snapshot freshness per collector ───────────────────────────
    pg_rows = []
    try:
        async with get_engine().connect() as conn:
            # Get latest snapshot timestamp per component
            result = await conn.execute(
                text("""
                    SELECT component, MAX(timestamp) as latest, COUNT(*) as total_24h
                    FROM status_snapshots
                    WHERE timestamp >= NOW() - INTERVAL '24 hours'
                    GROUP BY component
                    ORDER BY component
                """)
            )
            for row in result.mappings():
                ts = row["latest"]
                age_s = int((now - ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else now - ts).total_seconds()) if ts else None
                pg_rows.append({
                    "component": row["component"],
                    "latest_snapshot": ts.isoformat() if ts else None,
                    "age_s": age_s,
                    "snapshots_24h": row["total_24h"],
                    "stale": age_s is not None and age_s > 300,  # >5 min = stale
                })
    except Exception as e:
        pg_rows = [{"error": str(e)}]

    # ── Elasticsearch ingest health ───────────────────────────────────────────
    es_health = {}
    try:
        import httpx
        elastic_url = os.environ.get("ELASTIC_URL", "").rstrip("/")
        if elastic_url:
            # Document count + last document timestamp in hp1-logs-*
            r = httpx.post(
                f"{elastic_url}/hp1-logs-*/_search",
                json={
                    "size": 1,
                    "sort": [{"@timestamp": "desc"}],
                    "_source": ["@timestamp"],
                    "query": {"match_all": {}},
                    "aggs": {
                        "total_1h": {
                            "filter": {"range": {"@timestamp": {"gte": "now-1h"}}}
                        },
                        "total_5m": {
                            "filter": {"range": {"@timestamp": {"gte": "now-5m"}}}
                        }
                    }
                },
                timeout=8.0,
            )
            if r.is_success:
                data = r.json()
                hits = data.get("hits", {})
                aggs = data.get("aggregations", {})
                last_doc_ts = None
                if hits.get("hits"):
                    last_doc_ts = hits["hits"][0].get("_source", {}).get("@timestamp")
                last_doc_age_s = None
                if last_doc_ts:
                    try:
                        ld = datetime.fromisoformat(last_doc_ts.replace("Z", "+00:00"))
                        last_doc_age_s = int((now - ld).total_seconds())
                    except Exception:
                        pass
                es_health = {
                    "configured": True,
                    "total_docs": hits.get("total", {}).get("value", 0),
                    "docs_last_1h": aggs.get("total_1h", {}).get("doc_count", 0),
                    "docs_last_5m": aggs.get("total_5m", {}).get("doc_count", 0),
                    "last_document": last_doc_ts,
                    "last_document_age_s": last_doc_age_s,
                    "stale": last_doc_age_s is not None and last_doc_age_s > 600,  # >10min
                    "ingest_rate_per_min": round(aggs.get("total_5m", {}).get("doc_count", 0) / 5, 1),
                }
            else:
                es_health = {"configured": True, "error": f"HTTP {r.status_code}"}
        else:
            es_health = {"configured": False}
    except Exception as e:
        es_health = {"configured": True, "error": str(e)}

    # ── PostgreSQL connectivity + table sizes ─────────────────────────────────
    pg_meta = {}
    try:
        async with get_engine().connect() as conn:
            result = await conn.execute(
                text("""
                    SELECT
                      (SELECT COUNT(*) FROM status_snapshots) as snapshots_total,
                      (SELECT COUNT(*) FROM operations) as operations_total,
                      (SELECT COUNT(*) FROM tool_calls) as tool_calls_total,
                      (SELECT COUNT(*) FROM entity_changes) as entity_changes_total,
                      (SELECT COUNT(*) FROM entity_events) as entity_events_total
                """)
            )
            row = result.mappings().fetchone()
            if row:
                pg_meta = dict(row)
                pg_meta["connected"] = True
    except Exception as e:
        pg_meta = {"connected": False, "error": str(e)}

    # Overall pipeline health
    stale_collectors = [c["name"] for c in collector_rows if c.get("stale")]
    stale_pg = [r["component"] for r in pg_rows if r.get("stale")]
    es_stale = es_health.get("stale", False)

    if stale_collectors or stale_pg or es_stale:
        pipeline_health = "degraded"
    elif not pg_meta.get("connected"):
        pipeline_health = "error"
    else:
        pipeline_health = "healthy"

    return {
        "health": pipeline_health,
        "timestamp": now.isoformat(),
        "collectors": collector_rows,
        "postgres": {
            "connected": pg_meta.get("connected", False),
            "error": pg_meta.get("error"),
            "table_counts": {k: v for k, v in pg_meta.items() if k not in ("connected", "error")},
            "snapshots_by_component": pg_rows,
            "stale_components": stale_pg,
        },
        "elasticsearch": es_health,
        "alerts": {
            "stale_collectors": stale_collectors,
            "stale_pg_components": stale_pg,
            "es_stale": es_stale,
        },
    }
