"""GET /api/logs — retrieve tool call logs from SQLite."""
from fastapi import APIRouter, Query
from api.db import get_db

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("")
async def get_logs(
    status: str = Query("all", description="all | ok | degraded | failed | escalated | error"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    tool: str = Query("", description="Filter by tool name"),
):
    db = await get_db()
    try:
        clauses = []
        args = []
        if status != "all":
            clauses.append("tc.status = ?")
            args.append(status)
        if tool:
            clauses.append("tc.tool_name LIKE ?")
            args.append(f"%{tool}%")

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        args += [limit, offset]

        rows = await db.execute_fetchall(
            f"""SELECT tc.id, tc.timestamp, tc.tool_name, tc.params, tc.result,
                       tc.status, tc.model_used, tc.duration_ms,
                       op.session_id, op.label
                FROM tool_calls tc
                LEFT JOIN operations op ON tc.operation_id = op.id
                {where}
                ORDER BY tc.timestamp DESC
                LIMIT ? OFFSET ?""",
            args,
        )
        count_row = await db.execute_fetchall(
            f"SELECT COUNT(*) as n FROM tool_calls tc {where}",
            args[:-2],
        )
        total = count_row[0]["n"] if count_row else 0
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "logs": [dict(r) for r in rows],
        }
    finally:
        await db.close()


@router.get("/operations")
async def get_operations(limit: int = Query(50, ge=1, le=500)):
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT * FROM operations ORDER BY started_at DESC LIMIT ?", (limit,)
        )
        return {"operations": [dict(r) for r in rows]}
    finally:
        await db.close()


@router.get("/snapshots/{component}")
async def get_snapshots(component: str, limit: int = Query(20, ge=1, le=200)):
    db = await get_db()
    try:
        rows = await db.execute_fetchall(
            "SELECT * FROM status_snapshots WHERE component=? ORDER BY timestamp DESC LIMIT ?",
            (component, limit),
        )
        return {"snapshots": [dict(r) for r in rows]}
    finally:
        await db.close()
