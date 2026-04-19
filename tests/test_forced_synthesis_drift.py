"""v2.35.10 regression — forced_synthesis must never persist XML drift."""
from __future__ import annotations

import pytest


def test_drift_detector_catches_tool_call_prefix():
    from api.agents.forced_synthesis import _is_drift
    drift, reason = _is_drift(
        "<tool_call>\n<function=vm_exec>\n<parameter=host>\nfoo</parameter>"
    )
    assert drift
    assert "tool_call" in reason or "parameter" in reason


def test_drift_detector_catches_function_prefix():
    from api.agents.forced_synthesis import _is_drift
    drift, reason = _is_drift("<function=foo>\n<parameter=x>1</parameter>")
    assert drift


def test_drift_detector_catches_json_fence_prefix():
    from api.agents.forced_synthesis import _is_drift
    drift, reason = _is_drift('```json\n{"tool": "foo", "args": {}}\n```')
    assert drift


def test_drift_detector_accepts_clean_prose():
    from api.agents.forced_synthesis import _is_drift
    drift, reason = _is_drift(
        "EVIDENCE:\n- kafka_broker_status returned 3 brokers online\n"
        "- service_placement confirmed kafka_broker-3 on worker-03\n\n"
        "ROOT CAUSE: Broker 3 has ISR mismatch.\n\n"
        "NEXT STEPS:\n1. Reboot worker-03 via Proxmox."
    )
    assert not drift, f"clean prose should not trigger drift, reason={reason!r}"


def test_drift_detector_accepts_angle_bracket_lt_gt_comparisons():
    """Prose containing '>' or '<' as comparison operators must not trigger."""
    from api.agents.forced_synthesis import _is_drift
    drift, _ = _is_drift(
        "The partition count was > 3 for all topics. ISR was < expected on broker 2."
    )
    assert not drift


def test_programmatic_fallback_names_only_backward_compat():
    """v2.35.10 callers passing only names still work."""
    from api.agents.forced_synthesis import _programmatic_fallback
    out = _programmatic_fallback(
        reason="budget_cap", tool_count=8, budget=8,
        actual_tool_names=["runbook_search", "vm_exec", "vm_exec",
                           "service_placement"],
    )
    assert "HARNESS FALLBACK" in out
    assert "EVIDENCE" in out
    assert "NEXT STEPS" in out
    assert "<tool_call" not in out
    assert "<function=" not in out
    # De-duplicated: 2 vm_exec -> 1 row
    assert out.count("vm_exec()") <= 1 or out.count("vm_exec(") == 1
    assert "runbook_search" in out
    assert "service_placement" in out


def test_programmatic_fallback_enriched_with_results():
    """v2.35.12 new: per-tool result snippet included when available."""
    from api.agents.forced_synthesis import _programmatic_fallback
    calls = [
        {"name": "swarm_node_status", "status": "ok",
         "result": "6 nodes Ready, leader manager-02"},
        {"name": "vm_exec", "status": "ok",
         "result": "/dev/sda1 42G used 120G avail"},
        {"name": "vm_exec", "status": "ok",
         "result": "/dev/sda1 second run same"},
        {"name": "service_placement", "status": "error",
         "result": "Unknown service: foo"},
    ]
    out = _programmatic_fallback(
        reason="budget_cap", tool_count=4, budget=8,
        actual_tool_calls=calls,
    )
    assert "swarm_node_status" in out
    assert "6 nodes Ready" in out  # snippet included
    assert "vm_exec" in out
    assert "42G used" in out
    # Deduplicated: only one vm_exec row
    assert out.count("vm_exec()") == 1 or out.count("vm_exec() status") == 1
    # Error row gets rendered too (best we have for a tool that only failed)
    assert "service_placement" in out
    assert "Unknown service" in out


