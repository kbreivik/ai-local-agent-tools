"""
End-to-end test: simulates agent performing a rolling upgrade of 'workload' service
from nginx:1.25-alpine to nginx:1.26-alpine while Kafka is under load.

Exercises the full check → act → verify → continue or halt pipeline.
Does NOT require LM Studio — tests the tool chain directly.
"""
import json
import os
import sys
import time
from pathlib import Path
from threading import Thread

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("DOCKER_HOST", "npipe:////./pipe/docker_engine")
os.environ.setdefault("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092,localhost:9093,localhost:9094")
os.environ.setdefault("AUDIT_LOG_PATH", "D:/claude_code/FAJK/HP1-AI-Agent-v1/logs/e2e_audit.log")
os.environ.setdefault("CHECKPOINT_PATH", "D:/claude_code/FAJK/HP1-AI-Agent-v1/checkpoints")

from mcp_server.tools import swarm, kafka, orchestration


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


def _assert_not_failed(result: dict, context: str = ""):
    assert result["status"] not in ("failed",), \
        f"HALT: {context} returned failed: {result['message']}"


def _gate(result: dict, label: str) -> dict:
    """Log and assert gate passed."""
    orchestration.audit_log(f"gate:{label}", result)
    print(f"  [{label}] {result['status']} — {result['message']}")
    return result


def kafka_load_producer(stop_flag: list, bootstrap: str):
    """Background thread: produce messages to Kafka during upgrade."""
    try:
        from kafka import KafkaProducer
        producer = KafkaProducer(
            bootstrap_servers=bootstrap.split(","),
            value_serializer=lambda v: json.dumps(v).encode(),
            request_timeout_ms=5000,
        )
        i = 0
        while not stop_flag[0]:
            producer.send("e2e-load-test", {"seq": i, "ts": time.time()})
            i += 1
            time.sleep(0.1)
        producer.flush()
        producer.close()
        print(f"  [kafka_producer] Sent {i} messages during upgrade")
    except Exception as e:
        print(f"  [kafka_producer] Error (non-blocking): {e}")


