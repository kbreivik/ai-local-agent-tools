"""Tests for GET/POST /api/settings — DB-backed settings."""
import pytest
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)

SERVER_KEYS = [
    "lmStudioUrl", "lmStudioApiKey", "modelName",
    "kafkaBootstrapServers", "elasticsearchUrl", "kibanaUrl", "muninndbUrl",
    "dockerHost", "swarmManagerIPs", "swarmWorkerIPs",
    "externalProvider", "externalApiKey", "externalModel",
    "autoEscalate", "requireConfirmation", "dashboardRefreshInterval",
]


def auth_headers():
    r = client.post("/api/auth/login", json={"username": "admin", "password": "superduperadmin"})
    if r.status_code != 200:
        pytest.skip("Auth not available")
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_get_settings_requires_auth():
    """GET /api/settings without token returns 401 or 403."""
    r = client.get("/api/settings")
    assert r.status_code in (401, 403)


def test_get_settings_returns_all_server_keys():
    """GET /api/settings returns every key in SERVER_KEYS."""
    r = client.get("/api/settings", headers=auth_headers())
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    settings = body["data"]["settings"]
    for key in SERVER_KEYS:
        assert key in settings, f"Missing key: {key}"


def test_get_settings_masks_sensitive_fields():
    """lmStudioApiKey and externalApiKey are masked in GET response."""
    client.post("/api/settings",
        json={"lmStudioApiKey": "super-secret-key"},
        headers=auth_headers())
    r = client.get("/api/settings", headers=auth_headers())
    assert r.status_code == 200
    val = r.json()["data"]["settings"]["lmStudioApiKey"]
    assert "super-secret-key" not in val
    assert "***" in val


def test_post_settings_saves_to_db_and_returns_updated():
    """POST /api/settings saves values and returns them."""
    payload = {"lmStudioUrl": "http://test-host:1234/v1", "modelName": "test-model"}
    r = client.post("/api/settings", json=payload, headers=auth_headers())
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["data"]["updated"]["lmStudioUrl"] == "http://test-host:1234/v1"
    assert body["data"]["updated"]["modelName"] == "test-model"


def test_post_settings_persists_across_get():
    """Value saved via POST is returned in subsequent GET."""
    client.post("/api/settings",
        json={"muninndbUrl": "http://muninn-test:7700"},
        headers=auth_headers())
    r = client.get("/api/settings", headers=auth_headers())
    assert r.json()["data"]["settings"]["muninndbUrl"] == "http://muninn-test:7700"


def test_post_settings_ignores_unknown_keys():
    """POST /api/settings silently ignores keys not in SETTINGS_KEYS."""
    r = client.post("/api/settings",
        json={"unknownKey": "bad-value"},
        headers=auth_headers())
    assert r.status_code == 200
    assert "unknownKey" not in r.json().get("data", {}).get("updated", {})


def test_post_settings_requires_auth():
    """POST /api/settings without token returns 401 or 403."""
    r = client.post("/api/settings", json={"modelName": "x"})
    assert r.status_code in (401, 403)


def test_settings_seeded_on_startup():
    """At least lmStudioUrl is present in GET response (seeded from env or default)."""
    r = client.get("/api/settings", headers=auth_headers())
    assert r.status_code == 200
    assert "lmStudioUrl" in r.json()["data"]["settings"]
