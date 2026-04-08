"""Tests for TrueNASCollector — mock shape, to_entities, unconfigured, credential resolution."""
import asyncio
import os
from unittest.mock import patch, MagicMock

import pytest


def test_mock_returns_dict():
    from api.collectors.truenas import TrueNASCollector
    result = TrueNASCollector().mock()
    assert isinstance(result, dict)
    assert "health" in result
    assert "pools" in result
    assert isinstance(result["pools"], list)
    assert len(result["pools"]) >= 1


def test_mock_pool_has_required_fields():
    from api.collectors.truenas import TrueNASCollector
    pool = TrueNASCollector().mock()["pools"][0]
    for field in ("name", "status", "healthy", "usage_pct", "size_gb", "free_gb"):
        assert field in pool, f"mock pool missing '{field}'"


def test_to_entities_from_mock():
    from api.collectors.truenas import TrueNASCollector
    from api.collectors.base import Entity
    c = TrueNASCollector()
    entities = c.to_entities(c.mock())
    assert len(entities) >= 1
    for e in entities:
        assert isinstance(e, Entity)
        assert e.section == "STORAGE"
        assert e.platform == "truenas"
        assert e.status in ("healthy", "degraded", "error", "maintenance", "unknown")


def test_to_entities_degraded_pool_is_error():
    from api.collectors.truenas import TrueNASCollector
    state = {
        "health": "critical",
        "connection_label": "test-nas",
        "pools": [{"name": "tank", "status": "DEGRADED", "healthy": False,
                   "usage_pct": 50.0, "size_gb": 1000, "allocated_gb": 500,
                   "free_gb": 500, "scan_state": "FINISHED", "scan_errors": 0, "vdev_count": 2}],
    }
    entities = TrueNASCollector().to_entities(state)
    assert entities[0].status == "error"


def test_to_entities_high_usage_is_degraded():
    from api.collectors.truenas import TrueNASCollector
    state = {
        "health": "degraded",
        "connection_label": "test-nas",
        "pools": [{"name": "tank", "status": "ONLINE", "healthy": True,
                   "usage_pct": 93.0, "size_gb": 1000, "allocated_gb": 930,
                   "free_gb": 70, "scan_state": "FINISHED", "scan_errors": 0, "vdev_count": 2}],
    }
    entities = TrueNASCollector().to_entities(state)
    assert entities[0].status == "degraded"


def test_to_entities_healthy_pool():
    from api.collectors.truenas import TrueNASCollector
    state = {
        "health": "healthy",
        "connection_label": "test-nas",
        "pools": [{"name": "tank", "status": "ONLINE", "healthy": True,
                   "usage_pct": 42.0, "size_gb": 1000, "allocated_gb": 420,
                   "free_gb": 580, "scan_state": "FINISHED", "scan_errors": 0, "vdev_count": 2}],
    }
    entities = TrueNASCollector().to_entities(state)
    assert entities[0].status == "healthy"


def test_unconfigured_when_no_host():
    from api.collectors.truenas import TrueNASCollector
    with patch.dict(os.environ, {}, clear=True):
        with patch("api.connections.get_connection_for_platform", return_value=None):
            result = asyncio.run(TrueNASCollector().poll())
    assert result["health"] == "unconfigured"


def test_polls_with_connection_api_key():
    from api.collectors.truenas import TrueNASCollector

    mock_conn = {
        "host": "192.168.1.20", "port": 443,
        "label": "TrueNAS-Main", "id": "tn123",
        "credentials": {"api_key": "test-api-key-12345"},
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"hostname": "truenas"}
    mock_resp.raise_for_status = MagicMock()

    with patch("api.connections.get_connection_for_platform", return_value=mock_conn):
        with patch("httpx.get", return_value=mock_resp) as mock_get:
            TrueNASCollector()._collect_sync()

    call_kwargs = mock_get.call_args_list[0][1]
    auth = call_kwargs.get("headers", {}).get("Authorization", "")
    assert auth == "Bearer test-api-key-12345"


def test_truenas_collector_auto_registered():
    from api.collectors.manager import CollectorManager
    names = [c.component for c in CollectorManager()._discover()]
    assert "truenas" in names


def test_truenas_triggers_external_services():
    from api.collectors.manager import CollectorManager
    triggered = {c.component for c in CollectorManager()._discover() if "truenas" in c.platforms}
    assert "truenas" in triggered
    assert "external_services" in triggered
