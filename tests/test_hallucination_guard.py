"""Tests for v2.34.8 hallucination guard.

The v2.34.5 trace captured a sub-agent that emitted a confident final_answer
after a single `audit_log` call. Every infrastructure fact in the answer was
fabricated. The hallucination guard rejects a final_answer when the agent has
made fewer than MIN_SUBSTANTIVE_BY_TYPE real tool calls, forcing a retry.

These tests focus on the pure logic + source-level wiring. End-to-end parent
→ sub → final_answer with a live LLM is covered by the manual test plan in
CC_PROMPT_v2.34.8.md.
"""
from pathlib import Path


# ── META_TOOLS and MIN_SUBSTANTIVE_BY_TYPE constants ─────────────────────────

def test_meta_tools_contains_all_expected_entries():
    """Every tool named by the prompt as a "meta" (non-data-returning) tool
    must be in META_TOOLS. If this shrinks, the guard will over-count
    substantive calls and hallucinations slip through.
    """
    from api.agents import META_TOOLS
    expected = {
        "audit_log",
        "runbook_search",
        "memory_recall",
        "propose_subtask",
        "engram_activate",
        "plan_action",
    }
    assert expected.issubset(META_TOOLS), (
        f"META_TOOLS missing {expected - set(META_TOOLS)} — hallucination "
        "guard will over-count substantive calls."
    )


def test_min_substantive_table_covers_all_agent_types():
    """Every agent_type used by the harness must have a minimum configured,
    or the .get(agent_type, 1) default will silently lower the bar.
    """
    from api.agents import MIN_SUBSTANTIVE_BY_TYPE
    required_types = {"observe", "investigate", "execute", "build"}
    assert required_types.issubset(MIN_SUBSTANTIVE_BY_TYPE.keys())
    # Investigate and execute both need multi-step evidence before finalising.
    assert MIN_SUBSTANTIVE_BY_TYPE["investigate"] >= 2
    assert MIN_SUBSTANTIVE_BY_TYPE["execute"] >= 2
    assert MIN_SUBSTANTIVE_BY_TYPE["observe"] >= 1


def test_min_substantive_aliases_match_canonical():
    """Legacy aliases (status↔observe, research↔investigate, action↔execute)
    must carry the same minimum as their canonical name — the harness picks
    agent_type by either spelling.
    """
    from api.agents import MIN_SUBSTANTIVE_BY_TYPE as M
    assert M.get("status") == M.get("observe")
    assert M.get("research") == M.get("investigate")
    assert M.get("action") == M.get("execute")


# ── agent.py wiring ──────────────────────────────────────────────────────────

def _agent_src() -> str:
    # v2.41.2: guard logic extracted into api/agents/step_guard.py — return
    # both files concatenated so source-scan assertions still find the markers.
    root = Path(__file__).parent.parent
    router = (root / "api" / "routers" / "agent.py").read_text(encoding="utf-8")
    guard = (root / "api" / "agents" / "step_guard.py").read_text(encoding="utf-8")
    return router + "\n" + guard


def test_substantive_counter_increments_on_non_meta_tool():
    """The substantive counter must be incremented exactly where the loop
    records a tool call — next to `tools_used_names.append(fn_name)`.
    Without this, the guard can never fire.

    v2.41.0: counter lives on StepState as `substantive_tool_calls` and is
    mutated via `state.substantive_tool_calls += 1` in agent.py.
    """
    src = _agent_src()
    step_state_src = (
        Path(__file__).parent.parent / "api" / "agents" / "step_state.py"
    ).read_text(encoding="utf-8")
    assert "substantive_tool_calls: int = 0" in step_state_src, (
        "substantive_tool_calls counter missing from StepState — "
        "the hallucination guard cannot distinguish meta from real tool calls."
    )
    assert "if fn_name not in META_TOOLS:" in src
    assert "state.substantive_tool_calls += 1" in src


