# CC PROMPT — v2.45.19 — feat(tests): schedule executor — read test_schedules and fire runs at cron times

## What this does
Wires the 7 configured test schedules (daily-smoke-0200 etc.) to actually
execute. Currently they are write-only — the table is populated, but no loop
reads it. Adds a startup background task that polls `test_schedules` every
30s, parses cron strings, and fires `_run_tests_bg` when the next_run_at
window arrives. Updates `last_run_at` and recomputes `next_run_at`.

Adds `croniter` to requirements.txt.

Version bump: 2.45.18 → 2.45.19

---

## Change 1 — `requirements.txt`

Add to the bottom of the file:

```
croniter>=2.0.0
```

---

## Change 2 — NEW FILE — `api/scheduler.py`

Create new file `api/scheduler.py`:

```python
"""Test schedule executor — v2.45.19.

Polls test_schedules every 30s. For each enabled schedule whose next_run_at
has passed (or is null on first run), fires _run_tests_bg with the suite_id
and stamps last_run_at + recomputes next_run_at from the cron string.

Triggered_by='schedule' so DB rows are distinguishable from manual runs.
"""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)


def _next_from_cron(cron_str: str, base: datetime) -> datetime | None:
    """Compute next fire time after `base` from a cron string. UTC."""
    try:
        from croniter import croniter
        it = croniter(cron_str, base)
        return it.get_next(datetime)
    except Exception as e:
        log.warning("scheduler: invalid cron '%s': %s", cron_str, e)
        return None


def _update_schedule_times(schedule_id: str, ran_at: datetime,
                           next_at: datetime | None) -> None:
    """Stamp last_run_at; set next_run_at; non-PG environments are no-ops."""
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        if not conn:
            return
        cur = conn.cursor()
        cur.execute(
            "UPDATE test_schedules SET last_run_at=%s, next_run_at=%s "
            "WHERE id=%s",
            (ran_at, next_at, schedule_id),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        log.debug("scheduler: stamp times failed for %s: %s", schedule_id, e)


async def _scheduler_loop(poll_interval_s: int = 30) -> None:
    """Inner loop. Sleeps, evaluates, fires due schedules."""
    log.info("test_scheduler started — poll interval %ds", poll_interval_s)
    # First pass: hydrate next_run_at for any schedules where it is NULL.
    try:
        from api.db import test_runs as _tr
        now0 = datetime.now(timezone.utc)
        for sch in _tr.list_schedules():
            if sch.get("enabled") and not sch.get("next_run_at"):
                nxt = _next_from_cron(sch.get("cron") or "", now0)
                if nxt:
                    _update_schedule_times(sch["id"], sch.get("last_run_at"), nxt)
    except Exception as e:
        log.debug("scheduler: hydrate pass failed: %s", e)

    while True:
        try:
            await asyncio.sleep(poll_interval_s)
            now = datetime.now(timezone.utc)
            from api.db import test_runs as _tr
            from api.routers.tests_api import _run_tests_bg

            for sch in _tr.list_schedules():
                if not sch.get("enabled"):
                    continue
                next_at = sch.get("next_run_at")
                # If next_run_at is null, treat as "fire on next eligible tick"
                if next_at and now < next_at:
                    continue

                cron = sch.get("cron") or ""
                suite_id = sch.get("suite_id")
                if not suite_id:
                    log.debug("scheduler: schedule %s has no suite_id, skipping",
                              sch["id"])
                    continue

                # Fire and forget (suite resolved inside _run_tests_bg)
                log.info("scheduler: firing schedule '%s' (suite=%s, cron=%s)",
                         sch.get("name", "?"), suite_id, cron)
                try:
                    asyncio.create_task(_run_tests_bg(
                        categories=None,
                        test_ids=None,
                        suite_id=suite_id,
                        memory_enabled=None,
                        memory_backend=None,
                        suite_name=sch.get("name", ""),
                        caller_token="",
                    ))
                except Exception as e:
                    log.error("scheduler: failed to spawn run for %s: %s",
                              sch["id"], e)
                    continue

                # Recompute next_run_at from the cron string
                nxt = _next_from_cron(cron, now)
                _update_schedule_times(sch["id"], now, nxt)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("scheduler: tick failed: %s", e)


_task: asyncio.Task | None = None


def start_scheduler() -> None:
    """Start the scheduler loop; idempotent."""
    global _task
    if _task and not _task.done():
        return
    _task = asyncio.create_task(_scheduler_loop())


def stop_scheduler() -> None:
    """Cancel the scheduler loop."""
    global _task
    if _task and not _task.done():
        _task.cancel()
        _task = None
```

---

## Change 3 — `api/main.py` — start scheduler in lifespan

Find this block in the `lifespan` function (near the bottom, after auto-update
start, before the bookstack scheduler):

```python
    # Start auto-update background check
    try:
        from api.routers.dashboard import start_auto_update, stop_auto_update
        start_auto_update()
    except Exception as e:
        _log.warning("Auto-update start skipped: %s", e)
```

Right AFTER this block, insert:

```python
    # v2.45.19 — Test schedule executor: read test_schedules every 30s
    # and fire _run_tests_bg for schedules whose next_run_at has arrived.
    try:
        from api.scheduler import start_scheduler
        start_scheduler()
    except Exception as e:
        _log.warning("Test scheduler start skipped: %s", e)
```

Also find the lifespan shutdown section (the `yield` and what follows). After:

```python
    try:
        stop_auto_update()
    except Exception:
        pass
```

Insert:

```python
    try:
        from api.scheduler import stop_scheduler
        stop_scheduler()
    except Exception:
        pass
```

---

## Verify

```bash
python -m py_compile api/scheduler.py api/main.py
grep -n "test_scheduler started\|start_scheduler" api/main.py api/scheduler.py
```

Expected: scheduler module compiles, main.py imports it, no syntax errors.

After deploy, container logs should show
`test_scheduler started — poll interval 30s` within seconds of startup.

---

## Version bump

Update `VERSION`: `2.45.18` → `2.45.19`

---

## Commit

```
git add -A
git commit -m "feat(tests): v2.45.19 schedule executor — read test_schedules and fire runs at cron times"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```

After deploy, the daily-smoke-0200 schedule will actually execute at 02:00 UTC.
Verify with `SELECT name, last_run_at, next_run_at FROM test_schedules;`.
