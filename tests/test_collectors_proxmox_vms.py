# tests/test_collectors_proxmox_vms.py
import asyncio
import os
from unittest.mock import patch, MagicMock


def _mock_proxmox_api(*args, **kwargs):
    """Create a mock ProxmoxAPI that returns test data."""
    prox = MagicMock()
    # nodes.get() returns list of node dicts
    prox.nodes.get.return_value = [{"node": "pve1"}]
    return prox


def _mock_proxmox_with_vms(*args, **kwargs):
    """Mock ProxmoxAPI returning VMs and LXC."""
    prox = MagicMock()
    prox.nodes.get.return_value = [{"node": "pve1"}]
    # prox.nodes("pve1").qemu.get() → VM list
    node_mock = MagicMock()
    node_mock.qemu.get.return_value = [
        {"vmid": 9200, "name": "agent-01", "status": "running",
         "cpu": 0.14, "mem": 2200000000, "maxmem": 4294967296,
         "cpus": 2, "netin": 0, "netout": 0}
    ]
    node_mock.lxc.get.return_value = []
    # Guest agent get-fsinfo — return empty (no agent)
    node_mock.qemu.return_value.agent.return_value.get.return_value = {"result": []}
    prox.nodes.return_value = node_mock
    return prox


def _mock_proxmox_stopped_vm(*args, **kwargs):
    prox = MagicMock()
    prox.nodes.get.return_value = [{"node": "pve1"}]
    node_mock = MagicMock()
    node_mock.qemu.get.return_value = [
        {"vmid": 9221, "name": "worker-01", "status": "stopped",
         "cpu": 0, "mem": 0, "maxmem": 4294967296, "cpus": 2}
    ]
    node_mock.lxc.get.return_value = []
    prox.nodes.return_value = node_mock
    return prox


def test_poll_returns_vms_key():
    from api.collectors.proxmox_vms import ProxmoxVMsCollector
    collector = ProxmoxVMsCollector()

    with patch.dict(os.environ, {"PROXMOX_HOST": "192.168.1.5"}, clear=False), \
         patch("proxmoxer.ProxmoxAPI", side_effect=_mock_proxmox_with_vms):
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

    with patch.dict(os.environ, {"PROXMOX_HOST": "192.168.1.5"}, clear=False), \
         patch("proxmoxer.ProxmoxAPI", side_effect=_mock_proxmox_stopped_vm):
        result = asyncio.run(collector.poll())

    assert result["vms"][0]["dot"] == "red"
    assert result["vms"][0]["problem"] == "stopped"
    assert result["health"] == "critical"


def test_all_nodes_unreachable_returns_error():
    from api.collectors.proxmox_vms import ProxmoxVMsCollector
    collector = ProxmoxVMsCollector()

    def _mock_fail(*args, **kwargs):
        prox = MagicMock()
        prox.nodes.get.return_value = [{"node": "pve1"}]
        node_mock = MagicMock()
        node_mock.qemu.get.side_effect = Exception("Connection refused")
        node_mock.lxc.get.side_effect = Exception("Connection refused")
        prox.nodes.return_value = node_mock
        return prox

    with patch.dict(os.environ, {"PROXMOX_HOST": "192.168.1.5"}, clear=False), \
         patch("proxmoxer.ProxmoxAPI", side_effect=_mock_fail):
        result = asyncio.run(collector.poll())

    assert result["health"] == "error"
