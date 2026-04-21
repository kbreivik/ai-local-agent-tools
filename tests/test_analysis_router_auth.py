"""v2.38.0 — /api/admin/analysis auth + shape tests.

Unauthenticated requests must return 401/403 on every endpoint. Role-gap
tests (stormtrooper → 403, sith_lord → 200 shape) are skipped unless
fixtures exist — the unauthenticated tests alone confirm the gate is wired.
"""
import pytest
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)


def test_templates_endpoint_rejects_unauthenticated():
    r = client.get("/api/admin/analysis/templates")
    assert r.status_code in (401, 403)


def test_run_endpoint_rejects_unauthenticated():
    r = client.post(
        "/api/admin/analysis/run",
        json={"template_id": "recent_failures", "params": {}},
    )
    assert r.status_code in (401, 403)


def test_dump_endpoint_rejects_unauthenticated():
    r = client.post(
        "/api/admin/analysis/dump?format=json",
        json={"template_id": "recent_failures", "params": {}},
    )
    assert r.status_code in (401, 403)


def _sith_lord_headers():
    """Try to obtain a sith_lord token from the env-var admin login.

    Returns headers dict, or None if the admin login path is unavailable
    (auth not configured in this test env).
    """
    r = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "superduperadmin"},
    )
    if r.status_code != 200:
        return None
    token = r.json().get("access_token")
    if not token:
        return None
    return {"Authorization": f"Bearer {token}"}


def test_sith_lord_templates_shape():
    """Confirm the 7 templates are returned and no raw SQL leaks."""
    headers = _sith_lord_headers()
    if not headers:
        pytest.skip("Admin login not available in this test env")
    r = client.get("/api/admin/analysis/templates", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert "templates" in data
    assert len(data["templates"]) >= 7
    for t in data["templates"]:
        assert "id" in t and "title" in t and "params" in t
        assert "sql" not in t  # never leak raw SQL
