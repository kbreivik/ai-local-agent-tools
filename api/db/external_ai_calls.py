"""external_ai_calls — per-call billing + outcome log for external AI.

Writes one row per external AI round-trip (v2.36.3+). Distinct from
agent_llm_traces (which is the OpenAI-shape per-step dump) — this table is
billing-focused: which rule fired, which provider, how much it cost, and
whether the output survived the harness gates.
"""
import json
import logging
import os

log = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS external_ai_calls (
    id              SERIAL PRIMARY KEY,
    operation_id    TEXT NOT NULL,
    step_index      INTEGER,
    provider        TEXT NOT NULL,
    model           TEXT NOT NULL,
    rule_fired      TEXT NOT NULL,
    output_mode     TEXT NOT NULL,
    latency_ms      INTEGER,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    est_cost_usd    REAL,
    outcome         TEXT NOT NULL,
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_external_ai_calls_op
    ON external_ai_calls (operation_id);
CREATE INDEX IF NOT EXISTS idx_external_ai_calls_created
    ON external_ai_calls (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_external_ai_calls_rule
    ON external_ai_calls (rule_fired, created_at DESC);
"""

_initialized = False


def _is_pg() -> bool:
    return "postgres" in os.environ.get("DATABASE_URL", "")


def init_external_ai_calls() -> None:
    global _initialized
    if _initialized or not _is_pg():
        _initialized = True
        return
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        for stmt in _DDL.strip().split(";"):
            s = stmt.strip()
            if s:
                cur.execute(s)
        cur.close()
        conn.close()
        _initialized = True
        log.info("external_ai_calls table ready")
    except Exception as e:
        log.warning("external_ai_calls init failed: %s", e)


def write_external_ai_call(
    *,
    operation_id: str,
    step_index: int | None,
    provider: str,
    model: str,
    rule_fired: str,
    output_mode: str,
    latency_ms: int | None,
    input_tokens: int | None,
    output_tokens: int | None,
    est_cost_usd: float | None,
    outcome: str,
    error_message: str | None = None,
) -> None:
    """Persist one external AI call. Never raises.

    outcome ∈ {'success', 'rejected_by_gate', 'auth_error',
               'network_error', 'timeout', 'cancelled_by_user'}
    """
    if not _is_pg() or not operation_id:
        return
    try:
        init_external_ai_calls()
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO external_ai_calls
                   (operation_id, step_index, provider, model, rule_fired,
                    output_mode, latency_ms, input_tokens, output_tokens,
                    est_cost_usd, outcome, error_message)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                str(operation_id),
                int(step_index) if step_index is not None else None,
                provider,
                model,
                rule_fired,
                output_mode,
                int(latency_ms) if latency_ms is not None else None,
                int(input_tokens) if input_tokens is not None else None,
                int(output_tokens) if output_tokens is not None else None,
                float(est_cost_usd) if est_cost_usd is not None else None,
                outcome,
                (error_message or "")[:500] or None,
            ),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        log.warning("write_external_ai_call failed: %s", e)


def list_recent_external_calls(limit: int = 20) -> list[dict]:
    """Return the last N external AI calls for the UI dashboard."""
    if not _is_pg():
        return []
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            """SELECT id, operation_id, step_index, provider, model,
                      rule_fired, output_mode, latency_ms, input_tokens,
                      output_tokens, est_cost_usd, outcome, error_message,
                      created_at
               FROM external_ai_calls
               ORDER BY created_at DESC
               LIMIT %s""",
            (int(limit),),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [
            {
                "id": r[0], "operation_id": r[1], "step_index": r[2],
                "provider": r[3], "model": r[4], "rule_fired": r[5],
                "output_mode": r[6], "latency_ms": r[7],
                "input_tokens": r[8], "output_tokens": r[9],
                "est_cost_usd": r[10], "outcome": r[11],
                "error_message": r[12],
                "created_at": r[13].isoformat() if r[13] else None,
            }
            for r in rows
        ]
    except Exception as e:
        log.warning("list_recent_external_calls failed: %s", e)
        return []
