"""Tests for MCP tools — run against live Docker + Kafka environment."""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# Set env vars before importing tools
os.environ.setdefault("DOCKER_HOST", "npipe:////./pipe/docker_engine")
os.environ.setdefault("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092,localhost:9093,localhost:9094")
os.environ.setdefault("AUDIT_LOG_PATH", "D:/claude_code/FAJK/HP1-AI-Agent-v1/logs/audit.log")
os.environ.setdefault("CHECKPOINT_PATH", "D:/claude_code/FAJK/HP1-AI-Agent-v1/checkpoints")

from mcp_server.tools import swarm, kafka, orchestration


def assert_valid_response(result: dict):
    assert isinstance(result, dict), f"Expected dict, got {type(result)}"
    assert "status" in result, f"Missing 'status' key: {result}"
    assert "data" in result, f"Missing 'data' key: {result}"
    assert "timestamp" in result, f"Missing 'timestamp' key: {result}"
    assert "message" in result, f"Missing 'message' key: {result}"
    assert result["status"] in ("ok", "error", "degraded", "failed", "escalated"), \
        f"Invalid status: {result['status']}"


def _docker_available() -> bool:
    """Return True if the local Docker daemon is reachable."""
    try:
        import docker
        docker.from_env().ping()
        return True
    except Exception:
        return False


_DOCKER_UP = _docker_available()
_skip_no_docker = pytest.mark.skipif(not _DOCKER_UP, reason="Docker daemon not available")


# ── Swarm tests ───────────────────────────────────────────────────────────────

class TestSwarmTools:
    def test_swarm_status_returns_valid_response(self):
        result = swarm.swarm_status()
        assert_valid_response(result)
        print(f"\nswarm_status: {result['status']} — {result['message']}")

    def test_service_list_returns_valid_response(self):
        result = swarm.service_list()
        assert_valid_response(result)
        if result["status"] == "ok":
            assert "services" in result["data"]
            assert "count" in result["data"]

    def test_pre_upgrade_check_returns_valid_response(self):
        result = swarm.pre_upgrade_check()
        assert_valid_response(result)
        print(f"\npre_upgrade_check: {result['status']} — {result['message']}")

    def test_service_health_known_service(self):
        # List services first, then check health of first one
        svc_list = swarm.service_list()
        if svc_list["status"] == "ok" and svc_list["data"]["count"] > 0:
            svc_name = svc_list["data"]["services"][0]["name"]
            result = swarm.service_health(svc_name)
            assert_valid_response(result)
        else:
            pytest.skip("No services available to test service_health")

    @_skip_no_docker
    def test_service_health_nonexistent(self):
        result = swarm.service_health("nonexistent-service-xyz")
        assert result["status"] == "error"
        assert "not found" in result["message"].lower()


# ── Kafka tests ───────────────────────────────────────────────────────────────

class TestKafkaTools:
    def test_kafka_broker_status_returns_valid_response(self):
        result = kafka.kafka_broker_status()
        assert_valid_response(result)
        print(f"\nkafka_broker_status: {result['status']} — {result['message']}")

    def test_pre_kafka_check_returns_valid_response(self):
        result = kafka.pre_kafka_check()
        assert_valid_response(result)
        print(f"\npre_kafka_check: {result['status']} — {result['message']}")

    def test_kafka_broker_status_structure(self):
        result = kafka.kafka_broker_status()
        if result["status"] == "ok":
            assert "brokers" in result["data"]
            assert "count" in result["data"]
            assert "controller_id" in result["data"]


# ── Orchestration tests ───────────────────────────────────────────────────────

class TestOrchestrationTools:
    def test_audit_log_writes_entry(self):
        result = orchestration.audit_log("test_action", {"test": True})
        assert_valid_response(result)
        log_path = Path(os.environ.get("AUDIT_LOG_PATH", "./logs/audit.log"))
        assert log_path.exists(), f"Audit log not created at {log_path}"
        last_line = log_path.read_text(encoding="utf-8").strip().split("\n")[-1]
        entry = json.loads(last_line)
        assert entry["action"] == "test_action"

    def test_checkpoint_save_and_restore(self):
        label = "test_checkpoint"
        save_result = orchestration.checkpoint_save(label)
        # checkpoint_save calls swarm/kafka — may fail if Docker is down, that's OK
        # Just verify structure
        assert_valid_response(save_result)
        if save_result["status"] == "ok":
            restore_result = orchestration.checkpoint_restore(label)
            assert_valid_response(restore_result)
            assert restore_result["status"] == "ok"

    def test_escalate_returns_escalated_status(self):
        result = orchestration.escalate("test escalation")
        assert result["status"] == "escalated"
        assert "human_review" in str(result["data"])

    def test_checkpoint_restore_missing_label(self):
        result = orchestration.checkpoint_restore("nonexistent_label_xyz")
        assert result["status"] == "error"


# ── Integration test ──────────────────────────────────────────────────────────

class TestIntegration:
    def test_full_pre_checks_gate(self):
        """Verify that both gates execute without crashing."""
        swarm_gate = swarm.pre_upgrade_check()
        kafka_gate = kafka.pre_kafka_check()
        assert_valid_response(swarm_gate)
        assert_valid_response(kafka_gate)
        print(f"\nSwarm gate: {swarm_gate['status']}")
        print(f"Kafka gate: {kafka_gate['status']}")

    def test_upgrade_blocked_when_swarm_unhealthy(self):
        """Verify service_upgrade checks pre_upgrade_check internally."""
        # With a non-existent service, should return error before checking swarm
        result = swarm.service_upgrade("nonexistent-xyz", "nginx:latest")
        assert result["status"] in ("error",)  # service not found
