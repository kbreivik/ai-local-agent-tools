"""Tests for v2.33.13 contradiction detection (agent synthesis guard).

Verifies that the harness spots draft conclusions that assert
"nothing found" while the tool history shows non-zero results.
"""


def test_detect_no_entries_claim():
    from api.agents.orchestrator import detect_negative_claim
    assert detect_negative_claim("No error-level log entries were found") != []
    assert detect_negative_claim("Zero errors detected in the last hour") != []
    assert detect_negative_claim("The system is healthy") == []


def test_contradiction_flags_nonzero_history():
    from api.agents.orchestrator import detect_contradictions
    history = [
        {"tool": "elastic_search_logs", "step": 3, "args": {},
         "result": {"hits": [1] * 90}},
        {"tool": "elastic_search_logs", "step": 5, "args": {"level": "error"},
         "result": {"hits": []}},
    ]
    contra = detect_contradictions("No error entries were found.", history)
    assert len(contra) == 1
    assert contra[0]["tool"] == "elastic_search_logs"
    assert contra[0]["nonzero_count"] == 90


def test_no_contradiction_when_history_empty():
    from api.agents.orchestrator import detect_contradictions
    assert detect_contradictions("No errors found.", []) == []


def test_no_contradiction_when_claim_is_positive():
    from api.agents.orchestrator import detect_contradictions
    history = [{"tool": "foo", "step": 1, "args": {}, "result": {"hits": [1, 2]}}]
    assert detect_contradictions("Found 2 errors in worker-01.", history) == []
