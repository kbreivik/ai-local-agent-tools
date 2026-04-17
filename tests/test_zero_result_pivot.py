"""Tests for v2.33.12 zero-result pivot detection (`_result_count` helper)."""


def test_result_count_from_hits_array():
    from api.routers.agent import _result_count
    assert _result_count({"hits": [1, 2, 3]}) == 3
    assert _result_count({"hits": []}) == 0


def test_result_count_from_summary_text():
    from api.routers.agent import _result_count
    assert _result_count({"summary": "Found 90 log entries"}) == 90
    assert _result_count({"message": "Found 0 log entries"}) == 0


def test_result_count_from_total_field():
    from api.routers.agent import _result_count
    assert _result_count({"total": 42}) == 42


def test_result_count_none_for_unrecognised():
    from api.routers.agent import _result_count
    assert _result_count({"status": "ok"}) is None
