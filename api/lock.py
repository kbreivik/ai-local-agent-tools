"""
PlanLockManager — global singleton that enforces one pending destructive plan at a time.

When plan_action() is called, the session acquires the lock. All other sessions
that attempt to call a destructive tool receive a "locked" result until the lock
is released (plan approved, cancelled, or session errored out).
"""
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional
import logging

log = logging.getLogger(__name__)


@dataclass
class LockInfo:
    session_id: str
    owner_user: str
    acquired_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class PlanLockManager:
    """Thread-safe global lock for destructive operations."""

    def __init__(self):
        self._lock = asyncio.Lock()
        self._held_by: Optional[LockInfo] = None

    # Locks older than this are considered orphaned (session crashed without releasing)
    STALE_AFTER = timedelta(minutes=10)

    async def acquire(self, session_id: str, owner_user: str) -> bool:
        """
        Try to acquire the global destructive lock.
        Returns True if acquired (or already held by this session).
        Returns False if held by a different active session.
        Stale locks (held > STALE_AFTER with no release) are auto-cleared.
        """
        async with self._lock:
            if self._held_by is None:
                self._held_by = LockInfo(session_id=session_id, owner_user=owner_user)
                log.info("Plan lock acquired by session=%s user=%s", session_id, owner_user)
                return True
            if self._held_by.session_id == session_id:
                return True  # Re-entrant for same session
            # Auto-release if the lock has been held longer than STALE_AFTER
            age = datetime.now(timezone.utc) - self._held_by.acquired_at
            if age > self.STALE_AFTER:
                log.warning(
                    "Plan lock stale (held %.0fs by session=%s) — auto-releasing for session=%s",
                    age.total_seconds(), self._held_by.session_id, session_id,
                )
                self._held_by = LockInfo(session_id=session_id, owner_user=owner_user)
                return True
            return False

    async def release(self, session_id: str) -> bool:
        """Release the lock. Only the holding session can release it."""
        async with self._lock:
            if self._held_by and self._held_by.session_id == session_id:
                log.info("Plan lock released by session=%s", session_id)
                self._held_by = None
                return True
            return False

    async def force_release(self):
        """Admin force-release (e.g. session crashed)."""
        async with self._lock:
            prev = self._held_by
            self._held_by = None
            if prev:
                log.warning("Plan lock force-released (was held by session=%s)", prev.session_id)
            return prev is not None

    def get_info(self) -> Optional[dict]:
        """Return current lock state (no lock needed — reading is atomic enough)."""
        h = self._held_by
        if h is None:
            return None
        age_s = int((datetime.now(timezone.utc) - h.acquired_at).total_seconds())
        return {
            "locked": True,
            "session_id": h.session_id,
            "owner_user": h.owner_user,
            "since": h.acquired_at.isoformat(),
            "age_seconds": age_s,
            "stale": age_s > int(self.STALE_AFTER.total_seconds()),
        }

    def is_locked_by_other(self, session_id: str) -> bool:
        h = self._held_by
        return h is not None and h.session_id != session_id


# Module-level singleton
plan_lock = PlanLockManager()
