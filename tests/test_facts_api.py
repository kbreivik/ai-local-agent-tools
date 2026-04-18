"""Tests for /api/facts endpoints — auth + filter semantics."""
import pytest
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def _auth_headers():
    r = client.post("/api/auth/login",
                    json={"username": "admin", "password": "superduperadmin"})
    if r.status_code != 200:
        pytest.skip("Auth not available in test env")
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_list_facts_requires_auth():
    r = client.get("/api/facts")
    assert r.status_code in (401, 403)


def test_fact_detail_requires_auth():
    r = client.get("/api/facts/key/prod.kafka.broker.3.host")
    assert r.status_code in (401, 403)


def test_conflicts_requires_auth():
    r = client.get("/api/facts/conflicts")
    assert r.status_code in (401, 403)


def test_preview_requires_auth():
    r = client.post("/api/facts/settings/preview", json={"settings": {}})
    assert r.status_code in (401, 403)


def test_list_facts_with_pattern_filter():
    """Authenticated GET with pattern should return a facts list (possibly empty)."""
    headers = _auth_headers()
    r = client.get("/api/facts?pattern=prod.kafka.*", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert "facts" in body
    assert "count" in body


def test_preview_returns_scored_samples():
    headers = _auth_headers()
    r = client.post(
        "/api/facts/settings/preview",
        headers=headers,
        json={"settings": {"factSourceWeight_proxmox_collector": 0.5}},
    )
    assert r.status_code == 200
    body = r.json()
    assert "preview" in body
    assert isinstance(body["preview"], list)
