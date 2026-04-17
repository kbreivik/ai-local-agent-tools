"""Regression tests for elastic_search_logs signature.

Prompted by live trace 2026-04-17 09:39: investigate agent called
elastic_search_logs(level="error", ...) and got back
"got an unexpected keyword argument 'level'".
"""
import inspect


def test_level_kwarg_accepted():
    """Regression: agent must be able to call level='error' without TypeError."""
    from mcp_server.tools.elastic import elastic_search_logs
    sig = inspect.signature(elastic_search_logs)
    assert "level" in sig.parameters, "level kwarg must be accepted"


def test_aliases_accepted():
    """Models guess severity= and log_level= — both must be silent aliases."""
    from mcp_server.tools.elastic import elastic_search_logs
    sig = inspect.signature(elastic_search_logs)
    assert "severity" in sig.parameters
    assert "log_level" in sig.parameters


def test_level_normalisation():
    """Common synonyms expand to canonical pairs."""
    from mcp_server.tools.elastic import _norm_levels
    assert "error" in _norm_levels("err")
    assert "warn" in _norm_levels("warning") and "warning" in _norm_levels("warning")
    assert _norm_levels(None) == []
    assert "critical" in _norm_levels(["crit"])


def test_level_normalisation_dedupes():
    """Repeated inputs and synonym overlap should not duplicate."""
    from mcp_server.tools.elastic import _norm_levels
    out = _norm_levels(["error", "err", "ERROR"])
    assert out.count("error") == 1


def test_server_wrapper_signature():
    """The MCP server wrapper must also accept level/severity/log_level."""
    from mcp_server.server import elastic_search_logs as srv_elastic_search_logs
    sig = inspect.signature(srv_elastic_search_logs)
    assert "level" in sig.parameters
    assert "severity" in sig.parameters
    assert "log_level" in sig.parameters
    assert "host" in sig.parameters
