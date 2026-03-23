# tests/test_gate_rules.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from api.agents.gate_rules import kafka_rolling_restart, swarm_service_upgrade, changelog_check, evaluate


def test_kafka_all_up_is_go():
    verdict, msg = kafka_rolling_restart({"brokers_up": 3, "brokers_total": 3, "min_isr": 2, "replication_factor": 3})
    assert verdict == "GO"


def test_kafka_broker_offline_is_halt():
    verdict, msg = kafka_rolling_restart({"brokers_up": 2, "brokers_total": 3, "min_isr": 2, "replication_factor": 3})
    assert verdict == "HALT"
    assert "offline" in msg.lower()


def test_kafka_under_replicated_is_halt():
    verdict, msg = kafka_rolling_restart({"brokers_up": 3, "brokers_total": 3, "min_isr": 0, "replication_factor": 3})
    assert verdict == "HALT"
    assert "isr" in msg.lower()


def test_kafka_unknown_broker_count_is_ask():
    verdict, msg = kafka_rolling_restart({"brokers_up": 0, "brokers_total": 0})
    assert verdict == "ASK"


def test_swarm_quorum_maintained_is_go():
    verdict, msg = swarm_service_upgrade({"managers_up": 3, "managers_total": 3})
    assert verdict == "GO"


def test_swarm_below_quorum_is_halt():
    verdict, msg = swarm_service_upgrade({"managers_up": 1, "managers_total": 3})
    assert verdict == "HALT"
    assert "quorum" in msg.lower()


def test_changelog_ingested_no_breaking_is_go():
    verdict, msg = changelog_check({"changelog_ingested": True, "breaking_changes": [], "to_version": "3.8.0"})
    assert verdict == "GO"


def test_changelog_not_ingested_is_ask():
    verdict, msg = changelog_check({"changelog_ingested": False, "to_version": "3.8.0", "from_version": "3.7.1"})
    assert verdict == "ASK"
    assert "3.8.0" in msg


def test_changelog_breaking_changes_is_ask():
    verdict, msg = changelog_check({"changelog_ingested": True, "breaking_changes": ["API removed /foo"], "to_version": "3.8.0"})
    assert verdict == "ASK"


def test_evaluate_unknown_rule_returns_go():
    result = evaluate("nonexistent_rule", {})
    assert result["verdict"] == "GO"
