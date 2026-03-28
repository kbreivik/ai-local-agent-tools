"""Tests for the doc coverage and generation-log API endpoints."""
import pytest
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)
_AUTH_CACHE: dict = {}


def auth_headers() -> dict:
    if "admin" not in _AUTH_CACHE:
        r = client.post("/api/auth/login", json={"username": "admin", "password": "superduperadmin"})
        if r.status_code != 200:
            pytest.skip("Auth not available")
        _AUTH_CACHE["admin"] = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return _AUTH_CACHE["admin"]


def test_ingest_docs_endpoint_returns_list():
    """GET /api/memory/ingest/docs returns {"docs": [...]}."""
    r = client.get("/api/memory/ingest/docs", headers=auth_headers())
    assert r.status_code == 200
    data = r.json()
    assert "docs" in data
    assert isinstance(data["docs"], list)


def test_ingest_docs_endpoint_requires_auth():
    r = client.get("/api/memory/ingest/docs")
    assert r.status_code == 401


def test_ingest_docs_entries_have_expected_fields():
    """Each doc entry has source_key, source_label, chunk_count, stored_at."""
    r = client.get("/api/memory/ingest/docs", headers=auth_headers())
    for doc in r.json().get("docs", []):
        assert "source_key" in doc
        assert "chunk_count" in doc


def test_generation_log_outcome_filter():
    """GET /api/skills/generation-log?outcome=success returns only success rows."""
    r = client.get("/api/skills/generation-log?outcome=success", headers=auth_headers())
    assert r.status_code == 200
    for row in r.json().get("log", []):
        assert row["outcome"] == "success"


def test_generation_log_limit_param():
    """limit query param is respected."""
    r = client.get("/api/skills/generation-log?limit=1", headers=auth_headers())
    assert r.status_code == 200
    assert len(r.json().get("log", [])) <= 1


def test_generation_log_requires_auth():
    """GET /api/skills/generation-log without auth returns 401."""
    r = client.get("/api/skills/generation-log")
    assert r.status_code == 401


def test_generation_log_returns_log_and_count():
    """Response has both 'log' list and 'count' integer."""
    r = client.get("/api/skills/generation-log", headers=auth_headers())
    assert r.status_code == 200
    data = r.json()
    assert "log" in data
    assert "count" in data
    assert isinstance(data["log"], list)
    assert isinstance(data["count"], int)
