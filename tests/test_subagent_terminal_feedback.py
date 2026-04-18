"""Terminal-feedback hook tests for api/agents/propose_dedup.py (v2.34.16).

Verifies that on_subagent_terminal queues a [harness] system message when the
sub-agent outcome is notable (escalated, failed, fabrication or halluc_guard
fired) and stays silent on benign completions.
"""
from api.agents.propose_dedup import (
    handle_propose_subtask,
    make_parent_state,
    on_subagent_terminal,
)


def _spawn(state, task="T", step=4):
    r = handle_propose_subtask(
        {"task": task, "executable_steps": ["cmd"]}, state, step_index=step
    )
    return r["key"]


def test_escalated_subagent_injects_harness_warning():
    state = make_parent_state()
    key = _spawn(state)
    msg = on_subagent_terminal(
        sub_op_id="sub-abc-12345",
        terminal_status="escalated",
        final_answer="EVIDENCE: container_tcp_probe(...) → ok",
        fabrication_detail={"score": 0.9, "fabricated": ["container_tcp_probe"]},
        halluc_guard_detail=None,
        state=state,
        dedup_key=key,
    )
    assert state.queued_harness_messages, "no harness message queued"
    assert msg == state.queued_harness_messages[-1]
    lowered = msg.lower()
    assert "escalated" in lowered
    assert "container_tcp_probe" in msg
    assert "do not repeat" in lowered


def test_failed_status_queues_message():
    state = make_parent_state()
    key = _spawn(state, task="T2", step=6)
    msg = on_subagent_terminal(
        sub_op_id="sub-xyz-99999",
        terminal_status="failed",
        final_answer="",
        fabrication_detail=None,
        halluc_guard_detail=None,
        state=state,
        dedup_key=key,
    )
    assert msg is not None
    assert "failed" in msg.lower()


def test_completed_without_issues_does_not_queue():
    state = make_parent_state()
    key = _spawn(state, task="T3", step=2)
    msg = on_subagent_terminal(
        sub_op_id="sub-happy-ok",
        terminal_status="completed",
        final_answer="All good.",
        fabrication_detail=None,
        halluc_guard_detail=None,
        state=state,
        dedup_key=key,
    )
    # completed + no warning conditions → nothing queued
    assert msg is None
    assert state.queued_harness_messages == []


def test_halluc_guard_fired_queues_message():
    state = make_parent_state()
    key = _spawn(state, task="T4", step=3)
    msg = on_subagent_terminal(
        sub_op_id="sub-hg-01234567",
        terminal_status="completed",
        final_answer="",
        fabrication_detail=None,
        halluc_guard_detail={"fired": True, "attempts": 2},
        state=state,
        dedup_key=key,
    )
    assert msg is not None
    assert "hallucination guard" in msg.lower()
    assert "2" in msg


def test_terminal_updates_dedup_map_status():
    state = make_parent_state()
    key = _spawn(state, step=1)
    on_subagent_terminal(
        sub_op_id="sub-1-abc",
        terminal_status="escalated",
        final_answer="",
        fabrication_detail=None,
        halluc_guard_detail=None,
        state=state,
        dedup_key=key,
    )
    entry = state.proposed_subtask_map[key]
    assert entry["status"] == "escalated"
    assert entry["sub_op_id"] == "sub-1-abc"
