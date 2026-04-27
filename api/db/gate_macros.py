"""gate_macros — store recorded gate sequences from real test runs.

A macro is a named replayable sequence of gate answers (clarifications
+ plan_action approvals/cancels) captured from one specific test_run.
Macros are addressable by name and can later be applied to a fresh
test run instead of using the TestCase's hardcoded fields.

v2.47.18 — Phase 1: record-only. Replay is wired in Phase 2.
v2.47.19 — sync rewrite using psycopg2; v2.47.18 async version failed
because asyncpg rejects multi-statement DDL.

This module is sync-only (matches known_facts.py / test_runs.py
conventions), never raises into callers, and no-ops on SQLite.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

log = logging.getLogger(__name__)


_DDL_PG = """
CREATE TABLE IF NOT EXISTS gate_macros (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name          TEXT NOT NULL,
    description   TEXT NOT NULL DEFAULT '',
    source_run_id UUID,
    test_id       TEXT NOT NULL,
    gates         JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by    TEXT NOT NULL DEFAULT 'system',
    UNIQUE (name, test_id)
);

CREATE INDEX IF NOT EXISTS ix_gate_macros_name ON gate_macros (name);
CREATE INDEX IF NOT EXISTS ix_gate_macros_test ON gate_macros (test_id);
"""


_initialized = False


def _is_pg() -> bool:
    return "postgres" in os.environ.get("DATABASE_URL", "")


def _conn():
    """Sync psycopg2 connection — same pattern as test_runs.py."""
    from api.connections import _get_conn
    return _get_conn()


def init_gate_macros() -> bool:
    """Create gate_macros table + indexes. Idempotent. Sync. Best-effort."""
    global _initialized
    if _initialized:
        return True
    if not _is_pg():
        _initialized = True
        return True
    try:
        conn = _conn()
        if conn is None:
            return False
        conn.autocommit = True
        cur = conn.cursor()
        # Split DDL on ; — psycopg2 doesn't run multi-statement strings cleanly
        # without a server-side context. Same pattern as known_facts.py.
        for stmt in _DDL_PG.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                cur.execute(stmt)
        cur.close()
        conn.close()
        _initialized = True
        log.info("gate_macros table ready")
        return True
    except Exception as e:
        log.warning("gate_macros init failed: %s", e)
        return False


# ── Read API ──────────────────────────────────────────────────────────────────

def _rows_to_dicts(cur) -> list[dict]:
    """Convert a cursor's results to dicts with ISO timestamps."""
    cols = [d[0] for d in cur.description]
    out = []
    for r in cur.fetchall():
        d = dict(zip(cols, r))
        for k, v in list(d.items()):
            if hasattr(v, "isoformat"):
                d[k] = v.isoformat()
            elif k == "id" and v is not None:
                d[k] = str(v)
            elif k == "source_run_id" and v is not None:
                d[k] = str(v)
        out.append(d)
    return out


def list_macros(name_filter: str | None = None) -> list[dict]:
    """Return all macros, optionally filtered by name prefix."""
    if not _is_pg():
        return []
    try:
        conn = _conn()
        if conn is None:
            return []
        cur = conn.cursor()
        if name_filter:
            cur.execute(
                "SELECT id, name, description, source_run_id, test_id, "
                "gates, created_at, created_by "
                "FROM gate_macros WHERE name LIKE %s "
                "ORDER BY name, test_id",
                (f"{name_filter}%",),
            )
        else:
            cur.execute(
                "SELECT id, name, description, source_run_id, test_id, "
                "gates, created_at, created_by "
                "FROM gate_macros ORDER BY name, test_id"
            )
        rows = _rows_to_dicts(cur)
        cur.close()
        conn.close()
        return rows
    except Exception as e:
        log.warning("list_macros failed: %s", e)
        return []


def get_macro(name: str, test_id: str) -> dict | None:
    """Return one macro by (name, test_id) or None."""
    if not _is_pg() or not name or not test_id:
        return None
    try:
        conn = _conn()
        if conn is None:
            return None
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, description, source_run_id, test_id, "
            "gates, created_at, created_by "
            "FROM gate_macros WHERE name = %s AND test_id = %s",
            (name, test_id),
        )
        rows = _rows_to_dicts(cur)
        cur.close()
        conn.close()
        return rows[0] if rows else None
    except Exception as e:
        log.warning("get_macro failed: %s", e)
        return None


# ── Write API ─────────────────────────────────────────────────────────────────

def record_macro(
    *,
    name: str,
    description: str,
    source_run_id: str,
    test_id: str,
    gates: list[dict],
    created_by: str = "system",
) -> dict:
    """Insert or replace a macro for (name, test_id).

    `gates` is a list of dicts. Recognised shapes:
      {"kind": "clarification", "question": str, "answer": str}
      {"kind": "plan", "summary": str, "steps_count": int, "approved": bool}
    """
    if not _is_pg() or not name or not test_id:
        return {"name": name, "test_id": test_id, "gates_count": 0,
                "error": "noop"}
    try:
        conn = _conn()
        if conn is None:
            return {"name": name, "test_id": test_id, "gates_count": 0,
                    "error": "no_connection"}
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO gate_macros "
            "(name, description, source_run_id, test_id, gates, created_by) "
            "VALUES (%s, %s, %s, %s, %s::jsonb, %s) "
            "ON CONFLICT (name, test_id) DO UPDATE SET "
            "description = EXCLUDED.description, "
            "source_run_id = EXCLUDED.source_run_id, "
            "gates = EXCLUDED.gates, "
            "created_by = EXCLUDED.created_by, "
            "created_at = NOW()",
            (name, description, source_run_id, test_id,
             json.dumps(gates), created_by),
        )
        conn.commit()
        cur.close()
        conn.close()
        return {"name": name, "test_id": test_id,
                "gates_count": len(gates)}
    except Exception as e:
        log.warning("record_macro failed: %s", e)
        return {"name": name, "test_id": test_id, "gates_count": 0,
                "error": str(e)}


def delete_macro(name: str, test_id: str | None = None) -> int:
    """Delete one macro (if test_id given) or all macros named `name`."""
    if not _is_pg() or not name:
        return 0
    try:
        conn = _conn()
        if conn is None:
            return 0
        cur = conn.cursor()
        if test_id:
            cur.execute(
                "DELETE FROM gate_macros WHERE name = %s AND test_id = %s",
                (name, test_id),
            )
        else:
            cur.execute(
                "DELETE FROM gate_macros WHERE name = %s",
                (name,),
            )
        rows = cur.rowcount or 0
        conn.commit()
        cur.close()
        conn.close()
        return rows
    except Exception as e:
        log.warning("delete_macro failed: %s", e)
        return 0


# ── Run-to-macro extraction ───────────────────────────────────────────────────

def extract_gates_from_test_result(test_result: dict) -> list[dict]:
    """Pull gate events from a single test_run_result row.

    Returns a list with at most 2 entries (one clarification, one plan)
    matching the test_run_results schema:
      - clarification_question + clarification_answer_used
      - plan_summary + plan_steps_count + plan_approved
    """
    gates: list[dict] = []
    if test_result.get("clarification_question"):
        gates.append({
            "kind": "clarification",
            "question": test_result.get("clarification_question") or "",
            "answer":   test_result.get("clarification_answer_used") or "",
        })
    if test_result.get("plan_summary"):
        gates.append({
            "kind":        "plan",
            "summary":     test_result.get("plan_summary") or "",
            "steps_count": int(test_result.get("plan_steps_count") or 0),
            "approved":    bool(test_result.get("plan_approved")),
        })
    return gates
