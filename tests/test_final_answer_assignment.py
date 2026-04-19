"""v2.35.17 — regression test for final_answer assignment from step history.

Before v2.35.17: final_answer accepted content from any step,
including steps that emitted tool_calls. That made pre-action
reasoning ("I'll check the UniFi...") leak into final_answer.

After v2.35.17: final_answer is the content of the last step that
finished with 'stop' and no tool_calls. Any other exit yields empty
final_answer so the empty_completion rescue can produce a proper
synthesis.
"""
from __future__ import annotations


def _compute_final_answer(steps):
    """Reference implementation of the v2.35.17 rule for isolated testing.
    Mirrors api.routers.agent.compute_final_answer over the
    response_raw shape (full OpenAI chat.completions response object)
    rather than the flattened {content, finish_reason, tool_calls}
    shape used by the production helper. Both shapes apply the same
    rule: last step with finish_reason='stop' AND no tool_calls wins.
    """
    final_answer = ""
    for step in reversed(steps or []):
        resp = step.get("response_raw") or step.get("response") or {}
        choice = (resp.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        fin = choice.get("finish_reason")
        has_tool_calls = bool(msg.get("tool_calls"))
        content = (msg.get("content") or "").strip()
        if fin == "stop" and not has_tool_calls and content:
            final_answer = content
            break
    return final_answer


def _mk_step(content: str, finish_reason: str, tool_calls=None) -> dict:
    return {
        "response_raw": {
            "choices": [{
                "finish_reason": finish_reason,
                "message": {
                    "content": content,
                    "tool_calls": tool_calls or [],
                },
            }],
        },
    }


def test_preamble_with_tool_call_rejected():
    """Regression for op 07d326a1 — step 0 content with tool_calls
    must NOT become final_answer."""
    steps = [
        _mk_step("I'll check the UniFi status",
                 finish_reason="tool_calls",
                 tool_calls=[{"id": "1", "function": {"name": "unifi_network_status"}}]),
        _mk_step("", finish_reason="tool_calls",
                 tool_calls=[{"id": "2"}]),
        _mk_step("", finish_reason="tool_calls",
                 tool_calls=[{"id": "3"}]),
    ]
    assert _compute_final_answer(steps) == ""


def test_stop_no_tool_calls_content_wins():
    """Natural synthesis on the last step is the final_answer."""
    steps = [
        _mk_step("I'll check",
                 finish_reason="tool_calls",
                 tool_calls=[{"id": "1"}]),
        _mk_step("STATUS: HEALTHY. 39 clients connected.",
                 finish_reason="stop",
                 tool_calls=[]),
    ]
    assert _compute_final_answer(steps) == "STATUS: HEALTHY. 39 clients connected."


def test_reverse_traversal_picks_most_recent_synthesis():
    """If somehow two synthesis steps exist, the last one wins."""
    steps = [
        _mk_step("First synthesis.",
                 finish_reason="stop", tool_calls=[]),
        _mk_step("",
                 finish_reason="tool_calls",
                 tool_calls=[{"id": "1"}]),
        _mk_step("Second synthesis.",
                 finish_reason="stop", tool_calls=[]),
    ]
    assert _compute_final_answer(steps) == "Second synthesis."


def test_length_finish_reason_rejected():
    """finish_reason='length' is a truncation error, not a synthesis."""
    steps = [
        _mk_step("Answer cut off mid-sent",
                 finish_reason="length", tool_calls=[]),
    ]
    assert _compute_final_answer(steps) == ""


def test_content_filter_finish_reason_rejected():
    """finish_reason='content_filter' means blocked, not a synthesis."""
    steps = [
        _mk_step("",
                 finish_reason="content_filter", tool_calls=[]),
    ]
    assert _compute_final_answer(steps) == ""


def test_stop_with_tool_calls_rejected():
    """Edge case: 'stop' finish with tool_calls present (rare but
    possible) — still pre-action per semantics."""
    steps = [
        _mk_step("Let me verify this finding.",
                 finish_reason="stop",
                 tool_calls=[{"id": "1"}]),
    ]
    assert _compute_final_answer(steps) == ""


def test_no_steps_yields_empty():
    assert _compute_final_answer([]) == ""
    assert _compute_final_answer(None) == ""


def test_whitespace_only_content_rejected():
    """Must strip and check truthiness."""
    steps = [
        _mk_step("   \n  \t ",
                 finish_reason="stop", tool_calls=[]),
    ]
    assert _compute_final_answer(steps) == ""


# ── Production helper coverage (api.routers.agent.compute_final_answer) ──
# The production helper consumes the flattened shape used by the agent
# loop's per-step accumulator. The rule is identical to the reference
# implementation above — these tests pin it against the same scenarios.

from api.routers.agent import compute_final_answer


def test_production_preamble_with_tool_call_rejected():
    steps = [
        {"content": "I'll check the UniFi status",
         "finish_reason": "tool_calls",
         "tool_calls": [{"id": "1", "function": {"name": "unifi_network_status"}}]},
        {"content": "",
         "finish_reason": "tool_calls",
         "tool_calls": [{"id": "2"}]},
    ]
    assert compute_final_answer(steps) == ""


def test_production_stop_with_tool_calls_rejected():
    """v2.35.17 closes the v2.35.16 hole: stop+tool_calls is still
    pre-action reasoning, not a synthesis."""
    steps = [
        {"content": "Let me verify this finding.",
         "finish_reason": "stop",
         "tool_calls": [{"id": "1"}]},
    ]
    assert compute_final_answer(steps) == ""


def test_production_reverse_traversal_picks_most_recent():
    steps = [
        {"content": "First synthesis.",
         "finish_reason": "stop", "tool_calls": []},
        {"content": "",
         "finish_reason": "tool_calls", "tool_calls": [{"id": "1"}]},
        {"content": "Second synthesis.",
         "finish_reason": "stop", "tool_calls": []},
    ]
    assert compute_final_answer(steps) == "Second synthesis."


def test_production_stop_no_tool_calls_wins():
    steps = [
        {"content": "I'll check",
         "finish_reason": "tool_calls", "tool_calls": [{"id": "1"}]},
        {"content": "STATUS: HEALTHY. 39 clients connected.",
         "finish_reason": "stop", "tool_calls": []},
    ]
    assert compute_final_answer(steps) == "STATUS: HEALTHY. 39 clients connected."


def test_production_no_qualifying_step_returns_empty_for_rescue():
    """All-tool_calls history → '' so empty_completion rescue fires."""
    steps = [
        {"content": "preamble", "finish_reason": "tool_calls",
         "tool_calls": [{"id": "1"}]},
        {"content": "", "finish_reason": "tool_calls",
         "tool_calls": [{"id": "2"}]},
    ]
    assert compute_final_answer(steps) == ""
