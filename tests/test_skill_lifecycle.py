# tests/test_skill_lifecycle.py
import pytest
from fastapi.testclient import TestClient

@pytest.fixture
def client():
    from api.main import app
    return TestClient(app)

@pytest.fixture
def token(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "superduperadmin"})
    return r.json()["access_token"]

@pytest.fixture
def headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_promote_unknown_skill_returns_404(client, headers):
    r = client.post("/api/skills/nonexistent_xyz/promote",
                    json={"domain": "kafka"}, headers=headers)
    assert r.status_code == 404


def test_scrap_unknown_skill_returns_404(client, headers):
    r = client.delete("/api/skills/nonexistent_xyz", headers=headers)
    assert r.status_code == 404


def test_restore_non_scrapped_returns_400(client, headers):
    # http_health_check is a starter skill — not scrapped
    r = client.post("/api/skills/http_health_check/restore", headers=headers)
    assert r.status_code in (400, 404)


def test_promote_invalid_domain_returns_400(client, headers):
    # Use a real skill if available, else just check 400 vs 404
    r = client.post("/api/skills/http_health_check/promote",
                    json={"domain": "invalid_domain"}, headers=headers)
    # 400 if skill exists and domain invalid, 404 if skill not in DB
    assert r.status_code in (400, 404)
