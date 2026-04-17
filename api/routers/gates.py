"""
GET /api/gates/overview — aggregate state of every safety gate.

Read-only aggregation over agent_actions (v2.31.2), agent_escalations
(v2.15.10), drift_events (v2.33.9), entity_maintenance (v2.31.10), and
operation_log. Each sub-query tolerates a missing/empty source and returns
zeros instead of failing the whole endpoint — the panel stays readable
even when half the gates are unused.
"""
import datetime as _dt
import logging

from fastapi import APIRouter, Depends

from api.auth import get_current_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/gates", tags=["gates"])


def _since(window_hours: int) -> _dt.datetime:
    h = min(max(1, int(window_hours or 24)), 168)
    return _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=h)


def _plan_confirmations(cur, since) -> list[dict]:
    try:
        cur.execute(
            """
            SELECT blast_radius,
                   COUNT(*)                                                            AS total,
                   SUM(CASE WHEN was_planned = TRUE AND result_status = 'ok'
                            THEN 1 ELSE 0 END)                                          AS approved,
                   SUM(CASE WHEN result_status = 'refused' THEN 1 ELSE 0 END)           AS rejected,
                   SUM(CASE WHEN was_planned = TRUE THEN 1 ELSE 0 END)                  AS executed,
                   SUM(CASE WHEN result_status IN ('failed','error') THEN 1 ELSE 0 END) AS failed
              FROM agent_actions
             WHERE timestamp >= %s
             GROUP BY blast_radius
             ORDER BY blast_radius
            """,
            (since,),
        )
        cols = [d[0] for d in cur.description]
        rows = []
        for r in cur.fetchall():
            d = dict(zip(cols, r))
            # Coerce NULL aggregates to 0 for a clean payload
            for k in ("total", "approved", "rejected", "executed", "failed"):
                d[k] = int(d.get(k) or 0)
            d["blast_radius"] = d.get("blast_radius") or "unknown"
            rows.append(d)
        return rows
    except Exception as e:
        log.debug("gates plan_confirmations failed: %s", e)
        return []


def _escalations(cur, since) -> dict:
    empty = {"total": 0, "acknowledged": 0, "open": 0}
    try:
        cur.execute(
            """
            SELECT COUNT(*)                                                              AS total,
                   COALESCE(SUM(CASE WHEN acknowledged       THEN 1 ELSE 0 END), 0)      AS acknowledged,
                   COALESCE(SUM(CASE WHEN NOT acknowledged   THEN 1 ELSE 0 END), 0)      AS open
              FROM agent_escalations
             WHERE created_at >= %s
            """,
            (since,),
        )
        row = cur.fetchone()
        if not row:
            return empty
        cols = [d[0] for d in cur.description]
        return {k: int(v or 0) for k, v in zip(cols, row)}
    except Exception as e:
        log.debug("gates escalations failed: %s", e)
        return empty


def _drift(cur, since) -> dict:
    empty = {"total": 0, "acknowledged": 0, "suppressed": 0, "open": 0}
    try:
        cur.execute(
            """
            SELECT COUNT(*) AS total,
                   COALESCE(SUM(CASE WHEN suppressed_by_maintenance THEN 1 ELSE 0 END), 0) AS suppressed,
                   COALESCE(SUM(CASE WHEN acknowledged               THEN 1 ELSE 0 END), 0) AS acknowledged,
                   COALESCE(SUM(CASE WHEN NOT acknowledged
                             AND NOT suppressed_by_maintenance       THEN 1 ELSE 0 END), 0) AS open
              FROM drift_events
             WHERE snapshot_at >= %s
            """,
            (since,),
        )
        row = cur.fetchone()
        if not row:
            return empty
        cols = [d[0] for d in cur.description]
        return {k: int(v or 0) for k, v in zip(cols, row)}
    except Exception as e:
        log.debug("gates drift failed: %s", e)
        return empty


