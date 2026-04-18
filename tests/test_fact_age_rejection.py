"""Tests for v2.35.3 fact-age rejection engine.

The engine gates tool results against high-confidence recently-verified
facts in ``known_facts``. These tests stub out ``get_fact`` so no
Postgres dependency is required.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

import api.agents.fact_age_rejection as far


def _fresh_iso(minutes_ago: float) -> str:
    return (
        datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    ).isoformat()


def _patch_known_facts(monkeypatch, rows_by_key: dict[str, list[dict]]):
    """Monkeypatch get_fact to return predefined rows keyed by fact_key."""
    def _fake_get_fact(fact_key, min_confidence=0.0):
        return rows_by_key.get(fact_key, [])
    monkeypatch.setattr("api.db.known_facts.get_fact", _fake_get_fact)


def _kafka_result(host_for_broker_3: str) -> dict:
    return {
        "status": "ok",
        "data": {
            "brokers": [
                {"id": 1, "host": "192.168.199.31", "port": 9092},
                {"id": 2, "host": "192.168.199.32", "port": 9092},
                {"id": 3, "host": host_for_broker_3, "port": 9092},
            ],
        },
        "message": "ok",
    }


# ── mode tests ──────────────────────────────────────────────────────────────

def test_mode_off_passes_through(monkeypatch):
    _patch_known_facts(monkeypatch, {
        "prod.kafka.broker.3.host": [
            {"source": "proxmox_collector", "fact_value": "192.168.199.33",
             "confidence": 0.95, "last_verified": _fresh_iso(1)},
        ],
    })
    res = _kafka_result("10.0.4.17")
    modified, msgs, failure = far.check_and_apply_rejection(
        tool_name="kafka_broker_status",
        args={},
        result=res,
        settings={"factAgeRejectionMode": "off"},
    )
    assert failure is None
    assert msgs == []
    assert modified is res
    assert modified["data"]["brokers"][2]["host"] == "10.0.4.17"


def test_mode_soft_advisory_only(monkeypatch):
    _patch_known_facts(monkeypatch, {
        "prod.kafka.broker.3.host": [
            {"source": "proxmox_collector", "fact_value": "192.168.199.33",
             "confidence": 0.95, "last_verified": _fresh_iso(1)},
        ],
    })
    res = _kafka_result("10.0.4.17")
    modified, msgs, failure = far.check_and_apply_rejection(
        tool_name="kafka_broker_status",
        args={},
        result=res,
        settings={"factAgeRejectionMode": "soft"},
    )
    assert failure is None
    assert len(msgs) == 1
    assert "advisory" in msgs[0].lower()
    # result unchanged
    assert modified["data"]["brokers"][2]["host"] == "10.0.4.17"
    assert "_rejected_by_fact_age" not in modified


def test_mode_medium_strips_value(monkeypatch):
    _patch_known_facts(monkeypatch, {
        "prod.kafka.broker.3.host": [
            {"source": "proxmox_collector", "fact_value": "192.168.199.33",
             "confidence": 0.95, "last_verified": _fresh_iso(1)},
        ],
    })
    res = _kafka_result("10.0.4.17")
    modified, msgs, failure = far.check_and_apply_rejection(
        tool_name="kafka_broker_status",
        args={},
        result=res,
        settings={"factAgeRejectionMode": "medium"},
    )
    assert failure is None
    assert len(msgs) == 1
    # conflicting value stripped
    assert modified["data"]["brokers"][2]["host"] == "[REJECTED_BY_FACT_AGE]"
    # non-conflicting values preserved
    assert modified["data"]["brokers"][0]["host"] == "192.168.199.31"
    # marker populated
    assert "_rejected_by_fact_age" in modified
    assert modified["_rejected_by_fact_age"][0]["fact_key"] == "prod.kafka.broker.3.host"
    assert modified["_rejected_by_fact_age"][0]["tool_value"] == "10.0.4.17"
    assert modified["_rejected_by_fact_age"][0]["known_value"] == "192.168.199.33"


def test_mode_hard_returns_failure(monkeypatch):
    _patch_known_facts(monkeypatch, {
        "prod.kafka.broker.3.host": [
            {"source": "proxmox_collector", "fact_value": "192.168.199.33",
             "confidence": 0.95, "last_verified": _fresh_iso(1)},
        ],
    })
    res = _kafka_result("10.0.4.17")
    modified, msgs, failure = far.check_and_apply_rejection(
        tool_name="kafka_broker_status",
        args={},
        result=res,
        settings={"factAgeRejectionMode": "hard"},
    )
    assert failure == "fact_age_rejection"
    assert modified is None
    assert len(msgs) == 1
    assert "Hard fact-age rejection" in msgs[0]


# ── no-rejection scenarios ──────────────────────────────────────────────────

def test_no_recent_fact_passes_through(monkeypatch):
    # Last verified 10 minutes ago, but max_age_min=5 (default)
    _patch_known_facts(monkeypatch, {
        "prod.kafka.broker.3.host": [
            {"source": "proxmox_collector", "fact_value": "192.168.199.33",
             "confidence": 0.95, "last_verified": _fresh_iso(10)},
        ],
    })
    res = _kafka_result("10.0.4.17")
    modified, msgs, failure = far.check_and_apply_rejection(
        tool_name="kafka_broker_status",
        args={},
        result=res,
        settings={"factAgeRejectionMode": "medium"},
    )
    assert failure is None
    assert msgs == []
    assert modified["data"]["brokers"][2]["host"] == "10.0.4.17"
    assert "_rejected_by_fact_age" not in modified


def test_agreement_passes_through(monkeypatch):
    _patch_known_facts(monkeypatch, {
        "prod.kafka.broker.3.host": [
            {"source": "proxmox_collector", "fact_value": "192.168.199.33",
             "confidence": 0.95, "last_verified": _fresh_iso(1)},
        ],
    })
    # Tool also says 33 — agreement, no rejection
    res = _kafka_result("192.168.199.33")
    modified, msgs, failure = far.check_and_apply_rejection(
        tool_name="kafka_broker_status",
        args={},
        result=res,
        settings={"factAgeRejectionMode": "medium"},
    )
    assert failure is None
    assert msgs == []


def test_low_confidence_fact_no_rejection(monkeypatch):
    _patch_known_facts(monkeypatch, {
        "prod.kafka.broker.3.host": [
            {"source": "proxmox_collector", "fact_value": "192.168.199.33",
             "confidence": 0.60, "last_verified": _fresh_iso(1)},
        ],
    })
    res = _kafka_result("10.0.4.17")
    modified, msgs, failure = far.check_and_apply_rejection(
        tool_name="kafka_broker_status",
        args={},
        result=res,
        settings={"factAgeRejectionMode": "medium",
                  "factAgeRejectionMinConfidence": 0.85},
    )
    assert failure is None
    assert msgs == []


def test_agent_observation_source_ignored(monkeypatch):
    """agent_observation rows are never considered authoritative."""
    _patch_known_facts(monkeypatch, {
        "prod.kafka.broker.3.host": [
            {"source": "agent_observation", "fact_value": "192.168.199.33",
             "confidence": 0.95, "last_verified": _fresh_iso(1)},
        ],
    })
    res = _kafka_result("10.0.4.17")
    modified, msgs, failure = far.check_and_apply_rejection(
        tool_name="kafka_broker_status",
        args={},
        result=res,
        settings={"factAgeRejectionMode": "medium"},
    )
    assert failure is None
    assert msgs == []


def test_unknown_tool_passes_through(monkeypatch):
    # Tool not in extractors registry → no proposed facts → no rejection
    _patch_known_facts(monkeypatch, {})
    res = {"status": "ok", "data": {"whatever": 1}}
    modified, msgs, failure = far.check_and_apply_rejection(
        tool_name="nonexistent_tool",
        args={},
        result=res,
        settings={"factAgeRejectionMode": "medium"},
    )
    assert failure is None
    assert msgs == []
    assert modified is res


# ── helpers ─────────────────────────────────────────────────────────────────

def test_highest_confidence_row_wins(monkeypatch):
    """When multiple authoritative rows exist, pick the highest-confidence one."""
    _patch_known_facts(monkeypatch, {
        "prod.kafka.broker.3.host": [
            {"source": "swarm_collector", "fact_value": "10.20.30.40",
             "confidence": 0.88, "last_verified": _fresh_iso(2)},
            {"source": "proxmox_collector", "fact_value": "192.168.199.33",
             "confidence": 0.95, "last_verified": _fresh_iso(1)},
        ],
    })
    res = _kafka_result("10.0.4.17")
    modified, msgs, failure = far.check_and_apply_rejection(
        tool_name="kafka_broker_status",
        args={},
        result=res,
        settings={"factAgeRejectionMode": "medium"},
    )
    assert failure is None
    assert len(msgs) == 1
    # The highest-conf known_value should be cited
    assert modified["_rejected_by_fact_age"][0]["known_value"] == "192.168.199.33"
    assert modified["_rejected_by_fact_age"][0]["known_source"] == "proxmox_collector"
