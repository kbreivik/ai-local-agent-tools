"""agent_llm_traces + agent_llm_system_prompts — v2.34.14.

Persists full LLM round-trip data for post-hoc analysis of hallucinations,
fabrications, and agent behaviour. The system prompt is stored once per
operation (it's large and constant); per-step rows hold only the delta
messages and the raw response.

Retention: 7 days by default (AGENT_LLM_TRACE_RETENTION_DAYS env).
"""
import json
import logging
import os
from datetime import datetime, timezone

log = logging.getLogger(__name__)

_DDL_TRACES = """
CREATE TABLE IF NOT EXISTS agent_llm_traces (
    operation_id    TEXT NOT NULL,
    step_index      INTEGER NOT NULL,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    agent_type      TEXT,
    is_subagent     BOOLEAN NOT NULL DEFAULT FALSE,
    parent_op_id    TEXT,
    messages_delta  JSONB NOT NULL,
    response_raw    JSONB NOT NULL,
    tokens_prompt     INTEGER,
    tokens_completion INTEGER,
    tokens_total      INTEGER,
    temperature       REAL,
    model             TEXT,
    finish_reason     TEXT,
    tool_calls_count  INTEGER DEFAULT 0,
    PRIMARY KEY (operation_id, step_index)
);
CREATE INDEX IF NOT EXISTS idx_llm_traces_parent
    ON agent_llm_traces (parent_op_id) WHERE parent_op_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_llm_traces_ts
    ON agent_llm_traces (timestamp DESC);
"""

_DDL_PROMPTS = """
CREATE TABLE IF NOT EXISTS agent_llm_system_prompts (
    operation_id    TEXT PRIMARY KEY,
    system_prompt   TEXT NOT NULL,
    tools_manifest  JSONB NOT NULL,
    prompt_chars    INTEGER,
    tools_count     INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

_initialized = False


def _is_pg() -> bool:
    return "postgres" in os.environ.get("DATABASE_URL", "")


def init_llm_traces() -> None:
    """Create tables if missing. Safe to call multiple times."""
    global _initialized
    if _initialized:
        return
    if not _is_pg():
        _initialized = True
        return
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        for block in (_DDL_TRACES, _DDL_PROMPTS):
            for stmt in block.strip().split(";"):
                s = stmt.strip()
                if s:
                    cur.execute(s)
        cur.close()
        conn.close()
        _initialized = True
        log.info("agent_llm_traces tables ready")
    except Exception as e:
        log.warning("agent_llm_traces init failed: %s", e)


def _is_enabled() -> bool:
    return os.environ.get("AGENT_LLM_TRACE_ENABLED", "true").lower() in (
        "1", "true", "yes"
    )


def write_system_prompt(
    operation_id: str,
    system_prompt: str,
    tools_manifest: list | None = None,
) -> None:
    """Write the per-operation system prompt and tools manifest. Idempotent."""
    if not _is_enabled() or not _is_pg() or not operation_id or not system_prompt:
        return
    try:
        init_llm_traces()
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        manifest_json = json.dumps(tools_manifest or [])
        cur.execute(
            """INSERT INTO agent_llm_system_prompts
                   (operation_id, system_prompt, tools_manifest,
                    prompt_chars, tools_count)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (operation_id) DO NOTHING""",
            (
                str(operation_id),
                system_prompt,
                manifest_json,
                len(system_prompt or ""),
                len(tools_manifest or []),
            ),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        log.debug("write_system_prompt failed: %s", e)


def write_trace_step(
    operation_id: str,
    step_index: int,
    messages_delta: list,
    response_raw: dict,
    agent_type: str | None = None,
    is_subagent: bool = False,
    parent_op_id: str | None = None,
    temperature: float | None = None,
    model: str | None = None,
) -> None:
    """Persist one LLM round-trip step. Never raises."""
    if not _is_enabled() or not _is_pg() or not operation_id:
        return
    try:
        init_llm_traces()
        usage = (response_raw or {}).get("usage") or {}
        finish_reason = ""
        tool_calls_count = 0
        try:
            choice = (response_raw or {}).get("choices") or [{}]
            first = choice[0] if choice else {}
            finish_reason = first.get("finish_reason", "") or ""
            msg = (first.get("message") or {})
            tool_calls_count = len(msg.get("tool_calls") or [])
        except Exception:
            pass

        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO agent_llm_traces
                   (operation_id, step_index, agent_type, is_subagent,
                    parent_op_id, messages_delta, response_raw,
                    tokens_prompt, tokens_completion, tokens_total,
                    temperature, model, finish_reason, tool_calls_count)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (operation_id, step_index) DO NOTHING""",
            (
                str(operation_id),
                int(step_index),
                agent_type,
                bool(is_subagent),
                str(parent_op_id) if parent_op_id else None,
                json.dumps(messages_delta or []),
                json.dumps(response_raw or {}),
                usage.get("prompt_tokens"),
                usage.get("completion_tokens"),
                usage.get("total_tokens"),
                temperature,
                model,
                finish_reason,
                tool_calls_count,
            ),
        )
        conn.commit()
        cur.close()
        conn.close()

        try:
            from api.metrics import LLM_TRACES_WRITTEN_COUNTER
            LLM_TRACES_WRITTEN_COUNTER.labels(
                step_type="subagent" if is_subagent else "root"
            ).inc()
        except Exception:
            pass
    except Exception as e:
        log.debug("write_trace_step failed: %s", e)


