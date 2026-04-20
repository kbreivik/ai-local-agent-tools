"""v2.36.4 — GET /api/external-ai/calls smoke test.

Inserts a row via write_external_ai_call, asserts list_recent_external_calls
returns it. Skips on non-postgres environments (CI usually runs against
sqlite stub).
"""
import os
import pytest


@pytest.mark.skipif(
    "postgres" not in os.environ.get("DATABASE_URL", ""),
    reason="requires postgres",
)
def test_write_and_list_round_trip():
    from api.db.external_ai_calls import (
        init_external_ai_calls, write_external_ai_call,
        list_recent_external_calls,
    )
    init_external_ai_calls()
    write_external_ai_call(
        operation_id="test-op-v2.36.4", step_index=None,
        provider="claude", model="claude-sonnet-4-6",
        rule_fired="budget_exhaustion", output_mode="replace",
        latency_ms=1234, input_tokens=100, output_tokens=50,
        est_cost_usd=0.00105, outcome="success", error_message=None,
    )
    rows = list_recent_external_calls(limit=10)
    assert any(r["operation_id"] == "test-op-v2.36.4" for r in rows)


def test_list_returns_empty_on_non_pg():
    """Smoke: doesn't crash without postgres."""
    from api.db.external_ai_calls import list_recent_external_calls
    rows = list_recent_external_calls(limit=10)
    assert isinstance(rows, list)
