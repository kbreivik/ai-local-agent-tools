"""Logs API — all read/write endpoints for operations, tool calls, escalations, audit, stats."""
from fastapi import APIRouter, Query, HTTPException
from sqlalchemy import text

from api.db.base import get_engine
from api.db import queries as q

router = APIRouter(prefix="/api/logs", tags=["logs"])


# ── Tool Calls ────────────────────────────────────────────────────────────────

@router.get("")
async def get_logs(
    status: str = Query("all", description="all | ok | degraded | failed | escalated | error"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    tool: str = Query("", description="Substring filter on tool name"),
    session_id: str = Query("", description="Filter by session_id"),
    model: str = Query("", description="Substring filter on model_used"),
    date_from: str = Query("", description="ISO timestamp lower bound"),
    date_to: str = Query("", description="ISO timestamp upper bound"),
):
    async with get_engine().connect() as conn:
        rows, total = await q.get_tool_calls(
            conn,
            limit=limit, offset=offset,
            status_filter=status,
            tool_filter=tool,
            session_id=session_id,
            model_filter=model,
            date_from=date_from,
            date_to=date_to,
        )
    return {"total": total, "limit": limit, "offset": offset, "logs": rows}


# ── Operations ────────────────────────────────────────────────────────────────

@router.get("/operations")
async def get_operations(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status: str = Query("all"),
):
    async with get_engine().connect() as conn:
        rows = await q.get_operations(conn, limit=limit, offset=offset, status_filter=status)
    return {"operations": rows}


@router.get("/operations/{op_id}")
async def get_operation(op_id: str):
    async with get_engine().connect() as conn:
        op = await q.get_operation(conn, op_id)
        if not op:
            raise HTTPException(404, f"Operation '{op_id}' not found")
        tool_calls = await q.get_tool_calls_for_operation(conn, op_id)
    return {"operation": op, "tool_calls": tool_calls}


@router.get("/operations/{op_id}/correlate")
async def correlate_operation(op_id: str, window_minutes: int = Query(10, ge=1, le=60)):
    """Return log entries from Elasticsearch that overlap with the operation's time window."""
    async with get_engine().connect() as conn:
        op = await q.get_operation(conn, op_id)
        if not op:
            raise HTTPException(404, f"Operation '{op_id}' not found")

    start_ts = op.get("created_at") or op.get("started_at")
    end_ts   = op.get("completed_at") or op.get("updated_at")

    if not start_ts:
        return {"logs": [], "message": "No timestamp on operation"}

    try:
        import os
        import httpx
        from datetime import datetime, timedelta

        es_url = os.environ.get("ELASTIC_URL", "")
        if not es_url:
            return {"logs": [], "operation_id": op_id, "message": "ELASTIC_URL not configured"}

        # Build time range
        if isinstance(start_ts, str):
            start_dt = datetime.fromisoformat(start_ts.replace("Z", "+00:00"))
        else:
            start_dt = start_ts
        end_dt = None
        if end_ts:
            end_dt = datetime.fromisoformat(str(end_ts).replace("Z", "+00:00")) if isinstance(end_ts, str) else end_ts
        else:
            end_dt = start_dt + timedelta(minutes=window_minutes)

        query = {
            "size": 50,
            "sort": [{"@timestamp": "desc"}],
            "query": {
                "range": {
                    "@timestamp": {
                        "gte": start_dt.isoformat(),
                        "lte": end_dt.isoformat(),
                    }
                }
            }
        }
        r = httpx.post(f"{es_url}/filebeat-*/_search", json=query, verify=False, timeout=10)
        if not r.is_success:
            return {"logs": [], "operation_id": op_id, "message": f"Elasticsearch returned {r.status_code}"}
        hits = r.json().get("hits", {}).get("hits", [])
        logs = [{"timestamp": h["_source"].get("@timestamp"), "message": h["_source"].get("message", ""),
                 "host": h["_source"].get("host", {}).get("name", ""), "source": h["_source"].get("log", {}).get("file", {}).get("path", "")}
                for h in hits]
        return {"logs": logs, "operation_id": op_id, "window_minutes": window_minutes}
    except Exception as e:
        return {"logs": [], "operation_id": op_id, "message": f"Log correlation unavailable: {e}", "window_minutes": window_minutes}


# ── Escalations ───────────────────────────────────────────────────────────────

@router.get("/escalations")
async def get_escalations(limit: int = Query(50, ge=1, le=500)):
    async with get_engine().connect() as conn:
        rows = await q.get_escalations(conn, limit=limit)
    return {"escalations": rows}


@router.post("/escalations/{esc_id}/resolve")
async def resolve_escalation(esc_id: str):
    async with get_engine().begin() as conn:
        ok = await q.resolve_escalation(conn, esc_id)
    if not ok:
        raise HTTPException(404, f"Escalation '{esc_id}' not found")
    return {"resolved": True, "id": esc_id}


# ── Audit Log ─────────────────────────────────────────────────────────────────

@router.get("/audit")
async def get_audit(
    event_type: str = Query(""),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    async with get_engine().connect() as conn:
        rows = await q.get_audit_entries(conn, event_type=event_type, limit=limit, offset=offset)
    return {"audit": rows}


# ── Status Snapshots ──────────────────────────────────────────────────────────

@router.get("/snapshots/{component}")
async def get_snapshots(component: str, limit: int = Query(20, ge=1, le=200)):
    async with get_engine().connect() as conn:
        rows = await q.get_snapshots(conn, component=component, limit=limit)
    return {"snapshots": rows}


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/stats")
async def get_stats():
    async with get_engine().connect() as conn:
        stats = await q.get_stats(conn)
    return stats
