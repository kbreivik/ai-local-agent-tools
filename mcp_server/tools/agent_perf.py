"""Agent self-monitoring tool — read-only query of operations + LLM traces.

Returns aggregated agent performance over the past N hours: total run
count, per-(agent_type, status) breakdown, overall success rate,
median wall-clock per agent_type, and top-10 task labels that ended in
a failure-like status. The `agent_type` field lives on the
`agent_llm_traces` table (one row per LLM step), not on `operations`,
so this query joins the two. Sync-only, no HTTP fetch.
"""
import logging

log = logging.getLogger(__name__)


def agent_performance_summary(hours_back: int = 24) -> dict:
    """Return aggregated agent performance over the past N hours.

    Args:
        hours_back: Window size in hours (clamped to [1, 168]).

    Returns:
        {status, message, data: {
            total, buckets: [{agent_type, status, n, median_wall_s}],
            top_failing: [{task_label, status, n}],
            success_rate_pct, summary,
        }}
    """
    try:
        hours_back = int(hours_back)
    except (TypeError, ValueError):
        hours_back = 24
    hours_back = max(1, min(168, hours_back))

    try:
        from sqlalchemy import text
        from api.db.base import get_sync_engine, DB_BACKEND
        eng = get_sync_engine()
    except Exception as e:
        return {
            "status": "error",
            "message": f"agent_performance_summary init failed: {e}",
            "data": {},
        }

    # Backend-specific time-window predicate (NOW() is Postgres;
    # SQLite uses datetime('now', ...)).
    if DB_BACKEND == "postgres":
        cutoff_predicate = (
            f"o.started_at > NOW() - INTERVAL '{hours_back} hours'"
        )
        wall_seconds_expr = (
            "EXTRACT(EPOCH FROM (COALESCE(o.completed_at, NOW()) "
            "- o.started_at))"
        )
        median_expr = (
            "percentile_cont(0.5) WITHIN GROUP (ORDER BY "
            + wall_seconds_expr + ")"
        )
    else:  # sqlite
        cutoff_predicate = (
            f"o.started_at > datetime('now', '-{hours_back} hours')"
        )
        wall_seconds_expr = (
            "(julianday(COALESCE(o.completed_at, 'now')) "
            "- julianday(o.started_at)) * 86400.0"
        )
        # SQLite lacks percentile_cont; use AVG as a documented fallback
        # (median is not critical for this meta-tool).
        median_expr = "AVG(" + wall_seconds_expr + ")"

    try:
        with eng.connect() as conn:
            # Total run count in window
            total_row = conn.execute(
                text(
                    f"SELECT COUNT(*) AS n FROM operations o "
                    f"WHERE {cutoff_predicate}"
                )
            ).mappings().first()
            total = int((total_row or {}).get("n") or 0)

            if total == 0:
                return {
                    "status": "ok",
                    "message": f"No runs in past {hours_back}h",
                    "data": {"total": 0, "hours_back": hours_back,
                             "summary": "no runs"},
                }

            # Per-(agent_type, status) buckets.  agent_type lives on
            # agent_llm_traces; an operation may have many trace rows,
            # so we pick one representative agent_type per operation via
            # the earliest step_index (the primary agent type for the
            # run).
            buckets_rows = conn.execute(
                text(
                    f"""
                    WITH op_agent AS (
                        SELECT operation_id, agent_type,
                               ROW_NUMBER() OVER (
                                   PARTITION BY operation_id
                                   ORDER BY step_index ASC
                               ) AS rn
                        FROM agent_llm_traces
                    )
                    SELECT COALESCE(oa.agent_type, 'unknown') AS agent_type,
                           o.status AS status,
                           COUNT(*) AS n,
                           {median_expr} AS median_wall_s
                    FROM operations o
                    LEFT JOIN op_agent oa
                      ON CAST(oa.operation_id AS TEXT) = CAST(o.id AS TEXT)
                     AND oa.rn = 1
                    WHERE {cutoff_predicate}
                    GROUP BY COALESCE(oa.agent_type, 'unknown'), o.status
                    """
                )
            ).mappings().all()
            buckets = [dict(r) for r in buckets_rows]

            # Top-failing task labels
            failing_rows = conn.execute(
                text(
                    f"""
                    SELECT o.label AS task_label,
                           o.status AS status,
                           COUNT(*) AS n
                    FROM operations o
                    WHERE {cutoff_predicate}
                      AND o.status IN ('error', 'capped', 'escalated',
                                       'failed', 'cancelled')
                    GROUP BY o.label, o.status
                    ORDER BY COUNT(*) DESC
                    LIMIT 10
                    """
                )
            ).mappings().all()
            top_failing = [dict(r) for r in failing_rows]
    except Exception as e:
        return {
            "status": "error",
            "message": f"operations query failed: {e}",
            "data": {},
        }

    completed = sum(int(b.get("n") or 0) for b in buckets
                    if b.get("status") == "completed")
    success_rate = round(completed / total * 100.0, 1) if total else 0.0

    for b in buckets:
        if b.get("median_wall_s") is not None:
            try:
                b["median_wall_s"] = round(float(b["median_wall_s"]), 1)
            except (TypeError, ValueError):
                pass

    summary_prefix = (
        f"{total} runs in past {hours_back}h, {completed} completed "
        f"({success_rate}%)"
    )
    if top_failing:
        tf_snippets = ", ".join(
            f"{r['task_label']} ({r['n']}x {r['status']})"
            for r in top_failing[:3]
        )
        summary = f"{summary_prefix}. Top-failing tasks: {tf_snippets}"
    else:
        summary = f"{summary_prefix}. No failing tasks."

    return {
        "status": "ok",
        "message": summary,
        "data": {
            "total": total,
            "hours_back": hours_back,
            "buckets": buckets,
            "top_failing": top_failing,
            "success_rate_pct": success_rate,
            "summary": summary,
        },
    }
