"""v2.36.5 — Per-agent-type tool call budget helper tests.

Locks the fallback behaviour: misconfigured values return the hardcoded
default, valid values round-trip, aliases resolve correctly.
"""
import logging
from unittest.mock import patch, MagicMock


def _mock_backend(settings: dict | None = None):
    """Return a mock backend that returns `settings.get(key)` on get_setting."""
    settings = settings or {}
    backend = MagicMock()
    backend.get_setting = MagicMock(side_effect=lambda k: settings.get(k))
    return backend


def test_returns_default_when_setting_absent():
    from api.routers.agent import _tool_budget_for
    with patch("mcp_server.tools.skills.storage.get_backend",
               return_value=_mock_backend({})):
        assert _tool_budget_for("observe") == 8
        assert _tool_budget_for("investigate") == 16
        assert _tool_budget_for("execute") == 14
        assert _tool_budget_for("build") == 12


def test_returns_setting_value_when_configured():
    from api.routers.agent import _tool_budget_for
    with patch("mcp_server.tools.skills.storage.get_backend",
               return_value=_mock_backend({
                   "agentToolBudget_investigate": 24,
                   "agentToolBudget_observe": 10,
               })):
        assert _tool_budget_for("investigate") == 24
        assert _tool_budget_for("observe") == 10
        # Unconfigured types still use default
        assert _tool_budget_for("execute") == 14


def test_string_int_is_accepted():
    """Settings backend may return int as string (JSONB round-trip can do this)."""
    from api.routers.agent import _tool_budget_for
    with patch("mcp_server.tools.skills.storage.get_backend",
               return_value=_mock_backend({"agentToolBudget_investigate": "20"})):
        assert _tool_budget_for("investigate") == 20


def test_non_int_value_falls_back(caplog):
    from api.routers.agent import _tool_budget_for
    with patch("mcp_server.tools.skills.storage.get_backend",
               return_value=_mock_backend({"agentToolBudget_investigate": "not-a-number"})):
        with caplog.at_level(logging.WARNING):
            result = _tool_budget_for("investigate")
    assert result == 16
    assert any("non-int" in r.message for r in caplog.records)


def test_zero_value_falls_back_to_default():
    """Operator-documented: 0 means 'restore hardcoded default'."""
    from api.routers.agent import _tool_budget_for
    with patch("mcp_server.tools.skills.storage.get_backend",
               return_value=_mock_backend({"agentToolBudget_investigate": 0})):
        assert _tool_budget_for("investigate") == 16


def test_negative_value_falls_back():
    from api.routers.agent import _tool_budget_for
    with patch("mcp_server.tools.skills.storage.get_backend",
               return_value=_mock_backend({"agentToolBudget_investigate": -5})):
        assert _tool_budget_for("investigate") == 16


def test_out_of_range_clamps(caplog):
    """3 (below min) and 500 (above max) both fall back to default with warning."""
    from api.routers.agent import _tool_budget_for

    with patch("mcp_server.tools.skills.storage.get_backend",
               return_value=_mock_backend({"agentToolBudget_investigate": 3})):
        with caplog.at_level(logging.WARNING):
            assert _tool_budget_for("investigate") == 16
        assert any("outside safe range" in r.message for r in caplog.records)

    caplog.clear()

    with patch("mcp_server.tools.skills.storage.get_backend",
               return_value=_mock_backend({"agentToolBudget_investigate": 500})):
        with caplog.at_level(logging.WARNING):
            assert _tool_budget_for("investigate") == 16
        assert any("outside safe range" in r.message for r in caplog.records)


def test_alias_resolution():
    """status/research/action aliases route to observe/investigate/execute."""
    from api.routers.agent import _tool_budget_for
    with patch("mcp_server.tools.skills.storage.get_backend",
               return_value=_mock_backend({
                   "agentToolBudget_observe": 10,
                   "agentToolBudget_investigate": 20,
                   "agentToolBudget_execute": 18,
               })):
        assert _tool_budget_for("status") == 10
        assert _tool_budget_for("research") == 20
        assert _tool_budget_for("action") == 18
        assert _tool_budget_for("ambiguous") == 10   # → observe


def test_unknown_type_falls_back_to_investigate_default():
    """Unknown agent types (future additions) get the most permissive default."""
    from api.routers.agent import _tool_budget_for
    with patch("mcp_server.tools.skills.storage.get_backend",
               return_value=_mock_backend({})):
        assert _tool_budget_for("mystery_type") == 16   # investigate default


def test_backend_read_failure_falls_back():
    """Settings backend exception (DB down, etc.) must not crash the agent loop."""
    from api.routers.agent import _tool_budget_for
    bad_backend = MagicMock()
    bad_backend.get_setting = MagicMock(side_effect=RuntimeError("db down"))
    with patch("mcp_server.tools.skills.storage.get_backend",
               return_value=bad_backend):
        assert _tool_budget_for("investigate") == 16
        assert _tool_budget_for("observe") == 8


def test_no_max_tool_calls_dict_reference_remains():
    """Structural guard: v2.36.5 removes _MAX_TOOL_CALLS_BY_TYPE entirely.

    Any reference in api/routers/agent.py is a regression — the helper is the
    only path to the budget after this prompt lands.
    """
    import pathlib
    src = pathlib.Path(__file__).parent.parent / "api" / "routers" / "agent.py"
    text = src.read_text(encoding="utf-8")
    assert "_MAX_TOOL_CALLS_BY_TYPE" not in text, (
        "v2.36.5 removed _MAX_TOOL_CALLS_BY_TYPE — if it reappears, a regression "
        "has been introduced. Use _tool_budget_for(agent_type) instead."
    )
