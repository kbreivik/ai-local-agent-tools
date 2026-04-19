"""v2.35.16 — regression test for final_answer assignment from step history.

Before v2.35.16: ``last_reasoning`` was set whenever ``msg.content`` was
non-empty, so step-0 preamble ('I'll check ...') leaked into final_answer
when later steps emitted only tool_calls (op 07d326a1, fa_len=53).

After v2.35.16: ``compute_final_answer(steps)`` returns the LAST step's
content when that step finished with ``finish_reason='stop'``, else empty.
The agent loop mirrors this rule by only assigning ``last_reasoning =
msg.content`` when ``finish == 'stop'``. The v2.35.14 empty_completion
rescue handles the empty case via ``run_forced_synthesis``.
"""

from api.routers.agent import compute_final_answer


def test_all_tool_calls_yields_empty_final_answer():
    """When every step has finish_reason=tool_calls, final_answer is
    empty so the empty_completion rescue can fire."""
    steps = [
        {"content": "I'll check the UniFi status",
         "finish_reason": "tool_calls",
         "tool_calls": [{"id": "1", "function": {"name": "unifi_network_status"}}]},
        {"content": "",
         "finish_reason": "tool_calls",
         "tool_calls": [{"id": "2", "function": {"name": "result_fetch"}}]},
        {"content": "",
         "finish_reason": "tool_calls",
         "tool_calls": [{"id": "3", "function": {"name": "audit_log"}}]},
    ]
    result = compute_final_answer(steps)
    assert result == ""


def test_last_step_stop_content_becomes_final_answer():
    """When the last step has finish_reason=stop with content, that
    content is final_answer (no preamble leakage)."""
    steps = [
        {"content": "I'll check the UniFi status",
         "finish_reason": "tool_calls",
         "tool_calls": [{"id": "1", "function": {"name": "unifi_network_status"}}]},
        {"content": "STATUS: HEALTHY. 39 clients connected, all APs online.",
         "finish_reason": "stop",
         "tool_calls": []},
    ]
    result = compute_final_answer(steps)
    assert result == "STATUS: HEALTHY. 39 clients connected, all APs online."
    assert "I'll check" not in result  # no preamble leakage


def test_middle_step_content_not_aggregated():
    """Text from middle steps must not leak into final_answer."""
    steps = [
        {"content": "Let me gather the data first",
         "finish_reason": "tool_calls", "tool_calls": [{"id": "1"}]},
        {"content": "Now I have the results",
         "finish_reason": "tool_calls", "tool_calls": [{"id": "2"}]},
        {"content": "Summary: all green.",
         "finish_reason": "stop", "tool_calls": []},
    ]
    result = compute_final_answer(steps)
    assert result == "Summary: all green."
    assert "Let me gather" not in result
    assert "Now I have" not in result


def test_empty_steps_returns_empty_string():
    """Defensive: empty step list returns empty string."""
    assert compute_final_answer([]) == ""


def test_last_step_stop_with_empty_content_returns_empty():
    """Stop step with empty content returns '' so rescue can fire."""
    steps = [
        {"content": "I'll check the status",
         "finish_reason": "tool_calls", "tool_calls": [{"id": "1"}]},
        {"content": "",
         "finish_reason": "stop",
         "tool_calls": []},
    ]
    assert compute_final_answer(steps) == ""


def test_last_step_stop_with_whitespace_only_content_returns_empty():
    """Whitespace-only content on stop step strips to '' — rescue fires."""
    steps = [
        {"content": "   \n\t  ",
         "finish_reason": "stop",
         "tool_calls": []},
    ]
    assert compute_final_answer(steps) == ""


def test_finish_reason_length_treated_as_non_stop():
    """finish_reason='length' (token-budget exhaustion) is not 'stop' —
    return empty so the rescue path can produce a proper synthesis
    instead of accepting a truncated mid-thought as final_answer."""
    steps = [
        {"content": "I'll check the status and report back with details about",
         "finish_reason": "length",
         "tool_calls": []},
    ]
    assert compute_final_answer(steps) == ""


def test_missing_finish_reason_returns_empty():
    """Defensive: step without finish_reason key returns empty."""
    steps = [
        {"content": "Some content"},
    ]
    assert compute_final_answer(steps) == ""


def test_non_dict_step_returns_empty():
    """Defensive: malformed last step (non-dict) returns empty."""
    assert compute_final_answer([None]) == ""
    assert compute_final_answer(["not a dict"]) == ""


def test_strips_surrounding_whitespace():
    """Stop-step content is stripped of leading/trailing whitespace."""
    steps = [
        {"content": "  STATUS: HEALTHY. All systems nominal.  \n",
         "finish_reason": "stop",
         "tool_calls": []},
    ]
    assert compute_final_answer(steps) == "STATUS: HEALTHY. All systems nominal."