def test_hallucination_guard_block_is_present():
    """The guard has to be inserted on the final_answer path so a confident
    but unsubstantiated final_answer gets rejected before it's broadcast.
    """
    src = _agent_src()
    # Key guard markers
    assert 'MIN_SUBSTANTIVE_BY_TYPE.get(agent_type' in src
    assert '"hallucination_block"' in src, (
        "WebSocket event type missing — GUI banner will never render."
    )
    assert "halluc-guard" in src
    # v2.34.14: guard now retries + fails loudly instead of the old
    # "fire once → accept with HARNESS WARNING" fallback.
    # v2.41.0: guard counter migrated from `_halluc_guard_attempts` local to
    # `state.halluc_guard_attempts` (StepState dataclass).
    assert "state.halluc_guard_attempts" in src
    assert "AGENT_HALLUC_GUARD_MAX_ATTEMPTS" in src
    assert "hallucination_guard_exhausted" in src


def test_guard_retries_then_fails_loudly():
    """v2.34.14: guard must retry up to N times before failing the task —
    never silently accept fabricated evidence.

    v2.41.0: guard state consolidated into StepState.
    """
    src = _agent_src()
    assert "state.halluc_guard_attempts += 1" in src
    assert "state.halluc_guard_max" in src
    # Ensure there is a branch that breaks the loop with failure status
    assert 'state.final_status = "failed"' in src


def test_hallucination_counter_is_exported():
    """The Prometheus counter must be importable — the dashboard query relies
    on the metric name being stable.
    """
    from api.metrics import HALLUCINATION_GUARD_COUNTER
    # Label no-op validates the cardinality is as specified
    HALLUCINATION_GUARD_COUNTER.labels(
        agent_type="observe", outcome="retried",
    ).inc(0)
    HALLUCINATION_GUARD_COUNTER.labels(
        agent_type="investigate", outcome="fallback_accepted",
    ).inc(0)
    assert HALLUCINATION_GUARD_COUNTER._name == (
        "deathstar_agent_hallucination_guards"
    )


def test_subagent_runs_captures_substantive_count():
    """subagent_runs must expose a substantive_tool_calls column and the
    record_completion function must accept and persist it. Lets us query
    post-hoc for likely-hallucinated sub-agents.
    """
    from inspect import signature
    from api.db.subagent_runs import record_completion
    sig = signature(record_completion)
    assert "substantive_tool_calls" in sig.parameters, (
        "record_completion missing substantive_tool_calls param — "
        "audit of likely-hallucinated sub-agents is impossible."
    )

    # DDL mentions the column
    from api.db import subagent_runs as sr_mod
    assert "substantive_tool_calls" in sr_mod._DDL


def test_spawn_and_wait_passes_substantive_count():
    """_spawn_and_wait_subagent computes and forwards the sub-agent's
    substantive-tool-call count into record_completion, so post-hoc audits
    can spot runs that produced a final_answer with zero real tools.
    """
    src = _agent_src()
    assert "sub_substantive" in src
    assert "substantive_tool_calls=sub_substantive" in src


# ── propose_subtask agent_type guidance ──────────────────────────────────────

def test_investigate_prompt_has_agent_type_selection_rules():
    """The investigate prompt must tell the LLM when to pick `investigate`
    over `observe` when proposing a sub-task. Missing this guidance is half
    of the v2.34.8 bug — the sub-agent was asked to "deep-dive" under
    agent_type="observe" and got an under-sized budget.
    """
    from api.agents.router import INVESTIGATE_PROMPT
    assert "CHOOSING agent_type FOR SUB-TASK" in INVESTIGATE_PROMPT
    assert "deep-dive" in INVESTIGATE_PROMPT.lower()
    # Each of the four agent types should be named with its verb list
    for agent_type in ("observe", "investigate", "execute", "build"):
        assert agent_type in INVESTIGATE_PROMPT, (
            f"agent_type={agent_type} missing from selection rules"
        )


# ── migration is registered ──────────────────────────────────────────────────

def test_migration_9_adds_substantive_column():
    """Migration v9 must add substantive_tool_calls — otherwise existing
    prod databases from v2.34.0..v2.34.7 won't get the new column.
    """
    from api.db.migrations import MIGRATIONS
    migration_9 = [m for m in MIGRATIONS if m[0] == 9]
    assert migration_9, "Migration v9 missing"
    _, description, stmts = migration_9[0]
    assert "substantive_tool_calls" in description
    combined = "\n".join(stmts)
    assert "ALTER TABLE subagent_runs" in combined
    assert "substantive_tool_calls" in combined
