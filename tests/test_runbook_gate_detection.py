"""Tests for v2.35.4 runbook_injected gate detection."""
from __future__ import annotations

from api.agents.gate_detection import detect_gates_from_steps, GATE_DEFS


def test_gate_defs_includes_runbook_injected():
    assert "runbook_injected" in GATE_DEFS


def test_runbook_injected_detected_via_system_prompt():
    sp = (
        "═══ ROLE ═══\nInfrastructure agent.\n"
        "═══ ACTIVE RUNBOOK: kafka_triage ═══\n"
        "Title: Kafka triage\n"
        "Body...\n"
    )
    g = detect_gates_from_steps([], system_prompt=sp)
    assert g["runbook_injected"]["count"] == 1
    assert "kafka_triage" in g["runbook_injected"]["details"][0]["snippet"]


def test_runbook_injected_via_step_messages():
    step = {
        "step_index": 0,
        "messages_delta": [
            {"role": "system", "content": "═══ ACTIVE RUNBOOK: consumer_lag_path ═══\nbody"},
        ],
    }
    g = detect_gates_from_steps([step])
    assert g["runbook_injected"]["count"] == 1
    assert "consumer_lag_path" in g["runbook_injected"]["details"][0]["snippet"]


def test_no_runbook_injected_when_marker_absent():
    step = {
        "step_index": 0,
        "messages_delta": [
            {"role": "assistant", "content": "Just a regular message."},
        ],
    }
    g = detect_gates_from_steps([step], system_prompt="no marker here")
    assert g["runbook_injected"]["count"] == 0


def test_runbook_injected_is_per_operation_not_per_step():
    """Multiple steps with the marker still count as 1 (prompt-level event)."""
    step1 = {"step_index": 0, "messages_delta": [
        {"role": "system", "content": "═══ ACTIVE RUNBOOK: a ═══"}]}
    step2 = {"step_index": 1, "messages_delta": [
        {"role": "system", "content": "═══ ACTIVE RUNBOOK: b ═══"}]}
    g = detect_gates_from_steps([step1, step2])
    assert g["runbook_injected"]["count"] == 1
