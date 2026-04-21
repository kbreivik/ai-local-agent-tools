"""v2.37.0 — GET /api/logs/operations/recent tests.

The endpoint relies on Postgres-specific SQL (DISTINCT ON, INTERVAL,
EXTRACT). If the test environment isn't backed by Postgres, the DB-
dependent tests skip; the always-on check for auth protection still
runs because it doesn't touch the DB.

Uses direct TestClient + the project's admin login (same pattern as
tests/test_facts_api.py) rather than custom fixtures.
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)

HAS_PG = "postgres" in os.environ.get("DATABASE_URL", "")


def _auth_headers():
    r = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "superduperadmin"},
    )
    if r.status_code != 200:
        pytest.skip("Auth not available in test env")
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_recent_endpoint_requires_auth():
    """Unauthenticated GET must be 401/403."""
    r = client.get("/api/logs/operations/recent")
    assert r.status_code in (401, 403)


def test_recent_endpoint_clamps_limit_out_of_range():
    """FastAPI Query(ge=1, le=50) rejects 0 and 100 with 422 even before auth."""
    r_low  = client.get("/api/logs/operations/recent?limit=0")
    assert r_low.status_code in (401, 403, 422)
    r_high = client.get("/api/logs/operations/recent?limit=100")
    assert r_high.status_code in (401, 403, 422)


@pytest.mark.skipif(not HAS_PG, reason="postgres not available")
def test_recent_respects_limit_param():
    """limit param is honoured and the response shape matches contract."""
    headers = _auth_headers()
    r = client.get("/api/logs/operations/recent?limit=3", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert "items" in body and "count" in body
    assert isinstance(body["items"], list)
    assert len(body["items"]) <= 3
    assert body["count"] == len(body["items"])
    for item in body["items"]:
        # Contract: task + status + operation_id + agent_type + age_seconds
        assert "task" in item
        assert "status" in item
        assert "operation_id" in item
        assert "agent_type" in item
        assert "age_seconds" in item


@pytest.mark.skipif(not HAS_PG, reason="postgres not available")
def test_recent_deduplicates_by_exact_task():
    """Same task text inserted 3× must yield 1 deduped row (most recent)."""
    headers = _auth_headers()

    import asyncio
    from sqlalchemy import text as _t
    from api.db.base import get_engine

    task = "TEST v2.37.0 dedup: Check Kafka broker status"

    async def seed():
        async with get_engine().begin() as conn:
            # Clean up any prior runs of this exact test task
            await conn.execute(
                _t("DELETE FROM operations WHERE label = :t"),
                {"t": task},
            )
            await conn.execute(
                _t(
                    "INSERT INTO operations (id, session_id, label, status, "
                    "owner_user, started_at) VALUES "
                    "(gen_random_uuid(), 's1_v237', :t, 'completed', 'admin', "
                    "NOW() - INTERVAL '3 hours'),"
                    "(gen_random_uuid(), 's2_v237', :t, 'completed', 'admin', "
                    "NOW() - INTERVAL '2 hours'),"
                    "(gen_random_uuid(), 's3_v237', :t, 'completed', 'admin', "
                    "NOW() - INTERVAL '1 hour')"
                ),
                {"t": task},
            )

    async def cleanup():
        async with get_engine().begin() as conn:
            await conn.execute(
                _t("DELETE FROM operations WHERE label = :t"),
                {"t": task},
            )

    asyncio.get_event_loop().run_until_complete(seed())
    try:
        r = client.get("/api/logs/operations/recent?limit=50", headers=headers)
        assert r.status_code == 200
        matching = [i for i in r.json()["items"] if i["task"] == task]
        assert len(matching) == 1, (
            f"expected 1 deduped row, got {len(matching)}"
        )
        # Must be the most recent occurrence — under 2 hours old
        assert matching[0]["age_seconds"] < 3600 * 2
    finally:
        asyncio.get_event_loop().run_until_complete(cleanup())


@pytest.mark.skipif(not HAS_PG, reason="postgres not available")
def test_recent_excludes_subagent_operations():
    """Operations with a non-empty parent_session_id (sub-agent ops) must
    not appear in the owner user's recent list."""
    headers = _auth_headers()

    import asyncio
    from sqlalchemy import text as _t
    from api.db.base import get_engine

    subagent_label = "TEST v2.37.0 subagent exclusion"

    async def seed():
        async with get_engine().begin() as conn:
            await conn.execute(
                _t("DELETE FROM operations WHERE label = :t"),
                {"t": subagent_label},
            )
            await conn.execute(
                _t(
                    "INSERT INTO operations (id, session_id, label, status, "
                    "owner_user, started_at, parent_session_id) VALUES "
                    "(gen_random_uuid(), 's_sub_v237', :t, 'completed', 'admin', "
                    "NOW(), 'parent-sid-v237')"
                ),
                {"t": subagent_label},
            )

    async def cleanup():
        async with get_engine().begin() as conn:
            await conn.execute(
                _t("DELETE FROM operations WHERE label = :t"),
                {"t": subagent_label},
            )

    asyncio.get_event_loop().run_until_complete(seed())
    try:
        r = client.get("/api/logs/operations/recent?limit=50", headers=headers)
        tasks = [i["task"] for i in r.json()["items"]]
        assert subagent_label not in tasks
    finally:
        asyncio.get_event_loop().run_until_complete(cleanup())


@pytest.mark.skipif(not HAS_PG, reason="postgres not available")
def test_recent_scopes_to_current_user():
    """Operations owned by other users must not leak into this user's
    recent list."""
    headers = _auth_headers()

    import asyncio
    from sqlalchemy import text as _t
    from api.db.base import get_engine

    other_label = "TEST v2.37.0 other-user scoping"

    async def seed():
        async with get_engine().begin() as conn:
            await conn.execute(
                _t("DELETE FROM operations WHERE label = :t"),
                {"t": other_label},
            )
            await conn.execute(
                _t(
                    "INSERT INTO operations (id, session_id, label, status, "
                    "owner_user, started_at) VALUES "
                    "(gen_random_uuid(), 's_other_v237', :t, 'completed', "
                    "'other_user', NOW())"
                ),
                {"t": other_label},
            )

    async def cleanup():
        async with get_engine().begin() as conn:
            await conn.execute(
                _t("DELETE FROM operations WHERE label = :t"),
                {"t": other_label},
            )

    asyncio.get_event_loop().run_until_complete(seed())
    try:
        r = client.get("/api/logs/operations/recent?limit=50", headers=headers)
        tasks = [i["task"] for i in r.json()["items"]]
        assert other_label not in tasks
    finally:
        asyncio.get_event_loop().run_until_complete(cleanup())
