"""v2.37.1 — /api/logs/operations/recent excludes 'direct:' tool fires."""
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
async def test_recent_excludes_direct_tool_fires(postgres_engine, test_client):
    user = "testuser"
    # Seed a normal task and a direct: tool fire for the same user
    async with postgres_engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO operations (id, session_id, label, status, owner_user, started_at) VALUES "
            "(gen_random_uuid(), 's_normal', 'List all Swarm services', 'completed', :u, NOW()),"
            "(gen_random_uuid(), 's_direct', 'direct:container_networks', 'completed', :u, NOW())"
        ), {"u": user})

    r = test_client.get("/api/logs/operations/recent?limit=50")
    assert r.status_code == 200
    tasks = [i["task"] for i in r.json()["items"]]
    assert "List all Swarm services" in tasks
    assert not any(t.startswith("direct:") for t in tasks), (
        f"direct: tool fires must not appear in RECENT, got: {tasks}"
    )
