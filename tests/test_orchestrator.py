# tests/test_orchestrator.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from api.agents.orchestrator import build_step_plan, format_step_header, verdict_from_text


def test_single_observe_task_is_one_step():
    steps = build_step_plan("check swarm health")
    assert len(steps) == 1
    assert steps[0]["intent"] in ("observe", "status")


def test_build_task_is_one_step():
    steps = build_step_plan("create a skill to monitor nginx")
    assert len(steps) == 1
    assert steps[0]["intent"] == "build"


def test_execute_only_task_is_one_step():
    steps = build_step_plan("restart kafka broker 2")
    assert len(steps) == 1
    assert steps[0]["intent"] in ("execute", "action")
    assert steps[0]["domain"] == "kafka"


def test_verify_before_execute_is_two_steps():
    steps = build_step_plan("verify swarm is healthy then upgrade the nginx service")
    assert len(steps) == 2
    assert steps[0]["intent"] in ("observe", "status")
    assert steps[1]["intent"] in ("execute", "action")


def test_step_header_format():
    header = format_step_header(1, 2, "execute", "kafka")
    assert "1" in header and "2" in header
    assert "kafka" in header.lower() or "execute" in header.lower()


def test_verdict_from_text_healthy():
    v = verdict_from_text("All checks passed. System HEALTHY.")
    assert v["verdict"] == "GO"


def test_verdict_from_text_degraded():
    v = verdict_from_text("broker-2 is offline. Status: DEGRADED.")
    assert v["verdict"] in ("HALT", "ASK")


def test_v245_31_explicit_plan_skips_auto_precheck():
    """v2.45.31 — task mentioning plan_action explicitly should not get an
    auto-prepended observe step from the 'before' keyword."""
    from api.agents.orchestrator import build_step_plan
    task = (
        "perform a rolling restart of kafka brokers — use plan_action to "
        "propose the restart plan before executing kafka_rolling_restart_safe"
    )
    steps = build_step_plan(task)
    intents = [s["intent"] for s in steps]
    assert "observe" not in intents, (
        f"Expected no observe pre-step (explicit plan_action in task), "
        f"got {intents}"
    )
    assert intents[0] in ("execute", "action"), (
        f"Expected first step to be execute/action, got {intents}"
    )


def test_v245_31_check_keyword_still_triggers_precheck_when_no_plan():
    """v2.45.31 — the pre-check heuristic still fires when plan_action is
    NOT explicitly mentioned. Don't regress the original behaviour."""
    from api.agents.orchestrator import build_step_plan
    task = "verify kafka health then upgrade kafka-stack_kafka1"
    steps = build_step_plan(task)
    intents = [s["intent"] for s in steps]
    assert "observe" in intents, (
        f"Expected observe pre-step from 'verify' keyword, got {intents}"
    )
