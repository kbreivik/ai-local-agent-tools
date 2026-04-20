"""v2.36.7 — operations.model_used is populated at insert and backfilled
from agent_llm_traces on completion.

Two failure modes this test locks in:

1. Regression: the `log_operation` legacy alias used to silently drop
   `model_used`. If someone re-introduces the 3-arg signature without
   kwarg forwarding, `test_log_operation_alias_forwards_model_used`
   fails.

2. Regression: the complete-time backfill from `agent_llm_traces` was
   the v2.36.0 -> v2.36.7 missing link between provenance and the
   Operations view. If anyone removes the COALESCE subquery from
   `log_operation_complete`, `test_completion_backfills_model_from_trace`
   fails.
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from sqlalchemy import text

from api.db.base import get_engine
from api import logger as logger_mod


_REQUIRES_PG = pytest.mark.skipif(
    "postgres" not in os.environ.get("DATABASE_URL", ""),
    reason="requires postgres",
)


# ── Helper: run async test in sync pytest ─────────────────────────────────────

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── Helper: insert a fake agent_llm_traces row ────────────────────────────────

async def _insert_trace_row(operation_id: str, step_index: int, model: str) -> None:
    """Insert a minimal agent_llm_traces row for backfill testing.

    Uses raw SQL to avoid pulling in the full llm_traces schema — we only
    need step_index + model for the backfill subquery to find the row.
    """
    async with get_engine().begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO agent_llm_traces "
                "(id, operation_id, step_index, model, messages_delta, "
                " response_raw, created_at) "
                "VALUES (:id, :op, :step, :model, '[]'::jsonb, '{}'::jsonb, NOW())"
            ),
            {
                "id":    str(uuid.uuid4()),
                "op":    operation_id,
                "step":  step_index,
                "model": model,
            },
        )


async def _read_model_used(operation_id: str) -> str | None:
    async with get_engine().connect() as conn:
        result = await conn.execute(
            text("SELECT model_used FROM operations WHERE id = :id"),
            {"id": operation_id},
        )
        row = result.fetchone()
    return row[0] if row else None


# ── Tests ─────────────────────────────────────────────────────────────────────

@_REQUIRES_PG
def test_log_operation_alias_forwards_model_used():
    """The 3-arg `log_operation` alias must forward `model_used` kwarg."""
    session_id = str(uuid.uuid4())
    op_id = _run(logger_mod.log_operation(
        session_id=session_id,
        label="test v2.36.7 insert-seed",
        owner_user="test",
        model_used="test-model-v2.36.7",
    ))

    assert op_id

    model = _run(_read_model_used(op_id))
    assert model == "test-model-v2.36.7", (
        f"insert-time seed not persisted; got {model!r}. "
        "Check log_operation alias forwards model_used kwarg."
    )


@_REQUIRES_PG
def test_completion_backfills_model_from_trace():
    """log_operation_complete backfills model_used from latest trace row.

    Scenario: op inserts with seed='local-model'. Two trace rows written
    — step_index=0 with 'local-model', step_index=99999 with 'external-
    claude'. Completion must pick the higher step_index (external).
    """
    session_id = str(uuid.uuid4())
    op_id = _run(logger_mod.log_operation(
        session_id=session_id,
        label="test v2.36.7 complete-backfill",
        owner_user="test",
        model_used="local-model",
    ))

    # Simulate a v2.36.3 external-AI escalation: two trace rows, the
    # higher step_index carrying the external model name.
    _run(_insert_trace_row(op_id, step_index=0,     model="local-model"))
    _run(_insert_trace_row(op_id, step_index=99999, model="external-claude"))

    _run(logger_mod.log_operation_complete(op_id, status="completed"))

    model = _run(_read_model_used(op_id))
    assert model == "external-claude", (
        f"completion backfill should pick the highest step_index row "
        f"(external-claude), got {model!r}"
    )


@_REQUIRES_PG
def test_completion_preserves_seed_when_no_trace():
    """Empty `agent_llm_traces` → COALESCE preserves insert-time seed."""
    session_id = str(uuid.uuid4())
    op_id = _run(logger_mod.log_operation(
        session_id=session_id,
        label="test v2.36.7 complete-no-trace",
        owner_user="test",
        model_used="seed-only",
    ))

    _run(logger_mod.log_operation_complete(op_id, status="completed"))

    model = _run(_read_model_used(op_id))
    assert model == "seed-only", (
        f"no trace rows — COALESCE must preserve the insert-time seed; "
        f"got {model!r}"
    )


@_REQUIRES_PG
def test_completion_ignores_empty_trace_model():
    """Trace row with empty model → COALESCE skips it and preserves seed."""
    session_id = str(uuid.uuid4())
    op_id = _run(logger_mod.log_operation(
        session_id=session_id,
        label="test v2.36.7 complete-empty-trace-model",
        owner_user="test",
        model_used="seed-value",
    ))

    # Pre-v2.36.0 trace row — model column empty (it existed before the
    # provenance fix). Backfill SQL filters on `model <> ''` so this
    # row is ignored and the seed value is preserved.
    _run(_insert_trace_row(op_id, step_index=5, model=""))

    _run(logger_mod.log_operation_complete(op_id, status="completed"))

    model = _run(_read_model_used(op_id))
    assert model == "seed-value", (
        f"empty trace.model should be filtered by the WHERE clause; "
        f"got {model!r}"
    )
