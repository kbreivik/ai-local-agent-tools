"""Tests for v2.35.4 runbook classifier (keyword mode).

Stubs out ``list_active_runbooks_for_agent_type`` so no Postgres dependency
is required.
"""
from __future__ import annotations

import api.agents.runbook_classifier as rbc


def _mk_rb(name, keywords, agent_types, priority=100, is_active=True):
    return {
        "id":                     f"id-{name}",
        "name":                   name,
        "title":                  name.replace("_", " ").title(),
        "triage_keywords":        keywords,
        "applies_to_agent_types": agent_types,
        "priority":               priority,
        "is_active":              is_active,
        "body_md":                f"Body for {name}",
    }


def _patch_candidates(monkeypatch, candidates):
    def _fake(agent_type):
        return [rb for rb in candidates if not rb["applies_to_agent_types"] or
                agent_type in rb["applies_to_agent_types"]]
    monkeypatch.setattr(
        "api.db.runbooks.list_active_runbooks_for_agent_type",
        _fake,
    )


def test_clear_keyword_hit_selects_correct_runbook(monkeypatch):
    candidates = [
        _mk_rb("kafka_triage", ["kafka", "broker"], ["research"], priority=10),
        _mk_rb("overlay", ["overlay", "hairpin"], ["research"], priority=15),
    ]
    _patch_candidates(monkeypatch, candidates)
    hit = rbc.select_runbook("investigate kafka consumer lag", "research", {})
    assert hit is not None
    assert hit["runbook"]["name"] == "kafka_triage"
    assert hit["score"] >= 1
    assert "kafka" in hit["matched_keywords"]


def test_multi_match_highest_score_wins(monkeypatch):
    candidates = [
        _mk_rb("kafka_triage", ["kafka", "broker"], ["research"], priority=30),
        _mk_rb("consumer_lag", ["consumer lag", "lag"], ["research"], priority=20),
    ]
    _patch_candidates(monkeypatch, candidates)
    # "consumer lag" matches both 'consumer lag' AND 'lag' → score=2 for consumer_lag
    hit = rbc.select_runbook("consumer lag is high", "research", {})
    assert hit["runbook"]["name"] == "consumer_lag"
    assert hit["score"] == 2


def test_tie_broken_by_priority(monkeypatch):
    candidates = [
        _mk_rb("low_priority", ["kafka"], ["research"], priority=99),
        _mk_rb("high_priority", ["kafka"], ["research"], priority=10),
    ]
    _patch_candidates(monkeypatch, candidates)
    hit = rbc.select_runbook("check kafka", "research", {})
    assert hit["runbook"]["name"] == "high_priority"


def test_zero_matches_returns_none(monkeypatch):
    candidates = [
        _mk_rb("kafka_triage", ["kafka", "broker"], ["research"]),
    ]
    _patch_candidates(monkeypatch, candidates)
    hit = rbc.select_runbook("deploy a new service", "research", {})
    assert hit is None


def test_empty_task_returns_none(monkeypatch):
    candidates = [_mk_rb("any", ["any"], ["research"])]
    _patch_candidates(monkeypatch, candidates)
    assert rbc.select_runbook("", "research", {}) is None


def test_disabled_runbook_not_considered(monkeypatch):
    # list_active_runbooks_for_agent_type already filters is_active; emulate by
    # returning nothing for the "disabled" runbook
    def _fake(agent_type):
        return []  # no active candidates
    monkeypatch.setattr(
        "api.db.runbooks.list_active_runbooks_for_agent_type", _fake,
    )
    hit = rbc.select_runbook("kafka investigate", "research", {})
    assert hit is None


def test_agent_type_filter_respected(monkeypatch):
    candidates = [
        _mk_rb("research_only", ["foo"], ["research"], priority=10),
        _mk_rb("action_only",   ["foo"], ["action"],   priority=20),
    ]
    _patch_candidates(monkeypatch, candidates)
    hit_r = rbc.select_runbook("foo", "research", {})
    hit_a = rbc.select_runbook("foo", "action", {})
    assert hit_r["runbook"]["name"] == "research_only"
    assert hit_a["runbook"]["name"] == "action_only"


def test_word_boundary_phrase_match(monkeypatch):
    candidates = [
        _mk_rb("lag_rb", ["consumer lag"], ["research"], priority=10),
    ]
    _patch_candidates(monkeypatch, candidates)
    # exact phrase matches
    assert rbc.select_runbook("Investigate consumer lag now", "research", {})
    # substring inside a larger word does NOT match ('laggard' shouldn't hit 'lag')
    # (We have no 'lag' keyword alone, so 'laggard' must miss "consumer lag")
    hit = rbc.select_runbook("the laggard broker", "research", {})
    assert hit is None


def test_case_insensitive(monkeypatch):
    candidates = [_mk_rb("kafka_triage", ["Kafka", "BROKER"], ["research"])]
    _patch_candidates(monkeypatch, candidates)
    hit = rbc.select_runbook("KAFKA broker check", "research", {})
    assert hit is not None
    assert hit["score"] == 2


def test_semantic_mode_stub_returns_none(monkeypatch):
    # With settings → semantic, stub returns None (future v2.35.5)
    _patch_candidates(monkeypatch, [_mk_rb("x", ["foo"], ["research"])])
    hit = rbc.select_runbook("foo", "research", {"runbookClassifierMode": "semantic"})
    assert hit is None
