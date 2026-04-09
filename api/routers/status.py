"""
GET /api/status — live infrastructure status from DB snapshots.

All data comes from the status_snapshots table, written by background collectors.
Never calls Docker/Kafka/ES directly — that's the collectors' job.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query

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
        ["/version", "/config/datastore", "/admin/datastore", "/nodes/localhost/tasks"]
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