def _maintenance_active(cur) -> list[dict]:
    try:
        cur.execute(
            """
            SELECT entity_id, reason, set_by, set_at, expires_at
              FROM entity_maintenance
             WHERE expires_at IS NULL OR expires_at > NOW()
             ORDER BY set_at DESC
            """
        )
        cols = [d[0] for d in cur.description]
        out = []
        for r in cur.fetchall():
            d = dict(zip(cols, r))
            out.append({
                "entity_id":  d.get("entity_id"),
                "starts_at":  d["set_at"].isoformat()     if d.get("set_at") else None,
                "ends_at":    d["expires_at"].isoformat() if d.get("expires_at") else None,
                "reason":     d.get("reason") or "",
                "created_by": d.get("set_by") or "",
            })
        return out
    except Exception as e:
        log.debug("gates maintenance_active failed: %s", e)
        return []


def _hard_caps(_cur, _since) -> dict:
    # agent_tasks.terminated_reason counters are emitted by a future release.
    # Until the table lands, zeros keep the GUI happy without the endpoint failing.
    return {"wall_clock": 0, "token_cap": 0, "failure_cap": 0, "destructive_cap": 0}


def _tool_refusals(cur, since) -> list[dict]:
    # operation_log stores metadata as TEXT (JSON-serialised). We look for
    # either a dedicated 'refused' type or a "status":"refused" substring —
    # both are cheap enough over a 168h window.
    try:
        cur.execute(
            """
            SELECT COALESCE(
                       NULLIF(metadata::text::jsonb ->> 'tool', ''),
                       type
                   ) AS tool,
                   COUNT(*) AS count
              FROM operation_log
             WHERE timestamp >= %s
               AND (type = 'refused'
                    OR metadata LIKE '%%"status":"refused"%%'
                    OR metadata LIKE '%%"outcome":"refused"%%')
             GROUP BY tool
             ORDER BY count DESC
             LIMIT 20
            """,
            (since.isoformat(),),
        )
        cols = [d[0] for d in cur.description]
        return [
            {"tool": (r[0] or "unknown"), "count": int(r[1] or 0)}
            for r in cur.fetchall()
        ]
    except Exception as e:
        log.debug("gates tool_refusals failed: %s", e)
        return []


def _empty_payload(window_hours: int, since: _dt.datetime) -> dict:
    return {
        "window_hours":        int(window_hours),
        "since":               since.isoformat(),
        "plan_confirmations":  [],
        "escalations":         {"total": 0, "acknowledged": 0, "open": 0},
        "drift":               {"total": 0, "acknowledged": 0, "suppressed": 0, "open": 0},
        "maintenance_active":  [],
        "hard_caps":           {"wall_clock": 0, "token_cap": 0, "failure_cap": 0, "destructive_cap": 0},
        "tool_refusals":       [],
    }


@router.get("/overview")
async def gates_overview(
    window_hours: int = 24,
    _user: str = Depends(get_current_user),
):
    """Return aggregate gate state over the last window_hours (capped at 168)."""
    since = _since(window_hours)
    result = _empty_payload(window_hours, since)

    try:
        from api.connections import _get_conn
        conn = _get_conn()
    except Exception as e:
        log.debug("gates: db connect failed: %s", e)
        return result

    if conn is None:
        # SQLite backend — advanced aggregates are PG-only for now.
        return result

    try:
        cur = conn.cursor()
        result["plan_confirmations"] = _plan_confirmations(cur, since)
        result["escalations"]        = _escalations(cur, since)
        result["drift"]              = _drift(cur, since)
        result["maintenance_active"] = _maintenance_active(cur)
        result["hard_caps"]          = _hard_caps(cur, since)
        result["tool_refusals"]      = _tool_refusals(cur, since)
        cur.close()
    except Exception as e:
        log.warning("gates overview partial failure: %s", e)
    finally:
        try: conn.close()
        except Exception: pass

    return result
