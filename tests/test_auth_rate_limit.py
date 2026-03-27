"""Tests for login rate limiting."""
import pytest
from fastapi.testclient import TestClient
from api.main import app
import api.routers.auth as auth_router_module

client = TestClient(app)


def test_login_rate_limit():
    """Sending 11 login attempts from the same IP triggers 429 on the 11th."""
    payload = {"username": "admin", "password": "wrong-password"}
    last_status = None
    for i in range(11):
        r = client.post("/api/auth/login", json=payload)
        last_status = r.status_code

    assert last_status == 429, (
        f"Expected 429 on 11th attempt, got {last_status}"
    )
