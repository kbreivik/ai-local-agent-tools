"""v2.37.1 — /api/logs/escalations reads from agent_escalations.

Regression test for the split-brain bug where record_escalation wrote
to agent_escalations but the Logs view read from the orphaned SQLAlchemy
`escalations` table.
"""
import os
import uuid
import pytest

pg_only = pytest.mark.skipif(
    "postgres" not in os.environ.get("DATABASE_URL", ""),
    reason="Postgres required for this test",
)


@pg_only
def test_logs_escalations_returns_rows_written_by_record_escalation(test_client):
    """Seed agent_escalations directly (simulating record_escalation),
    then hit the logs endpoint and assert the row appears."""
    from api.routers.escalations import record_escalation, init_escalations
    init_escalations()

    reason = f"v2.37.1 regression test {uuid.uuid4()}"
    eid = record_escalation(
        session_id="test-session-v2371",
        reason=reason,
        operation_id="",
        severity="critical",
    )
    assert eid

    r = test_client.get("/api/logs/escalations?limit=50")
    assert r.status_code == 200
    data = r.json()
    assert "escalations" in data
    matching = [e for e in data["escalations"] if e["id"] == eid]
    assert len(matching) == 1, (
        f"expected exactly one row for id={eid}, got {len(matching)}; "
        f"full response: {data}"
    )
    row = matching[0]
    # Shape match — fields frontend EscView expects
    assert row["reason"] == reason
    assert row["severity"] == "critical"
    assert row["resolved"] is False            # acknowledged=False → resolved=False
    assert row["resolved_at"] is None
    assert row["timestamp"] is not None         # created_at → timestamp
    assert "context" in row                     # empty dict, frontend tolerates


@pg_only
def test_logs_escalations_resolve_marks_agent_escalations_acked(test_client):
    """POST /resolve should set acknowledged=TRUE on the underlying row."""
    from api.routers.escalations import record_escalation, init_escalations
    init_escalations()
    eid = record_escalation(
        session_id="test-resolve-v2371",
        reason=f"resolve-test {uuid.uuid4()}",
        operation_id="",
        severity="warning",
    )

    r = test_client.post(f"/api/logs/escalations/{eid}/resolve")
    assert r.status_code == 200
    assert r.json()["resolved"] is True

    # Second resolve should 404 (already acknowledged)
    r2 = test_client.post(f"/api/logs/escalations/{eid}/resolve")
    assert r2.status_code == 404

    # Verify via list that resolved=True now reflected
    r3 = test_client.get("/api/logs/escalations?limit=50")
    row = next(e for e in r3.json()["escalations"] if e["id"] == eid)
    assert row["resolved"] is True
    assert row["resolved_at"] is not None


@pg_only
def test_logs_escalations_include_resolved_default_true(test_client):
    """Logs view is history — must include resolved by default."""
    from api.routers.escalations import record_escalation, init_escalations
    init_escalations()
    eid = record_escalation(
        session_id="test-history-v2371",
        reason=f"history-test {uuid.uuid4()}",
        operation_id="",
        severity="warning",
    )
    test_client.post(f"/api/logs/escalations/{eid}/resolve")

    # Default (no query param) — resolved row should be present
    r = test_client.get("/api/logs/escalations?limit=50")
    ids = [e["id"] for e in r.json()["escalations"]]
    assert eid in ids, "Logs endpoint must include resolved by default"

    # Explicit include_resolved=false — resolved row should be absent
    r2 = test_client.get("/api/logs/escalations?limit=50&include_resolved=false")
    ids2 = [e["id"] for e in r2.json()["escalations"]]
    assert eid not in ids2
