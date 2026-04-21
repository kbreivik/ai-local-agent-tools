"""v2.36.9 — set_operation_final_answer_prepend + clobber-race regression.

Tests follow the existing pattern from tests/test_operations_model_column.py
(sync pytest via `_run` helper, `_REQUIRES_PG` marker for Postgres-only
paths). The helper is postgres-only because it writes via the SQLAlchemy
async engine bound at startup.
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


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


async def _read_final_answer(session_id: str) -> str | None:
    async with get_engine().connect() as conn:
        r = await conn.execute(
            text(
                "SELECT final_answer FROM operations "
                "WHERE session_id = :sid ORDER BY started_at DESC LIMIT 1"
            ),
            {"sid": session_id},
        )
        row = r.fetchone()
    return row[0] if row else None


@_REQUIRES_PG
def test_prepend_above_existing_content():
    """Render tool writes table; cleanup prepends caption. Final order:
    caption first, then blank line, then table. NOT table-then-clobber."""
    session_id = str(uuid.uuid4())

    # Setup: create an operation row via existing API
    _run(logger_mod.log_operation_start(
        session_id, "render-and-caption test", triggered_by="test",
    ))

    # Mid-run: render tool appends a pipe-delimited table
    _run(logger_mod.set_operation_final_answer_append(
        session_id, "| hostname | ip |\n|---|---|\n| h1 | 10.0.0.1 |",
    ))

    # End-of-run: cleanup prepends caption
    _run(logger_mod.set_operation_final_answer_prepend(
        session_id, "All 42 clients (table below):",
    ))

    final = _run(_read_final_answer(session_id))
    assert final is not None
    assert final.startswith("All 42 clients (table below):")
    assert "| hostname | ip |" in final
    # Caption must appear BEFORE table
    assert final.index("All 42 clients") < final.index("| hostname | ip |")


@_REQUIRES_PG
def test_prepend_noop_on_empty_prefix():
    """Empty / whitespace prefix is a no-op, not an overwrite."""
    session_id = str(uuid.uuid4())
    _run(logger_mod.log_operation_start(session_id, "test", "test"))
    _run(logger_mod.set_operation_final_answer_append(session_id, "original"))

    _run(logger_mod.set_operation_final_answer_prepend(session_id, ""))
    _run(logger_mod.set_operation_final_answer_prepend(session_id, "   \n  "))

    final = _run(_read_final_answer(session_id))
    assert final == "original"


@_REQUIRES_PG
def test_prepend_noop_when_operation_missing():
    """No exception when the operation row doesn't exist."""
    _run(logger_mod.set_operation_final_answer_prepend(
        "nonexistent-session-id-" + str(uuid.uuid4()), "some caption",
    ))
    # If we got here, the helper handled the missing-row case gracefully.
