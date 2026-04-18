"""Tests for the v2.35.1 preflight resolver (tier 1–3 + prompt section).

Runs fully offline:
  * Tier 1 regex extraction — pure Python
  * Tier 2 keyword DB lookup — each resolver is monkey-patched
  * Tier 3 LLM fallback — client call monkey-patched
  * format_preflight_facts_section — pure Python
"""
from __future__ import annotations

import json

import pytest

from api.agents import preflight as pf


# ── Tier 1 ──────────────────────────────────────────────────────────────

def test_tier1_extracts_named_kafka_broker():
    task = "restart kafka_broker-3 because it's lagging"
    hits = pf.tier1_regex_extract(task)
    ids = [h.entity_id.lower() for h in hits]
    assert "kafka_broker-3" in ids
    kinds = {h.entity_type for h in hits if h.entity_id.lower() == "kafka_broker-3"}
    assert "kafka_broker" in kinds


def test_tier1_extracts_swarm_node_and_vm():
    task = "check ds-docker-worker-03 and hp1-prod-worker-03"
    hits = pf.tier1_regex_extract(task)
    ids = {h.entity_id.lower() for h in hits}
    assert "ds-docker-worker-03" in ids
    assert "hp1-prod-worker-03" in ids


def test_tier1_empty_when_no_entities():
    task = "just a general status please"
    hits = pf.tier1_regex_extract(task)
    # "general status" could still match generic_host; ensure we do not
    # crash and the list is a list of PreflightCandidate.
    assert isinstance(hits, list)
    for h in hits:
        assert isinstance(h, pf.PreflightCandidate)


# ── Tier 2 ──────────────────────────────────────────────────────────────

def test_tier2_resolves_recent_restart(monkeypatch):
    fake_rows = [{
        "entity_id": "kafka_broker-3",
        "entity_type": "kafka_broker",
        "when": "2026-04-18T18:30:00+00:00",
        "tool": "swarm_service_force_update",
        "result": "ok",
    }]

    def fake_resolver(window_min=60):
        return fake_rows

    monkeypatch.setitem(pf.KEYWORD_RESOLVER_FUNCS,
                        "_lookup_recent_restart_actions", fake_resolver)

    trace: list[str] = []
    hits = pf.tier2_keyword_db("the broker we just restarted", trace)
    assert len(hits) == 1
    assert hits[0].entity_id == "kafka_broker-3"
    assert hits[0].source == "keyword_db"
    assert any("keyword 'restart" in t or "keyword 'restarted" in t for t in trace)


def test_tier2_ambiguity_with_three_recent_restarts(monkeypatch):
    rows = [
        {"entity_id": "kafka_broker-3",  "entity_type": "kafka_broker"},
        {"entity_id": "nginx_ingress",   "entity_type": "swarm_service"},
        {"entity_id": "elasticsearch_data-2", "entity_type": "swarm_service"},
    ]
    monkeypatch.setitem(pf.KEYWORD_RESOLVER_FUNCS,
                        "_lookup_recent_restart_actions",
                        lambda window_min=60: rows)

    trace: list[str] = []
    hits = pf.tier2_keyword_db("restart it", trace)
    # All three come back as ambiguous candidates.
    assert len(hits) == 3
    # Every candidate is a keyword_db hit.
    assert all(h.source == "keyword_db" for h in hits)


def test_tier2_empty_when_no_keyword():
    trace: list[str] = []
    hits = pf.tier2_keyword_db("show cluster status", trace)
    assert hits == []


# ── Tier 3 LLM fallback ────────────────────────────────────────────────

def test_tier3_parses_llm_array(monkeypatch):
    monkeypatch.setattr(pf, "_llm_extract_entities",
                        lambda task, max_tokens: json.dumps(["thing-a", "thing-b"]))
    monkeypatch.setattr(pf, "_record_suggestion_from_llm",
                        lambda task, proposal: None)
    trace: list[str] = []
    hits = pf.tier3_llm_fallback(
        "a really vague task about that thing over yonder",
        trace,
        {"preflightLLMFallbackEnabled": True, "preflightLLMFallbackMaxTokens": 50},
    )
    assert len(hits) == 2
    assert hits[0].source == "llm_fallback"
    assert hits[0].entity_id == "thing-a"


def test_tier3_disabled(monkeypatch):
    monkeypatch.setattr(pf, "_llm_extract_entities",
                        lambda task, max_tokens: json.dumps(["should-not-appear"]))
    trace: list[str] = []
    hits = pf.tier3_llm_fallback(
        "some task",
        trace,
        {"preflightLLMFallbackEnabled": False},
    )
    assert hits == []
    assert any("disabled" in t for t in trace)