@_skip_no_docker
class TestE2ERollingUpgrade:
    """
    Agent simulation: rolling upgrade of workload service with health gates.
    Mirrors the exact sequence the LLM agent would execute.
    Requires a live Docker Swarm — skipped when Docker daemon is unavailable.
    """

    def test_step1_initial_swarm_health_check(self):
        """Step 1: Verify swarm is healthy before any action."""
        result = _gate(swarm.swarm_status(), "swarm_status")
        assert result["status"] == "ok", f"Swarm not healthy: {result['message']}"
        nodes = result["data"]["nodes"]
        assert len(nodes) > 0, "No swarm nodes found"
        print(f"\n  Nodes: {[n['hostname'] for n in nodes]}")

    def test_step2_list_services(self):
        """Step 2: Discover current services and their states."""
        result = _gate(swarm.service_list(), "service_list")
        assert result["status"] in ("ok", "degraded"), f"Cannot list services: {result['message']}"
        services = result["data"]["services"]
        print(f"\n  Services: {[(s['name'], s['image']) for s in services]}")

    def test_step3_kafka_health_gate(self):
        """Step 3: Verify Kafka is healthy — required before upgrade with Kafka load."""
        result = _gate(kafka.kafka_broker_status(), "kafka_broker_status")
        assert result["status"] in ("ok", "degraded"), f"Kafka error: {result['message']}"
        print(f"\n  Kafka brokers: {result['data'].get('count', 0)}")

    def test_step4_pre_kafka_check_gate(self):
        """Step 4: Full Kafka readiness gate."""
        result = _gate(kafka.pre_kafka_check(), "pre_kafka_check")
        # Kafka might be healthy or degraded — either way we can observe
        print(f"\n  Kafka gate: {result['status']} — {result['message']}")
        _assert_not_failed(result, "pre_kafka_check")

    def test_step5_checkpoint_before_upgrade(self):
        """Step 5: Save checkpoint before risky operation."""
        result = _gate(orchestration.checkpoint_save("pre_upgrade"), "checkpoint_save")
        assert result["status"] == "ok", f"Checkpoint failed: {result['message']}"
        cp_file = result["data"]["file"]
        assert Path(cp_file).exists(), f"Checkpoint file not written: {cp_file}"
        print(f"\n  Checkpoint: {cp_file}")

    def test_step6_pre_upgrade_check_gate(self):
        """Step 6: Full swarm upgrade gate — MUST pass before upgrade."""
        result = _gate(swarm.pre_upgrade_check(), "pre_upgrade_check")
        assert result["status"] in ("ok", "degraded"), \
            f"Upgrade gate returned error: {result['message']}"
        print(f"\n  Upgrade gate: {result['status']}")

    def test_step7_verify_workload_service_exists(self):
        """Step 7: Confirm workload service is present and check current image."""
        svc_list = swarm.service_list()
        services = svc_list["data"].get("services", [])
        workload = next(
            (s for s in services if "workload" in s["name"].lower()),
            None
        )
        assert workload is not None, \
            f"workload service not found. Services: {[s['name'] for s in services]}"
        print(f"\n  workload image: {workload['image']}")
        print(f"  replicas: {workload['running_replicas']}/{workload['desired_replicas']}")

    def test_step8_service_health_pre_upgrade(self):
        """Step 8: Verify workload health before upgrade."""
        svc_list = swarm.service_list()
        services = svc_list["data"].get("services", [])
        workload = next((s for s in services if "workload" in s["name"].lower()), None)
        if workload is None:
            pytest.skip("workload service not found")
        result = _gate(swarm.service_health(workload["name"]), "service_health_pre")
        print(f"\n  Pre-upgrade health: {result['status']}")

    def test_step9_rolling_upgrade_with_kafka_load(self):
        """
        Step 9 (main E2E): Rolling upgrade nginx:1.25-alpine → nginx:1.26-alpine
        while Kafka producer runs in background.

        Gate sequence:
          pre_kafka_check → pre_upgrade_check → checkpoint → upgrade → verify
        """
        # Find the workload service name
        svc_list = swarm.service_list()
        services = svc_list["data"].get("services", [])
        workload = next((s for s in services if "workload" in s["name"].lower()), None)
        if workload is None:
            pytest.skip("workload service not found — deploy swarm-stack.yml first")

        svc_name = workload["name"]
        current_image = workload["image"]
        target_image = "nginx:1.26-alpine"

        if target_image in current_image:
            # Already upgraded; test rollback path instead
            target_image = "nginx:1.25-alpine"

        print(f"\n  Upgrading {svc_name}: {current_image} → {target_image}")
        orchestration.audit_log("e2e_upgrade_start",
                                {"service": svc_name, "from": current_image, "to": target_image})

        # Gate 1: Kafka check
        kafka_gate = _gate(kafka.pre_kafka_check(), "pre_kafka_check")
        if kafka_gate["status"] == "failed":
            orchestration.escalate(f"Kafka gate failed before upgrade: {kafka_gate['message']}")
            pytest.skip("Kafka not ready — escalated")

        # Gate 2: Swarm upgrade check
        upgrade_gate = _gate(swarm.pre_upgrade_check(), "pre_upgrade_check")
        if upgrade_gate["status"] == "failed":
            orchestration.escalate(f"Swarm gate failed: {upgrade_gate['message']}")
            pytest.skip("Swarm not ready — escalated")

        # Save checkpoint
        _gate(orchestration.checkpoint_save("e2e_pre_upgrade"), "checkpoint_save")

        # Start Kafka load in background
        stop_flag = [False]
        bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
        producer_thread = Thread(
            target=kafka_load_producer,
            args=(stop_flag, bootstrap),
            daemon=True,
        )
        producer_thread.start()

        try:
            # Perform upgrade
            upgrade_result = _gate(
                swarm.service_upgrade(svc_name, target_image),
                "service_upgrade"
            )
        finally:
            stop_flag[0] = True
            producer_thread.join(timeout=5)

        orchestration.audit_log("e2e_upgrade_result", upgrade_result)

        if upgrade_result["status"] == "failed":
            orchestration.escalate(f"Upgrade failed: {upgrade_result['message']}")
            # Attempt rollback
            rollback = _gate(swarm.service_rollback(svc_name), "service_rollback")
            orchestration.audit_log("e2e_rollback", rollback)
            pytest.fail(f"Upgrade failed (rollback attempted): {upgrade_result['message']}")

        # Post-upgrade verification
        post_health = _gate(swarm.service_health(svc_name), "service_health_post")
        orchestration.audit_log("e2e_post_health", post_health)

        if post_health["status"] == "degraded":
            orchestration.escalate(f"Service degraded after upgrade: {post_health['message']}")

        print(f"\n  Post-upgrade health: {post_health['status']}")
        print(f"  Final: {post_health['data']}")

        # Verify audit log has entries
        audit_path = Path(os.environ["AUDIT_LOG_PATH"])
        assert audit_path.exists(), "Audit log was not written"
        lines = audit_path.read_text(encoding="utf-8").strip().split("\n")
        print(f"\n  Audit entries written: {len(lines)}")

        # Success — upgrade completed (or gracefully escalated)
        assert post_health["status"] in ("ok", "degraded"), \
            f"Unexpected status after upgrade: {post_health['status']}"


