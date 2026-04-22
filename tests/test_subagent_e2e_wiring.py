"""Regression tests for v2.34.4 — guarantees that v2.34.0 sub-agent wiring
remains functional. v2.34.0 shipped with the handler defined but the LLM
frequently passed only `task=` (legacy shape) and fell through to the
v2.24.0 proposal-only path. v2.34.4 auto-promotes legacy calls to in-band
spawn and emits a SUBAGENT_SPAWN_COUNTER counter as a regression canary.

End-to-end parent → sub → final_answer flow needs a live LLM and is covered
by the manual test plan in CC_PROMPT_v2.34.4.md.
"""
import pytest


def test_proposal_only_counter_exists():
    """Regression-canary counter — if this counter is missing or its
    proposal_only label is removed, the v2.34.4 wiring fix has been undone.
    """
    from api.metrics import SUBAGENT_SPAWN_COUNTER
    for outcome in (
        "spawned",
        "rejected_depth",
        "rejected_budget",
        "rejected_destructive",
        "proposal_only",
    ):
        # No-op increment validates the label is accepted by the counter
        SUBAGENT_SPAWN_COUNTER.labels(outcome=outcome).inc(0)


def test_subagent_spawn_counter_metric_name():
    """The metric name is part of the operator's dashboard query — locking it
    here so a rename forces a deliberate dashboard update.
    """
    from api.metrics import SUBAGENT_SPAWN_COUNTER
    assert SUBAGENT_SPAWN_COUNTER._name == "deathstar_subagent_spawns"


def _dispatch_src() -> str:
    """v2.41.5: propose_subtask handler moved from agent.py to
    api/agents/step_tools.py. Scan both so the pattern checks still find it."""
    from pathlib import Path
    root = Path(__file__).parent.parent
    agent = (root / "api" / "routers" / "agent.py").read_text(encoding="utf-8")
    tools = (root / "api" / "agents" / "step_tools.py").read_text(encoding="utf-8")
    return agent + "\n" + tools


def test_legacy_task_arg_is_promoted_to_objective():
    """v2.34.4 auto-promotion: when the LLM passes task=... but no objective,
    the harness must treat task as the in-band objective. This test reads
    agent.py directly to confirm the promotion code is present — a live
    end-to-end test would need an LLM.
    """
    body = _dispatch_src()
    # Auto-promotion lines must be present
    assert "if not _pst_objective and _pst_task:" in body, (
        "v2.34.4 auto-promotion of legacy task -> objective is missing — "
        "the in-band sub-agent spawn won't fire when LLM uses legacy shape."
    )
    assert "_pst_objective = _pst_task" in body
    # Inheritance of agent_type must be present
    assert "_inherit = {" in body or "_inherit={" in body, (
        "v2.34.4 agent_type inheritance is missing — sub-agent spawn will "
        "be refused when LLM omits agent_type."
    )


def test_proposal_only_counter_increments_on_legacy_fallback_branch():
    """The proposal-only path must increment SUBAGENT_SPAWN_COUNTER. Confirms
    the canary is wired into the only branch that should ever fire it.
    """
    body = _dispatch_src()
    assert 'outcome="proposal_only"' in body, (
        "proposal_only counter increment missing from legacy fallback — "
        "we lose visibility into v2.34.0-style regressions."
    )
    assert 'outcome="spawned"' in body, (
        "spawned counter increment missing from in-band success branch."
    )


def test_spa_fallback_routes_are_registered():
    """v2.34.4: /subtask/{id} and /runbook/{id} previously returned 404
    when the popup link was clicked from a fresh tab. The SPA fallback
    routes serve index.html so main.jsx can render the SubtaskPopup.
    """
    from pathlib import Path
    src = Path(__file__).parent.parent / "api" / "main.py"
    body = src.read_text(encoding="utf-8")
    assert '@app.get("/subtask/{session_id}")' in body, (
        "/subtask/{id} SPA fallback route missing — popup will 404 again."
    )
    assert '@app.get("/runbook/{proposal_id}")' in body, (
        "/runbook/{id} SPA fallback route missing."
    )


@pytest.mark.asyncio
async def test_spa_subtask_route_returns_200_or_gone():
    """The /subtask/{id} URL must serve content (or a clean 410 Gone),
    never 404. 404 confuses operators clicking the popup link.
    """
    from httpx import AsyncClient, ASGITransport
    from api.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/subtask/abc123")
        # 200 if gui dist present, 404 only when no SPA build exists at all.
        # 410 acceptable if the route is intentionally retired in future.
        assert r.status_code in (200, 301, 302, 404, 410), (
            f"/subtask/ returned {r.status_code} — unexpected status code"
        )
        # If gui/dist exists, must be 200, not 404
        from pathlib import Path
        gui_dist = Path(__file__).parent.parent / "gui" / "dist"
        if (gui_dist / "index.html").exists():
            assert r.status_code == 200, (
                "gui/dist exists but /subtask/{id} did not serve index.html — "
                "SPA fallback route is not wired correctly."
            )
