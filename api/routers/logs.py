"""Logs API — all read/write endpoints for operations, tool calls, escalations, audit, stats."""
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import text

from api.auth import get_current_user
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


@router.get("/operations/recent")
async def get_recent_operations(
    limit: int = Query(10, ge=1, le=50),
    user: str = Depends(get_current_user),
):
    """v2.37.0 — return the N most recently run operations for this user,
    deduplicated by exact task text (most recent occurrence kept). Used
    by the GUI's RECENT panel below the task templates.

    Schema notes (operations table on this project):
      - Task text lives in the `label` column (returned as `task` to the
        frontend so the UI code stays shape-agnostic).
      - `parent_session_id` was backfilled with a default of '' rather
        than NULL, so both cases must be excluded for "top-level only".
      - `agent_type` is not stored on `operations`; it's sourced from
        the first `agent_llm_traces` step for the operation when
        available, otherwise defaults to 'observe'.

    Excludes:
      - Sub-agent operations (parent_session_id set to a non-empty value)
      - Operations with empty or null task text
      - Operations older than 30 days (noise floor)
    """
    async with get_engine().connect() as conn:
        rows = await conn.execute(
            text(
                """
                SELECT label, status, operation_id, started_at, agent_type, age_seconds
                FROM (
                    SELECT DISTINCT ON (label)
                        label,
                        status,
                        o.id         AS operation_id,
                        started_at,
                        COALESCE((
                            SELECT t.agent_type
                            FROM agent_llm_traces t
                            WHERE t.operation_id = o.id::text
                              AND t.agent_type IS NOT NULL
                            ORDER BY t.step_index ASC
                            LIMIT 1
                        ), 'observe') AS agent_type,
                        EXTRACT(EPOCH FROM (NOW() - started_at))::INT AS age_seconds
                    FROM operations o
                    WHERE label IS NOT NULL
                      AND label <> ''
                      AND owner_user = :user
                      AND (parent_session_id IS NULL OR parent_session_id = '')
                      AND started_at > NOW() - INTERVAL '30 days'
                    ORDER BY label, started_at DESC
                ) subq
                ORDER BY started_at DESC
                LIMIT :limit
                """
            ),
            {"user": user, "limit": limit},
        )
        items = [
            {
                "task":         r[0],
                "status":       r[1],
                "operation_id": str(r[2]) if r[2] else None,
                "agent_type":   r[4] or "observe",
                "age_seconds":  int(r[5]) if r[5] is not None else 0,
            }
            for r in rows.fetchall()
        ]
    return {"items": items, "count": len(items)}


@router.get("/operations/{op_id}")
async def get_operation(op_id: str):
    async with get_engine().connect() as conn:
        op = await q.get_operation(conn, op_id)
        if not op:
            raise HTTPException(404, f"Operation '{op_id}' not found")
        tool_calls = await q.get_tool_calls_for_operation(conn, op_id)
    return {"operation": op, "tool_calls": tool_calls}


@router.get("/operations/{op_id}/trace")
async def get_llm_trace(
    op_id: str,
    format: str = Query("structured", description="structured | digest"),
):
    """v2.34.14 — return the LLM trace for an operation.

    format=structured: JSON with system_prompt + per-step messages_delta and
                       response_raw (full fidelity).
    format=digest:     Markdown digest (~10x smaller, scannable).
    """
    from api.db import llm_traces
    trace = llm_traces.get_trace(op_id)
    if not trace.get("system_prompt") and not trace.get("steps"):
        raise HTTPException(404, f"No trace found for '{op_id}'")
    if format == "digest":
        return {"markdown": llm_traces.render_digest(trace, operation_id=op_id)}
    return {
        "operation_id": op_id,
        "system_prompt": trace.get("system_prompt"),
        "tools_count":   trace.get("tools_count"),
        "prompt_chars":  trace.get("prompt_chars"),
        "steps":         trace.get("steps", []),
    }


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


# ── SSH Connection Log ────────────────────────────────────────────────────────

@router.get("/ssh")
async def get_ssh_log(
    connection_id: str = Query(""),
    target_host:   str = Query(""),
    outcome:       str = Query(""),
    limit:         int = Query(100, ge=1, le=500),
    _: str = Depends(get_current_user),
):
    """Query SSH connection attempt log."""
    from api.db.ssh_log import query_log
    rows = query_log(connection_id=connection_id, target_host=target_host,
                     outcome=outcome, limit=limit)
    for r in rows:
        for k, v in r.items():
            if hasattr(v, 'isoformat'):
                r[k] = v.isoformat()
    return {"ssh_log": rows, "count": len(rows)}