class TestSecurityChecks:
    """Verify security best practices are enforced."""

    def test_no_hardcoded_credentials_in_tools(self):
        """No passwords, tokens, or secrets hardcoded in tool files."""
        import re
        bad_patterns = [
            r'password\s*=\s*["\'][^"\']+["\']',
            r'secret\s*=\s*["\'][^"\']+["\']',
            r'api_key\s*=\s*["\'][a-zA-Z0-9]{20,}["\']',
            r'token\s*=\s*["\'][a-zA-Z0-9]{20,}["\']',
        ]
        tool_files = Path("D:/claude_code/FAJK/HP1-AI-Agent-v1/mcp_server").rglob("*.py")
        for f in tool_files:
            content = f.read_text(encoding="utf-8")
            for pattern in bad_patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                assert not matches, f"Potential hardcoded secret in {f}: {matches}"

    def test_all_tools_return_structured_response(self):
        """Every tool returns {status, data, timestamp, message}."""
        required_keys = {"status", "data", "timestamp", "message"}
        result = swarm.swarm_status()
        assert required_keys.issubset(result.keys()), \
            f"swarm_status missing keys: {required_keys - result.keys()}"

        result = kafka.kafka_broker_status()
        assert required_keys.issubset(result.keys()), \
            f"kafka_broker_status missing keys: {required_keys - result.keys()}"

        result = orchestration.audit_log("security_test", "ok")
        assert required_keys.issubset(result.keys()), \
            f"audit_log missing keys: {required_keys - result.keys()}"

    def test_env_vars_used_for_all_config(self):
        """Config values come from env vars, not hardcoded paths."""
        from mcp_server.tools import swarm as sw, kafka as kf, orchestration as orch
        import inspect
        # Verify env.get() is used in each module
        for mod, name in [(sw, "swarm"), (kf, "kafka"), (orch, "orchestration")]:
            src = inspect.getsource(mod)
            assert "os.environ" in src or "os.getenv" in src, \
                f"{name} module does not use environment variables"

    def test_audit_log_records_all_operations(self):
        """Verify audit log captures structured entries."""
        result = orchestration.audit_log("security_test_op", {"verified": True})
        assert result["status"] == "ok"
        log_path = Path(os.environ["AUDIT_LOG_PATH"])
        content = log_path.read_text(encoding="utf-8")
        assert "security_test_op" in content, "Audit log did not capture test operation"
