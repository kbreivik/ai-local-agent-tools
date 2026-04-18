"""Forced-synthesis step tests (v2.34.17).

The harness must run one tools-free completion on every loop-exit cap so the
operator still gets an EVIDENCE / ROOT CAUSE / NEXT STEPS block instead of
``final_answer: null``. The fabrication detector still runs; if it fires we
prefix the output with a DRAFT warning but preserve it.
"""
from __future__ import annotations

from types import SimpleNamespace

from api.agents.forced_synthesis import build_harness_message, run_forced_synthesis


class _FakeChoice:
    def __init__(self, content: str):
        self.message = SimpleNamespace(content=content)
        self.finish_reason = "stop"


class _FakeResponse:
    def __init__(self, content: str):
        self.choices = [_FakeChoice(content)]
        self.usage = SimpleNamespace(
            prompt_tokens=10, completion_tokens=20, total_tokens=30
        )

    def model_dump(self) -> dict:
        return {"choices": [{"message": {"content": self.choices[0].message.content}}]}


class _FakeCompletionsClient:
    """Captures kwargs so tests can verify the ``tools=`` arg is absent."""

    def __init__(self, content: str):
        self.content = content
        self.last_kwargs: dict | None = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return _FakeResponse(self.content)


class _FakeClient:
    def __init__(self, content: str):
        self.chat = SimpleNamespace(
            completions=_FakeCompletionsClient(content)
        )


def test_harness_message_contains_reason_label_and_counts():
    msg = build_harness_message("budget_cap", 16, 16)
    assert "[harness]" in msg
    assert "budget-cap" in msg
    assert "16/16" in msg


def test_harness_message_for_all_reasons_has_cap_word():
    for reason in ("budget_cap", "wall_clock", "token_cap",
                    "destructive_cap", "tool_failures"):
        msg = build_harness_message(reason, 5, 16)
        assert "[harness]" in msg
        assert "cap" in msg.lower()


def test_forced_synthesis_does_not_pass_tools_arg():
    """No tools= kwarg means the model physically cannot call anything."""
    client = _FakeClient("EVIDENCE: ... / ROOT CAUSE: ...")
    text, harness_msg, raw = run_forced_synthesis(
        client=client,
        model="test-model",
        messages=[{"role": "system", "content": "prompt"},
                  {"role": "user", "content": "task"}],
        agent_type="research",
        reason="budget_cap",
        tool_count=16,
        budget=16,
        actual_tool_names=["swarm_status", "container_tcp_probe"],
    )
    kwargs = client.chat.completions.last_kwargs or {}
    assert "tools" not in kwargs, "forced synthesis must not supply tools"
    assert "tool_choice" not in kwargs
    assert text.startswith("EVIDENCE")
    assert "[harness]" in harness_msg
    assert raw is not None


def test_forced_synthesis_returns_empty_on_llm_failure():
    class _FailingCompletions:
        def create(self, **kw):
            raise RuntimeError("LM Studio unreachable")

    client = SimpleNamespace(chat=SimpleNamespace(completions=_FailingCompletions()))
    text, harness_msg, raw = run_forced_synthesis(
        client=client,
        model="test-model",
        messages=[],
        agent_type="investigate",
        reason="wall_clock",
        tool_count=3,
        budget=16,
        actual_tool_names=[],
    )
    assert text == ""
    assert "[harness]" in harness_msg
    assert raw is None


def test_forced_synthesis_flags_fabrication_as_draft():
    """Output citing uncalled tools gets a DRAFT prefix, not deletion."""
    # Tool-call-shaped citations in an evidence-style block. Use tool names
    # that are NOT in actual_tool_names so the detector fires.
    fabricated = (
        "EVIDENCE:\n"
        "- swarm_ghost_tool(node='a')\n"
        "- kafka_ghost_check(topic='b')\n"
        "- elastic_phantom(q='c')\n"
        "- proxmox_mirage(vm='d')\n"
        "ROOT CAUSE: invented\n"
    )
    client = _FakeClient(fabricated)
    text, _msg, _raw = run_forced_synthesis(
        client=client,
        model="test-model",
        messages=[],
        agent_type="research",
        reason="budget_cap",
        tool_count=16,
        budget=16,
        actual_tool_names=["swarm_status"],  # none of the cites ran
    )
    assert text.startswith("[HARNESS: this synthesis was generated after a hard cap")
    # Original content is still present — we annotate, not delete.
    assert "swarm_ghost_tool" in text


def test_forced_synthesis_does_not_flag_honest_output():
    """Output that only mentions tools that actually ran is not prefixed."""
    honest = (
        "EVIDENCE:\n"
        "- swarm_status returned 3 managers, 2 workers up\n"
        "ROOT CAUSE: worker-03 Down\n"
        "NEXT STEPS: reboot worker-03\n"
    )
    client = _FakeClient(honest)
    text, _msg, _raw = run_forced_synthesis(
        client=client,
        model="test-model",
        messages=[],
        agent_type="research",
        reason="budget_cap",
        tool_count=16,
        budget=16,
        actual_tool_names=["swarm_status", "kafka_broker_status"],
    )
    assert not text.startswith("[HARNESS: this synthesis was generated"), text
    assert "swarm_status" in text