def test_programmatic_fallback_snippet_truncation():
    """Results longer than 120 chars must be truncated with ellipsis."""
    from api.agents.forced_synthesis import _programmatic_fallback
    long_result = "X" * 500
    out = _programmatic_fallback(
        reason="budget_cap", tool_count=1, budget=8,
        actual_tool_calls=[{"name": "vm_exec", "status": "ok",
                            "result": long_result}],
    )
    # Must contain some X but not all 500 of them
    assert "XXX" in out
    assert "XXXXXXXXXX" * 50 not in out
    # Ellipsis marker
    assert "..." in out


def test_programmatic_fallback_dict_result_serialised():
    """Dict results should be JSON-stringified (not `{...object address...}`)."""
    from api.agents.forced_synthesis import _programmatic_fallback
    out = _programmatic_fallback(
        reason="budget_cap", tool_count=1, budget=8,
        actual_tool_calls=[{"name": "kafka_broker_status", "status": "ok",
                            "result": {"brokers": 3, "isr": "[1,2,3]"}}],
    )
    assert "kafka_broker_status" in out
    assert "brokers" in out
    assert "3" in out


def test_strip_xml_drift_from_messages_drops_drifted_entirely():
    """v2.35.12: drifted messages must be REMOVED, not sentinel-replaced."""
    from api.agents.forced_synthesis import (
        _strip_xml_drift_from_messages, _DRIFT_STRIPPED_PLACEHOLDER,
    )
    msgs = [
        {"role": "system", "content": "you are helpful"},
        {"role": "user", "content": "do something"},
        {"role": "assistant", "content": "Sure, I'll check."},
        {"role": "assistant", "content": "<tool_call>\n<function=foo>\n</tool_call>"},
        {"role": "tool", "tool_call_id": "x", "content": "{}"},
        {"role": "assistant", "content": "Results look good."},
    ]
    out = _strip_xml_drift_from_messages(msgs)
    # Drifted assistant PLUS its orphaned tool response are both gone
    assert len(out) == len(msgs) - 2
    assert all(_DRIFT_STRIPPED_PLACEHOLDER not in str(m.get("content", ""))
               for m in out)
    # Non-drift messages preserved
    assert out[0]["content"] == "you are helpful"
    assert out[2]["content"] == "Sure, I'll check."
    assert out[3]["content"] == "Results look good."


def test_strip_xml_drift_preserves_tool_responses_to_valid_calls():
    """Tool responses that follow a non-drift assistant must NOT be dropped."""
    from api.agents.forced_synthesis import _strip_xml_drift_from_messages
    msgs = [
        {"role": "user", "content": "query"},
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "1", "function": {"name": "foo"}}]},
        {"role": "tool", "tool_call_id": "1", "content": "result"},
        {"role": "assistant", "content": "done"},
    ]
    out = _strip_xml_drift_from_messages(msgs)
    # None of these drift — all preserved
    assert len(out) == len(msgs)


def test_run_forced_synthesis_falls_back_on_drift(monkeypatch):
    """Integration: if the mock LLM returns XML drift both times, the
    programmatic fallback must be returned - never the raw drift."""
    from api.agents import forced_synthesis as fs

    class _FakeMsg:
        def __init__(self, content): self.content = content
    class _FakeChoice:
        def __init__(self, content): self.message = _FakeMsg(content)
    class _FakeResp:
        def __init__(self, content):
            self.choices = [_FakeChoice(content)]
        def model_dump(self):
            return {"choices": [{"message": {"content": self.choices[0].message.content}}]}

    class _FakeCompletions:
        def __init__(self):
            self.call_count = 0
        def create(self, **kw):
            self.call_count += 1
            return _FakeResp("<tool_call>\n<function=vm_exec>\n</tool_call>")

    class _FakeClient:
        def __init__(self):
            self.chat = type("X", (), {"completions": _FakeCompletions()})()

    client = _FakeClient()
    text, harness, raw = fs.run_forced_synthesis(
        client=client, model="fake", messages=[{"role": "user", "content": "x"}],
        agent_type="observe", reason="budget_cap",
        tool_count=8, budget=8,
        actual_tool_names=["vm_exec", "swarm_node_status"],
    )
    # Must be 2 attempts made
    assert client.chat.completions.call_count == 2
    # Must NOT contain XML drift
    assert "<tool_call>" not in text
    assert "<function=" not in text
    # Must be the programmatic fallback
    assert "HARNESS FALLBACK" in text
    assert "vm_exec" in text    # tool list preserved


