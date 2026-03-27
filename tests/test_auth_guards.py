"""Tests that protected endpoints reject unauthenticated requests."""
import pytest
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)


def auth_headers():
    r = client.post("/api/auth/login", json={"username": "admin", "password": "superduperadmin"})
    if r.status_code != 200:
        pytest.skip("Auth not available in test env")
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ── Agent endpoints ───────────────────────────────────────────────────────────

def test_stop_requires_auth():
    """POST /api/agent/stop without token returns 401 or 403."""
    r = client.post("/api/agent/stop", json={"session_id": "test-session"})
    assert r.status_code in (401, 403)


def test_clarify_requires_auth():
    """POST /api/agent/clarify without token returns 401 or 403."""
    r = client.post("/api/agent/clarify", json={"session_id": "test-session", "answer": "yes"})
    assert r.status_code in (401, 403)


# ── Skill endpoints ───────────────────────────────────────────────────────────

def test_list_skills_requires_auth():
    """GET /api/skills without token returns 401 or 403."""
    r = client.get("/api/skills")
    assert r.status_code in (401, 403)


def test_execute_skill_requires_auth():
    """POST /api/skills/x/execute without token returns 401 or 403."""
    r = client.post("/api/skills/http_health_check/execute", json={})
    assert r.status_code in (401, 403)


def test_get_skill_requires_auth():
    """GET /api/skills/x without token returns 401 or 403."""
    r = client.get("/api/skills/http_health_check")
    assert r.status_code in (401, 403)
