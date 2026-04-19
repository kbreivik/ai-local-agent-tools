"""v2.35.15 — preamble-only detection regression tests.

Verifies that `_is_preamble_only` in api/routers/agent.py correctly
classifies thinking-preamble stubs (the "I'll check ..." style text
that was leaking into final_answer in op 07d326a1) and does NOT
false-positive on real short syntheses.
"""

import pytest


def test_detect_short_preamble_as_preamble():
    """Short preamble stubs must all be flagged."""
    from api.routers.agent import _is_preamble_only

    preambles = [
        "I'll check the UniFi network device stat...",
        "Let me look into the swarm status",
        "Sure, I'll start by calling the tool",
        "First, let me gather some information",
        "I'm going to call list_connections first",
        "To answer this, I'll need to run several checks",
    ]
    for p in preambles:
        assert _is_preamble_only(p), f"Failed to detect: {p!r}"


def test_real_synthesis_not_flagged_as_preamble():
    """Short real syntheses (with verdict markers) must NOT be flagged."""
    from api.routers.agent import _is_preamble_only

    real = [
        "STATUS: HEALTHY. 6/6 nodes Ready, no issues detected.",
        "FINDINGS: 39 clients connected, all APs online.",
        "ROOT CAUSE: disk pressure on worker-03.",
        # Starts with "I'll" but also includes a verdict marker
        "I'll note that STATUS: HEALTHY based on the tool results.",
    ]
    for r in real:
        assert not _is_preamble_only(r), \
            f"False-positive preamble on real answer: {r!r}"


def test_preamble_with_long_but_unfinished_text_still_flagged():
    """Long preamble text that ends with '...' (no verdict) is still preamble."""
    from api.routers.agent import _is_preamble_only
    t = (
        "I'll start by checking the UniFi controller status "
        "and then look at the individual AP connectivity. "
        "Let me gather the information now..."
    )
    assert _is_preamble_only(t)


def test_empty_text_is_not_preamble():
    """Empty / whitespace text is not classified as preamble (caught by
    the separate empty_completion reason)."""
    from api.routers.agent import _is_preamble_only
    assert not _is_preamble_only("")
    assert not _is_preamble_only("   \n  ")
    assert not _is_preamble_only(None)  # defensive None input


def test_non_preamble_text_not_flagged():
    """Arbitrary text that doesn't start with a preamble opener must not
    be flagged even if it's short."""
    from api.routers.agent import _is_preamble_only
    assert not _is_preamble_only("The cluster is healthy.")
    assert not _is_preamble_only("All brokers are online and in sync.")
    # "I" without "I'll / I will / I'm going to" → not a preamble opener
    assert not _is_preamble_only("I found no issues in the logs.")


def test_classify_terminal_final_answer_dispatch():
    """v2.35.15 — the three rescue reasons dispatch correctly."""
    from api.routers.agent import _classify_terminal_final_answer

    assert _classify_terminal_final_answer("") == "empty_completion"
    assert _classify_terminal_final_answer("   \n  ") == "empty_completion"
    # < 60 chars is too short
    assert _classify_terminal_final_answer("abc") == "too_short_completion"
    # Preamble-only stub (dominates short-check because it has >60 chars)
    preamble_text = (
        "I'll start by checking the UniFi controller status "
        "and then look at the individual AP connectivity..."
    )
    assert _classify_terminal_final_answer(preamble_text) \
        == "preamble_only_completion"
    # Real answer → no rescue
    real = (
        "STATUS: HEALTHY. All nodes Ready. 39 clients connected. "
        "No degraded services found."
    )
    assert _classify_terminal_final_answer(real) is None


def test_new_gate_names_in_gate_defs():
    """v2.35.15 — both new gate names must appear in GATE_DEFS."""
    from api.agents.gate_detection import GATE_DEFS
    assert "too_short_completion_rescued" in GATE_DEFS
    assert "preamble_only_completion_rescued" in GATE_DEFS


def test_preamble_harness_message_detected_as_new_gate():
    """Harness messages built with the new reasons must fire the matching
    distinct gate, not the generic cap-based forced_synthesis gate and
    not the v2.35.14 empty_completion_rescued gate."""
    from api.agents.forced_synthesis import build_harness_message
    from api.agents.gate_detection import detect_gates_from_steps

    cases = [
        ("too_short_completion", "too_short_completion_rescued"),
        ("preamble_only_completion", "preamble_only_completion_rescued"),
    ]
    for reason, expected_gate in cases:
        harness = build_harness_message(reason=reason, tool_count=3, budget=8)
        steps = [{
            "step_index": 1,
            "messages_delta": [{"role": "system", "content": harness}],
        }]
        gates = detect_gates_from_steps(steps)
        assert gates[expected_gate]["count"] == 1, (
            f"Expected {expected_gate} to fire for reason {reason!r}, "
            f"got {gates[expected_gate]}"
        )
        # Cap-based forced_synthesis must NOT fire (no cap label)
        assert gates["forced_synthesis"]["count"] == 0
        # v2.35.14 empty_completion_rescued must NOT fire (different label)
        assert gates["empty_completion_rescued"]["count"] == 0