def test_placeholder_echo_treated_as_drift():
    """The unique placeholder must be detected as drift so the fallback fires."""
    from api.agents.forced_synthesis import _is_drift, _DRIFT_STRIPPED_PLACEHOLDER
    drift, reason = _is_drift(_DRIFT_STRIPPED_PLACEHOLDER)
    assert drift
    assert reason == "placeholder_echo"


def test_placeholder_echo_with_small_wrapper_still_drift():
    """Model might wrap the placeholder in a few words — still drift."""
    from api.agents.forced_synthesis import _is_drift, _DRIFT_STRIPPED_PLACEHOLDER
    text = f"Sure: {_DRIFT_STRIPPED_PLACEHOLDER}"
    drift, reason = _is_drift(text)
    # Placeholder is majority content -> drift
    assert drift
    assert reason == "placeholder_echo"


def test_placeholder_substring_in_long_prose_not_drift():
    """A long clean synthesis that happens to mention the placeholder
    name (e.g. in a docstring quote) must NOT trigger drift — the
    majority-content check prevents this false positive."""
    from api.agents.forced_synthesis import _is_drift, _DRIFT_STRIPPED_PLACEHOLDER
    # 2000 chars of clean prose + one mention of the placeholder
    text = (
        "EVIDENCE:\n- Tool A returned foo\n- Tool B returned bar\n" * 50
        + f"\n\n(debug note: context included the sentinel "
        f"{_DRIFT_STRIPPED_PLACEHOLDER} from stripping)\n"
    )
    drift, reason = _is_drift(text)
    assert not drift, (
        f"placeholder appearing in long prose should not trigger drift; "
        f"reason={reason!r}, length={len(text)}"
    )


def test_run_forced_synthesis_falls_back_on_placeholder_echo(monkeypatch):
    """Integration: if attempt 1 drifts via XML and attempt 2 echoes the
    placeholder, the programmatic fallback must fire — the placeholder
    MUST NOT leak into final_answer."""
    from api.agents import forced_synthesis as fs

    class _FakeMsg:
        def __init__(self, content): self.content = content
    class _FakeChoice:
        def __init__(self, content): self.message = _FakeMsg(content)
    class _FakeResp:
        def __init__(self, content):
            self.choices = [_FakeChoice(content)]
        def model_dump(self):
            return {"choices": [{"message": {"content": self.choices[0].message.content}}]}

    class _FakeCompletions:
        def __init__(self):
            self.call_count = 0
            self.responses = [
                "<tool_call>\n<function=vm_exec>\n</tool_call>",   # attempt 1 drift
                fs._DRIFT_STRIPPED_PLACEHOLDER,                    # attempt 2 echo
            ]
        def create(self, **kw):
            i = self.call_count
            self.call_count += 1
            return _FakeResp(self.responses[min(i, len(self.responses) - 1)])

    class _FakeClient:
        def __init__(self):
            self.chat = type("X", (), {"completions": _FakeCompletions()})()

    client = _FakeClient()
    text, harness, raw = fs.run_forced_synthesis(
        client=client, model="fake",
        messages=[{"role": "user", "content": "x"}],
        agent_type="observe", reason="budget_cap",
        tool_count=8, budget=8,
        actual_tool_names=["vm_exec"],
    )
    # 2 attempts made
    assert client.chat.completions.call_count == 2
    # Neither XML drift nor placeholder must leak into output
    assert "<tool_call>" not in text
    assert fs._DRIFT_STRIPPED_PLACEHOLDER not in text
    # Must be programmatic fallback
    assert "HARNESS FALLBACK" in text
    assert "EVIDENCE" in text
