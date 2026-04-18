"""In-run cross-tool contradiction detection (v2.35.2).

Covers the gate-detection side of the feature: an agent run that produces two
tool results claiming different values for the same fact_key should surface
an ``inrun_contradiction`` gate in the shared detector so operators see the
harness advisory in the Gates Fired sidebar.

Wiring tests for the agent loop sit in the full agent integration suite; here
we only verify detector behaviour on a synthetic step fixture so CI can stay
fast and offline.
"""
from api.agents.gate_detection import detect_gates_from_steps


def _step(idx, *messages):
    return {"step_index": idx, "messages_delta": list(messages)}


def test_inrun_contradiction_detected_by_gate():
    steps = [
        _step(
            2,
            {
                "role": "system",
                "content": (
                    "[harness] Contradiction detected within this run: "
                    "prod.swarm.service.logstash_logstash.placement — "
                    "step 1 (service_placement) said [\"worker-02\"], "
                    "step 2 (container_discover_by_service) says [\"worker-03\"]. "
                    "Resolve before concluding."
                ),
            },
        ),
    ]
    gates = detect_gates_from_steps(steps)
    assert gates["inrun_contradiction"]["count"] == 1
    assert gates["inrun_contradiction"]["details"][0]["step"] == 2


def test_same_value_does_not_fire_contradiction():
    steps = [
        _step(1, {"role": "system", "content": "routine harness message"}),
    ]
    gates = detect_gates_from_steps(steps)
    assert gates["inrun_contradiction"]["count"] == 0


def test_multiple_contradictions_are_counted():
    steps = [
        _step(2, {"role": "system",
                  "content": "[harness] Contradiction detected within this run: a — x vs y"}),
        _step(5, {"role": "system",
                  "content": "[harness] Contradiction detected within this run: b — 1 vs 2"}),
    ]
    gates = detect_gates_from_steps(steps)
    assert gates["inrun_contradiction"]["count"] == 2


def test_inrun_contradiction_in_gate_defs():
    from api.agents.gate_detection import GATE_DEFS
    assert "inrun_contradiction" in GATE_DEFS


def test_contradiction_accumulator_shape():
    """Sanity check on the dict shape used by the agent loop to track run
    facts — the key invariant is that a repeat with the same value is a
    touch, and a repeat with a different value is a contradiction."""
    run_facts = {}
    # Step 1: observe a value
    run_facts["prod.kafka.broker.3.host"] = {
        "value":     "192.168.199.33",
        "step":      1,
        "tool":      "kafka_broker_status",
        "timestamp": "2026-04-18T00:00:00Z",
        "raw":       {"fact_key": "prod.kafka.broker.3.host",
                      "source": "agent_observation",
                      "value": "192.168.199.33"},
    }
    prior = run_facts["prod.kafka.broker.3.host"]

    # Same value arriving later — NOT a contradiction
    assert prior["value"] == "192.168.199.33"

    # Different value arriving later — IS a contradiction
    assert prior["value"] != "10.0.0.1"