@router.get("/ssh/summary")
async def get_ssh_summary(_: str = Depends(get_current_user)):
    """Summary of SSH connection health: success rate, recent failures."""
    from api.db.ssh_log import query_log
    from collections import defaultdict
    recent = query_log(limit=200)
    if not recent:
        return {"summary": [], "total": 0}
    by_host = defaultdict(lambda: {"success": 0, "fail": 0, "last_outcome": "", "last_at": "", "last_error": ""})
    for r in recent:
        host = r.get("resolved_label") or r.get("target_host", "?")
        if r.get("outcome") == "success":
            by_host[host]["success"] += 1
        else:
            by_host[host]["fail"] += 1
        at = str(r.get("attempted_at", ""))
        if hasattr(r.get("attempted_at"), "isoformat"):
            at = r["attempted_at"].isoformat()
        if not by_host[host]["last_at"] or at > by_host[host]["last_at"]:
            by_host[host]["last_outcome"] = r.get("outcome", "")
            by_host[host]["last_at"] = at
            by_host[host]["last_error"] = r.get("error_message", "")
    summary = [
        {"host": host, "success": v["success"], "fail": v["fail"],
         "success_rate": round(v["success"] / max(v["success"] + v["fail"], 1) * 100),
         "last_outcome": v["last_outcome"], "last_at": v["last_at"],
         "last_error": v["last_error"]}
        for host, v in sorted(by_host.items())
    ]
    return {"summary": summary, "total": len(recent)}


# ── SSH Capability Map ────────────────────────────────────────────────────────

@router.get("/ssh/capabilities")
async def get_ssh_capabilities(
    connection_id: str = Query(""), target_host: str = Query(""),
    verified_only: bool = Query(False), days: int = Query(7, ge=1, le=90),
    alerts_only: bool = Query(False), _: str = Depends(get_current_user),
):
    """Query SSH capability map — which credentials work on which hosts."""
    from api.db.ssh_capabilities import query_capabilities
    rows = query_capabilities(connection_id=connection_id, target_host=target_host,
                              verified_only=verified_only, days=days, alerts_only=alerts_only)
    return {"capabilities": rows, "count": len(rows)}


@router.get("/ssh/capabilities/summary")
async def get_ssh_capabilities_summary(_: str = Depends(get_current_user)):
    """High-level SSH capability summary."""
    from api.db.ssh_capabilities import get_capability_summary
    return {"summary": get_capability_summary()}


@router.get("/ssh/capabilities/alerts")
async def get_ssh_capability_alerts(_: str = Depends(get_current_user)):
    """Credentials that gained access to new/unexpected hosts."""
    from api.db.ssh_capabilities import query_capabilities
    alerts = query_capabilities(alerts_only=True, days=30)
    return {"alerts": alerts, "count": len(alerts),
            "message": f"{len(alerts)} credential(s) gained access to new host(s)" if alerts else "No new host alerts."}


# ── Entity History ───────────────────────────────────────────────────────────

@router.get("/entity/{entity_id}/changes")
async def get_entity_changes(
    entity_id: str,
    hours: int = Query(24, ge=1, le=720),
    field_name: str = Query(""),
    limit: int = Query(50, ge=1, le=200),
    _: str = Depends(get_current_user),
):
    """Field-level change history for an entity."""
    from api.db.entity_history import get_changes
    return {"changes": get_changes(entity_id, hours=hours, field_name=field_name, limit=limit),
            "entity_id": entity_id, "hours": hours}

@router.get("/entity/{entity_id}/events")
async def get_entity_events(
    entity_id: str,
    hours: int = Query(24, ge=1, le=720),
    event_type: str = Query(""),
    severity: str = Query(""),
    limit: int = Query(50, ge=1, le=200),
    _: str = Depends(get_current_user),
):
    """Named event log for an entity."""
    from api.db.entity_history import get_events
    return {"events": get_events(entity_id, hours=hours, event_type=event_type,
                                  severity=severity, limit=limit),
            "entity_id": entity_id, "hours": hours}


# ── SSH Capability Alert Management ──────────────────────────────────────────

