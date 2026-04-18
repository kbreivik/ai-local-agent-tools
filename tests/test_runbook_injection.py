"""Tests for v2.35.4 runbook injection helper.

Covers mode=off / augment / replace for the prompt-builder helper.
Stubs out settings + classifier — no DB dependency.
"""
from __future__ import annotations

import api.agents.router as router


_SAMPLE_PROMPT = (
    "═══ ROLE ═══\nSystem role.\n\n"
    "═══ ENVIRONMENT ═══\nDocker Swarm.\n\n"
    "═══ KAFKA TRIAGE ORDER ═══\n1. kafka_broker_status.\n\n"
    "═══ OTHER ═══\nOther section.\n"
)


def _patch_settings(monkeypatch, **kw):
    def _fake_settings():
        return dict(kw)
    monkeypatch.setattr(
        "api.db.known_facts._get_facts_settings", _fake_settings,
    )


def _patch_classifier(monkeypatch, result):
    def _fake(task, agent_type, settings):
        return result
    monkeypatch.setattr(
        "api.agents.runbook_classifier.select_runbook", _fake,
    )


def _make_hit(name="kafka_triage", priority=10):
    return {
        "runbook": {
            "id":                     f"id-{name}",
            "name":                   name,
            "title":                  f"Title of {name}",
            "body_md":                f"BODY OF {name}\nStep 1...\nStep 2...",
            "priority":               priority,
            "applies_to_agent_types": ["research"],
            "triage_keywords":        ["kafka", "consumer lag"],
        },
        "score":            2,
        "matched_keywords": ["kafka", "consumer lag"],
    }


def test_mode_off_returns_prompt_unchanged(monkeypatch):
    _patch_settings(monkeypatch, runbookInjectionMode="off")
    _patch_classifier(monkeypatch, _make_hit())
    out = router.maybe_inject_runbook(_SAMPLE_PROMPT, "kafka investigate", "research")
    assert out == _SAMPLE_PROMPT
    assert "ACTIVE RUNBOOK" not in out


def test_mode_augment_appends_section_on_match(monkeypatch):
    _patch_settings(monkeypatch, runbookInjectionMode="augment",
                    runbookClassifierMode="keyword")
    _patch_classifier(monkeypatch, _make_hit())
    out = router.maybe_inject_runbook(_SAMPLE_PROMPT, "kafka investigate", "research")
    assert "═══ ACTIVE RUNBOOK: kafka_triage ═══" in out
    assert "BODY OF kafka_triage" in out
    # Original sections retained (augment, not replace)
    assert "═══ KAFKA TRIAGE ORDER ═══" in out
    # Runbook block comes AFTER the existing TRIAGE section
    assert out.index("═══ KAFKA TRIAGE ORDER ═══") < out.index("═══ ACTIVE RUNBOOK:")


def test_mode_augment_no_match_returns_unchanged(monkeypatch):
    _patch_settings(monkeypatch, runbookInjectionMode="augment")
    _patch_classifier(monkeypatch, None)
    out = router.maybe_inject_runbook(_SAMPLE_PROMPT, "deploy something", "research")
    assert out == _SAMPLE_PROMPT
    assert "ACTIVE RUNBOOK" not in out


def test_mode_replace_swaps_triage_section(monkeypatch):
    _patch_settings(monkeypatch, runbookInjectionMode="replace")
    _patch_classifier(monkeypatch, _make_hit(name="kafka_triage"))
    out = router.maybe_inject_runbook(_SAMPLE_PROMPT, "kafka investigate", "research")
    # Runbook body present
    assert "═══ ACTIVE RUNBOOK: kafka_triage ═══" in out
    # The hardcoded KAFKA TRIAGE ORDER section should be gone
    assert "═══ KAFKA TRIAGE ORDER ═══" not in out
    # Role section preserved
    assert "═══ ROLE ═══" in out


def test_empty_task_no_injection(monkeypatch):
    _patch_settings(monkeypatch, runbookInjectionMode="augment")
    _patch_classifier(monkeypatch, _make_hit())
    out = router.maybe_inject_runbook(_SAMPLE_PROMPT, "", "research")
    assert out == _SAMPLE_PROMPT


def test_empty_prompt_no_injection(monkeypatch):
    _patch_settings(monkeypatch, runbookInjectionMode="augment")
    _patch_classifier(monkeypatch, _make_hit())
    out = router.maybe_inject_runbook("", "some task", "research")
    assert out == ""


def test_classifier_error_safe_passthrough(monkeypatch):
    _patch_settings(monkeypatch, runbookInjectionMode="augment")
    def _raises(task, agent_type, settings):
        raise RuntimeError("classifier broken")
    monkeypatch.setattr(
        "api.agents.runbook_classifier.select_runbook", _raises,
    )
    out = router.maybe_inject_runbook(_SAMPLE_PROMPT, "kafka", "research")
    assert out == _SAMPLE_PROMPT


def test_unknown_mode_defaults_to_augment(monkeypatch):
    _patch_settings(monkeypatch, runbookInjectionMode="bogus_mode")
    _patch_classifier(monkeypatch, _make_hit())
    out = router.maybe_inject_runbook(_SAMPLE_PROMPT, "kafka", "research")
    assert "ACTIVE RUNBOOK" in out
