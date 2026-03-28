"""Unit tests for _cancel_flags lifecycle in api.routers.agent."""
import time
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import api.routers.agent as agent_mod


def _reset():
    agent_mod._cancel_flags.clear()


def test_stop_empty_session_id_rejected():
    _reset()
    import asyncio
    from api.routers.agent import StopRequest, stop_agent
    req = StopRequest(session_id="")
    result = asyncio.get_event_loop().run_until_complete(stop_agent(req))
    assert result["status"] == "error"
    assert not agent_mod._cancel_flags


def test_stop_too_long_session_id_rejected():
    _reset()
    import asyncio
    from api.routers.agent import StopRequest, stop_agent
    req = StopRequest(session_id="x" * 200)
    result = asyncio.get_event_loop().run_until_complete(stop_agent(req))
    assert result["status"] == "error"
    assert not agent_mod._cancel_flags


def test_stop_valid_session_inserts_flag():
    _reset()
    import asyncio
    from api.routers.agent import StopRequest, stop_agent
    req = StopRequest(session_id="test-session-abc")
    result = asyncio.get_event_loop().run_until_complete(stop_agent(req))
    assert result["status"] == "ok"
    assert "test-session-abc" in agent_mod._cancel_flags
    flag, ts = agent_mod._cancel_flags["test-session-abc"]
    assert flag is True
    assert isinstance(ts, float)


def test_cleanup_removes_stale_entries():
    _reset()
    old_ts = time.monotonic() - (agent_mod._CANCEL_FLAG_TTL_SECONDS + 10)
    agent_mod._cancel_flags["stale-session"] = (True, old_ts)
    agent_mod._cleanup_stale_cancel_flags()
    assert "stale-session" not in agent_mod._cancel_flags


def test_cleanup_preserves_fresh_entries():
    _reset()
    agent_mod._cancel_flags["fresh-session"] = (True, time.monotonic())
    agent_mod._cleanup_stale_cancel_flags()
    assert "fresh-session" in agent_mod._cancel_flags


def test_flag_read_returns_bool_and_pops():
    _reset()
    agent_mod._cancel_flags["pop-me"] = (True, time.monotonic())
    val = agent_mod._cancel_flags.pop("pop-me", (False, 0.0))[0]
    assert val is True
    assert "pop-me" not in agent_mod._cancel_flags
