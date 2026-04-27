"""gate_macros — store recorded gate sequences from real test runs.

A macro is a named replayable sequence of gate answers (clarifications
+ plan_action approvals/cancels) captured from one specific test_run.
Macros are addressable by name and can later be applied to a fresh
test run instead of using the TestCase's hardcoded fields.

v2.47.18 — Phase 1: record-only. Replay is wired in Phase 2.
"""
from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text

from api.db.base import get_engine

log = logging.getLogger(__name__)


# ── Schema ────────────────────────────────────────────────────────────────────
_DDL = """
CREATE TABLE IF NOT EXISTS gate_macros (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name          TEXT NOT NULL,
    description   TEXT NOT NULL DEFAULT '',
    source_run_id UUID,
    test_id       TEXT NOT NULL,
    -- gates: JSON array of {kind, question?, answer?, plan_summary?, approved?}
    gates         JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by    TEXT NOT NULL DEFAULT 'system',
    UNIQUE (name, test_id)
);

CREATE INDEX IF NOT EXISTS ix_gate_macros_name ON gate_macros (name);
CREATE INDEX IF NOT EXISTS ix_gate_macros_test ON gate_macros (test_id);
"""


async def ensure_schema() -> None:
    """Create gate_macros table if missing."""
    try:
        async with get_engine().begin() as conn:
            await conn.execute(text(_DDL))
    except Exception as e:
        log.warning("gate_macros schema init failed: %s", e)


# ── Read API ──────────────────────────────────────────────────────────────────
async def list_macros(name_filter: Optional[str] = None) -> list[dict]:
    """Return all macros, optionally filtered by name prefix."""
    sql = (
        "SELECT id, name, description, source_run_id, test_id, "
        "gates, created_at, created_by "
        "FROM gate_macros"
    )
    params: dict = {}
    if name_filter:
        sql += " WHERE name LIKE :pat"
        params["pat"] = f"{name_filter}%"
    sql += " ORDER BY name, test_id"

    async with get_engine().begin() as conn:
        rows = (await conn.execute(text(sql), params)).mappings().all()
    return [dict(r) for r in rows]


async def get_macro(name: str, test_id: str) -> Optional[dict]:
    """Return one macro by (name, test_id) or None."""
    async with get_engine().begin() as conn:
        row = (await conn.execute(
            text(
                "SELECT id, name, description, source_run_id, test_id, "
                "gates, created_at, created_by "
                "FROM gate_macros WHERE name = :n AND test_id = :t"
            ),
            {"n": name, "t": test_id},
        )).mappings().first()
    return dict(row) if row else None


# ── Write API ─────────────────────────────────────────────────────────────────
async def record_macro(
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
    async with get_engine().begin() as conn:
        # Upsert
        await conn.execute(
            text(
                "INSERT INTO gate_macros "
                "(name, description, source_run_id, test_id, gates, created_by) "
                "VALUES (:n, :d, :s, :t, CAST(:g AS jsonb), :u) "
                "ON CONFLICT (name, test_id) DO UPDATE SET "
                "description = EXCLUDED.description, "
                "source_run_id = EXCLUDED.source_run_id, "
                "gates = EXCLUDED.gates, "
                "created_by = EXCLUDED.created_by, "
                "created_at = now()"
            ),
            {
                "n": name, "d": description, "s": source_run_id,
                "t": test_id, "g": json.dumps(gates), "u": created_by,
            },
        )
    return {
        "name": name, "test_id": test_id, "gates_count": len(gates),
    }


async def delete_macro(name: str, test_id: Optional[str] = None) -> int:
    """Delete one macro (if test_id given) or all macros named `name`."""
    if test_id:
        sql = "DELETE FROM gate_macros WHERE name = :n AND test_id = :t"
        params = {"n": name, "t": test_id}
    else:
        sql = "DELETE FROM gate_macros WHERE name = :n"
        params = {"n": name}
    async with get_engine().begin() as conn:
        result = await conn.execute(text(sql), params)
    return result.rowcount or 0


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
