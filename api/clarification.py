"""
Pending clarification store — suspends the agent loop until the user answers.

The agent calls clarifying_question() → the loop awaits wait_for_clarification().
The GUI POSTs /api/agent/clarify → resolve_clarification() resolves the Future.
"""
import asyncio
import logging
from typing import Dict

log = logging.getLogger(__name__)

# Map session_id → Future. Agents await it; resolve_clarification sets it.
_pending: Dict[str, asyncio.Future] = {}

# v2.45.32 — pre-armed answers: set by /clarify when no future yet exists,
# then consumed by the next prearm_clarification / wait_for_clarification
# call for the same session. Lets test runners send the answer before the
# agent has actually called clarifying_question() without race conditions.
_prearmed_answers: Dict[str, str] = {}


def prearm_clarification(session_id: str) -> asyncio.Future:
    """Create + register a future for `session_id` if not already present.

    Returns the future. If a pre-armed answer was deposited via
    `resolve_clarification` before any waiter existed, the future is returned
    already-resolved. Idempotent.
    """
    loop = asyncio.get_event_loop()
    fut = _pending.get(session_id)
    if fut is None or fut.done():
        fut = loop.create_future()
        _pending[session_id] = fut
    if session_id in _prearmed_answers and not fut.done():
        fut.set_result(_prearmed_answers.pop(session_id))
    return fut


async def wait_for_clarification(session_id: str, timeout: float = 300.0) -> str:
    """Suspend caller until resolve_clarification() is called or timeout fires.

    v2.45.32: reuses any future created by prearm_clarification(); also
    consumes a pre-armed answer if one was deposited before the agent reached
    this call.
    """
    future = prearm_clarification(session_id)
    try:
        return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
    except asyncio.TimeoutError:
        log.warning("[clarification] timeout waiting for session %s", session_id)
        return "timeout — proceed with best guess"
    finally:
        _pending.pop(session_id, None)


def resolve_clarification(session_id: str, answer: str) -> bool:
    """Called by POST /api/agent/clarify to unblock the waiting agent loop.

    v2.45.32: if no future exists yet (test runner is faster than agent),
    deposit the answer in _prearmed_answers; the next prearm/wait call
    consumes it. Returns True in both cases so the API endpoint's
    'no pending future' message stops appearing on success.
    """
    future = _pending.get(session_id)
    if future is not None and not future.done():
        future.set_result(answer)
        log.info("[clarification] resolved session %s: %r", session_id, answer)
        return True
    # No waiter yet — deposit for the next caller to consume.
    _prearmed_answers[session_id] = answer
    log.info("[clarification] pre-armed session %s: %r", session_id, answer)
    return True
