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


async def wait_for_confirmation(session_id: str, timeout: float = 300.0) -> bool:
    """Suspend caller until resolve_confirmation() is called or timeout fires."""
    loop = asyncio.get_event_loop()
    future: asyncio.Future = loop.create_future()
    _pending[session_id] = future
    try:
        return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
    except asyncio.TimeoutError:
        log.warning("[confirmation] timeout waiting for session %s — auto-cancelling", session_id)
        return False
    finally:
        _pending.pop(session_id, None)


def resolve_confirmation(session_id: str, approved: bool) -> bool:
    """Called by POST /api/agent/confirm to unblock the waiting agent loop."""
    future = _pending.get(session_id)
    if future and not future.done():
        future.set_result(approved)
        log.info("[confirmation] session %s: approved=%s", session_id, approved)
        return True
    log.warning("[confirmation] no pending future for session %s", session_id)
    return False
