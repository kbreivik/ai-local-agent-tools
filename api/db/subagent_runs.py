"""subagent_runs — links each in-band sub-agent execution to its parent.

Introduced in v2.34.0. Tracks the ancestry chain, budget, destructive
permission, and terminal status of sub-agents spawned by parent agents
via propose_subtask (when the harness executes the proposal in-band
rather than surfacing it to the operator as a card).
"""
import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS subagent_runs (
    id                  TEXT PRIMARY KEY,
    parent_task_id      TEXT NOT NULL DEFAULT '',
    sub_task_id         TEXT NOT NULL UNIQUE,
    depth               INTEGER NOT NULL DEFAULT 1,
    spawned_at          TIMESTAMPTZ DEFAULT NOW(),
    completed_at        TIMESTAMPTZ,
    objective           TEXT NOT NULL,
    agent_type          TEXT NOT NULL,
    scope_entity        TEXT,
    budget_tools        INTEGER NOT NULL DEFAULT 8,
    tools_used          INTEGER DEFAULT 0,
    allow_destructive   BOOLEAN DEFAULT FALSE,
    terminal_status     TEXT,
    final_answer        TEXT,
    diagnosis           TEXT,
    error               TEXT
);
CREATE INDEX IF NOT EXISTS idx_subagent_parent ON subagent_runs(parent_task_id);
CREATE INDEX IF NOT EXISTS idx_subagent_sub    ON subagent_runs(sub_task_id);
"""

_initialized = False


def _ts():
    return datetime.now(timezone.utc).isoformat()


def init_subagent_runs():
    global _initialized
    if _initialized:
        return
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        for stmt in _DDL.strip().split(";"):
            s = stmt.strip()
            if s:
                cur.execute(s)
        cur.close()
        conn.close()
        _initialized = True
        log.info("subagent_runs table ready")
    except Exception as e:
        log.warning("subagent_runs init failed: %s", e)


def record_spawn(parent_task_id: str, sub_task_id: str, depth: int,
                 objective: str, agent_type: str, scope_entity: str | None,
                 budget_tools: int, allow_destructive: bool) -> bool:
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO subagent_runs
               (id, parent_task_id, sub_task_id, depth, objective, agent_type,
                scope_entity, budget_tools, allow_destructive)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (f"sr_{sub_task_id}", parent_task_id, sub_task_id, depth,
             (objective or "")[:2000], agent_type, scope_entity,
             int(budget_tools), bool(allow_destructive)),
        )
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        log.debug("record_spawn failed: %s", e)
        return False


def record_completion(sub_task_id: str, terminal_status: str,
                      final_answer: str | None, diagnosis: str | None,
                      tools_used: int, error: str | None = None) -> bool:
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            """UPDATE subagent_runs
                  SET completed_at=NOW(),
                      terminal_status=%s,
                      final_answer=%s,
                      diagnosis=%s,
                      tools_used=%s,
                      error=%s
                WHERE sub_task_id=%s""",
            (terminal_status,
             (final_answer or "")[:4000],
             (diagnosis or "")[:2000],
             int(tools_used or 0),
             (error or "")[:2000],
             sub_task_id),
        )
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        log.debug("record_completion failed: %s", e)
        return False


def get_ancestry(task_id: str) -> list[dict]:
    """Return the chain of parent tasks up to the root, ordered root-first.

    Walks the subagent_runs table from the given task_id up, following
    parent_task_id pointers. Used to compute depth and enforce caps.
    """
    chain: list[dict] = []
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        current = task_id
        for _ in range(10):  # hard stop against corrupt cycles
            cur.execute(
                """SELECT id, parent_task_id, sub_task_id, depth, objective,
                          agent_type, scope_entity, budget_tools, tools_used,
                          allow_destructive, terminal_status
                   FROM subagent_runs WHERE sub_task_id=%s""",
                (current,),
            )
            row = cur.fetchone()
            if not row:
                break
            chain.insert(0, {
                "id": row[0], "parent_task_id": row[1], "sub_task_id": row[2],
                "depth": row[3], "objective": row[4], "agent_type": row[5],
                "scope_entity": row[6], "budget_tools": row[7],
                "tools_used": row[8], "allow_destructive": bool(row[9]),
                "terminal_status": row[10],
            })
            current = row[1]
            if not current:
                break
        cur.close()
        conn.close()
    except Exception as e:
        log.debug("get_ancestry failed: %s", e)
    return chain


def list_children(parent_task_id: str) -> list[dict]:
    """Return sub-agent rows for a given parent task_id."""
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            """SELECT sub_task_id, depth, objective, agent_type, scope_entity,
                      budget_tools, tools_used, allow_destructive,
                      terminal_status, final_answer, diagnosis,
                      spawned_at, completed_at, error
               FROM subagent_runs
               WHERE parent_task_id=%s
               ORDER BY spawned_at ASC""",
            (parent_task_id,),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [
            {
                "sub_task_id": r[0], "depth": r[1], "objective": r[2],
                "agent_type": r[3], "scope_entity": r[4],
                "budget_tools": r[5], "tools_used": r[6],
                "allow_destructive": bool(r[7]),
                "terminal_status": r[8],
                "final_answer": r[9], "diagnosis": r[10],
                "spawned_at": r[11].isoformat() if r[11] else "",
                "completed_at": r[12].isoformat() if r[12] else "",
                "error": r[13],
            }
            for r in rows
        ]
    except Exception as e:
        log.debug("list_children failed: %s", e)
        return []
