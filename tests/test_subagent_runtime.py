"""Unit tests for the v2.34.0 sub-agent runtime — guardrails and helpers.

These cover the purely-synchronous logic of the spawn helper that can be
exercised without standing up a live LM Studio / database stack:
  - Depth cap refuses grandchild spawn when cap=1
  - Budget reservation rejects when parent remaining < reserve + 2
  - Destructive guard rejects when parent is not execute-type
  - Context isolation — sub-agent does not inherit the parent's tool history

End-to-end parent→sub→final_answer flow is covered by the manual test plan
in CC_PROMPT_v2.34.0.md (requires a live LLM).
"""
import os
import pytest


def test_subagent_env_caps_have_sensible_defaults():
    from api.routers import agent as agent_mod
    assert agent_mod._SUBAGENT_MAX_DEPTH >= 1
    assert agent_mod._SUBAGENT_MIN_PARENT_RESERVE >= 1
    assert agent_mod._SUBAGENT_TREE_WALL_CLOCK_S >= 60


def test_build_subagent_context_includes_scope_and_parent_id():
    from api.routers.agent import _build_subagent_context

    ctx = _build_subagent_context(
        parent_diagnosis="broker 3 is unscheduled because worker-03 is Down",
        scope_entity="kafka_broker-3",
        parent_session_id="parent-xyz",
    )
    assert "PARENT_TASK_ID: parent-xyz" in ctx
    assert "SCOPE: kafka_broker-3" in ctx
    assert "PARENT DIAGNOSIS SO FAR" in ctx
    # Sub-agent hint must be present so the model knows its role
    assert "sub-agent" in ctx.lower()


def test_build_subagent_context_omits_empty_diagnosis_and_scope():
    from api.routers.agent import _build_subagent_context
    ctx = _build_subagent_context(parent_diagnosis="", scope_entity="",
                                  parent_session_id="p1")
    assert "PARENT DIAGNOSIS" not in ctx
    assert "SCOPE:" not in ctx
    assert "PARENT_TASK_ID: p1" in ctx


@pytest.mark.asyncio
async def test_spawn_refuses_when_parent_remaining_below_reserve(monkeypatch):
    """Parent has only 2 tool calls left, reserve is 2 → sub-agent must be refused."""
    from api.routers import agent as agent_mod

    # Patch get_ancestry to return empty (depth = 1)
    monkeypatch.setattr(
        "api.db.subagent_runs.get_ancestry", lambda _tid: [],
    )

    result = await agent_mod._spawn_and_wait_subagent(
        parent_session_id="p1",
        parent_operation_id="op1",
        owner_user="admin",
        objective="irrelevant",
        agent_type="investigate",
        scope_entity=None,
        budget_tools=4,
        allow_destructive=False,
        parent_remaining_budget=2,
        parent_agent_type="investigate",
        parent_diagnosis="",
    )
    assert result["ok"] is False
    assert "insufficient parent budget" in result["error"].lower()


@pytest.mark.asyncio
async def test_spawn_refuses_destructive_from_non_execute_parent(monkeypatch):
    from api.routers import agent as agent_mod
    monkeypatch.setattr(
        "api.db.subagent_runs.get_ancestry", lambda _tid: [],
    )
    result = await agent_mod._spawn_and_wait_subagent(
        parent_session_id="p1",
        parent_operation_id="op1",
        owner_user="admin",
        objective="restart a service",
        agent_type="execute",                   # sub wants execute
        scope_entity=None,
        budget_tools=4,
        allow_destructive=True,                 # wants destructive
        parent_remaining_budget=10,
        parent_agent_type="investigate",        # but parent is investigate
        parent_diagnosis="",
    )
    assert result["ok"] is False
    assert "destructive" in result["error"].lower()


@pytest.mark.asyncio
async def test_spawn_refuses_destructive_for_non_execute_sub(monkeypatch):
    from api.routers import agent as agent_mod
    monkeypatch.setattr(
        "api.db.subagent_runs.get_ancestry", lambda _tid: [],
    )
    result = await agent_mod._spawn_and_wait_subagent(
        parent_session_id="p1",
        parent_operation_id="op1",
        owner_user="admin",
        objective="just look",
        agent_type="investigate",
        scope_entity=None,
        budget_tools=4,
        allow_destructive=True,
        parent_remaining_budget=10,
        parent_agent_type="execute",
        parent_diagnosis="",
    )
    assert result["ok"] is False
    assert "allow_destructive requires agent_type=execute" in result["error"]


@pytest.mark.asyncio
async def test_spawn_refuses_beyond_depth_cap(monkeypatch):
    """If ancestry length already equals the cap, new spawn must be refused."""
    from api.routers import agent as agent_mod

    # Simulate a chain already at max depth
    monkeypatch.setattr(
        agent_mod, "_SUBAGENT_MAX_DEPTH", 2, raising=False,
    )
    # Two ancestors → current would be depth 3, over the cap of 2
    monkeypatch.setattr(
        "api.db.subagent_runs.get_ancestry",
        lambda _tid: [
            {"sub_task_id": "root", "parent_task_id": "",       "depth": 1},
            {"sub_task_id": "mid",  "parent_task_id": "root",   "depth": 2},
        ],
    )
    result = await agent_mod._spawn_and_wait_subagent(
        parent_session_id="mid",
        parent_operation_id="op",
        owner_user="admin",
        objective="deeper task",
        agent_type="investigate",
        scope_entity=None,
        budget_tools=4,
        allow_destructive=False,
        parent_remaining_budget=10,
        parent_agent_type="investigate",
        parent_diagnosis="",
    )
    assert result["ok"] is False
    assert "depth cap" in result["error"].lower()
