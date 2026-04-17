"""v2.33.20 gates overview endpoint — shape + auth tests.

DB queries are exercised by integration runs against a live Postgres; these
unit tests only cover the contract the GUI depends on: authentication is
required, the payload carries every expected key, and the window is
clamped.
"""
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def _auth():
    r = client.post("/api/auth/login", json={"username": "admin", "password": "superduperadmin"})
    if r.status_code != 200:
        return None
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_overview_endpoint_auth_required():
    r = client.get("/api/gates/overview")
    assert r.status_code in (401, 403)


def test_overview_shape():
    h = _auth()
    if not h:
        import pytest
        pytest.skip("auth not available in this env")
    r = client.get("/api/gates/overview?window_hours=24", headers=h)
    assert r.status_code == 200
    d = r.json()
    for k in (
        "window_hours", "since",
        "plan_confirmations", "escalations", "drift",
        "maintenance_active", "hard_caps", "tool_refusals",
    ):
        assert k in d, f"missing key: {k}"

    assert isinstance(d["plan_confirmations"], list)
    assert isinstance(d["maintenance_active"], list)
    assert isinstance(d["tool_refusals"], list)
    for k in ("total", "open", "acknowledged"):
        assert k in d["escalations"]
    for k in ("total", "open", "acknowledged", "suppressed"):
        assert k in d["drift"]
    for k in ("wall_clock", "token_cap", "failure_cap", "destructive_cap"):
        assert k in d["hard_caps"]


def test_overview_window_is_capped_but_input_echoed():
    h = _auth()
    if not h:
        import pytest
        pytest.skip("auth not available in this env")
    r = client.get("/api/gates/overview?window_hours=9999", headers=h)
    assert r.status_code == 200
    d = r.json()
    # The raw input is echoed back for GUI transparency; the server-side
    # since-timestamp enforces the 168h cap.
    assert d["window_hours"] == 9999
    import datetime as _dt
    since = _dt.datetime.fromisoformat(d["since"].replace("Z", "+00:00"))
    now   = _dt.datetime.now(_dt.timezone.utc)
    delta = now - since
    assert delta <= _dt.timedelta(hours=168, minutes=1)
    assert delta >= _dt.timedelta(hours=167, minutes=59)


def test_overview_window_is_floor_clamped():
    h = _auth()
    if not h:
        import pytest
        pytest.skip("auth not available in this env")
    r = client.get("/api/gates/overview?window_hours=0", headers=h)
    assert r.status_code == 200
    import datetime as _dt
    d = r.json()
    since = _dt.datetime.fromisoformat(d["since"].replace("Z", "+00:00"))
    now   = _dt.datetime.now(_dt.timezone.utc)
    delta = now - since
    # window_hours=0 must clamp up to 1h.
    assert delta <= _dt.timedelta(hours=1, minutes=1)
    assert delta >= _dt.timedelta(minutes=59)
