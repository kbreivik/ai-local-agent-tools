"""api/maintenance.py — periodic background tasks for the FastAPI lifespan.

v2.45.33 — extracted from api/main.py:lifespan to reduce cyclomatic
complexity. Each public coroutine here is created via asyncio.create_task
once at startup. They run until cancellation (or process exit). All swallow
exceptions per-iteration so a single failure cannot kill the loop.
"""
from __future__ import annotations

import asyncio
import logging

log = logging.getLogger(__name__)


async def result_store_cleanup_loop() -> None:
    """Purge expired result_store rows every 30 minutes."""
    while True:
        await asyncio.sleep(1800)
        try:
            from api.db.result_store import cleanup_expired
            n = cleanup_expired()
            if n:
                log.info("result_store: purged %d expired rows", n)
        except Exception:
            pass


async def status_snapshot_cleanup_loop() -> None:
    """Daily 30-day retention purge of status_snapshots."""
    while True:
        await asyncio.sleep(86400)
        try:
            from api.db.base import get_engine
            from sqlalchemy import text as _t
            async with get_engine().begin() as conn:
                result = await conn.execute(_t(
                    "DELETE FROM status_snapshots "
                    "WHERE timestamp < NOW() - INTERVAL '30 days'"
                ))
                deleted = result.rowcount
                if deleted:
                    log.info(
                        "status_snapshots cleanup: deleted %d rows older than 30 days",
                        deleted,
                    )
        except Exception as e:
            log.debug("status_snapshots cleanup error: %s", e)


async def metric_samples_cleanup_loop() -> None:
    """Daily 30-day retention purge of metric_samples."""
    while True:
        await asyncio.sleep(86400)
        try:
            from api.db.metric_samples import cleanup_old_samples
            n = cleanup_old_samples(days=30)
            if n:
                log.info(
                    "metric_samples cleanup: deleted %d rows older than 30d", n,
                )
        except Exception as e:
            log.debug("metric_samples cleanup failed: %s", e)


async def operation_log_cleanup_loop() -> None:
    """Hourly retention + per-session trim of operation_log."""
    while True:
        await asyncio.sleep(3600)
        try:
            from mcp_server.tools.skills.storage import get_backend
            retention_days = int(get_backend().get_setting("opLogRetentionDays") or 30)
            from api.session_store import cleanup_old_logs
            n = await cleanup_old_logs(retention_days)
            if n:
                log.info(
                    "operation_log: purged %d rows older than %d days",
                    n, retention_days,
                )
        except Exception as e:
            log.debug("operation_log cleanup failed: %s", e)


async def llm_trace_cleanup_loop() -> None:
    """Daily retention purge of agent_llm_traces."""
    while True:
        await asyncio.sleep(86400)
        try:
            from api.db.llm_trace_retention import purge_old_traces
            r = purge_old_traces()
            if r.get("steps_purged") or r.get("prompts_purged"):
                log.info(
                    "llm_traces cleanup: purged %d steps, %d prompts",
                    r["steps_purged"], r["prompts_purged"],
                )
        except Exception as e:
            log.debug("llm_traces cleanup failed: %s", e)


async def refresh_facts_gauges_loop() -> None:
    """v2.35.0 — periodic Prometheus gauge refresh from known_facts."""
    while True:
        await asyncio.sleep(60)
        try:
            from api.db.known_facts import get_gauge_snapshot
            from api.metrics import (
                KNOWN_FACTS_TOTAL, KNOWN_FACTS_CONFIDENT_TOTAL,
                KNOWN_FACTS_CONFLICTS_TOTAL, FACTS_REFRESH_STALE_GAUGE,
            )
            snap = get_gauge_snapshot()
            KNOWN_FACTS_TOTAL.set(snap.get("total", 0))
            KNOWN_FACTS_CONFIDENT_TOTAL.set(snap.get("confident", 0))
            KNOWN_FACTS_CONFLICTS_TOTAL.set(snap.get("pending_conflicts", 0))
            for platform, count in (snap.get("stale_by_platform") or {}).items():
                FACTS_REFRESH_STALE_GAUGE.labels(platform=platform).set(count)
        except Exception:
            pass


async def preflight_timeout_sweeper_loop() -> None:
    """v2.35.1 — auto-cancel preflight-awaiting operations past timeout."""
    while True:
        await asyncio.sleep(60)
        try:
            from api.db.base import get_engine
            from sqlalchemy import text as _t
            timeout_sec = 300
            try:
                async with get_engine().connect() as conn:
                    r = await conn.execute(_t(
                        "SELECT value FROM settings "
                        "WHERE key='preflightDisambiguationTimeout'"
                    ))
                    row = r.fetchone()
                    if row and row[0]:
                        timeout_sec = int(row[0])
            except Exception:
                pass
            async with get_engine().begin() as conn:
                res = await conn.execute(_t(
                    "UPDATE operations SET status='cancelled', "
                    "final_answer='preflight clarification timeout' "
                    "WHERE status='awaiting_clarification' "
                    "  AND created_at < NOW() - (:sec || ' seconds')::interval "
                    "RETURNING id"
                ), {"sec": timeout_sec})
                cancelled = res.fetchall() or []
            for _row in cancelled:
                try:
                    from api.agents.preflight import record_disambiguation_outcome
                    record_disambiguation_outcome("timeout")
                except Exception:
                    pass
        except Exception as e:
            log.debug("preflight timeout sweeper failed: %s", e)
