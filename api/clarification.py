"""
Pending clarification store — suspends the agent loop until the user answers.

The agent calls clarifying_question() → the loop awaits wait_for_clarification().
The GUI POSTs /api/agent/clarify → resolve_clarification() resolves the Future.
"""
import asyncio
import logging
from typing import Dict

log = logging.getLogger(__name__)

_pending: Dict[str, asyncio.Future] = {}


async def wait_for_clarification(session_id: str, timeout: float = 300.0) -> str:
    """Suspend caller until resolve_clarification() is called or timeout fires."""
    loop = asyncio.get_event_loop()
    future: asyncio.Future = loop.create_future()
    _pending[session_id] = future
    try:
        return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
    except asyncio.TimeoutError:
        log.warning("[clarification] timeout waiting for session %s", session_id)
        return "timeout — proceed with best guess"
    finally:
        _pending.pop(session_id, None)


def resolve_clarification(session_id: str, answer: str) -> bool:
    """Called by POST /api/agent/clarify to unblock the waiting agent loop."""
    future = _pending.get(session_id)
    if future and not future.done():
        future.set_result(answer)
        log.info("[clarification] resolved session %s: %r", session_id, answer)
        return True
    log.warning("[clarification] no pending future for session %s", session_id)
    return False
