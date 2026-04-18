"""Tool-result fact extractors (v2.35.2).

Each extractor reads a tool call's args + result dict and emits a list of
fact dicts at source=agent_observation. The dispatcher is the public entry
point — unknown tools and malformed input must not raise.
"""
from api.facts import tool_extractors as tx


# ── service_placement ────────────────────────────────────────────────────────


def test_service_placement_emits_placement_and_container_mapping():
    args = {"service_name": "logstash_logstash"}
    result = {
        "status": "ok",
        "data": {
            "containers": [
                {"node": "ds-docker-worker-03",
                 "vm_host_label": "ds-docker-worker-03",
                 "container_id": "f3ef70283135abcdef"},
                {"node": "ds-docker-worker-02",
                 "vm_host_label": "ds-docker-worker-02",
                 "container_id": "aaaaa0000000bbbbbb"},
            ],
        },
    }
    facts = tx.extract_facts_from_service_placement(args, result)
    keys = {f["fact_key"]: f for f in facts}
    placement_key = "prod.swarm.service.logstash_logstash.placement"
    assert placement_key in keys
    assert sorted(keys[placement_key]["value"]) == sorted([
        "ds-docker-worker-02", "ds-docker-worker-03",
    ])
    assert keys["prod.container.f3ef70283135.service_name"]["value"] == "logstash_logstash"
    assert keys["prod.container.f3ef70283135.host"]["value"] == "ds-docker-worker-03"
    for f in facts:
        assert f["source"] == "agent_observation"


def test_service_placement_status_not_ok_returns_empty():
    assert tx.extract_facts_from_service_placement({"service_name": "s"}, {"status": "error"}) == []


def test_service_placement_missing_service_name_returns_empty():
    assert tx.extract_facts_from_service_placement({}, {"status": "ok", "data": {"containers": []}}) == []


def test_container_discover_by_service_matches_service_placement():
    args = {"service_name": "foo"}
    result = {"status": "ok", "data": {"containers": [
        {"node": "n1", "vm_host_label": "n1", "container_id": "abc000111222"},
    ]}}
    a = tx.extract_facts_from_container_discover_by_service(args, result)
    b = tx.extract_facts_from_service_placement(args, result)
    assert a == b


# ── kafka_broker_status ──────────────────────────────────────────────────────


def test_kafka_broker_status_emits_host_and_port():
    result = {
        "status": "ok",
        "data": {
            "brokers": [
                {"id": 3, "host": "192.168.199.33", "port": 9093},
                {"id": 1, "host": "192.168.199.31", "port": 9093},
            ],
        },
    }
    facts = tx.extract_facts_from_kafka_broker_status({}, result)
    keys = {f["fact_key"]: f["value"] for f in facts}
    assert keys["prod.kafka.broker.3.host"] == "192.168.199.33"
    assert keys["prod.kafka.broker.3.port"] == 9093
    assert keys["prod.kafka.broker.1.host"] == "192.168.199.31"


def test_kafka_broker_status_degraded_still_extracts():
    result = {"status": "degraded", "data": {
        "brokers": [{"id": 2, "host": "x.x.x.x", "port": 9093}],
    }}
    facts = tx.extract_facts_from_kafka_broker_status({}, result)
    assert len(facts) == 2


def test_kafka_broker_status_skips_unknown_id():
    result = {"status": "ok", "data": {"brokers": [{"id": -1, "host": "x", "port": 1}]}}
    assert tx.extract_facts_from_kafka_broker_status({}, result) == []


# ── container_networks ───────────────────────────────────────────────────────


def test_container_networks_emits_network_attachments():
    result = {"status": "ok", "data": {"networks": {"elastic-net": {"ip": "10.0.0.5"}}}}
    facts = tx.extract_facts_from_container_networks(
        {"container_id": "f3ef70283135abcdef"}, result,
    )
    assert len(facts) == 1
    assert facts[0]["fact_key"] == "prod.container.f3ef70283135.networks"


def test_container_networks_no_container_id_returns_empty():
    result = {"status": "ok", "data": {"networks": {"net-a": {}}}}
    assert tx.extract_facts_from_container_networks({}, result) == []


# ── container_tcp_probe ──────────────────────────────────────────────────────


def test_container_tcp_probe_emits_reachability_with_volatile_metadata():
    args = {"container_id": "f3ef70283135abcdef",
            "target_host": "192.168.199.40", "target_port": 9093}
    result = {"status": "ok", "data": {"reachable": True}}
    facts = tx.extract_facts_from_container_tcp_probe(args, result)
    assert len(facts) == 1
    f = facts[0]
    assert f["fact_key"] == "prod.container.f3ef70283135.reachability.192.168.199.40:9093"
    assert f["value"] is True
    assert f["metadata"]["volatile"] is True


# ── proxmox_vm_power ─────────────────────────────────────────────────────────


def test_proxmox_vm_power_status_emits_vm_status():
    args = {"action": "status", "vm_label": "hp1-prod-worker-03"}
    result = {"status": "ok", "data": {"status": "running"}}
    facts = tx.extract_facts_from_proxmox_vm_power(args, result)
    assert len(facts) == 1
    assert facts[0]["fact_key"] == "prod.proxmox.vm.hp1-prod-worker-03.status"
    assert facts[0]["value"] == "running"


def test_proxmox_vm_power_non_status_returns_empty():
    assert tx.extract_facts_from_proxmox_vm_power(
        {"action": "start", "vm_label": "x"}, {"status": "ok"},
    ) == []


# ── swarm_node_status ────────────────────────────────────────────────────────


def test_swarm_node_status_emits_availability():
    result = {"status": "ok", "data": {"nodes": [
        {"hostname": "manager-01", "availability": "active"},
        {"hostname": "worker-03",  "availability": "drain"},
    ]}}
    facts = tx.extract_facts_from_swarm_node_status({}, result)
    keys = {f["fact_key"]: f["value"] for f in facts}
    assert keys["prod.swarm.node.manager-01.status"] == "active"
    assert keys["prod.swarm.node.worker-03.status"] == "drain"


# ── dispatcher ───────────────────────────────────────────────────────────────


def test_dispatcher_unknown_tool_returns_empty():
    assert tx.extract_facts_from_tool_result("no_such_tool", {}, {"status": "ok"}) == []


def test_dispatcher_malformed_result_returns_empty():
    # None instead of dict
    assert tx.extract_facts_from_tool_result("service_placement", {}, None) == []
    # Missing 'status'
    assert tx.extract_facts_from_tool_result(
        "service_placement", {"service_name": "s"}, {"data": {"containers": []}},
    ) == []
    # Missing 'data'
    assert tx.extract_facts_from_tool_result(
        "kafka_broker_status", {}, {"status": "ok"},
    ) == []


def test_dispatcher_wraps_extractor_exceptions():
    # Monkey-patch an extractor that raises — dispatcher must swallow.
    original = tx.TOOL_EXTRACTORS.get("service_placement")
    def _boom(*a, **kw):
        raise RuntimeError("boom")
    tx.TOOL_EXTRACTORS["service_placement"] = _boom
    try:
        assert tx.extract_facts_from_tool_result("service_placement", {}, {}) == []
    finally:
        tx.TOOL_EXTRACTORS["service_placement"] = original


def test_dispatcher_routes_by_name():
    args = {"service_name": "svc-a"}
    result = {"status": "ok", "data": {"containers": [
        {"node": "n1", "container_id": "abc000111222"},
    ]}}
    facts = tx.extract_facts_from_tool_result("service_placement", args, result)
    assert any(f["fact_key"] == "prod.swarm.service.svc-a.placement" for f in facts)
