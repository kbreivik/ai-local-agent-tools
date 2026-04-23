"""Tests for get_first_tool_hint — MuninnDB tool-sequence memory."""
from __future__ import annotations
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_returns_none_on_no_results():
    from api.memory.feedback import get_first_tool_hint
    mock_client = AsyncMock()
    mock_client.activate = AsyncMock(return_value=[])
    with patch("api.memory.feedback.get_client", return_value=mock_client):
        result = _run(get_first_tool_hint("check kafka status", "observe"))
    assert result is None


def test_returns_first_tool_from_sequence():
    from api.memory.feedback import get_first_tool_hint
    mock_client = AsyncMock()
    mock_client.activate = AsyncMock(return_value=[{
        "concept": "tools_for:check-kafka-status",
        "content": "Successful tool sequence for 'check kafka status': kafka_broker_status,kafka_topic_inspect,kafka_consumer_lag. Outcome: completed. Agent: observe.",
        "tags": ["tool_association", "observe", "success"],
    }])
    with patch("api.memory.feedback.get_client", return_value=mock_client):
        result = _run(get_first_tool_hint("check kafka status", "observe"))
    assert result == "kafka_broker_status"


def test_ignores_failure_engrams():
    from api.memory.feedback import get_first_tool_hint
    mock_client = AsyncMock()
    mock_client.activate = AsyncMock(return_value=[{
        "concept": "tools_for:check-kafka-status",
        "content": "Failed/cancelled tool sequence for 'check kafka status': audit_log. Outcome: failed. Agent: observe.",
        "tags": ["tool_association", "observe", "failure"],
    }])
    with patch("api.memory.feedback.get_client", return_value=mock_client):
        result = _run(get_first_tool_hint("check kafka status", "observe"))
    assert result is None


def test_ignores_wrong_agent_type():
    from api.memory.feedback import get_first_tool_hint
    mock_client = AsyncMock()
    mock_client.activate = AsyncMock(return_value=[{
        "concept": "tools_for:check-kafka",
        "content": "Successful tool sequence for 'check kafka': swarm_service_force_update. Outcome: completed. Agent: execute.",
        "tags": ["tool_association", "execute", "success"],
    }])
    with patch("api.memory.feedback.get_client", return_value=mock_client):
        result = _run(get_first_tool_hint("check kafka", "observe"))
    assert result is None


def test_returns_none_on_exception():
    from api.memory.feedback import get_first_tool_hint
    mock_client = AsyncMock()
    mock_client.activate = AsyncMock(side_effect=Exception("db down"))
    with patch("api.memory.feedback.get_client", return_value=mock_client):
        result = _run(get_first_tool_hint("check kafka", "observe"))
    assert result is None
