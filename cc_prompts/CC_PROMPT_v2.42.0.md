# CC PROMPT — v2.42.0 — test(agents): test_gates.py — pure gate function tests

## What this does

`api/agents/gates.py` (v2.40.3) contains five pure functions extracted from
agent.py. They have zero tests. This prompt adds a focused test file covering
all five: `_is_preamble_only`, `_classify_terminal_final_answer`,
`compute_final_answer`, `_result_count`, `_should_disable_thinking`.

All tests are pure/fast — no DB, no network, no LLM. They can run in CI
on every push.

Version bump: 2.41.5 → 2.42.0.

---

## Change 1 — create `tests/test_gates.py`

```python
"""Tests for api/agents/gates.py — pure gate helpers.

v2.42.0: first coverage for functions extracted from agent.py in v2.40.3.
No DB, no network, no LLM required.
"""
from __future__ import annotations
import pytest


# ── _is_preamble_only ─────────────────────────────────────────────────────────

def test_preamble_only_flags_ill_start():
    from api.agents.gates import _is_preamble_only
    assert _is_preamble_only("I'll check the Kafka brokers now") is True
    assert _is_preamble_only("Let me look into this issue") is True
    assert _is_preamble_only("Sure, let me investigate") is True


def test_preamble_only_passes_verdict_text():
    from api.agents.gates import _is_preamble_only
    # Contains a verdict marker — not a preamble
    assert _is_preamble_only("Let me check. STATUS: all green") is False
    assert _is_preamble_only("I'll summarise. FINDINGS: broker 2 is down") is False


def test_preamble_only_passes_long_substantive_text():
    from api.agents.gates import _is_preamble_only
    long_text = "Let me check. " + "X" * 300 + "."
    # Long text ending with punctuation is substantive despite preamble start
    assert _is_preamble_only(long_text) is False


def test_preamble_only_flags_short_ellipsis():
    from api.agents.gates import _is_preamble_only
    assert _is_preamble_only("I'll investigate...") is True


def test_preamble_only_passes_normal_synthesis():
    from api.agents.gates import _is_preamble_only
    assert _is_preamble_only("Kafka broker-3 is offline. The ISR for hp1-logs is reduced to 1/3.") is False
    assert _is_preamble_only("") is False


# ── _classify_terminal_final_answer ──────────────────────────────────────────

def test_classify_empty():
    from api.agents.gates import _classify_terminal_final_answer
    assert _classify_terminal_final_answer("") == "empty_completion"
    assert _classify_terminal_final_answer("   ") == "empty_completion"
    assert _classify_terminal_final_answer(None) == "empty_completion"


def test_classify_too_short():
    from api.agents.gates import _classify_terminal_final_answer
    assert _classify_terminal_final_answer("looks ok") == "too_short_completion"
    assert _classify_terminal_final_answer("x" * 59) == "too_short_completion"


def test_classify_preamble():
    from api.agents.gates import _classify_terminal_final_answer
    result = _classify_terminal_final_answer("I'll check this and report back...")
    assert result == "preamble_only_completion"


def test_classify_returns_none_for_substantive():
    from api.agents.gates import _classify_terminal_final_answer
    text = "STATUS: Kafka cluster is degraded. Broker 3 is offline. ISR count is 1 for hp1-logs partition 0. Recommend rebooting worker-03 via Proxmox."
    assert _classify_terminal_final_answer(text) is None


# ── compute_final_answer ──────────────────────────────────────────────────────

def _mk_step(content, finish_reason, tool_calls=None):
    return {
        "finish_reason": finish_reason,
        "content": content,
        "tool_calls": tool_calls or [],
    }


def test_compute_picks_last_stop_no_tools():
    from api.agents.gates import compute_final_answer
    steps = [
        _mk_step("I'll check this", "tool_calls", tool_calls=[{"id": "1"}]),
        _mk_step("Kafka is degraded.", "stop"),
    ]
    assert compute_final_answer(steps) == "Kafka is degraded."


def test_compute_rejects_stop_with_tool_calls():
    from api.agents.gates import compute_final_answer
    steps = [
        _mk_step("pre-action reasoning", "stop", tool_calls=[{"id": "1"}]),
    ]
    assert compute_final_answer(steps) == ""


def test_compute_empty_steps():
    from api.agents.gates import compute_final_answer
    assert compute_final_answer([]) == ""
    assert compute_final_answer(None) == ""


def test_compute_prefers_last_over_first():
    from api.agents.gates import compute_final_answer
    steps = [
        _mk_step("First synthesis", "stop"),
        _mk_step("tool result", "tool_calls", tool_calls=[{"id": "x"}]),
        _mk_step("Better synthesis after more data.", "stop"),
    ]
    assert compute_final_answer(steps) == "Better synthesis after more data."


# ── _result_count ─────────────────────────────────────────────────────────────

def test_result_count_hits():
    from api.agents.gates import _result_count
    assert _result_count({"hits": [1, 2, 3]}) == 3
    assert _result_count({"hits": []}) == 0


def test_result_count_total():
    from api.agents.gates import _result_count
    assert _result_count({"total": 42}) == 42
    assert _result_count({"total": 0}) == 0


def test_result_count_summary_text():
    from api.agents.gates import _result_count
    assert _result_count({"summary": "Found 12 log entries"}) == 12
    assert _result_count({"message": "Found 0 results"}) == 0


def test_result_count_none_for_unknown():
    from api.agents.gates import _result_count
    assert _result_count({"status": "ok"}) is None
    assert _result_count({}) is None


# ── _should_disable_thinking ──────────────────────────────────────────────────

def test_disable_thinking_for_audit_log_only():
    from api.agents.gates import _should_disable_thinking
    # Step 2, previous step only called audit_log — skip thinking
    assert _should_disable_thinking(["audit_log"], step=2, max_steps=12) is True


def test_disable_thinking_false_for_data_tools():
    from api.agents.gates import _should_disable_thinking
    assert _should_disable_thinking(["kafka_broker_status"], step=2, max_steps=12) is False


def test_disable_thinking_false_for_step_1():
    from api.agents.gates import _should_disable_thinking
    # First step should always think
    assert _should_disable_thinking(["audit_log"], step=1, max_steps=12) is False


# ── constants completeness ────────────────────────────────────────────────────

def test_preamble_starters_nonempty():
    from api.agents.gates import _PREAMBLE_STARTERS
    assert len(_PREAMBLE_STARTERS) >= 5


def test_verdict_markers_nonempty():
    from api.agents.gates import _VERDICT_MARKERS
    assert "STATUS:" in _VERDICT_MARKERS or "STATUS:" in list(_VERDICT_MARKERS)
    assert "FINDINGS:" in _VERDICT_MARKERS or "FINDINGS:" in list(_VERDICT_MARKERS)
```

---

## Version bump

Update `VERSION`: `2.41.5` → `2.42.0`

---

## Commit

```
git add -A
git commit -m "test(agents): v2.42.0 test_gates.py — pure gate function coverage"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
