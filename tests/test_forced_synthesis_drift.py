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


def test_programmatic_fallback_produces_readable_output():
    from api.agents.forced_synthesis import _programmatic_fallback
    out = _programmatic_fallback(
        reason="budget_cap", tool_count=8, budget=8,
        actual_tool_names=["runbook_search", "vm_exec", "vm_exec", "service_placement"],
    )
    assert "HARNESS FALLBACK" in out
    assert "EVIDENCE" in out
    assert "NEXT STEPS" in out
    assert "<tool_call" not in out
    assert "<function=" not in out
    # De-duplicated list of tools (2 vm_exec -> 1 entry)
    assert "runbook_search" in out
    assert "vm_exec" in out
    assert "service_placement" in out


def test_strip_xml_drift_from_messages_preserves_non_drift():
    from api.agents.forced_synthesis import _strip_xml_drift_from_messages
    msgs = [
        {"role": "system", "content": "you are helpful"},
        {"role": "user", "content": "do something"},
        {"role": "assistant", "content": "Sure, I'll check."},
        {"role": "assistant", "content": "<tool_call>\n<function=foo>\n</tool_call>"},
        {"role": "tool", "tool_call_id": "x", "content": "{}"},
    ]
    out = _strip_xml_drift_from_messages(msgs)
    assert len(out) == len(msgs)
    assert out[0] == msgs[0]
    assert out[1] == msgs[1]
    assert out[2] == msgs[2]
    assert out[3]["content"].startswith("[prior step")
    assert out[3]["content"] != msgs[3]["content"]
    assert out[4] == msgs[4]


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
