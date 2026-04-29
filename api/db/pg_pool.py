"""Unified sync Postgres connection pool — the canonical sync DB path.

Used by api/connections.py and the modules in api/db/ that perform
sync psycopg2 work. Replaces the unbounded `psycopg2.connect(dsn)`
per-call pattern that previously caused PG-side connection exhaustion
under concurrent load.

Architecture: a process-wide ThreadedConnectionPool (psycopg2's
thread-safe variant). Connections handed to callers are wrapped in
_PooledConnProxy, which intercepts `.close()` to return the underlying
conn to the pool instead of closing it. This preserves API
compatibility with the previous _get_conn() pattern — every existing
caller that does `conn.close()` automatically benefits.

SQLite is not pooled here — get_pooled_conn() returns None when
DATABASE_URL is unset, and callers fall back to their existing SQLite
paths.
"""
from __future__ import annotations

import logging
import os
import threading
from contextlib import contextmanager

log = logging.getLogger(__name__)

_pool = None
_pool_lock = threading.Lock()


def _is_postgres() -> bool:
    return bool(os.environ.get("DATABASE_URL", ""))


def _build_pool():
    import psycopg2.pool
    dsn = os.environ.get("DATABASE_URL", "").replace(
        "postgresql+asyncpg://", "postgresql://"
    )
    if not dsn:
        return None
    pool = psycopg2.pool.ThreadedConnectionPool(
        minconn=2,
        maxconn=20,
        dsn=dsn,
        connect_timeout=5,
    )
    log.info("pg_pool: ThreadedConnectionPool initialised (min=2, max=20)")
    return pool


def _get_pool():
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                if not _is_postgres():
                    return None
                _pool = _build_pool()
    return _pool


class _PooledConnProxy:
    """Wraps a pooled psycopg2 connection.

    Forwards every attribute access to the underlying connection EXCEPT
    `.close()`, which returns the conn to the pool instead of closing
    it. This makes the proxy a drop-in replacement for the previous
    `psycopg2.connect(...)` pattern: callers that do `conn.close()`
    after use now release to the pool transparently.

    The proxy is single-use — once `.close()` is called, the underlying
    conn is back in the pool and the proxy is inert. Calling `.close()`
    twice is harmless.
    """

    __slots__ = ("_conn", "_pool", "_released")

    def __init__(self, conn, pool):
        # Use object.__setattr__ to bypass our __setattr__ forwarding
        object.__setattr__(self, "_conn", conn)
        object.__setattr__(self, "_pool", pool)
        object.__setattr__(self, "_released", False)

    def __getattr__(self, name):
        # Called only when name is not found on the proxy itself.
        return getattr(self._conn, name)

    def __setattr__(self, name, value):
        # Forward attribute writes to the underlying conn so callers
        # that do `conn.autocommit = True` etc. work as expected.
        if name in self.__slots__:
            object.__setattr__(self, name, value)
        else:
            setattr(self._conn, name, value)

    def cursor(self, *args, **kwargs):
        return self._conn.cursor(*args, **kwargs)

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        if self._released:
            return
        object.__setattr__(self, "_released", True)
        # Defensive cleanup: rollback any half-finished tx so the next
        # user gets a clean conn.
        try:
            if not self._conn.closed:
                self._conn.rollback()
        except Exception:
            pass
        try:
            broken = bool(getattr(self._conn, "closed", 0))
            if broken:
                # Pool will discard and rebuild on next getconn
                self._pool.putconn(self._conn, close=True)
            else:
                self._pool.putconn(self._conn)
        except Exception as e:
            log.debug("pg_pool: putconn failed (will be discarded): %s", e)

    def __enter__(self):
        # psycopg2 connections support `with conn:` for tx management
        # (commit on success, rollback on exception). Forward, but DO
        # NOT close — caller still owns the conn lifecycle via .close().
        return self._conn.__enter__()

    def __exit__(self, exc_type, exc, tb):
        return self._conn.__exit__(exc_type, exc, tb)


def get_pooled_conn():
    """Return a pooled connection wrapped in _PooledConnProxy.

    Returns None when DATABASE_URL is unset (SQLite mode). Caller MUST
    call `.close()` to return the conn to the pool. Calling `.close()`
    multiple times is safe.
    """
    pool = _get_pool()
    if pool is None:
        return None
    try:
        raw = pool.getconn()
    except Exception as e:
        log.warning("pg_pool: getconn failed: %s", e)
        return None
    return _PooledConnProxy(raw, pool)


@contextmanager
def pooled_conn():
    """Context-manager variant — guaranteed release on exit.

    Yields the proxy or None (SQLite mode). Prefer this in new code:

        from api.db.pg_pool import pooled_conn
        with pooled_conn() as conn:
            if conn is None:
                ... sqlite fallback ...
            else:
                cur = conn.cursor()
                ...
    """
    proxy = get_pooled_conn()
    try:
        yield proxy
    finally:
        if proxy is not None:
            try:
                proxy.close()
            except Exception:
                pass


def shutdown():
    """Close all pool connections. Call from app shutdown lifespan."""
    global _pool
    with _pool_lock:
        if _pool is not None:
            try:
                _pool.closeall()
            except Exception:
                pass
            _pool = None
            log.info("pg_pool: shutdown complete")
