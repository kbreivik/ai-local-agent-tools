"""Tests for PBSCollector — connection-based credential resolution, mock(), to_entities()."""
import asyncio
import os
from unittest.mock import patch, MagicMock

import pytest


# ── mock() shape ──────────────────────────────────────────────────────────────

def test_mock_returns_dict():
    from api.collectors.pbs import PBSCollector
    result = PBSCollector().mock()
    assert isinstance(result, dict)
    assert "health" in result
    assert "datastores" in result
    assert isinstance(result["datastores"], list)
    assert len(result["datastores"]) >= 1


def test_mock_datastore_has_required_fields():
    from api.collectors.pbs import PBSCollector
    ds = PBSCollector().mock()["datastores"][0]
    for field in ("name", "usage_pct", "total_gb", "used_gb"):
        assert field in ds, f"mock datastore missing field '{field}'"


# ── to_entities() ──────────────────────────────────────────────────────────────

def test_to_entities_from_mock():
    from api.collectors.pbs import PBSCollector
    from api.collectors.base import Entity
    c = PBSCollector()
    entities = c.to_entities(c.mock())
    assert len(entities) >= 1
    for e in entities:
        assert isinstance(e, Entity)
        assert e.section == "STORAGE"
        assert e.platform == "pbs"
        assert e.status in ("healthy", "degraded", "error", "maintenance", "unknown")


def test_to_entities_full_datastore_is_error():
    from api.collectors.pbs import PBSCollector
    state = {
        "health": "critical",
        "connection_label": "test-pbs",
        "datastores": [{"name": "full", "usage_pct": 97.0, "total_gb": 1000, "used_gb": 970}],
        "tasks": {},
    }
    entities = PBSCollector().to_entities(state)
    assert entities[0].status == "error"


def test_to_entities_warning_datastore_is_degraded():
    from api.collectors.pbs import PBSCollector
    state = {
        "health": "degraded",
        "connection_label": "test-pbs",
        "datastores": [{"name": "warn", "usage_pct": 88.0, "total_gb": 1000, "used_gb": 880}],
        "tasks": {},
    }
    entities = PBSCollector().to_entities(state)
    assert entities[0].status == "degraded"


# ── unconfigured ──────────────────────────────────────────────────────────────

def test_unconfigured_when_no_host():
    from api.collectors.pbs import PBSCollector

    with patch.dict(os.environ, {}, clear=True):
        with patch("api.connections.get_connection_for_platform", return_value=None):
            result = asyncio.run(PBSCollector().poll())

    assert result["health"] == "unconfigured"


# ── credential resolution ─────────────────────────────────────────────────────

def test_polls_with_connection_creds():
    """Credentials from DB connection are used for the API call."""
    from api.collectors.pbs import PBSCollector

    mock_conn = {
        "host": "192.168.1.5", "port": 8007,
        "label": "test-pbs", "id": "abc123",
        "credentials": {"user": "root@pam", "token_name": "agent", "secret": "test-secret"},
    }
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": {"version": "3.2.0"}}
    mock_response.raise_for_status = MagicMock()

    with patch("api.connections.get_connection_for_platform", return_value=mock_conn):
        with patch("httpx.get", return_value=mock_response) as mock_get:
            result = PBSCollector()._collect_sync()

    # Auth header must use PBSAPIToken format
    call_kwargs = mock_get.call_args_list[0][1]
    auth_header = call_kwargs.get("headers", {}).get("Authorization", "")
    assert auth_header.startswith("PBSAPIToken=root@pam!agent:")


# ── collector registry ────────────────────────────────────────────────────────

def test_pbs_collector_auto_registered():
    from api.collectors.manager import CollectorManager
    collectors = CollectorManager()._discover()
    names = [c.component for c in collectors]
    assert "pbs" in names


def test_pbs_in_platforms_triggers_pbs_collector():
    from api.collectors.manager import CollectorManager
    collectors = CollectorManager()._discover()
    triggered = {c.component for c in collectors if "pbs" in c.platforms}
    assert "pbs" in triggered
    # external_services also covers pbs health check
    assert "external_services" in triggered
