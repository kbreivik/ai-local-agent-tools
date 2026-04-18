"""v2.34.15 budget truncation behaviour.

The v2.34.14 trace endpoint caught investigate agents running 17 tools
with a budget of 16. The step-level `len(tools_used_names) >= _tool_budget`
check stops the NEXT step from entering, but it did not stop the CURRENT
step's batch from overflowing cap.

This module covers the pure truncation logic in isolation (no FastAPI,
no LLM). We replicate the small computation used by the harness and
verify the kept/dropped split.
"""
from types import SimpleNamespace


def _truncate(proposed, tool_budget, already_used):
    """Pure mirror of the truncation math in api/routers/agent.py.

    Returns (kept, dropped, remaining_before, nudge_kind).
    ``nudge_kind`` is 'exhausted' | 'truncated' | 'none'.
    """
    remaining = tool_budget - already_used
    if remaining <= 0:
        return [], list(proposed), remaining, "exhausted"
    if len(proposed) > remaining:
        return list(proposed[:remaining]), list(proposed[remaining:]), remaining, "truncated"
    return list(proposed), [], remaining, "none"


def _mk(names):
    return [SimpleNamespace(function=SimpleNamespace(name=n)) for n in names]


class TestBudgetTruncation:
    def test_truncate_drops_overflow_in_mid_run(self):
        # Parent at 15/16, model proposes 3 tools.
        proposed = _mk(["tool_a", "tool_b", "tool_c"])
        kept, dropped, remaining, kind = _truncate(proposed, 16, 15)
        assert remaining == 1
        assert [t.function.name for t in kept] == ["tool_a"]
        assert [t.function.name for t in dropped] == ["tool_b", "tool_c"]
        assert kind == "truncated"

    def test_exhausted_drops_entire_batch(self):
        # Parent already at 16/16 (the nightmare case). Batch of 2 → drop all.
        proposed = _mk(["tool_a", "tool_b"])
        kept, dropped, remaining, kind = _truncate(proposed, 16, 16)
        assert remaining == 0
        assert kept == []
        assert [t.function.name for t in dropped] == ["tool_a", "tool_b"]
        assert kind == "exhausted"

    def test_within_budget_passthrough(self):
        # 3 tools proposed with plenty of budget → no truncation.
        proposed = _mk(["tool_a", "tool_b", "tool_c"])
        kept, dropped, remaining, kind = _truncate(proposed, 16, 5)
        assert remaining == 11
        assert [t.function.name for t in kept] == ["tool_a", "tool_b", "tool_c"]
        assert dropped == []
        assert kind == "none"

    def test_exact_fit_keeps_all(self):
        # Boundary case: remaining == len(proposed).
        proposed = _mk(["a", "b"])
        kept, dropped, remaining, kind = _truncate(proposed, 16, 14)
        assert remaining == 2
        assert [t.function.name for t in kept] == ["a", "b"]
        assert dropped == []
        assert kind == "none"


class TestBudgetTruncationMetric:
    """Prometheus counter must be importable even without prometheus runtime."""

    def test_counter_label_values(self):
        from api.metrics import BUDGET_TRUNCATE_COUNTER
        # Must accept the agent_type label without raising.
        BUDGET_TRUNCATE_COUNTER.labels(agent_type="research").inc(0)
        BUDGET_TRUNCATE_COUNTER.labels(agent_type="execute").inc(0)
