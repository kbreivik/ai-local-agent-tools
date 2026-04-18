"""Unit tests for api.facts.extractors — snapshot → fact list shape."""
from api.facts import extractors as ex


def test_proxmox_extractor_produces_status_node_and_ip():
    snapshot = {
        "vms": [
            {"vmid": 100, "name": "hp1-prod-worker-03", "node": "Pmox2",
             "status": "running", "ip": "192.168.199.33",
             "vcpus": 4, "maxmem_gb": 8.0},
        ],
        "lxc": [
            {"vmid": 200, "name": "ct-dns-01", "node": "Pmox1",
             "status": "running"},
        ],
    }
    facts = ex.extract_facts_from_proxmox_vm_snapshot(snapshot, connection_label="hp1-proxmox")
    keys = [f["fact_key"] for f in facts]
    assert "prod.proxmox.vm.hp1-prod-worker-03.status" in keys
    assert "prod.proxmox.vm.hp1-prod-worker-03.node" in keys
    assert "prod.proxmox.vm.hp1-prod-worker-03.ip" in keys
    assert "prod.proxmox.lxc.ct-dns-01.status" in keys
    for f in facts:
        assert f["source"] == "proxmox_collector"


def test_swarm_extractor_from_desired_replicas_shape():
    snapshot = {
        "services": [
            {"id": "abc", "name": "kafka_broker-3",
             "desired_replicas": 1, "running_replicas": 0,
             "image": "bitnami/kafka:3.7.0",
             "image_digest": "sha256:deadbeef"},
        ],
        "nodes": [
            {"hostname": "ds-docker-worker-03", "state": "ready",
             "availability": "active", "role": "worker"},
        ],
    }
    facts = ex.extract_facts_from_swarm_snapshot(snapshot)
    keys = {f["fact_key"]: f["value"] for f in facts}
    assert keys["prod.swarm.service.kafka_broker-3.replicas.desired"] == 1
    assert keys["prod.swarm.service.kafka_broker-3.replicas.running"] == 0
    assert keys["prod.swarm.service.kafka_broker-3.image"] == "bitnami/kafka:3.7.0"
    assert keys["prod.swarm.node.ds-docker-worker-03.state"] == "ready"


def test_docker_agent_extractor_uses_short_id():
    snapshot = {
        "containers": [
            {"id": "f3ef70283135abc", "name": "logstash_logstash",
             "image": "logstash:8.0", "state": "running",
             "networks": ["elastic-net"],
             "ip_addresses": ["10.0.0.5"]},
        ],
    }
    facts = ex.extract_facts_from_docker_agent_snapshot(snapshot)
    keys = [f["fact_key"] for f in facts]
    assert "prod.container.f3ef70283135.service_name" in keys
    assert "prod.container.f3ef70283135.image" in keys
    assert "prod.container.f3ef70283135.state" in keys
    assert "prod.container.f3ef70283135.networks" in keys
    assert "prod.container.f3ef70283135.ip" in keys


def test_kafka_extractor_broker_and_topic():
    snapshot = {
        "brokers": [
            {"id": 3, "host": "192.168.199.33", "port": 9093, "is_controller": True},
        ],
        "topics": [
            {"name": "hp1-logs", "partition_count": 3, "replication_factor": 3},
        ],
    }
    facts = ex.extract_facts_from_kafka_snapshot(snapshot)
    keys = {f["fact_key"]: f["value"] for f in facts}
    assert keys["prod.kafka.broker.3.host"] == "192.168.199.33"
    assert keys["prod.kafka.broker.3.port"] == 9093
    assert keys["prod.kafka.broker.3.is_controller"] is True
    assert keys["prod.kafka.topic.hp1-logs.partitions"] == 3
    assert keys["prod.kafka.topic.hp1-logs.replication_factor"] == 3


def test_pbs_extractor_last_backups_and_datastore():
    snapshot = {
        "last_backups": [
            {"backup_type": "vm", "backup_id": 101,
             "last_backup_ts": 1700000000, "datastore": "local-zfs"},
        ],
        "datastores": [
            {"name": "local-zfs", "usage_pct": 42.0, "total_gb": 2000.0},
        ],
    }
    facts = ex.extract_facts_from_pbs_snapshot(snapshot)
    keys = {f["fact_key"]: f["value"] for f in facts}
    assert keys["prod.pbs.backup.vm-101.last_success_ts"] == 1700000000
    assert keys["prod.pbs.backup.vm-101.vm_id"] == 101
    assert keys["prod.pbs.datastore.local-zfs.usage_pct"] == 42.0


def test_fortiswitch_extractor_safe_on_empty():
    assert ex.extract_facts_from_fortiswitch_snapshot({}) == []
    snapshot = {
        "switches": [
            {"serial": "FS1E48T-XYZ", "model": "FS-148F",
             "firmware": "v7.4.1", "mac_addresses": ["aa:bb:cc:dd:ee:ff"]},
        ],
    }
    facts = ex.extract_facts_from_fortiswitch_snapshot(snapshot)
    keys = {f["fact_key"]: f["value"] for f in facts}
    assert keys["prod.fortiswitch.FS1E48T-XYZ.model"] == "FS-148F"
    assert keys["prod.fortiswitch.FS1E48T-XYZ.firmware"] == "v7.4.1"


def test_extractors_safe_on_none_or_garbage():
    assert ex.extract_facts_from_proxmox_vm_snapshot({}, connection_label="") == []
    assert ex.extract_facts_from_swarm_snapshot({}) == []
    assert ex.extract_facts_from_docker_agent_snapshot({}) == []
    assert ex.extract_facts_from_kafka_snapshot({}) == []
    assert ex.extract_facts_from_pbs_snapshot({}) == []
    # Non-dict input should still not raise
    assert ex.extract_facts_from_proxmox_vm_snapshot(None, "") == []  # type: ignore[arg-type]
