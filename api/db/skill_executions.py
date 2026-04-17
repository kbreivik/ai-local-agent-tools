"""skill_executions + auto_promoter_scans helpers (v2.34.2).

Adoption / observability telemetry for the skill system:
  - skill_executions:      one row per skill_execute invocation
  - auto_promoter_scans:   one row per auto-promoter scan

All writes are sync, non-blocking, and swallow their own errors so they
never break the dispatch path or the scheduler loop.
"""
import json
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import text as _t

log = logging.getLogger(__name__)


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_conn():
    try:
        from api.db.base import get_sync_engine
        return get_sync_engine().connect()
    except Exception as e:
        log.debug("skill_executions get_conn failed: %s", e)
        return None


# ── skill_executions ─────────────────────────────────────────────────────────

def record_start(
    *,
    skill_id: str,
    task_id: str = "",
    agent_type: str = "unknown",
    invoked_by: str = "agent",
    args: Optional[dict] = None,
) -> str:
    """Insert a new skill_executions row. Returns the execution id (or "" on failure)."""
    exec_id = uuid.uuid4().hex[:16]
    conn = _get_conn()
    if not conn:
        return ""
    try:
        conn.execute(_t("""
            INSERT INTO skill_executions
                (id, skill_id, task_id, agent_type, invoked_by, args, started_at)
            VALUES
                (:id, :sid, :tid, :at, :iby, :args, :started)
        """), {
            "id": exec_id,
            "sid": skill_id,
            "tid": task_id or "",
            "at": agent_type or "unknown",
            "iby": invoked_by or "",
            "args": json.dumps(args or {}, default=str)[:4096],
            "started": _ts(),
        })
        conn.commit()
        return exec_id
    except Exception as e:
        log.debug("record_start failed: %s", e)
        return ""
    finally:
        try: conn.close()
        except Exception: pass


def record_end(
    exec_id: str,
    *,
    outcome: str,
    result_summary: Optional[str] = None,
    error: Optional[str] = None,
    started_at_iso: Optional[str] = None,
) -> None:
    """Finalise a skill_executions row with outcome + duration."""
    if not exec_id:
        return
    conn = _get_conn()
    if not conn:
        return
    try:
        now = datetime.now(timezone.utc)
        completed = now.isoformat()
        duration_ms = None
        if started_at_iso:
            try:
                started = datetime.fromisoformat(started_at_iso)
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
                duration_ms = int((now - started).total_seconds() * 1000)
            except Exception:
                duration_ms = None
        if duration_ms is None:
            # Derive from DB row if started_at not passed
            row = conn.execute(
                _t("SELECT started_at FROM skill_executions WHERE id = :id"),
                {"id": exec_id},
            ).fetchone()
            if row and row[0]:
                try:
                    started = datetime.fromisoformat(str(row[0]))
                    if started.tzinfo is None:
                        started = started.replace(tzinfo=timezone.utc)
                    duration_ms = int((now - started).total_seconds() * 1000)
                except Exception:
                    duration_ms = 0
        conn.execute(_t("""
            UPDATE skill_executions
               SET completed_at = :done,
                   duration_ms  = :dur,
                   outcome      = :oc,
                   error        = :err,
                   result_summary = :rs
             WHERE id = :id
        """), {
            "done": completed,
            "dur": int(duration_ms or 0),
            "oc": (outcome or "unknown")[:32],
            "err": (error or "")[:500] or None,
            "rs": (result_summary or "")[:500] or None,
            "id": exec_id,
        })
        conn.commit()
    except Exception as e:
        log.debug("record_end failed: %s", e)
    finally:
        try: conn.close()
        except Exception: pass


def list_executions(*, skill_id: str = "", limit: int = 50) -> list[dict]:
    """Return most recent skill_executions rows, newest first."""
    limit = max(1, min(int(limit or 50), 500))
    conn = _get_conn()
    if not conn:
        return []
    try:
        if skill_id:
            rows = conn.execute(_t("""
                SELECT id, skill_id, task_id, agent_type, invoked_by, args,
                       started_at, completed_at, duration_ms, outcome, error,
                       result_summary
                  FROM skill_executions
                 WHERE skill_id = :sid
                 ORDER BY started_at DESC
                 LIMIT :lim
            """), {"sid": skill_id, "lim": limit}).mappings().fetchall()
        else:
            rows = conn.execute(_t("""
                SELECT id, skill_id, task_id, agent_type, invoked_by, args,
                       started_at, completed_at, duration_ms, outcome, error,
                       result_summary
                  FROM skill_executions
                 ORDER BY started_at DESC
                 LIMIT :lim
            """), {"lim": limit}).mappings().fetchall()
        out = []
        for r in rows:
            d = dict(r)
            a = d.get("args")
            if isinstance(a, str):
                try: d["args"] = json.loads(a)
                except Exception: pass
            out.append(d)
        return out
    except Exception as e:
        log.debug("list_executions failed: %s", e)
        return []
    finally:
        try: conn.close()
        except Exception: pass


