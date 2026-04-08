"""
Contract tests for v1.23 collector additions: platforms, mock(), to_entities().
Does NOT test poll() — covered by existing test_collectors_*.py files.
"""
import pytest
from api.collectors.base import BaseCollector, Entity, PLATFORM_SECTION
from api.collectors.manager import CollectorManager


@pytest.fixture
def all_collectors():
    mgr = CollectorManager()
    return mgr._discover()


def test_all_collectors_have_platforms_attr(all_collectors):
    for c in all_collectors:
        assert hasattr(c, "platforms"), f"{c.component} missing 'platforms'"
        assert isinstance(c.platforms, list), f"{c.component}.platforms must be list"


def test_proxmox_vms_platforms(all_collectors):
    c = next(c for c in all_collectors if c.component == "proxmox_vms")
    assert "proxmox" in c.platforms
    assert "pbs" in c.platforms


def test_external_services_covers_all_sections(all_collectors):
    c = next(c for c in all_collectors if c.component == "external_services")
    for p in ("fortigate", "truenas", "wazuh", "proxmox"):
        assert p in c.platforms, f"external_services missing platform '{p}'"


def test_network_ssh_platforms(all_collectors):
    c = next(c for c in all_collectors if c.component == "network_ssh")
    for p in ("fortiswitch", "cisco", "juniper", "aruba"):
        assert p in c.platforms


def test_trigger_derivation_proxmox(all_collectors):
    triggered = {c.component for c in all_collectors if "proxmox" in c.platforms}
    assert "proxmox_vms" in triggered
    assert "external_services" in triggered


def test_trigger_derivation_truenas(all_collectors):
    triggered = {c.component for c in all_collectors if "truenas" in c.platforms}
    assert "external_services" in triggered
    assert "proxmox_vms" not in triggered
    assert "network_ssh" not in triggered


def test_trigger_derivation_fortiswitch(all_collectors):
    """FortiSwitch uses SSH — triggers network_ssh (not external_services which is HTTP-only)."""
    triggered = {c.component for c in all_collectors if "fortiswitch" in c.platforms}
    assert "network_ssh" in triggered


_MOCK_REQUIRED = {"proxmox_vms", "external_services", "network_ssh"}

def test_required_collectors_have_mock(all_collectors):
    for c in all_collectors:
        if c.component not in _MOCK_REQUIRED:
            continue
        try:
            result = c.mock()
        except NotImplementedError:
            pytest.fail(f"{c.component}.mock() raises NotImplementedError")
        assert isinstance(result, dict), f"{c.component}.mock() must return dict"
        assert "health" in result, f"{c.component}.mock() missing 'health'"


def test_mock_proxmox_shape():
    from api.collectors.proxmox_vms import ProxmoxVMsCollector
    state = ProxmoxVMsCollector().mock()
    assert "vms" in state and "lxc" in state
    assert isinstance(state["vms"], list) and len(state["vms"]) >= 1


def test_mock_external_services_shape():
    from api.collectors.external_services import ExternalServicesCollector
    state = ExternalServicesCollector().mock()
    assert "services" in state and isinstance(state["services"], list) and len(state["services"]) >= 1


def test_mock_network_ssh_shape():
    from api.collectors.network_ssh import NetworkSSHCollector
    state = NetworkSSHCollector().mock()
    assert "devices" in state and isinstance(state["devices"], list)


def test_entity_dataclass_serialises():
    import json
    e = Entity(id="test:1", label="Test", component="test",
               platform="proxmox", section="COMPUTE", status="healthy",
               latency_ms=42, metadata={"k": "v"})
    d = e.to_dict()
    json.dumps(d)
    assert d["id"] == "test:1" and d["metadata"]["k"] == "v"


def test_proxmox_to_entities_from_mock():
    from api.collectors.proxmox_vms import ProxmoxVMsCollector
    c = ProxmoxVMsCollector()
    entities = c.to_entities(c.mock())
    assert len(entities) >= 2
    for e in entities:
        assert isinstance(e, Entity)
        assert e.section == "COMPUTE" and e.platform == "proxmox"
        assert e.status in ("healthy", "degraded", "error", "maintenance", "unknown")
        assert e.id.startswith("proxmox_vms:")


def test_external_services_to_entities_from_mock():
    from api.collectors.external_services import ExternalServicesCollector
    c = ExternalServicesCollector()
    entities = c.to_entities(c.mock())
    ids = [e.id for e in entities]
    assert any("fortigate" in i for i in ids)
    assert any("truenas" in i for i in ids)
    for e in entities:
        assert e.section == PLATFORM_SECTION.get(e.platform, "PLATFORM")


def test_network_ssh_to_entities_from_mock():
    from api.collectors.network_ssh import NetworkSSHCollector
    c = NetworkSSHCollector()
    entities = c.to_entities(c.mock())
    assert len(entities) >= 1
    for e in entities:
        assert e.section == "NETWORK"


def test_to_entities_stopped_vm_is_degraded():
    from api.collectors.proxmox_vms import ProxmoxVMsCollector
    state = {"health": "degraded", "connection_label": "test", "connection_id": "x",
             "vms": [{"vmid": 101, "name": "stopped-vm", "node": "pve1",
                      "status": "stopped", "dot": "amber", "type": "qemu"}], "lxc": []}
    entities = ProxmoxVMsCollector().to_entities(state)
    assert entities[0].status == "degraded"


def test_to_entities_unreachable_service_is_error():
    from api.collectors.external_services import ExternalServicesCollector
    state = {"health": "critical", "services": [
        {"name": "FortiGate", "slug": "fortigate", "service_type": "fortigate",
         "dot": "red", "problem": "unreachable", "latency_ms": None,
         "host_port": "1.2.3.4:443", "open_ui_url": None, "connection_id": "x"}]}
    entities = ExternalServicesCollector().to_entities(state)
    assert entities[0].status == "error" and entities[0].last_error == "unreachable"


def test_platform_section_completeness():
    from api.collectors.external_services import ExternalServicesCollector
    c = ExternalServicesCollector()
    missing = [p for p in c.platforms if p not in PLATFORM_SECTION and p != "lm_studio"]
    assert missing == [], f"Platforms missing from PLATFORM_SECTION: {missing}"
