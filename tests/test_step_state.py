"""Tests for api/agents/step_state.py — StepState dataclass contract.

v2.42.1: ensures the accumulator dataclass that drives the v2.41.x
agent.py split has correct defaults, isolation guarantees, and a
to_result_dict() that matches what _run_single_agent_step returned.
"""
from __future__ import annotations


def _make_state(**kwargs):
    from api.agents.step_state import StepState
    return StepState(
        session_id=kwargs.get("session_id", "sess-test"),
        operation_id=kwargs.get("operation_id", "op-test"),
        agent_type=kwargs.get("agent_type", "observe"),
        task=kwargs.get("task", "check kafka status"),
        **{k: v for k, v in kwargs.items()
           if k not in ("session_id", "operation_id", "agent_type", "task")},
    )


# ── field defaults ────────────────────────────────────────────────────────────

def test_default_final_status():
    state = _make_state()
    assert state.final_status == "completed"


def test_default_substantive_tool_calls():
    state = _make_state()
    assert state.substantive_tool_calls == 0


def test_default_halluc_guard_attempts():
    state = _make_state()
    assert state.halluc_guard_attempts == 0
    assert state.halluc_guard_max == 3


def test_default_fabrication_threshold():
    state = _make_state()
    assert state.fabrication_score_threshold == 0.5
    assert state.fabrication_min_cites == 3


def test_default_last_reasoning_empty():
    state = _make_state()
    assert state.last_reasoning == ""


def test_default_empty_completion_synth_done_false():
    state = _make_state()
    assert state.empty_completion_synth_done is False


# ── mutable default isolation ─────────────────────────────────────────────────

def test_tools_used_names_isolated():
    a = _make_state()
    b = _make_state()
    a.tools_used_names.append("kafka_broker_status")
    assert b.tools_used_names == []


def test_run_facts_isolated():
    a = _make_state()
    b = _make_state()
    a.run_facts["prod.kafka.broker.1.host"] = {"value": "10.0.0.1"}
    assert "prod.kafka.broker.1.host" not in b.run_facts


def test_zero_streaks_isolated():
    a = _make_state()
    b = _make_state()
    a.zero_streaks["elastic_search_logs"] = 3
    assert b.zero_streaks == {}


def test_zero_pivot_fired_isolated():
    a = _make_state()
    b = _make_state()
    a.zero_pivot_fired.add("elastic_search_logs")
    assert b.zero_pivot_fired == set()


# ── to_result_dict ─────────────────────────────────────────────────────────────

def test_to_result_dict_keys():
    """to_result_dict must return the exact keys the old return dict had."""
    state = _make_state()
    state.steps_taken = 5
    result = state.to_result_dict()
    expected_keys = {
        "output",
        "tools_used",
        "substantive_tool_calls",
        "tool_history",
        "final_status",
        "positive_signals",
        "negative_signals",
        "steps_taken",
        "prompt_tokens",
        "completion_tokens",
        "run_facts",
        "fabrication_detected",
        "render_tool_calls",
    }
    assert set(result.keys()) == expected_keys, (
        f"to_result_dict key mismatch. "
        f"Missing: {expected_keys - set(result.keys())} "
        f"Extra: {set(result.keys()) - expected_keys}"
    )


def test_to_result_dict_values_from_state():
    state = _make_state()
    state.last_reasoning = "Kafka is degraded."
    state.tools_used_names = ["kafka_broker_status", "kafka_topic_inspect"]
    state.substantive_tool_calls = 2
    state.final_status = "completed"
    state.positive_signals = 1
    state.negative_signals = 0
    state.total_prompt_tokens = 500
    state.total_completion_tokens = 200
    state.fabrication_detected_once = False
    state.render_tool_calls = 0
    state.steps_taken = 3

    r = state.to_result_dict()
    assert r["output"] == "Kafka is degraded."
    assert r["tools_used"] == ["kafka_broker_status", "kafka_topic_inspect"]
    assert r["substantive_tool_calls"] == 2
    assert r["final_status"] == "completed"
    assert r["steps_taken"] == 3
    assert r["prompt_tokens"] == 500
    assert r["completion_tokens"] == 200
    assert r["fabrication_detected"] is False


def test_to_result_dict_fabrication_detected_true():
    state = _make_state()
    state.fabrication_detected_once = True
    assert state.to_result_dict()["fabrication_detected"] is True


def test_to_result_dict_steps_taken_zero_default():
    """steps_taken must default to 0 (caller sets it before calling to_result_dict)."""
    state = _make_state()
    result = state.to_result_dict()
    assert result["steps_taken"] == 0


# ── identity fields ───────────────────────────────────────────────────────────

def test_identity_fields_preserved():
    state = _make_state(
        session_id="s-abc", operation_id="op-xyz",
        agent_type="investigate", task="why is broker 3 down"
    )
    assert state.session_id == "s-abc"
    assert state.operation_id == "op-xyz"
    assert state.agent_type == "investigate"
    assert state.task == "why is broker 3 down"


# ── plan_action_called init from plan_already_approved ────────────────────────

def test_plan_action_called_preset():
    """If plan_already_approved=True was passed at construction, plan_action_called
    must start True so the gate doesn't re-prompt for plan_action."""
    from api.agents.step_state import StepState
    state = StepState(
        session_id="s", operation_id="o",
        agent_type="execute", task="restart service",
        plan_action_called=True,
    )
    assert state.plan_action_called is True
