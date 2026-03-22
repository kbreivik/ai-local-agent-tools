"""Tests for /api/skills endpoints."""
import pytest
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)


def auth_headers():
    """Get a valid JWT for test requests."""
    r = client.post("/api/auth/login", json={"username": "admin", "password": "superduperadmin"})
    if r.status_code != 200:
        pytest.skip("Auth not available in test env")
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_list_skills_returns_list():
    h = auth_headers()
    r = client.get("/api/skills", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert "skills" in body
    assert isinstance(body["skills"], list)


def test_list_skills_category_filter():
    h = auth_headers()
    r = client.get("/api/skills?category=compute", headers=h)
    assert r.status_code == 200
    for skill in r.json()["skills"]:
        assert skill["category"] == "compute"


def test_execute_unknown_skill_returns_404():
    h = auth_headers()
    r = client.post("/api/skills/no_such_skill/execute", json={}, headers=h)
    assert r.status_code == 404


def test_execute_skill_http_health_check():
    """http_health_check is a starter skill — just check response shape."""
    h = auth_headers()
    r = client.post(
        "/api/skills/http_health_check/execute",
        json={"url": "http://localhost:8000/api/health"},
        headers=h,
    )
    assert r.status_code == 200
    body = r.json()
    assert "status" in body


def test_get_single_skill_returns_metadata():
    h = auth_headers()
    # First get the list to find a real skill name
    r = client.get("/api/skills", headers=h)
    skills = r.json().get("skills", [])
    if not skills:
        pytest.skip("No skills registered")
    name = skills[0]["name"]
    r2 = client.get(f"/api/skills/{name}", headers=h)
    assert r2.status_code == 200
    assert r2.json().get("name") == name


def test_get_unknown_skill_returns_404():
    h = auth_headers()
    r = client.get("/api/skills/no_such_skill_xyz", headers=h)
    assert r.status_code == 404
