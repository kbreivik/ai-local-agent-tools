"""Tests for UniFiCollector — dual auth modes, mock shape, to_entities, SSH fallback."""
import asyncio
import os
import sys
from unittest.mock import patch, MagicMock


def test_mock_shape():
    from api.collectors.unifi import UniFiCollector
    r = UniFiCollector().mock()
    assert r["health"] == "healthy"
    assert r["auth_mode"] == "apikey"
    assert len(r["devices"]) >= 1
    assert r["client_count"] == 20


def test_mock_device_fields():
    from api.collectors.unifi import UniFiCollector
    dev = UniFiCollector().mock()["devices"][0]
    for f in ("name", "mac", "type", "state", "clients"):
        assert f in dev


def test_to_entities_from_mock():
    from api.collectors.unifi import UniFiCollector
    from api.collectors.base import Entity
    c = UniFiCollector()
    entities = c.to_entities(c.mock())
    assert len(entities) >= 3  # 2 devices + 1 client summary
    assert all(isinstance(e, Entity) for e in entities)
    assert all(e.section == "NETWORK" for e in entities)
    assert all(e.platform == "unifi" for e in entities)


def test_to_entities_client_summary_always_present():
    from api.collectors.unifi import UniFiCollector
    entities = UniFiCollector().to_entities(UniFiCollector().mock())
    summary = next(e for e in entities if "clients" in e.id)
    assert summary.metadata["total_clients"] == 20
    assert "wired" in summary.metadata
    assert "wireless" in summary.metadata


def test_disconnected_device_is_degraded():
    from api.collectors.unifi import UniFiCollector
    state = {
        "health": "degraded", "connection_label": "UniFi", "auth_mode": "apikey",
        "client_count": 0, "wired_clients": 0, "wireless_clients": 0,
        "device_count": 1, "devices_up": 0, "devices_down": 1,
        "devices": [{"name": "AP", "mac": "aa:bb:cc:dd:ee:ff", "model": "U6",
                     "type": "uap", "type_label": "AP", "state": "disconnected",
                     "clients": 0, "uptime": 0, "version": "6.5"}],
    }
    entities = UniFiCollector().to_entities(state)
    dev_entities = [e for e in entities if "device" in e.id]
    assert dev_entities[0].status == "degraded"
    assert dev_entities[0].last_error is not None


def test_unconfigured_when_no_host():
    from api.collectors.unifi import UniFiCollector
    with patch.dict(os.environ, {}, clear=True):
        with patch("api.connections.get_connection_for_platform", return_value=None):
            r = asyncio.run(UniFiCollector().poll())
    assert r["health"] == "unconfigured"


def test_apikey_mode_uses_x_api_key_header():
    from api.collectors.unifi import _collect_apikey
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": []}
    mock_resp.raise_for_status = MagicMock()
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp

    with patch("httpx.get", return_value=mock_resp) as mock_get:
        with patch("httpx.Client", return_value=mock_client):
            _collect_apikey("192.168.1.1", 443, "test-key", "default", "lbl", "id1")

    headers = mock_get.call_args[1].get("headers", {})
    assert "X-API-KEY" in headers
    assert headers["X-API-KEY"] == "test-key"
    assert "Authorization" not in headers


def test_session_mode_posts_to_login():
    from api.collectors.unifi import _collect_session
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": []}
    mock_resp.raise_for_status = MagicMock()
    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp
    mock_client.get.return_value = mock_resp

    with patch("httpx.Client", return_value=mock_client):
        _collect_session("192.168.1.1", 8443, "admin", "secret", "default", "lbl", "id2")

    post_args = mock_client.post.call_args
    assert "/api/login" in str(post_args)
    assert post_args[1].get("json", {}).get("username") == "admin"


def test_collector_registered():
    from api.collectors.manager import CollectorManager
    names = [c.component for c in CollectorManager()._discover()]
    assert "unifi" in names


def test_ssh_exec_uses_netmiko_when_wingpy_missing():
    from api.collectors.network_ssh import _ssh_exec
    mock_conn = MagicMock()
    mock_conn.send_command.return_value = "Cisco IOS Version 15.1"
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    mock_netmiko = MagicMock()
    mock_netmiko.ConnectHandler = MagicMock(return_value=mock_conn)

    with patch.dict(sys.modules, {"wingpy": None, "netmiko": mock_netmiko}):
        result = _ssh_exec("192.168.1.1", 22, "admin", "pass",
                           "cisco_ios", "show version | include Version")

    assert len(result) > 0


def test_ssh_exec_falls_back_to_paramiko():
    from api.collectors.network_ssh import _ssh_exec
    mock_ssh = MagicMock()
    mock_stdout = MagicMock()
    mock_stdout.read.return_value = b"Junos 21.4R1"
    mock_ssh.exec_command.return_value = (MagicMock(), mock_stdout, MagicMock())

    mock_paramiko = MagicMock()
    mock_paramiko.SSHClient.return_value = mock_ssh
    mock_paramiko.AutoAddPolicy.return_value = MagicMock()

    # netmiko raises, paramiko succeeds
    mock_netmiko = MagicMock()
    mock_netmiko.ConnectHandler.side_effect = Exception("netmiko unavailable")

    with patch.dict(sys.modules, {"wingpy": None, "netmiko": mock_netmiko, "paramiko": mock_paramiko}):
        result = _ssh_exec("192.168.1.2", 22, "admin", "pass",
                           "juniper_junos", "show version | match Junos")

    assert "Junos" in result
