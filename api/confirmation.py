"""
Pending plan confirmation store — suspends the agent loop until the user
approves or rejects the proposed action plan.

The agent calls plan_action() → the loop awaits wait_for_confirmation().
The GUI POSTs /api/agent/confirm → resolve_confirmation() resolves the Future.
"""
import asyncio
import logging
from typing import Dict

log = logging.getLogger(__name__)

_pending: Dict[str, asyncio.Future] = {}
_prearmed_decisions: Dict[str, bool] = {}


def prearm_confirmation(session_id: str) -> asyncio.Future:
    """v2.45.32 — pre-arm a future for `session_id`; consume any pre-armed
    decision. Idempotent."""
    loop = asyncio.get_event_loop()
    fut = _pending.get(session_id)
    if fut is None or fut.done():
        fut = loop.create_future()
        _pending[session_id] = fut
    if session_id in _prearmed_decisions and not fut.done():
        fut.set_result(_prearmed_decisions.pop(session_id))
    return fut


async def wait_for_confirmation(session_id: str, timeout: float = 300.0) -> bool:
    future = prearm_confirmation(session_id)

    # If pre-armed, future is already done — return immediately
    if future.done():
        try:
            return future.result()
        finally:
            _pending.pop(session_id, None)

    # v2.47.11 — auto-reject during test runs to prevent zombie modals.
    # See companion change in api/clarification.py for rationale. Tests
    # that explicitly trigger plan_action pre-arm via tc.triggers_plan;
    # gates triggered unexpectedly (e.g. v2.45.18 clarify→plan injection)
    # would otherwise block for the full 300s timeout.
    # Defaults to False (rejected) — matches the assertion in
    # tests/integration/test_agent.py:main that no test may have
    # auto_confirm=True.
    try:
        from api.routers.tests_api import test_run_active
        if test_run_active:
            log.info("[confirmation] auto-reject session %s (test run, no pre-arm)",
                     session_id)
            _pending.pop(session_id, None)
            return False
    except Exception:
        pass

    try:
        return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
    except asyncio.TimeoutError:
        log.warning("[confirmation] timeout waiting for session %s — auto-cancelling", session_id)
        return False
    finally:
        _pending.pop(session_id, None)


def resolve_confirmation(session_id: str, approved: bool) -> bool:
    future = _pending.get(session_id)
    if future is not None and not future.done():
        future.set_result(approved)
        log.info("[confirmation] session %s: approved=%s", session_id, approved)
        return True
    _prearmed_decisions[session_id] = approved
    log.info("[confirmation] pre-armed session %s: approved=%s", session_id, approved)
    return True