@router.post("/ssh/capabilities/alerts/{connection_id}/reviewed")
async def mark_capability_reviewed(
    connection_id: str,
    target_host: str = Query(...),
    _: str = Depends(get_current_user),
):
    """Clear the new_host_alert flag after operator review."""
    import os
    if "postgres" not in os.environ.get("DATABASE_URL", ""):
        return {"status": "error", "message": "Postgres required"}
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            UPDATE ssh_capabilities
            SET new_host_alert = false
            WHERE connection_id = %s AND target_host = %s
        """, (connection_id, target_host))
        conn.commit(); cur.close(); conn.close()
        return {"status": "ok", "message": "Alert cleared"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── Result Store ─────────────────────────────────────────────────────────────

@router.get("/session/{session_id}/output")
async def get_session_output(
    session_id: str,
    type_filter: str = Query("", description="Comma-separated types: step,tool,reasoning,halt,done,error,memory"),
    keyword: str = Query("", description="Case-insensitive keyword filter on content"),
    limit: int = Query(500, ge=1, le=2000),
    _: str = Depends(get_current_user),
):
    """Return the full raw WS output log for a session from operation_log table.

    Used by 'View full log' and the Raw Output sub-panel in Operations detail.
    Lines are in chronological order (oldest first).
    """
    try:
        import json as _json

        types = [t.strip() for t in type_filter.split(",") if t.strip()] if type_filter else []

        where_clauses = ["session_id = :sid"]
        params: dict = {"sid": session_id, "lim": limit}

        if types:
            where_clauses.append("type = ANY(:types)")
            params["types"] = types

        if keyword:
            where_clauses.append("content ILIKE :kw")
            params["kw"] = f"%{keyword}%"

        where = " AND ".join(where_clauses)
        sql = f"""
            SELECT id, type, content, metadata, timestamp
            FROM operation_log
            WHERE {where}
            ORDER BY timestamp ASC
            LIMIT :lim
        """

        async with get_engine().connect() as conn:
            rows = await conn.execute(text(sql), params)
            lines = []
            for row in rows:
                meta = {}
                try:
                    meta = _json.loads(row[3]) if row[3] else {}
                except Exception:
                    pass
                lines.append({
                    "id": row[0],
                    "type": row[1],
                    "content": row[2] or "",
                    "timestamp": row[4].isoformat() if row[4] else "",
                    **meta,
                })

        return {
            "session_id": session_id,
            "count": len(lines),
            "lines": lines,
            "filters": {"types": types, "keyword": keyword},
        }
    except Exception as e:
        raise HTTPException(500, f"Session output fetch failed: {e}")


@router.get("/result-store")
async def list_result_refs(
    limit: int = 50,
    session_id: str = "",
    _: str = Depends(get_current_user),
):
    """List active (non-expired) result store references."""
    try:
        from api.db.result_store import _is_pg
        if not _is_pg():
            return {"refs": [], "count": 0}
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        sql = """
            SELECT id, tool_name, session_id, operation_id,
                   row_count, columns, created_at, expires_at, accessed_at
            FROM result_store
            WHERE expires_at > NOW()
        """
        params = []
        if session_id:
            sql += " AND session_id = %s"
            params.append(session_id)
        sql += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.close(); conn.close()
        for r in rows:
            for k in ('created_at', 'expires_at', 'accessed_at'):
                if r.get(k):
                    try: r[k] = r[k].isoformat()
                    except: pass
            if isinstance(r.get('columns'), list):
                r['columns'] = r['columns']
        return {"refs": rows, "count": len(rows)}
    except Exception as e:
        return {"refs": [], "count": 0, "error": str(e)}


@router.get("/session-log/stats")
async def session_log_stats(_: str = Depends(get_current_user)):
    """Diagnostic: check operation_log table size and most recent sessions."""
    try:
        from api.db.base import get_engine
        from sqlalchemy import text as _t
        engine = get_engine()
        async with engine.connect() as conn:
            total = (await conn.execute(_t(
                "SELECT COUNT(*) FROM operation_log"
            ))).scalar()
            recent = await conn.execute(_t(
                "SELECT session_id, COUNT(*) as cnt, MAX(timestamp) as latest "
                "FROM operation_log GROUP BY session_id "
                "ORDER BY latest DESC LIMIT 10"
            ))
            rows = [{"session_id": r[0], "count": r[1], "latest": str(r[2])}
                    for r in recent]
        return {"total_rows": total, "recent_sessions": rows}
    except Exception as e:
        return {"error": str(e), "total_rows": 0}


@router.get("/result-store/{ref}")
async def get_result_ref(
    ref: str,
    offset: int = 0,
    limit: int = 20,
    _: str = Depends(get_current_user),
):
    """Retrieve rows from a specific result ref."""
    from api.db.result_store import fetch_result
    result = fetch_result(ref, offset=offset, limit=limit)
    if result is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Ref not found or expired")
    return result
