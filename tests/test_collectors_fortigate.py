"""Tests for FortiGateCollector."""
import asyncio
import os
from unittest.mock import patch, MagicMock

import pytest


def test_mock_returns_dict():
    from api.collectors.fortigate import FortiGateCollector
    result = FortiGateCollector().mock()
    assert isinstance(result, dict)
    assert "health" in result
    assert "interfaces" in result
    assert isinstance(result["interfaces"], list)
    assert len(result["interfaces"]) >= 1


def test_mock_interface_has_required_fields():
    from api.collectors.fortigate import FortiGateCollector
    iface = FortiGateCollector().mock()["interfaces"][0]
    for field in ("name", "link", "speed", "type", "rx_bytes", "tx_bytes"):
        assert field in iface, f"mock interface missing '{field}'"


def test_to_entities_from_mock():
    from api.collectors.fortigate import FortiGateCollector
    from api.collectors.base import Entity
    c = FortiGateCollector()
    entities = c.to_entities(c.mock())
    assert len(entities) >= 1
    for e in entities:
        assert isinstance(e, Entity)
        assert e.section == "NETWORK"
        assert e.platform == "fortigate"
        assert e.status in ("healthy", "degraded", "error", "maintenance", "unknown")


def test_to_entities_link_down_is_degraded():
    from api.collectors.fortigate import FortiGateCollector
    state = {
        "health": "degraded",
        "connection_label": "FGT1",
        "hostname": "FGT1",
        "interfaces": [
            {"name": "wan1", "alias": "WAN", "link": False, "speed": 0,
             "type": "physical", "ip": "", "rx_bytes": 0, "tx_bytes": 0,
             "rx_errors": 0, "tx_errors": 0},
        ],
    }
    entities = FortiGateCollector().to_entities(state)
    assert entities[0].status == "degraded"
    assert entities[0].last_error is not None


def test_to_entities_link_up_is_healthy():
    from api.collectors.fortigate import FortiGateCollector
    state = {
        "health": "healthy",
        "connection_label": "FGT1",
        "hostname": "FGT1",
        "interfaces": [
            {"name": "wan1", "alias": "WAN", "link": True, "speed": 1000,
             "type": "physical", "ip": "1.2.3.4/24", "rx_bytes": 100,
             "tx_bytes": 100, "rx_errors": 0, "tx_errors": 0},
        ],
    }
    entities = FortiGateCollector().to_entities(state)
    assert entities[0].status == "healthy"


def test_to_entities_errors_cause_degraded():
    from api.collectors.fortigate import FortiGateCollector
    state = {
        "health": "degraded",
        "connection_label": "FGT1",
        "hostname": "FGT1",
        "interfaces": [
            {"name": "wan1", "alias": "", "link": True, "speed": 1000,
             "type": "physical", "ip": "1.2.3.4/24", "rx_bytes": 1000,
             "tx_bytes": 1000, "rx_errors": 50, "tx_errors": 0},
        ],
    }
    entities = FortiGateCollector().to_entities(state)
    assert entities[0].status == "degraded"


def test_unconfigured_when_no_host():
    from api.collectors.fortigate import FortiGateCollector
    with patch.dict(os.environ, {}, clear=True):
        with patch("api.connections.get_connection_for_platform", return_value=None):
            result = asyncio.run(FortiGateCollector().poll())
    assert result["health"] == "unconfigured"


def test_polls_with_query_param_auth():
    """API key must be passed as access_token query param, not a header."""
    from api.collectors.fortigate import FortiGateCollector

    mock_conn = {
        "host": "192.168.1.1", "port": 443,
        "label": "FGT-Main", "id": "fg123",
        "credentials": {"api_key": "test-fg-key-xyz"},
    }
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"results": {"hostname": "FGT-Main", "version": "7.4.1"}}
    mock_resp.raise_for_status = MagicMock()

    with patch("api.connections.get_connection_for_platform", return_value=mock_conn):
        with patch("httpx.get", return_value=mock_resp) as mock_get:
            FortiGateCollector()._collect_sync()

    # Verify access_token in query params, NOT in headers
    call_kwargs = mock_get.call_args_list[0][1]
    assert call_kwargs.get("params", {}).get("access_token") == "test-fg-key-xyz"
    assert "Authorization" not in call_kwargs.get("headers", {})


def test_fortigate_collector_auto_registered():
    from api.collectors.manager import CollectorManager
    names = [c.component for c in CollectorManager()._discover()]
    assert "fortigate" in names


def test_fortigate_triggers_external_services():
    from api.collectors.manager import CollectorManager
    triggered = {c.component for c in CollectorManager()._discover() if "fortigate" in c.platforms}
    assert "fortigate" in triggered
    assert "external_services" in triggered
