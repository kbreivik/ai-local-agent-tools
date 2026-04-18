"""Unit tests for api.db.known_facts — confidence formula + helper semantics.

Tests that hit the DB are skipped when DATABASE_URL is not Postgres (CI runs
against SQLite). The confidence-formula test is pure Python and runs anywhere.
"""
import os
from datetime import datetime, timezone, timedelta

import pytest

from api.db import known_facts as kf


def _is_pg():
    return "postgres" in os.environ.get("DATABASE_URL", "")


def test_compute_confidence_fresh_collector_is_high():
    row = {
        "source": "proxmox_collector",
        "last_verified": datetime.now(timezone.utc),
        "verify_count": 3,
        "contradicts": [],
    }
    c = kf.compute_confidence(row, settings={})
    assert c >= 0.7, f"expected >= 0.7 for fresh collector, got {c}"


def test_compute_confidence_stale_agent_observation_is_low():
    # agent_observation has 24h half-life; 48h old → ~0.25 of weight
    row = {
        "source": "agent_observation",
        "last_verified": datetime.now(timezone.utc) - timedelta(hours=48),
        "verify_count": 1,
        "contradicts": [],
    }
    c = kf.compute_confidence(row, settings={})
    assert c < 0.5, f"expected < 0.5 for stale agent observation, got {c}"


def test_compute_confidence_manual_phase1_is_max():
    row = {
        "source": "manual",
        "last_verified": datetime.now(timezone.utc),
        "verify_count": 1,
        "contradicts": [],
    }
    c = kf.compute_confidence(row, settings={})
    assert c > 0.9


def test_compute_confidence_contradiction_penalty():
    base = {
        "source": "proxmox_collector",
        "last_verified": datetime.now(timezone.utc),
        "verify_count": 3,
        "contradicts": [],
    }
    baseline = kf.compute_confidence(base, settings={})
    base["contradicts"] = [{"source": "manual", "value": "disagree",
                            "seen_at": "2026-01-01T00:00:00+00:00"}]
    with_contradiction = kf.compute_confidence(base, settings={})
    assert with_contradiction < baseline


def test_compute_confidence_deterministic():
    fixed_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    row = {
        "source": "kafka_collector",
        "last_verified": fixed_time - timedelta(hours=12),
        "verify_count": 5,
        "contradicts": [],
    }
    a = kf.compute_confidence(row, settings={})
    b = kf.compute_confidence(row, settings={})
    assert a == b


def test_values_equal_handles_dict_ordering():
    assert kf._values_equal({"a": 1, "b": 2}, {"b": 2, "a": 1})
    assert not kf._values_equal({"a": 1}, {"a": 2})


def test_pattern_to_like():
    assert kf._pattern_to_like("prod.kafka.*") == "prod.kafka.%"
    assert kf._pattern_to_like("*") == "%"


# ─── Postgres-only tests ───────────────────────────────────────────────────
pg_only = pytest.mark.skipif(not _is_pg(), reason="known_facts requires Postgres")


@pg_only
def test_upsert_insert_touch_change(tmp_path):
    kf.init_known_facts()
    key = "prod.test.known_facts.sample"
    # Clean any prior row from flaky runs
    from api.connections import _get_conn
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM known_facts_current WHERE fact_key = %s", (key,))
    cur.execute("DELETE FROM known_facts_history WHERE fact_key = %s", (key,))
    conn.commit(); cur.close(); conn.close()

    r1 = kf.upsert_fact(key, "proxmox_collector", "running")
    assert r1["action"] == "insert"

    r2 = kf.upsert_fact(key, "proxmox_collector", "running")
    assert r2["action"] == "touch"

    r3 = kf.upsert_fact(key, "proxmox_collector", "stopped")
    assert r3["action"] == "change"

    rows = kf.get_fact(key)
    assert len(rows) == 1
    assert rows[0]["fact_value"] == "stopped"


@pg_only
def test_cross_source_contradiction_populates_contradicts():
    kf.init_known_facts()
    key = "prod.test.known_facts.contradict"
    from api.connections import _get_conn
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM known_facts_current WHERE fact_key = %s", (key,))
    conn.commit(); cur.close(); conn.close()

    kf.upsert_fact(key, "proxmox_collector", "running")
    r = kf.upsert_fact(key, "agent_observation", "stopped")
    assert r.get("contradict") is True

    rows = kf.get_fact(key)
    assert len(rows) == 2
    for row in rows:
        assert len(row["contradicts"]) >= 1
