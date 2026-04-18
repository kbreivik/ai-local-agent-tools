"""Regression test for /api/health version corruption (v2.34.17).

The v2.34.14-v2.34.16 observability cluster repeatedly saw the health
endpoint return ``"version": "[BLOCKED: JWT token]"`` because something
in the boot/serialisation path was running the LLM-inbound sanitiser over
response payloads. v2.34.15 scoped the sanitiser to LLM-inbound call sites;
v2.34.17 closes out the audit and this test is the guard-rail.
"""
from fastapi.testclient import TestClient

from api.main import app


def test_health_version_is_plain_semver():
    client = TestClient(app)
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert "version" in data
    v = data["version"]
    assert isinstance(v, str)
    # Semver-ish — first character must be a digit, no sanitiser markers.
    assert v and v[0].isdigit(), f"version is not plain semver: {v!r}"
    assert "BLOCKED" not in v
    assert "REDACTED" not in v
    assert "[" not in v
