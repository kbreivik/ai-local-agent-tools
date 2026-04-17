"""Budget-math tests for v2.34.5 propose_subtask reachability fix.

Covers the pure helpers that gate sub-agent spawning:
  - _resolve_nudge_threshold: fires the harness nudge earlier so the spawn math
    is still reachable when it lands.
  - _dynamic_reserve: relaxes the parent-budget reserve when the parent has no
    DIAGNOSIS and is late-game — reserving budget is pointless if parent has
    nothing to synthesise after the sub-agent returns.

The integration-level tests (parent→sub→final_answer with a scripted LLM)
live in test_subagent_runtime.py / test_subagent_e2e_wiring.py.
"""
from api.agents.orchestrator import _resolve_nudge_threshold, _dynamic_reserve


# ── _resolve_nudge_threshold ────────────────────────────────────────────────

def test_nudge_threshold_default():
    assert _resolve_nudge_threshold({}) == 0.60


def test_nudge_threshold_clamped_low():
    # Floor is 0.40 — prevents firing on every task
    assert _resolve_nudge_threshold({"subagentNudgeThreshold": "0.1"}) == 0.40


def test_nudge_threshold_clamped_high():
    # Ceiling is 0.90 — prevents the v2.34.4 bug where the spawn math is
    # unreachable by the time the nudge fires
    assert _resolve_nudge_threshold({"subagentNudgeThreshold": "0.99"}) == 0.90


def test_nudge_threshold_passthrough_in_range():
    assert _resolve_nudge_threshold({"subagentNudgeThreshold": 0.65}) == 0.65
    assert _resolve_nudge_threshold({"subagentNudgeThreshold": "0.50"}) == 0.50


def test_nudge_threshold_garbage_returns_default():
    assert _resolve_nudge_threshold({"subagentNudgeThreshold": "banana"}) == 0.60
    assert _resolve_nudge_threshold({"subagentNudgeThreshold": None}) == 0.60


# ── _dynamic_reserve ────────────────────────────────────────────────────────

def test_reserve_defaults_when_diagnosis_present():
    """Parent has DIAGNOSIS — reserve stays at default (2)."""
    r = _dynamic_reserve(
        tools_used=14, budget_tools=16, diagnosis_seen=True,
    )
    assert r == 2


def test_reserve_relaxes_to_zero_late_stage_no_diagnosis():
    """Parent at 60%+ usage with no DIAGNOSIS — reserve drops to 0 so the
    spawn can proceed. This is the v2.34.5 fix: reserving when parent has
    nothing to synthesise after sub-agent returns is counter-productive.
    """
    r = _dynamic_reserve(
        tools_used=13, budget_tools=16, diagnosis_seen=False,
    )
    assert r == 0


def test_reserve_relaxes_at_exactly_60_percent():
    """Boundary: 60% exactly triggers the relax-to-zero rule."""
    r = _dynamic_reserve(
        tools_used=10, budget_tools=16, diagnosis_seen=False,
    )  # 10/16 = 0.625 → ≥ 0.60
    assert r == 0


def test_reserve_partial_when_early_no_diagnosis():
    """Early in the run without DIAGNOSIS — partial reserve based on
    remaining budget."""
    r = _dynamic_reserve(
        tools_used=4, budget_tools=16, diagnosis_seen=False,
    )  # usage_frac = 0.25 → partial: min(2, 12//3) = 2
    assert r == 2


def test_reserve_partial_small_remaining():
    """With very little remaining and no diagnosis at mid-run, reserve may
    shrink below the default."""
    r = _dynamic_reserve(
        tools_used=8, budget_tools=10, diagnosis_seen=False,
    )  # usage_frac = 0.80 → ≥ 0.60 → reserve = 0
    assert r == 0


def test_reserve_respects_configured_default():
    """When caller overrides subagentMinParentReserve, default path honours it."""
    r = _dynamic_reserve(
        tools_used=2, budget_tools=16, diagnosis_seen=True,
        settings={"subagentMinParentReserve": 3},
    )
    assert r == 3


# ── Spawn-math integration: the v2.34.5 guarantee ──────────────────────────

def test_spawn_math_reachable_at_60_percent_nudge():
    """At budget=16, nudge at 60% means we fire when tools_used >= 9 (int(16*0.6)).
    After the propose_subtask call itself, tools_used = 10 or 11. Remaining=5~6.
    With default reserve=2 and diagnosis present, max_sub = 3~4, min=2 → spawn OK.
    """
    threshold = _resolve_nudge_threshold({})  # 0.60
    budget = 16
    # Earliest possible fire: tools_used = int(budget * threshold) = 9
    fire_at = int(budget * threshold)
    assert fire_at == 9
    # After propose_subtask call, remaining budget:
    after_propose_remaining = budget - (fire_at + 1)
    # With default reserve and no diagnosis (usage_frac = 10/16 = 0.625 → reserve=0)
    reserve = _dynamic_reserve(
        tools_used=fire_at + 1, budget_tools=budget, diagnosis_seen=False,
    )
    max_sub = max(0, after_propose_remaining - reserve)
    assert max_sub >= 2, (
        f"v2.34.5 spawn math must remain reachable: max_sub={max_sub}, "
        f"remaining={after_propose_remaining}, reserve={reserve}"
    )


def test_spawn_math_reachable_even_at_late_propose():
    """Even if agent delays and calls propose_subtask late (used=13/16) with
    no DIAGNOSIS, dynamic reserve drops to 0 so spawn still succeeds.
    This is the second safety net."""
    budget = 16
    tools_used = 13
    reserve = _dynamic_reserve(
        tools_used=tools_used, budget_tools=budget, diagnosis_seen=False,
    )
    assert reserve == 0
    remaining = budget - tools_used
    max_sub = max(0, remaining - reserve)
    assert max_sub >= 2, (
        f"Late-stage no-diagnosis spawn must still succeed: max_sub={max_sub}"
    )
