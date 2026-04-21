"""v2.37.2 — /api/logs/operations populates agent_type from traces."""
import os
import uuid
import pytest
from sqlalchemy import text

pg_only = pytest.mark.skipif(
    "postgres" not in os.environ.get("DATABASE_URL", ""),
    reason="Postgres required",
)


@pg_only
@pytest.mark.asyncio
async def test_operations_list_returns_agent_type_from_trace(postgres_engine, test_client):
    """Seed an operation + a trace step; list endpoint should return the
    trace's agent_type, not the fallback default or '?'."""
    op_id = str(uuid.uuid4())
    async with postgres_engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO operations (id, session_id, label, status, owner_user, started_at) VALUES "
            "(:id, :sid, 'v2.37.2 agent_type test', 'completed', 'testuser', NOW())"
        ), {"id": op_id, "sid": f"sid-{op_id[:8]}"})
        await conn.execute(text(
            "INSERT INTO agent_llm_traces "
            "(operation_id, step_index, agent_type, model, messages_delta, response_raw) "
            "VALUES (:op, 0, 'investigate', 'qwen', '[]', '{}')"
        ), {"op": op_id})

    r = test_client.get("/api/logs/operations?limit=50")
    assert r.status_code == 200
    row = next(o for o in r.json()["operations"] if o["id"] == op_id)
    assert row["agent_type"] == "investigate"
    assert row["session_id"] == f"sid-{op_id[:8]}"


@pg_only
@pytest.mark.asyncio
async def test_operations_list_agent_type_fallback_when_no_traces(postgres_engine, test_client):
    """Operation with no trace rows falls back to 'observe', not null or '?'."""
    op_id = str(uuid.uuid4())
    async with postgres_engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO operations (id, session_id, label, status, owner_user, started_at) VALUES "
            "(:id, 'sid-notrace', 'no-trace operation', 'running', 'testuser', NOW())"
        ), {"id": op_id})

    r = test_client.get("/api/logs/operations?limit=100")
    row = next(o for o in r.json()["operations"] if o["id"] == op_id)
    assert row["agent_type"] == "observe"
    assert row["status"] == "running"


@pg_only
@pytest.mark.asyncio
async def test_operations_list_picks_first_step_agent_type(postgres_engine, test_client):
    """If multiple trace steps exist, agent_type comes from step_index=0
    (matches /recent endpoint behaviour)."""
    op_id = str(uuid.uuid4())
    async with postgres_engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO operations (id, session_id, label, status, owner_user, started_at) VALUES "
            "(:id, 'sid-multistep', 'multi-step op', 'completed', 'testuser', NOW())"
        ), {"id": op_id})
        await conn.execute(text(
            "INSERT INTO agent_llm_traces "
            "(operation_id, step_index, agent_type, model, messages_delta, response_raw) "
            "VALUES "
            "(:op, 0, 'execute', 'qwen', '[]', '{}'),"
            "(:op, 1, 'investigate', 'qwen', '[]', '{}')"
        ), {"op": op_id})

    r = test_client.get("/api/logs/operations?limit=100")
    row = next(o for o in r.json()["operations"] if o["id"] == op_id)
    assert row["agent_type"] == "execute"


@pg_only
@pytest.mark.asyncio
async def test_operations_list_includes_session_id_field(postgres_engine, test_client):
    """Regression: session_id must be present in the list response
    so TraceView can render it."""
    op_id = str(uuid.uuid4())
    sid = f"sid-{op_id[:8]}"
    async with postgres_engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO operations (id, session_id, label, status, owner_user, started_at) VALUES "
            "(:id, :sid, 'session_id presence test', 'completed', 'testuser', NOW())"
        ), {"id": op_id, "sid": sid})

    r = test_client.get("/api/logs/operations?limit=100")
    row = next(o for o in r.json()["operations"] if o["id"] == op_id)
    assert row.get("session_id") == sid
    assert row.get("task") == row.get("label") == "session_id presence test"
