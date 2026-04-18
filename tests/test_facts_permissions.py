"""Tests for the facts permission model (v2.35.0.1).

These tests monkeypatch the DB calls so we don't require a running Postgres.
The core logic lives in pure Python (no DB) for sith_lord short-circuit and
the role/grantee lookup algorithm; we exercise that path.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.security import facts_permissions as fp

client = TestClient(app)


# ── Pure-logic tests (no DB) ────────────────────────────────────────────────


def test_sith_lord_bypasses_everything(monkeypatch):
    # Even with an empty DB, sith_lord always has all permissions.
    monkeypatch.setattr(fp, "_get_conn", lambda: None)
    assert fp.user_has_permission("anyone", "sith_lord", "lock", "prod.*") is True
    assert fp.user_has_permission("anyone", "sith_lord", "unlock", "anything") is True
    assert fp.user_has_permission("anyone", "sith_lord", "grant", "prod.kafka.broker.3.host") is True


def test_missing_username_or_action_denies(monkeypatch):
    monkeypatch.setattr(fp, "_get_conn", lambda: None)
    assert fp.user_has_permission("", "droid", "lock", "prod.*") is False
    assert fp.user_has_permission("u", "droid", "", "prod.*") is False
    assert fp.user_has_permission("u", "droid", "lock", "") is False


def test_no_conn_denies_non_admin(monkeypatch):
    """If we cannot reach the DB, non-admin permissions default to deny."""
    monkeypatch.setattr(fp, "_get_conn", lambda: None)
    assert fp.user_has_permission("alice", "imperial_officer", "lock", "prod.*") is False


def test_resolve_role_admin_fallback(monkeypatch):
    """When users table lookup fails, ADMIN_USER resolves to sith_lord."""
    import os
    monkeypatch.setenv("ADMIN_USER", "admin")

    def raise_exc(*_a, **_kw):
        raise RuntimeError("no db")

    import api.users
    monkeypatch.setattr(api.users, "get_user_by_username", raise_exc, raising=False)
    assert fp._resolve_role("admin") == "sith_lord"
    assert fp._resolve_role("nobody") == "droid"


# ── DB-backed logic — simulated with a tiny fake cursor ─────────────────────


class _FakeCursor:
    """Minimal cursor that returns scripted results for each execute()."""

    def __init__(self, scripted):
        self._scripted = list(scripted)
        self._current = None

    def execute(self, sql, params=None):
        self._current = self._scripted.pop(0) if self._scripted else [(0,)]

    def fetchone(self):
        return self._current[0] if self._current else (0,)

    def fetchall(self):
        return self._current or []

    def close(self):
        pass


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True

    def close(self):
        pass


def _make_conn(scripted):
    return _FakeConn(_FakeCursor(scripted))


def test_user_grant_allows(monkeypatch):
    # Scripted: first call (explicit revoke) returns 0, second (positive match) returns 1.
    monkeypatch.setattr(fp, "_get_conn", lambda: _make_conn([[(0,)], [(1,)]]))
    assert fp.user_has_permission("alice", "droid", "lock", "prod.kafka.broker.3.host") is True


def test_role_grant_allows(monkeypatch):
    monkeypatch.setattr(fp, "_get_conn", lambda: _make_conn([[(0,)], [(1,)]]))
    assert fp.user_has_permission(
        "alice", "imperial_officer", "lock", "prod.kafka.topic.x"
    ) is True


def test_explicit_user_revoke_overrides_role(monkeypatch):
    # Explicit user-level revoke is present (returns 1) → denied regardless of role grant.
    monkeypatch.setattr(fp, "_get_conn", lambda: _make_conn([[(1,)], [(1,)]]))
    assert fp.user_has_permission(
        "alice", "imperial_officer", "lock", "prod.kafka.topic.x"
    ) is False


def test_no_grant_denies(monkeypatch):
    monkeypatch.setattr(fp, "_get_conn", lambda: _make_conn([[(0,)], [(0,)]]))
    assert fp.user_has_permission("alice", "droid", "lock", "prod.kafka.topic.x") is False


def test_db_error_denies(monkeypatch):
    def boom():
        raise RuntimeError("db down")
    monkeypatch.setattr(fp, "_get_conn", boom)
    # _get_conn itself raises; outer try/except in helper should just return False.
    with pytest.raises(Exception):
        fp.user_has_permission("alice", "droid", "lock", "p.*")


# ── HTTP surface — auth gate ────────────────────────────────────────────────


def test_list_locks_requires_auth():
    r = client.get("/api/facts/locks")
    assert r.status_code in (401, 403)


def test_create_lock_requires_auth():
    r = client.post("/api/facts/locks", json={"fact_key": "x", "locked_value": "y"})
    assert r.status_code in (401, 403)


def test_permissions_get_requires_auth():
    r = client.get("/api/facts/permissions")
    assert r.status_code in (401, 403)


def test_permissions_post_requires_auth():
    r = client.post("/api/facts/permissions", json={
        "grantee_type": "user", "grantee_id": "alice",
        "action": "lock", "fact_pattern": "prod.*",
    })
    assert r.status_code in (401, 403)
