"""Nightly purge of agent_llm_traces older than retention window — v2.34.14.

Retention default: 7 days. Override via AGENT_LLM_TRACE_RETENTION_DAYS.
"""
import logging
import os
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)


def _retention_days() -> int:
    try:
        return int(os.environ.get("AGENT_LLM_TRACE_RETENTION_DAYS", "7"))
    except Exception:
        return 7


def _is_pg() -> bool:
    return "postgres" in os.environ.get("DATABASE_URL", "")


def purge_old_traces() -> dict:
    """Delete trace rows older than the retention window, then drop any
    system_prompt rows whose operation has no remaining traces.

    Never raises. Returns counts dict.
    """
    result = {"steps_purged": 0, "prompts_purged": 0}
    if not _is_pg():
        return result
    try:
        from api.connections import _get_conn
        cutoff = datetime.now(timezone.utc) - timedelta(days=_retention_days())
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM agent_llm_traces WHERE timestamp < %s",
            (cutoff,),
        )
        result["steps_purged"] = cur.rowcount or 0
        cur.execute(
            """DELETE FROM agent_llm_system_prompts
               WHERE operation_id NOT IN (
                   SELECT DISTINCT operation_id FROM agent_llm_traces
               )"""
        )
        result["prompts_purged"] = cur.rowcount or 0
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        log.debug("purge_old_traces failed: %s", e)
    return result
