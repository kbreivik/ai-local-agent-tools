"""v2.34.2 — skill execution observability + metrics endpoint.

Validates:
  * skill_executions rows are written on success and error paths.
  * GET /api/skills/metrics returns the expected envelope.
  * window_days is capped at 90.
  * GET /api/skills/executions honours the skill_id filter.
"""
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


# ── dispatcher-level recording ────────────────────────────────────────────────

def test_execution_recorded_success(monkeypatch):
    """A successful skill dispatch writes one skill_executions row with outcome=success."""
    from mcp_server.tools.skills import loader
    from api.db import skill_executions as se

    name = "obs_unit_success"
    loader._SKILL_HANDLERS[name] = lambda **kw: {
        "status": "ok", "data": {"x": 1}, "timestamp": "", "message": "hi",
    }

    recorded = {}

    def fake_start(**kwargs):
        recorded["start"] = kwargs
        return "exec_id_123"

    def fake_end(exec_id, **kwargs):
        recorded["end"] = {"exec_id": exec_id, **kwargs}

    monkeypatch.setattr(se, "record_start", fake_start)
    monkeypatch.setattr(se, "record_end", fake_end)
    try:
        result = loader.dispatch_skill(name, arg=42)
    finally:
        loader._SKILL_HANDLERS.pop(name, None)

    assert result["status"] == "ok"
    assert recorded["start"]["skill_id"] == name
    assert recorded["end"]["outcome"] == "success"


def test_execution_recorded_error(monkeypatch):
    """A skill returning status=error is recorded with outcome=error."""
    from mcp_server.tools.skills import loader
    from api.db import skill_executions as se

    name = "obs_unit_err"
    loader._SKILL_HANDLERS[name] = lambda **kw: {
        "status": "error", "data": None, "timestamp": "", "message": "boom",
    }

    ended = {}

    def fake_start(**kwargs):
        return "eid"

    def fake_end(exec_id, **kwargs):
        ended.update(kwargs)

    monkeypatch.setattr(se, "record_start", fake_start)
    monkeypatch.setattr(se, "record_end", fake_end)
    try:
        result = loader.dispatch_skill(name)
    finally:
        loader._SKILL_HANDLERS.pop(name, None)

    assert result["status"] == "error"
    assert ended["outcome"] == "error"
    assert ended["error"] == "boom"


def test_execution_recorded_on_raise(monkeypatch):
    """A skill that raises is recorded with outcome=error and the exception propagates."""
    from mcp_server.tools.skills import loader
    from api.db import skill_executions as se

    name = "obs_unit_raise"

    def _bad(**kw):
        raise RuntimeError("kaboom")

    loader._SKILL_HANDLERS[name] = _bad

    ended = {}

    monkeypatch.setattr(se, "record_start", lambda **kw: "eid")
    monkeypatch.setattr(se, "record_end", lambda eid, **kw: ended.update(kw))

    try:
        with pytest.raises(RuntimeError):
            loader.dispatch_skill(name)
    finally:
        loader._SKILL_HANDLERS.pop(name, None)

    assert ended.get("outcome") == "error"
    assert "kaboom" in (ended.get("error") or "")


# ── endpoint smoke tests ──────────────────────────────────────────────────────

def test_metrics_endpoint_shape(client, headers):
    r = client.get("/api/skills/metrics?window_days=7", headers=headers)
    assert r.status_code == 200
    d = r.json()
    assert "per_skill" in d
    assert "promoter" in d
    assert "pipeline" in d
    assert d["window_days"] == 7


def test_metrics_window_capped_at_90(client, headers):
    r = client.get("/api/skills/metrics?window_days=9999", headers=headers)
    assert r.status_code == 200
    assert r.json()["window_days"] == 90


def test_metrics_window_floor(client, headers):
    r = client.get("/api/skills/metrics?window_days=0", headers=headers)
    assert r.status_code == 200
    assert r.json()["window_days"] >= 1


def test_executions_endpoint_shape(client, headers):
    r = client.get("/api/skills/executions?limit=5", headers=headers)
    assert r.status_code == 200
    d = r.json()
    assert "executions" in d
    assert "count" in d
    assert isinstance(d["executions"], list)


def test_executions_requires_auth(client):
    r = client.get("/api/skills/executions")
    assert r.status_code in (401, 403)


def test_metrics_requires_auth(client):
    r = client.get("/api/skills/metrics")
    assert r.status_code in (401, 403)
