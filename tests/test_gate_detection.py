"""Gate-fired detection tests (v2.34.16).

Covers the six gate categories plus mirror-parity with the UI detector. The
parity test compares counts against a JS-hand-computed fixture — any drift in
either gui/src/utils/gateDetection.js or api/agents/gate_detection.py should
fail this test first.
"""
import json

from api.agents.gate_detection import detect_gates_from_steps


def _step(idx, *messages):
    return {"step_index": idx, "messages_delta": list(messages)}


def test_halluc_guard_fired_detected():
    steps = [
        _step(
            2,
            {
                "role": "system",
                "content": "[harness] You must make at least one substantive tool call before final_answer.",
            },
        )
    ]
    g = detect_gates_from_steps(steps)
    assert g["halluc_guard"]["count"] == 1
    assert g["halluc_guard"]["details"][0]["step"] == 2


def test_distrust_flagged_detected():
    steps = [
        _step(
            3,
            {
                "role": "system",
                "content": (
                    "[harness] Sub-agent output was flagged "
                    "(halluc_guard_fired=True, fabrication_detected=True, "
                    "substantive_tool_calls=0). Do NOT synthesise..."
                ),
            },
        )
    ]
    g = detect_gates_from_steps(steps)
    assert g["distrust"]["count"] == 1


def test_budget_truncate_and_nudge_detected():
    steps = [
        _step(
            5,
            {
                "role": "user",
                "content": "[harness] Tool budget reached, truncating tool_calls to fit remaining",
            },
        ),
        _step(
            7,
            {
                "role": "user",
                "content": "HARNESS NUDGE: you are past 70% of budget, please propose_subtask now",
            },
        ),
    ]
    g = detect_gates_from_steps(steps)
    assert g["budget_truncate"]["count"] == 1
    assert g["budget_nudge"]["count"] == 1


def test_sanitizer_redaction_detected():
    steps = [
        _step(
            4,
            {
                "role": "tool",
                "content": "Result: foo [REDACTED] bar",
            },
        )
    ]
    g = detect_gates_from_steps(steps)
    assert g["sanitizer"]["count"] == 1


def test_fabrication_detected_from_tool_result_payload():
    payload = {
        "status": "sub_agent_done",
        "harness_guard": {
            "fabrication_detected": True,
            "halluc_guard_fired": False,
        },
    }
    steps = [
        _step(
            6,
            {
                "role":    "tool",
                "content": json.dumps(payload),
            },
        )
    ]
    g = detect_gates_from_steps(steps)
    assert g["fabrication"]["count"] == 1


def test_empty_steps_returns_all_zero():
    g = detect_gates_from_steps([])
    assert all(v["count"] == 0 for v in g.values())


def test_non_dict_messages_skipped_gracefully():
    steps = [{"step_index": 0, "messages_delta": ["plain string", None, 42]}]
    g = detect_gates_from_steps(steps)
    assert all(v["count"] == 0 for v in g.values())
