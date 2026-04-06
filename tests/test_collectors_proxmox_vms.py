# tests/test_collectors_proxmox_vms.py
import asyncio
import os
from unittest.mock import patch, MagicMock


def _mock_httpx_get(url, **kwargs):
    """Return different responses based on URL path."""
    resp = MagicMock()
    resp.status_code = 200
    if "/nodes" in url and "/qemu" not in url and "/lxc" not in url:
        resp.json.return_value = {"data": [{"node": "pve1"}]}
    else:
        resp.json.return_value = {
            "data": [{"vmid": 9200, "name": "agent-01", "status": "running",
                      "cpu": 0.14, "mem": 2200000000, "maxmem": 4294967296,
                      "cpus": 2, "netin": 0, "netout": 0}]
        }
    return resp


def test_poll_returns_vms_key():
    from api.collectors.proxmox_vms import ProxmoxVMsCollector
    collector = ProxmoxVMsCollector()

    with patch.dict(os.environ, {"PROXMOX_HOST": "192.168.1.5"}, clear=False), \
         patch("api.collectors.proxmox_vms.httpx.get", side_effect=_mock_httpx_get), \
         patch("api.collectors.proxmox_vms._get_vm_disk_usage", return_value=[]):
        result = asyncio.run(collector.poll())

    assert "vms" in result
    assert result["health"] in ("healthy", "degraded", "critical", "error", "unconfigured")
    assert result["vms"][0]["vmid"] == 9200
    assert result["vms"][0]["dot"] == "green"
    assert result["vms"][0]["node"] == "pve1"


def test_unconfigured_when_no_host():
    from api.collectors.proxmox_vms import ProxmoxVMsCollector
    collector = ProxmoxVMsCollector()
    with patch.dict(os.environ, {"PROXMOX_HOST": ""}, clear=False):
        result = asyncio.run(collector.poll())
    assert result["health"] == "unconfigured"


def test_stopped_vm_returns_red_dot():
    from api.collectors.proxmox_vms import ProxmoxVMsCollector
    collector = ProxmoxVMsCollector()

    def _mock_get(url, **kw):
        resp = MagicMock()
        resp.status_code = 200
        if "/nodes" in url and "/qemu" not in url and "/lxc" not in url:
            resp.json.return_value = {"data": [{"node": "pve1"}]}
        else:
            resp.json.return_value = {
                "data": [{"vmid": 9221, "name": "worker-01", "status": "stopped",
                          "cpu": 0, "mem": 0, "maxmem": 4294967296, "cpus": 2}]
            }
        return resp

    with patch.dict(os.environ, {"PROXMOX_HOST": "192.168.1.5"}, clear=False), \
         patch("api.collectors.proxmox_vms.httpx.get", side_effect=_mock_get), \
         patch("api.collectors.proxmox_vms._get_vm_disk_usage", return_value=[]):
        result = asyncio.run(collector.poll())

    assert result["vms"][0]["dot"] == "red"
    assert result["vms"][0]["problem"] == "stopped"
    assert result["health"] == "critical"


def test_all_nodes_unreachable_returns_error():
    from api.collectors.proxmox_vms import ProxmoxVMsCollector
    collector = ProxmoxVMsCollector()

    with patch.dict(os.environ, {"PROXMOX_HOST": "192.168.1.5"}, clear=False), \
         patch("api.collectors.proxmox_vms.httpx.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_get.return_value = mock_resp
        result = asyncio.run(collector.poll())

    assert result["health"] == "error"
    assert result["vms"] == []
