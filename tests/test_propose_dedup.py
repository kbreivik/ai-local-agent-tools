"""Unit tests for api/agents/propose_dedup.py (v2.34.16).

Covers the within-run dedup key, duplicate rejection, and stability across
argument-order permutations.
"""
from api.agents.propose_dedup import (
    ProposeState,
    handle_propose_subtask,
    make_parent_state,
    subtask_dedup_key,
)


def test_identical_proposal_rejected_on_second_call():
    state = make_parent_state()
    args = {
        "task": "Reschedule X",
        "executable_steps": ["docker service update --force X"],
        "manual_steps": [],
    }
    r1 = handle_propose_subtask(args, state, step_index=4)
    assert r1["status"] == "new"

    r2 = handle_propose_subtask(args, state, step_index=5)
    assert r2["status"] == "duplicate_proposal"
    assert r2["key"] == r1["key"]
    assert "already proposed" in r2["harness_message"].lower()
    # Four next-step options mentioned by letter
    msg = r2["harness_message"]
    for marker in ("(a)", "(b)", "(c)", "(d)"):
        assert marker in msg


def test_different_task_not_duplicate():
    state = make_parent_state()
    handle_propose_subtask(
        {"task": "A", "executable_steps": []}, state, step_index=4
    )
    r2 = handle_propose_subtask(
        {"task": "B", "executable_steps": []}, state, step_index=5
    )
    assert r2["status"] == "new"


def test_dedup_key_stable_across_arg_order():
    args_a = {
        "task": "X",
        "executable_steps": ["a", "b"],
        "manual_steps": [],
    }
    args_b = {
        "manual_steps": [],
        "executable_steps": ["a", "b"],
        "task": "X",
    }
    assert subtask_dedup_key(args_a) == subtask_dedup_key(args_b)


def test_objective_aliased_to_task_for_dedup():
    # `objective` arrives on the in-band-spawn shape; must be treated the
    # same as `task` so two calls with different shapes but the same intent
    # still collide.
    state = ProposeState()
    r1 = handle_propose_subtask(
        {"objective": "Reschedule X", "executable_steps": ["cmd"]},
        state, step_index=4,
    )
    r2 = handle_propose_subtask(
        {"task": "Reschedule X", "executable_steps": ["cmd"]},
        state, step_index=5,
    )
    assert r1["status"] == "new"
    assert r2["status"] == "duplicate_proposal"


def test_dedup_tracks_proposed_at_step():
    state = ProposeState()
    handle_propose_subtask(
        {"task": "T", "executable_steps": ["cmd"]}, state, step_index=7
    )
    r = handle_propose_subtask(
        {"task": "T", "executable_steps": ["cmd"]}, state, step_index=9
    )
    assert r["prior"]["proposed_at_step"] == 7
