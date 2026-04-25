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
