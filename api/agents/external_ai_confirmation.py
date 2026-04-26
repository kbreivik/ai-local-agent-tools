"""External AI confirmation gate — the wait primitive for v2.36.2.

Mirrors api/confirmation.py (plan_action) and api/clarification.py (preflight
disambiguation). Keys on session_id. wait_for_confirmation blocks on an
asyncio.Event with a timeout; resolve_confirmation fires the event.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class _PendingConfirm:
    event: asyncio.Event
    decision: str = "pending"   # 'approved' | 'rejected' | 'timeout'
    created_at: float = 0.0


_pending: dict[str, _PendingConfirm] = {}


def _cleanup_stale(ttl_s: int = 900) -> None:
    """Drop entries older than ttl_s so zombie sessions don't leak."""
    cutoff = time.monotonic() - ttl_s
    stale = [k for k, p in _pending.items() if p.created_at < cutoff]
    for k in stale:
        _pending.pop(k, None)


async def wait_for_confirmation(session_id: str, timeout_s: int = 300) -> str:
    """Block until the user approves/rejects, or timeout_s elapses.

    Returns one of 'approved' | 'rejected' | 'timeout'. Safe to call
    concurrently for different session_ids; calling twice for the same
    session_id without an intervening resolve returns the cached decision
    of the first wait.
    """
    # v2.47.9 — defensive auto-reject during test runs in case the
    # _maybe_route_to_external_ai short-circuit is bypassed by a future
    # code path that reaches this gate directly.
    try:
        from api.routers.tests_api import test_run_active
        if test_run_active:
            return "rejected"
    except Exception:
        pass

    _cleanup_stale()
    pending = _pending.get(session_id)
    if pending is None:
        pending = _PendingConfirm(
            event=asyncio.Event(),
            created_at=time.monotonic(),
        )
        _pending[session_id] = pending
    try:
        await asyncio.wait_for(pending.event.wait(), timeout=timeout_s)
        return pending.decision
    except asyncio.TimeoutError:
        pending.decision = "timeout"
        pending.event.set()   # unblock any concurrent waiters
        return "timeout"
    finally:
        # Leave the entry briefly so late resolve_confirmation calls don't
        # crash; it'll be cleaned up by _cleanup_stale on next call.
        pass


def resolve_confirmation(session_id: str, approved: bool) -> bool:
    """Called by the /confirm-external endpoint. Returns True if the session
    had a pending wait, False otherwise (stale call)."""
    pending = _pending.get(session_id)
    if pending is None:
        return False
    pending.decision = "approved" if approved else "rejected"
    pending.event.set()
    return True


def has_pending(session_id: str) -> bool:
    return session_id in _pending and _pending[session_id].decision == "pending"