def get_trace(operation_id: str) -> dict:
    """Fetch a complete trace for an operation.

    Returns:
      {"system_prompt": str|None, "tools_count": int|None, "steps": [rows...]}
    """
    result = {"system_prompt": None, "tools_count": None, "steps": []}
    if not _is_pg() or not operation_id:
        return result
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            """SELECT system_prompt, tools_manifest, prompt_chars, tools_count
               FROM agent_llm_system_prompts WHERE operation_id = %s""",
            (str(operation_id),),
        )
        sp_row = cur.fetchone()
        if sp_row:
            result["system_prompt"] = sp_row[0]
            result["tools_count"] = sp_row[3]
            result["prompt_chars"] = sp_row[2]

        cur.execute(
            """SELECT step_index, timestamp, messages_delta, response_raw,
                      tokens_prompt, tokens_completion, tokens_total,
                      temperature, finish_reason, tool_calls_count,
                      agent_type, is_subagent, parent_op_id, model
               FROM agent_llm_traces WHERE operation_id = %s
               ORDER BY step_index""",
            (str(operation_id),),
        )
        rows = cur.fetchall()
        for r in rows:
            msgs = r[2]
            resp = r[3]
            # psycopg2 returns JSONB as dict/list already
            if isinstance(msgs, str):
                try:
                    msgs = json.loads(msgs)
                except Exception:
                    msgs = []
            if isinstance(resp, str):
                try:
                    resp = json.loads(resp)
                except Exception:
                    resp = {}
            result["steps"].append({
                "step_index": r[0],
                "timestamp": r[1].isoformat() if r[1] else None,
                "messages_delta": msgs,
                "response_raw": resp,
                "tokens_prompt": r[4],
                "tokens_completion": r[5],
                "tokens_total": r[6],
                "temperature": r[7],
                "finish_reason": r[8],
                "tool_calls_count": r[9],
                "agent_type": r[10],
                "is_subagent": r[11],
                "parent_op_id": r[12],
                "model": r[13],
            })
        cur.close()
        conn.close()
    except Exception as e:
        log.debug("get_trace failed: %s", e)
    return result


def render_digest(trace: dict) -> str:
    """Render a compact markdown digest of the trace."""
    lines: list[str] = []
    if trace.get("system_prompt"):
        lines.append(
            f"# System prompt: {trace.get('prompt_chars') or len(trace['system_prompt'])} "
            f"chars, {trace.get('tools_count') or 0} tools exposed"
        )
        lines.append("")
    for r in trace.get("steps", []):
        lines.append(
            f"## Step {r['step_index']} — finish={r.get('finish_reason','')} "
            f"tools={r.get('tool_calls_count', 0)} "
            f"toks={r.get('tokens_total')}"
        )
        resp = r.get("response_raw") or {}
        try:
            choice = (resp.get("choices") or [{}])[0]
            msg = choice.get("message") or {}
            content = msg.get("content") or ""
            if content:
                trunc = content[:400]
                if len(content) > 400:
                    trunc += "..."
                lines.append(f"**Assistant:** {trunc}")
            for tc in (msg.get("tool_calls") or []):
                fn = tc.get("function", {}) or {}
                args = str(fn.get("arguments", ""))[:200]
                lines.append(f"- `{fn.get('name','')}({args})`")
        except Exception as e:
            lines.append(f"*Malformed response: {e}*")
        for m in (r.get("messages_delta") or []):
            role = m.get("role") if isinstance(m, dict) else ""
            if role == "tool":
                content_preview = (m.get("content") or "")[:300]
                more = "..." if len(m.get("content") or "") > 300 else ""
                lines.append(f"- tool_result: {content_preview}{more}")
            elif role == "user":
                user_preview = (m.get("content") or "")[:200]
                lines.append(f"- **User/harness:** {user_preview}")
        lines.append("")
    return "\n".join(lines)
