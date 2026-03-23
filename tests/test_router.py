# tests/test_router.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def test_detect_domain_kafka():
    from api.agents.router import detect_domain
    assert detect_domain("restart kafka brokers") == "kafka"


def test_detect_domain_swarm():
    from api.agents.router import detect_domain
    assert detect_domain("upgrade swarm service to new image") == "swarm"


def test_detect_domain_proxmox():
    from api.agents.router import detect_domain
    assert detect_domain("restart proxmox vm 101") == "proxmox"


def test_detect_domain_unknown_defaults_general():
    from api.agents.router import detect_domain
    assert detect_domain("do something random") == "general"


def test_classify_build_intent():
    from api.agents.router import classify_task
    assert classify_task("create a skill to monitor nginx") == "build"


def test_classify_observe_intent():
    from api.agents.router import classify_task
    result = classify_task("check swarm health")
    assert result in ("observe", "status")  # status is backward-compat alias


def test_filter_tools_execute_kafka_is_narrow(monkeypatch):
    from api.agents.router import filter_tools
    # Build a fake tools spec with many tools
    all_tools = [{"function": {"name": n}} for n in [
        "kafka_rolling_restart_safe", "service_upgrade", "skill_create",
        "pre_kafka_check", "kafka_broker_status", "plan_action",
    ]]
    kafka_tools = filter_tools(all_tools, "execute", domain="kafka")
    names = {t["function"]["name"] for t in kafka_tools}
    assert "kafka_rolling_restart_safe" in names
    assert "service_upgrade" not in names
    assert "skill_create" not in names
