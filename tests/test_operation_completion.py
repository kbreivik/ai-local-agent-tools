"""Tests for operation completion (Bug 1) and stop_agent cancellation (Bug 2)."""
import asyncio
import sys
import os
from unittest.mock import AsyncMock, patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def _run(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        return loop.run_until_complete(coro)
    return asyncio.run(coro)


# ── Bug 1: flush_now called before complete_operation ────────────────────────

def test_stream_agent_calls_flush_before_complete():
    """Verify flush_now() is called before complete_operation in _stream_agent."""
    import inspect
    import api.routers.agent as agent_mod

    source = inspect.getsource(agent_mod._stream_agent)
    flush_pos = source.find("flush_now()")
    complete_pos = source.find("complete_operation(")
    # flush_now must appear before complete_operation in the finally block
    assert flush_pos != -1, "flush_now() not found in _stream_agent"
    assert complete_pos != -1, "complete_operation() not found in _stream_agent"
    assert flush_pos < complete_pos, (
        "flush_now() must be called BEFORE complete_operation() "
        f"(flush at {flush_pos}, complete at {complete_pos})"
    )


# ── Bug 2: stop_agent marks operation as 'cancelled' ────────────────────────

def test_stop_agent_uses_cancelled_status():
    """stop_agent must write status='cancelled' to DB, not 'running' or 'stopped'."""
    import api.routers.agent as agent_mod

    agent_mod._cancel_flags.clear()

    captured_status = []

    async def mock_complete_op(conn, op_id, status):
        captured_status.append(status)

    mock_op = {"id": "op-abc", "status": "running"}

    async def mock_get_op(conn, sid):
        return mock_op

    mock_conn = AsyncMock()
    mock_engine = MagicMock()

    # Create an async context manager that yields mock_conn
    class FakeConn:
        async def __aenter__(self):
            return mock_conn
        async def __aexit__(self, *args):
            pass

    mock_engine.begin = lambda: FakeConn()

    with patch("api.db.base.get_engine", return_value=mock_engine), \
         patch("api.db.queries.get_operation_by_session", mock_get_op), \
         patch("api.db.queries.complete_operation", mock_complete_op):

        from api.routers.agent import StopRequest, stop_agent
        req = StopRequest(session_id="test-cancel-session")
        result = _run(stop_agent(req))

    assert result["status"] == "ok"
    assert "test-cancel-session" in agent_mod._cancel_flags
    assert len(captured_status) == 1, f"Expected 1 DB write, got {len(captured_status)}"
    assert captured_status[0] == "cancelled", (
        f"Expected status='cancelled', got '{captured_status[0]}'"
    )
    agent_mod._cancel_flags.clear()


def test_stop_agent_skips_non_running_operation():
    """stop_agent should not overwrite a completed operation."""
    import api.routers.agent as agent_mod

    agent_mod._cancel_flags.clear()

    captured_status = []

    async def mock_complete_op(conn, op_id, status):
        captured_status.append(status)

    mock_op = {"id": "op-xyz", "status": "completed"}

    async def mock_get_op(conn, sid):
        return mock_op

    mock_conn = AsyncMock()
    mock_engine = MagicMock()

    class FakeConn:
        async def __aenter__(self):
            return mock_conn
        async def __aexit__(self, *args):
            pass

    mock_engine.begin = lambda: FakeConn()

    with patch("api.db.base.get_engine", return_value=mock_engine), \
         patch("api.db.queries.get_operation_by_session", mock_get_op), \
         patch("api.db.queries.complete_operation", mock_complete_op):

        from api.routers.agent import StopRequest, stop_agent
        req = StopRequest(session_id="already-done")
        result = _run(stop_agent(req))

    assert result["status"] == "ok"
    assert len(captured_status) == 0, "Should not overwrite completed operation"
    agent_mod._cancel_flags.clear()
