"""Escalation tracking — store and serve unacknowledged agent escalations."""
import json
import logging
import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from api.auth import get_current_user
from api.metrics import ESCALATIONS

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/escalations", tags=["escalations"])

_DDL = """
CREATE TABLE IF NOT EXISTS agent_escalations (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    operation_id    TEXT,
    reason          TEXT NOT NULL,
    severity        TEXT DEFAULT 'warning',
    acknowledged    BOOLEAN DEFAULT FALSE,
    acknowledged_at TIMESTAMPTZ,
    acknowledged_by TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_escalations_session ON agent_escalations(session_id);
CREATE INDEX IF NOT EXISTS idx_escalations_acked   ON agent_escalations(acknowledged);
"""

_initialized = False

def init_escalations():
    global _initialized
    if _initialized: return
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        for stmt in _DDL.strip().split(";"):
            s = stmt.strip()
            if s: cur.execute(s)
        cur.close(); conn.close()
        _initialized = True
        log.info("agent_escalations table ready")
    except Exception as e:
        log.warning("agent_escalations init failed: %s", e)


def record_escalation(session_id: str, reason: str, operation_id: str = "",
                      severity: str = "warning") -> str:
    """Store an escalation. Returns the escalation ID."""
    eid = str(uuid.uuid4())
    try:
        ESCALATIONS.labels(reason=(reason or "unspecified")[:64]).inc()
    except Exception:
        pass
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO agent_escalations
               (id, session_id, operation_id, reason, severity)
               VALUES (%s, %s, %s, %s, %s)""",
            (eid, session_id, operation_id or None, reason[:1000], severity)
        )
        conn.commit(); cur.close(); conn.close()
    except Exception as e:
        log.warning("record_escalation failed: %s", e)
    return eid


@router.get("")
async def list_escalations(
    unacked_only: bool = True,
    limit: int = 20,
    _: str = Depends(get_current_user)
):
    """List escalations, unacknowledged first."""
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        where = "WHERE acknowledged = FALSE" if unacked_only else ""
        cur.execute(f"""
            SELECT id, session_id, operation_id, reason, severity,
                   acknowledged, acknowledged_at, acknowledged_by, created_at
            FROM agent_escalations
            {where}
            ORDER BY created_at DESC
            LIMIT %s
        """, (limit,))
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.close(); conn.close()
        for r in rows:
            for k in ('acknowledged_at', 'created_at'):
                if r.get(k):
                    try: r[k] = r[k].isoformat()
                    except: pass
        return {"escalations": rows, "count": len(rows)}
    except Exception as e:
        return {"escalations": [], "count": 0, "error": str(e)}


@router.post("/{escalation_id}/acknowledge")
async def acknowledge_escalation(
    escalation_id: str,
    user: str = Depends(get_current_user)
):
    """Acknowledge an escalation — clears it from the banner."""
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            UPDATE agent_escalations
            SET acknowledged = TRUE,
                acknowledged_at = NOW(),
                acknowledged_by = %s
            WHERE id = %s
        """, (user, escalation_id))
        updated = cur.rowcount
        conn.commit(); cur.close(); conn.close()
        return {"status": "ok" if updated else "error",
                "message": "Acknowledged" if updated else "Not found"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/acknowledge-all")
async def acknowledge_all_escalations(user: str = Depends(get_current_user)):
    """Acknowledge all outstanding escalations."""
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            UPDATE agent_escalations
            SET acknowledged = TRUE, acknowledged_at = NOW(), acknowledged_by = %s
            WHERE acknowledged = FALSE
        """, (user,))
        n = cur.rowcount
        conn.commit(); cur.close(); conn.close()
        return {"status": "ok", "acknowledged": n}
    except Exception as e:
        return {"status": "error", "message": str(e)}
