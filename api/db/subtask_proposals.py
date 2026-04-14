"""Subtask proposals — agent-generated offers to run a follow-up execute task."""
import json
import logging
import uuid
from datetime import datetime, timezone

log = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS subtask_proposals (
    id                TEXT PRIMARY KEY,
    parent_session_id TEXT NOT NULL DEFAULT '',
    parent_op_id      TEXT NOT NULL DEFAULT '',
    task              TEXT NOT NULL,
    executable_steps  JSONB NOT NULL DEFAULT '[]',
    manual_steps      JSONB NOT NULL DEFAULT '[]',
    confidence        TEXT NOT NULL DEFAULT 'medium',
    status            TEXT NOT NULL DEFAULT 'pending',
    created_at        TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_proposals_status  ON subtask_proposals(status);
CREATE INDEX IF NOT EXISTS idx_proposals_session ON subtask_proposals(parent_session_id);
"""

_initialized = False

def _ts():
    return datetime.now(timezone.utc).isoformat()

def init_subtask_proposals():
    global _initialized
    if _initialized: return
    try:
        from api.connections import _get_conn
        conn = _get_conn(); conn.autocommit = True
        cur = conn.cursor()
        for stmt in _DDL.strip().split(";"):
            s = stmt.strip()
            if s: cur.execute(s)
        cur.close(); conn.close()
        _initialized = True
        log.info("subtask_proposals table ready")
    except Exception as e:
        log.warning("subtask_proposals init failed: %s", e)

def save_proposal(proposal_id: str, parent_session_id: str, parent_op_id: str,
                  task: str, executable_steps: list, manual_steps: list,
                  confidence: str = "medium") -> bool:
    try:
        from api.connections import _get_conn
        conn = _get_conn(); cur = conn.cursor()
        cur.execute(
            """INSERT INTO subtask_proposals
               (id, parent_session_id, parent_op_id, task, executable_steps,
                manual_steps, confidence, status)
               VALUES (%s,%s,%s,%s,%s,%s,%s,'pending')""",
            (proposal_id, parent_session_id, parent_op_id, task,
             json.dumps(executable_steps), json.dumps(manual_steps), confidence),
        )
        conn.commit(); cur.close(); conn.close()
        return True
    except Exception as e:
        log.debug("save_proposal failed: %s", e)
        return False

def update_proposal_status(proposal_id: str, status: str) -> bool:
    try:
        from api.connections import _get_conn
        conn = _get_conn(); cur = conn.cursor()
        cur.execute(
            "UPDATE subtask_proposals SET status=%s WHERE id=%s",
            (status, proposal_id),
        )
        conn.commit(); cur.close(); conn.close()
        return True
    except Exception as e:
        log.debug("update_proposal_status failed: %s", e)
        return False

def get_proposal(proposal_id: str) -> dict | None:
    try:
        from api.connections import _get_conn
        conn = _get_conn(); cur = conn.cursor()
        cur.execute(
            """SELECT id, parent_session_id, parent_op_id, task,
                      executable_steps, manual_steps, confidence, status, created_at
               FROM subtask_proposals WHERE id=%s""",
            (proposal_id,),
        )
        row = cur.fetchone()
        cur.close(); conn.close()
        if not row: return None
        return {
            "id": row[0], "parent_session_id": row[1], "parent_op_id": row[2],
            "task": row[3], "executable_steps": row[4] or [],
            "manual_steps": row[5] or [], "confidence": row[6],
            "status": row[7], "created_at": row[8].isoformat() if row[8] else "",
        }
    except Exception as e:
        log.debug("get_proposal failed: %s", e)
        return None

def list_proposals(status: str = "pending", limit: int = 10) -> list:
    try:
        from api.connections import _get_conn
        conn = _get_conn(); cur = conn.cursor()
        cur.execute(
            """SELECT id, parent_session_id, task, executable_steps,
                      manual_steps, confidence, status, created_at
               FROM subtask_proposals WHERE status=%s
               ORDER BY created_at DESC LIMIT %s""",
            (status, limit),
        )
        rows = cur.fetchall(); cur.close(); conn.close()
        return [
            {"id": r[0], "parent_session_id": r[1], "task": r[2],
             "executable_steps": r[3] or [], "manual_steps": r[4] or [],
             "confidence": r[5], "status": r[6],
             "created_at": r[7].isoformat() if r[7] else ""}
            for r in rows
        ]
    except Exception as e:
        log.debug("list_proposals failed: %s", e)
        return []
