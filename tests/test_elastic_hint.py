"""Tests for the _compute_hint helper and the elastic response envelope.

Introduced in v2.33.14 to make elastic_search_logs self-describing:
every response carries total_in_window / applied_filters / query_lucene,
and a hint string is added when results look suspiciously narrow.
"""


def test_hint_flags_narrow_filter():
    from mcp_server.tools.elastic import _compute_hint
    hint = _compute_hint(
        total=0, total_in_window=500, levels=["error"], service=None, host=None,
    )
    assert hint is not None
    assert "level" in hint
    assert "500" in hint


def test_hint_silent_when_empty_window():
    from mcp_server.tools.elastic import _compute_hint
    assert _compute_hint(0, 0, ["error"], None, None) is None
    assert _compute_hint(0, None, ["error"], None, None) is None


def test_hint_silent_when_results_nonzero():
    from mcp_server.tools.elastic import _compute_hint
    assert _compute_hint(5, 500, ["error"], None, None) is None


def test_hint_silent_when_no_filters():
    from mcp_server.tools.elastic import _compute_hint
    assert _compute_hint(0, 100, [], None, None) is None


def test_hint_includes_service_and_host_when_set():
    from mcp_server.tools.elastic import _compute_hint
    hint = _compute_hint(
        total=0,
        total_in_window=42,
        levels=[],
        service="kafka_broker-1",
        host="worker-01",
    )
    assert hint is not None
    assert "kafka_broker-1" in hint
    assert "worker-01" in hint
    assert "42" in hint


def test_response_shape_includes_keys():
    """Contract test — the envelope must carry these keys even on empty results.

    Skipped unless ELASTIC_URL is configured; documents the expected shape.
    """
    import os

    import pytest

    if not os.environ.get("ELASTIC_URL"):
        pytest.skip("ELASTIC_URL not set — envelope shape check requires live ES")

    from mcp_server.tools.elastic import elastic_search_logs

    result = elastic_search_logs(level="error", minutes_ago=60, size=1)
    assert result["status"] in ("ok", "error", "degraded")
    if result["status"] != "ok":
        return
    data = result["data"]
    required = {
        "total",
        "total_in_window",
        "applied_filters",
        "query_lucene",
        "index",
    }
    assert required <= set(data.keys()), (
        f"Missing keys: {required - set(data.keys())}"
    )