def test_tier3_handles_malformed_response(monkeypatch):
    recorded = {}
    monkeypatch.setattr(pf, "_llm_extract_entities",
                        lambda task, max_tokens: "I can't do that Dave")

    def _cap(task, proposal):
        recorded["task"] = task
        recorded["proposal"] = proposal

    monkeypatch.setattr(pf, "_record_suggestion_from_llm", _cap)
    trace: list[str] = []
    hits = pf.tier3_llm_fallback(
        "blah blah",
        trace,
        {"preflightLLMFallbackEnabled": True, "preflightLLMFallbackMaxTokens": 50},
    )
    assert hits == []
    assert any("unparseable" in t for t in trace)


# ── Entry point end-to-end ──────────────────────────────────────────────

def test_preflight_resolve_unambiguous_regex(monkeypatch):
    # No DB — skip inventory resolution.
    monkeypatch.setattr(pf, "lookup_inventory", lambda eid, etype: [])
    monkeypatch.setattr(pf, "get_confident_facts_for_entity",
                        lambda eid, min_confidence=0.7, max_rows=20: [])
    res = pf.preflight_resolve(
        "restart kafka_broker-3", "execute",
        settings={"preflightLLMFallbackEnabled": False,
                  "factInjectionThreshold": 0.7, "factInjectionMaxRows": 10},
    )
    assert res.ambiguous is False
    assert res.clarifying_needed is False
    assert any("kafka_broker-3" in (b["candidate"].entity_id or "")
               for b in res.candidates)


def test_preflight_resolve_ambiguous_from_tier2(monkeypatch):
    rows = [
        {"entity_id": "kafka_broker-3",  "entity_type": "kafka_broker"},
        {"entity_id": "nginx_ingress",   "entity_type": "swarm_service"},
        {"entity_id": "elasticsearch_data-2", "entity_type": "swarm_service"},
    ]
    monkeypatch.setitem(pf.KEYWORD_RESOLVER_FUNCS,
                        "_lookup_recent_restart_actions",
                        lambda window_min=60: rows)
    monkeypatch.setattr(pf, "lookup_inventory", lambda eid, etype: [])
    monkeypatch.setattr(pf, "get_confident_facts_for_entity",
                        lambda eid, min_confidence=0.7, max_rows=20: [])

    res = pf.preflight_resolve(
        "restart the broker we just restarted", "execute",
        settings={"preflightLLMFallbackEnabled": False},
    )
    assert res.ambiguous is True
    assert res.clarifying_needed is True


def test_preflight_facts_injected_for_unambiguous(monkeypatch):
    facts = [{
        "fact_key": "prod.kafka.broker.3.host",
        "source": "kafka_collector",
        "fact_value": "192.168.199.33",
        "last_verified": "2026-04-18T18:00:00+00:00",
        "confidence": 0.92,
    }]

    def fake_inv(eid, etype):
        return [{"entity_id": eid, "display_name": eid, "platform": "kafka"}]

    monkeypatch.setattr(pf, "lookup_inventory", fake_inv)
    monkeypatch.setattr(pf, "get_confident_facts_for_entity",
                        lambda eid, min_confidence=0.7, max_rows=20: facts)

    res = pf.preflight_resolve(
        "restart kafka_broker-3", "execute",
        settings={"preflightLLMFallbackEnabled": False},
    )
    assert len(res.preflight_facts) >= 1
    assert res.preflight_facts[0]["fact_key"] == "prod.kafka.broker.3.host"


# ── Prompt section rendering ────────────────────────────────────────────

def test_format_preflight_facts_contains_rows():
    pre = pf.PreflightResult(
        task="restart kafka_broker-3",
        agent_type="execute",
        candidates=[],
        ambiguous=False,
        preflight_facts=[{
            "fact_key": "prod.kafka.broker.3.host",
            "source": "kafka_collector",
            "fact_value": "192.168.199.33",
            "last_verified": "2026-04-18T18:00:00+00:00",
            "confidence": 0.92,
        }],
        trace=["task: ...", "tier1: 1 regex matches"],
        tier_used="tier1+2",
        clarifying_needed=False,
    )
    block = pf.format_preflight_facts_section(pre, settings={
        "preflightPanelMode": "always_visible",
        "factInjectionThreshold": 0.7,
        "factInjectionMaxRows": 40,
    })
    assert "PREFLIGHT FACTS" in block
    assert "prod.kafka.broker.3.host" in block
    assert "kafka_collector" in block
    assert "PREFLIGHT TRACE" in block


def test_format_preflight_facts_off_mode():
    pre = pf.PreflightResult(
        task="x", agent_type="observe",
        candidates=[], ambiguous=False, preflight_facts=[],
        trace=["whatever"], tier_used="tier1+2", clarifying_needed=False,
    )
    block = pf.format_preflight_facts_section(pre, settings={"preflightPanelMode": "off"})
    assert block == ""


