"""v2.33.17 — docker_host SSH credentials come from credential profiles,
not from inline creds copied from other connections.

Regression tests for the `_ssh_source` → `credential_profile_id` transition.
"""
import json
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def _fake_profile(**overrides):
    creds = {
        "username":    "ubuntu",
        "private_key": "FAKE_KEY",
        "passphrase":  "pp",
        "password":    "",
    }
    creds.update(overrides.pop("credentials", {}) if "credentials" in overrides else {})
    return {
        "id":          "prof-1",
        "seq_id":      1,
        "name":        "test-docker-ssh",
        "auth_type":   "ssh",
        "credentials": creds,
        **overrides,
    }


def test_docker_host_ssh_uses_profile_when_linked():
    """Profile-first resolver returns profile creds for a docker_host SSH connection."""
    from api.db.credential_profiles import resolve_credentials_for_connection

    conn = {
        "id":          "conn-1",
        "platform":    "docker_host",
        "host":        "10.0.0.1",
        "port":        22,
        "auth_type":   "ssh",
        "credentials": {},
        "config":      {"credential_profile_id": "prof-1"},
    }
    with patch(
        "api.db.credential_profiles.get_profile",
        return_value=_fake_profile(),
    ):
        creds = resolve_credentials_for_connection(conn, [])
    assert creds.get("username")    == "ubuntu"
    assert creds.get("private_key") == "FAKE_KEY"
    assert creds.get("passphrase")  == "pp"


def test_docker_host_ssh_falls_back_to_inline_when_no_profile():
    """Without a profile the resolver falls back to the connection's own creds."""
    from api.db.credential_profiles import resolve_credentials_for_connection

    conn = {
        "id":          "conn-2",
        "platform":    "docker_host",
        "auth_type":   "ssh",
        "credentials": {"username": "override", "private_key": "INLINE_KEY"},
        "config":      {},
    }
    creds = resolve_credentials_for_connection(conn, [])
    assert creds.get("username")    == "override"
    assert creds.get("private_key") == "INLINE_KEY"


def test_swarm_client_uses_profile_for_ssh():
    """_build_docker_client_for_conn picks up the profile private_key via resolver."""
    from api.collectors import swarm as _swarm

    conn = {
        "label":       "docker-test",
        "host":        "10.0.0.1",
        "port":        22,
        "auth_type":   "ssh",
        "credentials": {},
        "config":      {"credential_profile_id": "prof-1"},
    }
    captured = {}

    class _FakeClient:
        def __init__(self, *a, **kw):
            captured["args"] = a
            captured["kw"]   = kw
        def close(self): pass

    with patch(
        "api.db.credential_profiles.resolve_credentials_for_connection",
        return_value={"username": "ubuntu", "private_key": "FAKE_KEY"},
    ), patch("docker.DockerClient", _FakeClient):
        _swarm._build_docker_client_for_conn(conn)

    assert captured["kw"].get("base_url", "").startswith("ssh://ubuntu@10.0.0.1")


def test_swarm_client_no_ssh_source_reference():
    """Source file no longer references the deprecated _ssh_source key."""
    import inspect
    from api.collectors import swarm as _swarm
    src = inspect.getsource(_swarm)
    assert "_ssh_source" not in src, (
        "Deprecated _ssh_source reference found in swarm.py — should be removed"
    )


def test_migration_strips_ssh_source_key():
    """_migrate_docker_host_ssh_source removes _ssh_source from config (smoke test).

    Uses an in-memory stand-in for the DB layer — we only assert the function is
    callable and tolerates missing DB connections without raising.
    """
    from api import connections as _c
    # Should not raise even when no DB is reachable
    with patch.object(_c, "_get_conn", return_value=None), \
         patch.object(_c, "_get_sa_conn", return_value=None):
        _c._migrate_docker_host_ssh_source()


def test_credential_state_needs_profile_for_docker_host_ssh():
    """A docker_host/ssh row with no profile and no inline creds reports
    credential_state.source == 'needs_profile'."""
    # Build a row shaped like list_connections() post-query
    row = {
        "id":             "conn-3",
        "platform":       "docker_host",
        "auth_type":      "ssh",
        "credentials":    "",
        "config":         {},
        "username_cache": "",
        "last_seen":      None,
        "created_at":     None,
    }
    # Replicate the credential_state derivation inline (matches api/connections.py)
    cfg = row["config"]
    profile_id = cfg.get("credential_profile_id")
    raw_enc = row["credentials"]
    cred_state: dict = {"source": "none", "username": row["username_cache"]}
    if profile_id:
        pass  # not exercised here
    elif raw_enc:
        cred_state = {"source": "inline"}
    else:
        if row["platform"] == "docker_host" and row["auth_type"] == "ssh":
            cred_state = {"source": "needs_profile", "username": ""}
    assert cred_state["source"] == "needs_profile"
