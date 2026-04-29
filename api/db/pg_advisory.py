"""Postgres advisory locks — lightweight cross-process mutexes.

Used to serialise destructive operations across the agent so that only
one runs at a time per named scope, even with multiple operators
clicking 'approve' simultaneously in different tabs.

Uses pg_try_advisory_lock (non-blocking). The lock is held for the
duration of the dedicated connection — release on disconnect is
automatic, so a crashed worker cannot deadlock the system. The named
lock is hashed to a 32-bit int via hashtext().

Sync-only (matches known_facts.py / test_runs.py convention).
SQLite has no equivalent — on SQLite, the helper is a no-op (treats
every acquire as success). This is acceptable because SQLite
deployments are single-process by definition.
"""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager

log = logging.getLogger(__name__)


class LockBusy(Exception):
    """Raised when an advisory lock cannot be acquired (held elsewhere)."""


def _is_postgres() -> bool:
    return bool(os.environ.get("DATABASE_URL", ""))


def _open_dedicated_conn():
    """Open a dedicated psycopg2 connection for the lock's lifetime.

    NOT pooled — the lock is bound to this conn. Closing it releases
    the lock. Caller is responsible for closing via release().
    """
    if not _is_postgres():
        return None
    import psycopg2
    dsn = os.environ.get("DATABASE_URL", "").replace(
        "postgresql+asyncpg://", "postgresql://"
    )
    return psycopg2.connect(dsn, connect_timeout=5)


def try_acquire(name: str):
    """Try to acquire an advisory lock. Returns a holder object on
    success, None on failure. Caller must call release(holder).
    """
    if not _is_postgres():
        return _NoOpLock(name)
    conn = _open_dedicated_conn()
    if conn is None:
        return None
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pg_try_advisory_lock(hashtext(%s)::bigint)", (name,)
            )
            row = cur.fetchone()
        ok = bool(row and row[0])
        if not ok:
            try: conn.close()
            except Exception: pass
            return None
        return _PgLock(name, conn)
    except Exception as e:
        log.warning("advisory_lock(%r) acquire failed: %s", name, e)
        try: conn.close()
        except Exception: pass
        return None


def release(holder) -> None:
    """Release a lock previously returned by try_acquire."""
    if holder is None:
        return
    try:
        holder.release()
    except Exception as e:
        log.warning("advisory_lock release failed: %s", e)


@contextmanager
def advisory_lock(name: str):
    """Acquire the named lock or raise LockBusy.

    Usage:
        from api.db.pg_advisory import advisory_lock, LockBusy
        try:
            with advisory_lock("destructive_global"):
                do_thing()
        except LockBusy:
            return {"status": "busy", "message": "..."}
    """
    holder = try_acquire(name)
    if holder is None:
        raise LockBusy(f"advisory lock {name!r} is held by another session")
    try:
        yield
    finally:
        release(holder)


class _PgLock:
    """Holder for a real PG advisory lock."""
    def __init__(self, name: str, conn):
        self.name = name
        self._conn = conn

    def release(self) -> None:
        if self._conn is None:
            return
        try:
            with self._conn.cursor() as cur:
                cur.execute(
                    "SELECT pg_advisory_unlock(hashtext(%s)::bigint)",
                    (self.name,),
                )
        except Exception:
            pass
        try:
            self._conn.close()
        finally:
            self._conn = None


class _NoOpLock:
    """SQLite stub — single-process, lock is meaningless."""
    def __init__(self, name: str):
        self.name = name

    def release(self) -> None:
        pass