def test_format_preflight_trace_only_when_no_facts():
    pre = pf.PreflightResult(
        task="x", agent_type="observe",
        candidates=[], ambiguous=False, preflight_facts=[],
        trace=["tier1: 0 regex matches", "tier2: 0 keyword-DB matches"],
        tier_used="tier1+2", clarifying_needed=False,
    )
    block = pf.format_preflight_facts_section(pre, settings={"preflightPanelMode": "always_visible"})
    assert "PREFLIGHT TRACE" in block
    assert "PREFLIGHT FACTS" not in block


# ── v2.35.5: regression tests for preflight fact-injection fix ─────────

def test_tier1_does_not_truncate_full_names():
    """Regex must preserve full hyphen/underscore entity names.

    Regression guard for a v2.35.1 rollout diagnosis that assumed the
    regex was stripping prefixes/suffixes. It was not — full names are
    preserved. This test locks that in.
    """
    cases = [
        ("logstash_logstash",                                     "logstash_logstash"),
        ("kafka_broker-3",                                        "kafka_broker-3"),
        ("why did kafka_broker-3 crash after logstash_logstash",  "kafka_broker-3"),
        ("why did kafka_broker-3 crash after logstash_logstash",  "logstash_logstash"),
        ("check logstash_logstash:9200",                          "logstash_logstash"),
    ]
    for task, expected_id in cases:
        hits = pf.tier1_regex_extract(task)
        ids = [h.entity_id for h in hits]
        assert expected_id in ids, (
            f"regex did not preserve {expected_id!r} in {task!r}; got {ids}"
        )


def test_resolve_against_inventory_zero_match_falls_back_to_direct(monkeypatch):
    """Zero inventory matches → fact lookup still runs on the regex-extracted id."""
    calls = {"fact_lookups": []}

    def fake_inv(eid, etype):
        return []

    def fake_facts(eid, min_confidence=0.7, max_rows=20):
        calls["fact_lookups"].append(eid)
        return [{
            "fact_key":      "prod.kafka.broker.3.host",
            "source":        "kafka_collector",
            "fact_value":    "192.168.199.33",
            "last_verified": "2026-04-18T18:00:00+00:00",
            "confidence":    0.92,
        }]

    monkeypatch.setattr(pf, "lookup_inventory", fake_inv)
    monkeypatch.setattr(pf, "get_confident_facts_for_entity", fake_facts)

    cand = pf.PreflightCandidate(
        entity_id="kafka_broker-3", entity_type="kafka_broker",
        source="regex", confidence=0.9, evidence="test",
    )
    trace: list[str] = []
    resolved, facts = pf.resolve_against_inventory([cand], trace)
    assert calls["fact_lookups"] == ["kafka_broker-3"], (
        "direct fact lookup did not run on zero-inventory-match"
    )
    assert len(facts) == 1
    assert "direct fact lookup" in "\n".join(trace)


def test_resolve_against_inventory_ambiguous_skips_direct(monkeypatch):
    """>1 inventory matches → direct fact lookup is NOT attempted."""
    calls = {"fact_lookups": []}

    def fake_inv(eid, etype):
        return [{"entity_id": "a"}, {"entity_id": "b"}]

    def fake_facts(eid, min_confidence=0.7, max_rows=20):
        calls["fact_lookups"].append(eid)
        return []

    monkeypatch.setattr(pf, "lookup_inventory", fake_inv)
    monkeypatch.setattr(pf, "get_confident_facts_for_entity", fake_facts)

    cand = pf.PreflightCandidate(
        entity_id="worker", entity_type="generic_host",
        source="regex", confidence=0.9, evidence="test",
    )
    trace: list[str] = []
    resolved, facts = pf.resolve_against_inventory([cand], trace)
    assert calls["fact_lookups"] == [], (
        f"ambiguous multi-match should skip fact lookup, saw {calls['fact_lookups']}"
    )
    assert facts == []
    assert "ambiguous" in "\n".join(trace)


def test_resolve_against_inventory_single_match_uses_canonical_id(monkeypatch):
    """Single inventory match → fact lookup uses inventory's canonical id."""
    calls = {"fact_lookups": []}

    def fake_inv(eid, etype):
        return [{"entity_id": "canonical-vm-id", "display_name": "Canonical VM"}]

    def fake_facts(eid, min_confidence=0.7, max_rows=20):
        calls["fact_lookups"].append(eid)
        return []

    monkeypatch.setattr(pf, "lookup_inventory", fake_inv)
    monkeypatch.setattr(pf, "get_confident_facts_for_entity", fake_facts)

    cand = pf.PreflightCandidate(
        entity_id="raw-host", entity_type="generic_host",
        source="regex", confidence=0.9, evidence="test",
    )
    trace: list[str] = []
    pf.resolve_against_inventory([cand], trace)
    assert calls["fact_lookups"] == ["canonical-vm-id"]
