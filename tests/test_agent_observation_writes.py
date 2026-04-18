"""agent_observation fact writer — guard-rail tests (v2.35.2).

The agent loop batch-upserts facts into known_facts at the agent_observation
source tier once a run terminates. Only runs in the ``completed`` status with
no fabrication firing are allowed to write, and writes are capped to
``factInjectionMaxRows × 2`` rows per run.

Because the writer lives inside an async FastAPI stream, these tests exercise
the *policy* directly via a helper that mirrors the production guard-rails.
The helper returns what would be written + the skip reason (if any) so we can
assert on both the positive and negative paths without running an LLM.
"""
from __future__ import annotations


def _decide_fact_write(
    final_status: str,
    fabrication_detected: bool,
    run_facts: dict,
    max_rows: int = 80,
) -> tuple[list[dict] | None, str | None, int]:
    """Pure-function mirror of the policy logic in _stream_agent's terminal
    block. Kept in-sync by intent — if the production policy changes, update
    both this helper and the test assertions.

    Returns (facts_to_write, skip_reason, dropped).
    """
    if final_status != "completed":
        return None, "skipped_nonterminal", 0
    if fabrication_detected:
        return None, "skipped_fabrication", 0
    if not run_facts:
        return [], None, 0
    to_write: list[dict] = []
    for fk, info in run_facts.items():
        if len(to_write) >= max_rows:
            break
        to_write.append({
            "fact_key": fk,
            "source":   "agent_observation",
            "value":    info.get("value"),
            "metadata": {
                "operation_id": "op123",
                "via_tool":     info.get("tool"),
                "step":         info.get("step"),
            },
        })
    dropped = max(0, len(run_facts) - len(to_write))
    return to_write, None, dropped


def _fake_fact(val, tool="service_placement", step=1):
    return {"value": val, "tool": tool, "step": step, "timestamp": "t", "raw": {}}


# ── positive path ────────────────────────────────────────────────────────────


def test_completed_clean_run_writes_all_facts():
    run_facts = {
        "prod.kafka.broker.3.host": _fake_fact("192.168.199.33"),
        "prod.swarm.service.x.placement": _fake_fact(["w-01"]),
    }
    facts, reason, dropped = _decide_fact_write("completed", False, run_facts)
    assert reason is None
    assert dropped == 0
    assert facts is not None and len(facts) == 2
    for f in facts:
        assert f["source"] == "agent_observation"
        assert "operation_id" in f["metadata"]


# ── fabrication guardrail ────────────────────────────────────────────────────


def test_completed_but_fabrication_skips_writes():
    run_facts = {"prod.kafka.broker.3.host": _fake_fact("x")}
    facts, reason, dropped = _decide_fact_write("completed", True, run_facts)
    assert reason == "skipped_fabrication"
    assert facts is None


# ── non-terminal guardrails ─────────────────────────────────────────────────


def test_capped_run_does_not_write():
    run_facts = {"k": _fake_fact("v")}
    facts, reason, _ = _decide_fact_write("capped", False, run_facts)
    assert reason == "skipped_nonterminal"
    assert facts is None


def test_failed_run_does_not_write():
    facts, reason, _ = _decide_fact_write(
        "failed", False, {"k": _fake_fact("v")},
    )
    assert reason == "skipped_nonterminal"
    assert facts is None


def test_escalated_run_does_not_write():
    facts, reason, _ = _decide_fact_write(
        "escalated", False, {"k": _fake_fact("v")},
    )
    assert reason == "skipped_nonterminal"
    assert facts is None


# ── cap at 80 rows ───────────────────────────────────────────────────────────


def test_large_run_caps_at_max_rows():
    run_facts = {f"prod.x.{i}": _fake_fact(i) for i in range(100)}
    facts, reason, dropped = _decide_fact_write(
        "completed", False, run_facts, max_rows=80,
    )
    assert reason is None
    assert facts is not None and len(facts) == 80
    assert dropped == 20


# ── metadata propagation ────────────────────────────────────────────────────


def test_metadata_includes_operation_id_and_via_tool():
    run_facts = {"prod.kafka.broker.3.host": _fake_fact("v",
                                                       tool="kafka_broker_status",
                                                       step=4)}
    facts, reason, _ = _decide_fact_write("completed", False, run_facts)
    assert reason is None
    assert facts[0]["metadata"]["via_tool"] == "kafka_broker_status"
    assert facts[0]["metadata"]["step"] == 4
    assert facts[0]["metadata"]["operation_id"] == "op123"


# ── volatile half-life lookup lives on settings side ────────────────────────


def test_volatile_half_life_is_honoured_by_half_life_lookup():
    """Confirm the new factHalfLifeHours_agent_volatile setting routes
    through _half_life_for_source when metadata.volatile=True."""
    from api.db.known_facts import _half_life_for_source
    # Without metadata → agent_observation default (24h)
    assert _half_life_for_source("agent_observation", {}, age_hours=0.0) == 24.0
    # With volatile metadata → 2h default
    v = _half_life_for_source("agent_observation", {},
                              age_hours=0.0, metadata={"volatile": True})
    assert v == 2.0
    # Settings override
    v2 = _half_life_for_source(
        "agent_observation",
        {"factHalfLifeHours_agent_volatile": 5.0},
        age_hours=0.0, metadata={"volatile": True},
    )
    assert v2 == 5.0
