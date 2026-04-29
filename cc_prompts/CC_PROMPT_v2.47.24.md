# CC PROMPT — v2.47.24 — feat(db): pg_advisory_lock around destructive tool dispatch

## What this does

Adds a Postgres advisory-lock guard around any destructive tool call
so that exactly one destructive operation can run platform-wide at a
time. Closes the "two operators in two tabs" gap: previously, two
simultaneously-approved plan_action gates could each fire a
restart/drain/power tool concurrently, with no serialisation other
than what the target system enforces.

Mechanism:

- New helper `api/db/pg_advisory.py` wraps `pg_try_advisory_lock` /
  `pg_advisory_unlock`. The lock is bound to a dedicated psycopg2
  connection — when that conn closes, the lock auto-releases. A
  crashed worker therefore cannot deadlock the system.
- A context manager `advisory_lock(name)` raises `LockBusy` when the
  lock is held by another session.
- The tool dispatcher in `api/agents/step_tools.py` (and any per-
  category dispatcher introduced by the v2.45.16 split) recognises a
  hardcoded set of destructive tools and acquires `destructive_global`
  before invoking them.
- If the lock is busy, the tool result is a structured `{"status":
  "busy", "message": "...", "tool": "..."}` and the agent step
  terminates cleanly. The agent surfaces this to the operator via the
  normal tool-result rendering path — no exception bubble-up.

The dedicated psycopg2 connection used for the lock is NOT pooled
(it must persist for the duration of the held lock). The lock helper
closes it explicitly on release. We accept that this opens up to one
extra TCP connection per concurrent destructive op — acceptable given
destructive ops are rare, gated, and bounded.

Version bump: 2.47.23 → 2.47.24

---

## Change 1 — new file: `api/db/pg_advisory.py`

Create the file with exactly this content:

```python
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
```

## Change 2 — wire into the tool dispatcher

CC: read `api/agents/step_tools.py` first to find the current dispatch
shape (post-v2.45.16 split, dispatch logic may be in step_tools.py
itself, or split across `api/agents/dispatch_*.py` files — do a quick
`grep -rn "tool_name\|handler(args)\|call_tool" api/agents/` to locate
the actual invocation site).

**At the top of the dispatch module**, near the imports, add:

```python
DESTRUCTIVE_TOOLS = frozenset({
    "vm_exec",
    "kafka_exec",
    "proxmox_vm_power",
    "swarm_service_force_update",
    "swarm_node_drain",
    "swarm_node_activate",
})
```

**At the actual tool-invocation site** (the line that calls the
underlying tool function — the names of variables differ depending on
how dispatch is structured; CC must adapt), wrap it:

```python
# BEFORE (conceptual)
result = await call_tool(tool_name, args, ...)
# or
result = handler(args)

# AFTER
if tool_name in DESTRUCTIVE_TOOLS:
    from api.db.pg_advisory import try_acquire, release
    holder = try_acquire("destructive_global")
    if holder is None:
        result = {
            "status": "busy",
            "message": (
                "Another destructive operation is currently running. "
                "Wait for it to finish, then retry."
            ),
            "tool": tool_name,
        }
    else:
        try:
            result = await call_tool(tool_name, args, ...)  # original line
        finally:
            release(holder)
else:
    result = await call_tool(tool_name, args, ...)  # original line
```

If the call is sync (no `await`), drop the `await`. Match whatever
shape the existing call site has — only the wrapping changes.

If dispatch is split across multiple files (e.g. `dispatch_vm.py`,
`dispatch_swarm.py`), apply the same guard wherever a tool from
DESTRUCTIVE_TOOLS actually runs. Easiest: define DESTRUCTIVE_TOOLS in
one shared place (e.g. `api/agents/destructive_tools.py`) and import
from each dispatcher.

## Verify

```bash
# 1. Compile
python -m py_compile api/db/pg_advisory.py
python -m py_compile api/agents/step_tools.py

# 2. Confirm the file exists and the wiring is in place
test -f api/db/pg_advisory.py && echo "pg_advisory.py present"
grep -rn "DESTRUCTIVE_TOOLS\|advisory_lock\|try_acquire" api/agents/

# 3. Live test after deploy:
#    Open two browser tabs. In each, queue a destructive task targeting
#    a different entity (e.g. "restart kafka_broker-1" and
#    "restart kafka_broker-2"). Approve both within a 1-second window.
#    Expected: one completes normally, the other returns the 'busy'
#    tool result and the agent terminates that step cleanly.
```

## Version bump

Update `VERSION`: 2.47.23 → 2.47.24

## Commit

```bash
git add -A
git commit -m "feat(db): advisory locks for destructive tool dispatch (v2.47.24)

Wraps destructive tool invocations in a Postgres advisory lock named
'destructive_global'. Non-blocking try-acquire; on busy, the agent
sees a structured 'busy' result and terminates the step cleanly.
Lock auto-releases on conn close so crashed workers cannot deadlock.

Closes the 'two operators in two tabs' concurrent-destructive gap."
git push origin main
```

## Deploy

```bash
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