def per_skill_metrics(*, since_iso: str) -> list[dict]:
    """Left-join skills with aggregate execution stats since ``since_iso``."""
    conn = _get_conn()
    if not conn:
        return []
    try:
        # The skills table lives in the skill registry backend. The column names
        # (id, name, created_at) are consistent across the Postgres and SQLite
        # storage backends (see mcp_server/tools/skills/storage/*).
        rows = conn.execute(_t("""
            SELECT s.id                                      AS id,
                   s.name                                    AS name,
                   s.created_at                              AS created_at,
                   COUNT(e.id)                               AS execution_count,
                   SUM(CASE WHEN e.outcome='success' THEN 1 ELSE 0 END) AS successes,
                   SUM(CASE WHEN e.outcome='error'   THEN 1 ELSE 0 END) AS errors,
                   AVG(e.duration_ms)                        AS avg_duration_ms,
                   MAX(e.started_at)                         AS last_run
              FROM skills s
              LEFT JOIN skill_executions e
                     ON e.skill_id = s.id
                    AND e.started_at >= :since
             GROUP BY s.id, s.name, s.created_at
             ORDER BY execution_count DESC, s.name
        """), {"since": since_iso}).mappings().fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        log.debug("per_skill_metrics failed: %s", e)
        return []
    finally:
        try: conn.close()
        except Exception: pass


# ── auto_promoter_scans ──────────────────────────────────────────────────────

def record_scan(
    *,
    window_days: int,
    actions_scanned: int,
    candidates_found: int,
    candidates_new: int,
    duration_ms: int,
    triggered_by: str = "cron",
) -> str:
    """Insert a single auto_promoter_scans row."""
    scan_id = uuid.uuid4().hex[:16]
    conn = _get_conn()
    if not conn:
        return ""
    try:
        conn.execute(_t("""
            INSERT INTO auto_promoter_scans
                (id, scanned_at, window_days, actions_scanned,
                 candidates_found, candidates_new, duration_ms, triggered_by)
            VALUES
                (:id, :ts, :wd, :asn, :cf, :cn, :dur, :tb)
        """), {
            "id": scan_id,
            "ts": _ts(),
            "wd": int(window_days),
            "asn": int(actions_scanned),
            "cf": int(candidates_found),
            "cn": int(candidates_new),
            "dur": int(duration_ms),
            "tb": (triggered_by or "cron")[:64],
        })
        conn.commit()
        return scan_id
    except Exception as e:
        log.debug("record_scan failed: %s", e)
        return ""
    finally:
        try: conn.close()
        except Exception: pass


def promoter_summary(*, since_iso: str) -> dict:
    """Aggregate auto_promoter_scans activity since ``since_iso``."""
    conn = _get_conn()
    if not conn:
        return {"scans": 0, "last_scan": None,
                "total_new_candidates": 0, "total_candidates_seen": 0}
    try:
        row = conn.execute(_t("""
            SELECT COUNT(*)                  AS scans,
                   MAX(scanned_at)           AS last_scan,
                   COALESCE(SUM(candidates_new),0)   AS total_new_candidates,
                   COALESCE(SUM(candidates_found),0) AS total_candidates_seen
              FROM auto_promoter_scans
             WHERE scanned_at >= :since
        """), {"since": since_iso}).mappings().fetchone()
        return dict(row) if row else {
            "scans": 0, "last_scan": None,
            "total_new_candidates": 0, "total_candidates_seen": 0,
        }
    except Exception as e:
        log.debug("promoter_summary failed: %s", e)
        return {"scans": 0, "last_scan": None,
                "total_new_candidates": 0, "total_candidates_seen": 0}
    finally:
        try: conn.close()
        except Exception: pass


def candidate_pipeline() -> dict:
    """Return status -> count for skill_candidates."""
    conn = _get_conn()
    if not conn:
        return {}
    try:
        rows = conn.execute(_t(
            "SELECT status, COUNT(*) AS n FROM skill_candidates GROUP BY status"
        )).mappings().fetchall()
        return {r["status"]: r["n"] for r in rows}
    except Exception as e:
        log.debug("candidate_pipeline failed: %s", e)
        return {}
    finally:
        try: conn.close()
        except Exception: pass


def since_iso(window_days: int) -> str:
    window_days = max(1, min(int(window_days or 7), 90))
    return (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
