"""Tests for v2.34.9 MCP tool signature injection.

Verifies that build_tool_signatures() returns real parameter names matching
the functions the agent actually invokes, and that format_tool_signatures_section()
renders a prompt-ready block for a given allowlist.
"""


def _reset_cache():
    import api.agents.router as _r
    _r._TOOL_SIGNATURES_CACHE = None


def test_signatures_built_for_known_tools():
    _reset_cache()
    from api.agents.router import build_tool_signatures
    sigs = build_tool_signatures()
    assert "kafka_consumer_lag" in sigs
    assert "group" in sigs["kafka_consumer_lag"]
    assert "elastic_search_logs" in sigs
    # The real signature uses minutes_ago, not the frequently-guessed since_minutes
    assert "minutes_ago" in sigs["elastic_search_logs"]
    assert "since_minutes" not in sigs["elastic_search_logs"]


def test_signature_section_formatted():
    _reset_cache()
    from api.agents.router import format_tool_signatures_section
    section = format_tool_signatures_section(["kafka_consumer_lag", "elastic_search_logs"])
    assert "═══ TOOL SIGNATURES ═══" in section
    assert "kafka_consumer_lag(group:" in section
    assert "elastic_search_logs(" in section


def test_empty_allowlist_returns_empty_string():
    _reset_cache()
    from api.agents.router import format_tool_signatures_section
    assert format_tool_signatures_section([]) == ""


def test_hallucinated_kwargs_pinned_to_correct_tools():
    """Regression: the specific tool/kwarg pairs the agent hallucinated in 2026-04-17 traces.

    The LLM guessed `since_minutes` on elastic_* tools (real param is `minutes_ago`)
    and `service_name` on service_health (real param is `name`). Pin those here.
    Other tools may legitimately use `since_minutes` or `service_name`.
    """
    _reset_cache()
    from api.agents.router import build_tool_signatures
    sigs = build_tool_signatures()
    if "elastic_error_logs" in sigs:
        assert "since_minutes" not in sigs["elastic_error_logs"]
        assert "minutes_ago" in sigs["elastic_error_logs"]
    if "elastic_search_logs" in sigs:
        assert "since_minutes" not in sigs["elastic_search_logs"]
        assert "minutes_ago" in sigs["elastic_search_logs"]
    if "elastic_kafka_logs" in sigs:
        assert "since_minutes" not in sigs["elastic_kafka_logs"]
    if "service_health" in sigs:
        assert "service_name" not in sigs["service_health"]
        assert "name" in sigs["service_health"]
    if "service_current_version" in sigs:
        assert "service_name" not in sigs["service_current_version"]
        assert "name" in sigs["service_current_version"]


def test_allowlist_for_returns_sorted_observe_tools():
    from api.agents.router import allowlist_for, OBSERVE_AGENT_TOOLS
    got = allowlist_for("observe")
    assert got == sorted(OBSERVE_AGENT_TOOLS)
    # And investigate
    got2 = allowlist_for("investigate")
    assert "elastic_search_logs" in got2


def test_allowlist_for_execute_domain():
    from api.agents.router import allowlist_for, EXECUTE_KAFKA_TOOLS
    got = allowlist_for("execute", domain="kafka")
    assert got == sorted(EXECUTE_KAFKA_TOOLS)


def test_signatures_cache_reused():
    _reset_cache()
    from api.agents.router import build_tool_signatures
    first = build_tool_signatures()
    second = build_tool_signatures()
    assert first is second  # cached identity
