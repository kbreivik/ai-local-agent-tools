"""agent_actions — immutable forensic record of destructive agent tool calls.

One row per audited tool invocation. Args are redacted before storage.
Never mutated after insert (no update/delete endpoints).

Used by:
  - GET /api/agent/actions (authorised users only)
  - Post-incident forensics ("what did the agent do last Tuesday?")
  - Security reviews (who triggered destructive ops, when, was it planned)
"""
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone

log = logging.getLogger(__name__)

_DDL_PG = """
CREATE TABLE IF NOT EXISTS agent_actions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    session_id      TEXT NOT NULL,
    operation_id    TEXT,
    task_id         TEXT,
    tool_name       TEXT NOT NULL,
    args_redacted   JSONB NOT NULL DEFAULT '{}'::jsonb,
    result_status   TEXT NOT NULL,
    result_summary  TEXT NOT NULL DEFAULT '',
    duration_ms     INTEGER NOT NULL DEFAULT 0,
    owner_user      TEXT NOT NULL DEFAULT '',
    was_planned     BOOLEAN NOT NULL DEFAULT FALSE,
    blast_radius    TEXT NOT NULL DEFAULT 'unknown'
);
CREATE INDEX IF NOT EXISTS idx_agent_actions_ts        ON agent_actions(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_agent_actions_session   ON agent_actions(session_id);
CREATE INDEX IF NOT EXISTS idx_agent_actions_tool      ON agent_actions(tool_name);
CREATE INDEX IF NOT EXISTS idx_agent_actions_user      ON agent_actions(owner_user);
"""

_DDL_SQLITE = """
CREATE TABLE IF NOT EXISTS agent_actions (
    id              TEXT PRIMARY KEY,
    timestamp       TEXT NOT NULL DEFAULT (datetime('now')),
    session_id      TEXT NOT NULL,
    operation_id    TEXT,
    task_id         TEXT,
    tool_name       TEXT NOT NULL,
    args_redacted   TEXT NOT NULL DEFAULT '{}',
    result_status   TEXT NOT NULL,
    result_summary  TEXT NOT NULL DEFAULT '',
    duration_ms     INTEGER NOT NULL DEFAULT 0,
    owner_user      TEXT NOT NULL DEFAULT '',
    was_planned     INTEGER NOT NULL DEFAULT 0,
    blast_radius    TEXT NOT NULL DEFAULT 'unknown'
);
CREATE INDEX IF NOT EXISTS idx_agent_actions_ts      ON agent_actions(timestamp);
CREATE INDEX IF NOT EXISTS idx_agent_actions_session ON agent_actions(session_id);
CREATE INDEX IF NOT EXISTS idx_agent_actions_tool    ON agent_actions(tool_name);
CREATE INDEX IF NOT EXISTS idx_agent_actions_user    ON agent_actions(owner_user);
"""

# ── Blast radius by tool ─────────────────────────────────────────────────────
# node    = affects one VM/host/container
# service = affects one Swarm service across its replicas
# cluster = affects a whole cluster (Kafka, Swarm control plane)
# fleet   = affects many hosts at once
BLAST_RADIUS = {
    "vm_exec":                      "node",
    "proxmox_vm_power":             "node",
    "proxmox_vm_action":            "node",
    "node_drain":                   "node",
    "node_activate":                "node",
    "swarm_service_force_update":   "service",
    "service_upgrade":              "service",
    "service_rollback":             "service",
    "docker_prune":                 "node",
    "docker_engine_update":         "node",
    "checkpoint_restore":           "service",
    "kafka_exec":                   "cluster",
    "kafka_rolling_restart_safe":   "cluster",
    "skill_create":                 "service",
    "skill_regenerate":             "service",
    "skill_disable":                "service",
    "skill_enable":                 "service",
    "skill_import":                 "service",
}

# Which tools to audit. Wider than DESTRUCTIVE_TOOLS — also covers read-side
# remote exec (vm_exec status checks, kafka_exec describe) so we have a
# complete forensic picture of what touched remote systems.
AUDITED_TOOLS = frozenset(BLAST_RADIUS.keys())


def is_audited(tool_name: str) -> bool:
    return tool_name in AUDITED_TOOLS


# ── Arg redaction ────────────────────────────────────────────────────────────

# Match keys that may carry secrets. Case-insensitive, substring match.
_REDACT_KEY_RE = re.compile(
    r"(pass|password|secret|token|key|credential|auth|bearer|api[_-]?key)",
    re.IGNORECASE,
)


def redact_args(args: dict) -> dict:
    """Return a deep copy of `args` with any value whose key hints at a secret
    replaced with '***REDACTED***'. Nested dicts and lists are walked.

    Strings are not length-limited here (the DB column can hold them), but a
    few suspiciously long hex/base64 blobs are trimmed to 32 chars + ellipsis.
    """
    def _walk(v):
        if isinstance(v, dict):
            out = {}
            for k, vv in v.items():
                if isinstance(k, str) and _REDACT_KEY_RE.search(k):
                    out[k] = "***REDACTED***"
                else:
                    out[k] = _walk(vv)
            return out
        if isinstance(v, list):
            return [_walk(x) for x in v]
        if isinstance(v, str) and len(v) > 256:
            return v[:256] + "…"
        return v

    try:
        return _walk(args or {})
    except Exception as e:
        log.debug("redact_args failed, storing placeholder: %s", e)
        return {"_redact_error": str(e)[:120]}


# ── DB helpers ───────────────────────────────────────────────────────────────

_initialized = False


def _pg_dsn() -> str:
    return os.environ.get("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")


def _get_pg_conn():
    dsn = _pg_dsn()
    if not dsn:
        return None
    try:
        import psycopg2
        return psycopg2.connect(dsn)
    except Exception as e:
        log.debug("agent_actions PG connect failed: %s", e)
        return None


def _get_sa_conn():
    try:
        from api.db.base import get_sync_engine
        return get_sync_engine().connect()
    except Exception:
        return None


def init_agent_actions() -> bool:
    """Create the agent_actions table. Idempotent. Returns True if ready."""
    global _initialized
    if _initialized:
        return True
    conn = _get_pg_conn()
    if conn:
        try:
            conn.autocommit = True
            cur = conn.cursor()
            for stmt in _DDL_PG.strip().split(";"):
                s = stmt.strip()
                if s:
                    cur.execute(s)
            cur.close(); conn.close()
            _initialized = True
            log.info("agent_actions table ready (PostgreSQL)")
            return True
        except Exception as e:
            log.warning("agent_actions init failed (PG): %s", e)
            try: conn.close()
            except Exception: pass
    sa = _get_sa_conn()
    if not sa:
        return False
    try:
        from sqlalchemy import text as _t
        for stmt in _DDL_SQLITE.strip().split(";"):
            s = stmt.strip()
            if s:
                sa.execute(_t(s))
        sa.commit(); sa.close()
        _initialized = True
        log.info("agent_actions table ready (SQLite)")
        return True
    except Exception as e:
        log.warning("agent_actions init failed (SQLite): %s", e)
        try: sa.close()
        except Exception: pass
        return False


def write_action(
    *,
    session_id: str,
    tool_name: str,
    args: dict,
    result_status: str,
    result_summary: str,
    duration_ms: int,
    owner_user: str = "",
    was_planned: bool = False,
    operation_id: str = "",
    task_id: str = "",
) -> str:
    """Insert one immutable audit row. Returns the row id.

    Never raises — any failure is logged and an empty string returned so the
    agent loop is never blocked by the audit path.
    """
    if not is_audited(tool_name):
        return ""
    aid = str(uuid.uuid4())
    radius = BLAST_RADIUS.get(tool_name, "unknown")
    args_red = redact_args(args)
    args_json = json.dumps(args_red, default=str)[:8192]  # defensive cap
    summary = (result_summary or "")[:500]

    conn = _get_pg_conn()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO agent_actions
                    (id, session_id, operation_id, task_id, tool_name,
                     args_redacted, result_status, result_summary, duration_ms,
                     owner_user, was_planned, blast_radius)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s)
                """,
                (aid, session_id, operation_id or None, task_id or None,
                 tool_name, args_json, result_status, summary, int(duration_ms or 0),
                 owner_user, bool(was_planned), radius),
            )
            conn.commit(); cur.close(); conn.close()
            return aid
        except Exception as e:
            log.warning("write_action (PG) failed tool=%s: %s", tool_name, e)
            try: conn.close()
            except Exception: pass
            return ""
    # SQLite fallback
    try:
        from sqlalchemy import text as _t
        sa = _get_sa_conn()
        if not sa:
            return ""
        sa.execute(_t("""
            INSERT INTO agent_actions
                (id, session_id, operation_id, task_id, tool_name,
                 args_redacted, result_status, result_summary, duration_ms,
                 owner_user, was_planned, blast_radius)
            VALUES (:id, :sid, :oid, :tid, :tool, :args, :rs, :rsum, :dur,
                    :user, :planned, :radius)
        """), {
            "id": aid, "sid": session_id, "oid": operation_id or None,
            "tid": task_id or None, "tool": tool_name, "args": args_json,
            "rs": result_status, "rsum": summary, "dur": int(duration_ms or 0),
            "user": owner_user, "planned": 1 if was_planned else 0, "radius": radius,
        })
        sa.commit(); sa.close()
        return aid
    except Exception as e:
        log.warning("write_action (SQLite) failed tool=%s: %s", tool_name, e)
        return ""


def list_actions(
    *,
    session_id: str = "",
    tool_name: str = "",
    owner_user: str = "",
    since_iso: str = "",
    limit: int = 100,
) -> list[dict]:
    """Query audit rows. All filters optional. Ordered newest-first.
    Cap on limit to keep the payload sane."""
    limit = max(1, min(int(limit or 100), 500))

    where = []
    params_pg: list = []
    params_sa: dict = {"lim": limit}
    if session_id:
        where.append("session_id = %s"); params_pg.append(session_id)
        params_sa["sid"] = session_id
    if tool_name:
        where.append("tool_name = %s"); params_pg.append(tool_name)
        params_sa["tool"] = tool_name
    if owner_user:
        where.append("owner_user = %s"); params_pg.append(owner_user)
        params_sa["user"] = owner_user
    if since_iso:
        where.append("timestamp >= %s"); params_pg.append(since_iso)
        params_sa["since"] = since_iso
    where_sql_pg = ("WHERE " + " AND ".join(where)) if where else ""
    # SA uses named params, rewrite in SA-compatible form below
    where_sa_parts = []
    if session_id: where_sa_parts.append("session_id = :sid")
    if tool_name:  where_sa_parts.append("tool_name = :tool")
    if owner_user: where_sa_parts.append("owner_user = :user")
    if since_iso:  where_sa_parts.append("timestamp >= :since")
    where_sql_sa = ("WHERE " + " AND ".join(where_sa_parts)) if where_sa_parts else ""

    conn = _get_pg_conn()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute(
                f"""SELECT id, timestamp, session_id, operation_id, task_id,
                           tool_name, args_redacted, result_status, result_summary,
                           duration_ms, owner_user, was_planned, blast_radius
                      FROM agent_actions
                      {where_sql_pg}
                      ORDER BY timestamp DESC
                      LIMIT %s""",
                (*params_pg, limit),
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            cur.close(); conn.close()
            for r in rows:
                if r.get("timestamp"):
                    try: r["timestamp"] = r["timestamp"].isoformat()
                    except Exception: pass
                r["id"] = str(r["id"])
            return rows
        except Exception as e:
            log.warning("list_actions (PG) failed: %s", e)
            try: conn.close()
            except Exception: pass
            return []
    try:
        from sqlalchemy import text as _t
        sa = _get_sa_conn()
        if not sa:
            return []
        rows = sa.execute(_t(
            f"""SELECT id, timestamp, session_id, operation_id, task_id,
                       tool_name, args_redacted, result_status, result_summary,
                       duration_ms, owner_user, was_planned, blast_radius
                  FROM agent_actions
                  {where_sql_sa}
                  ORDER BY timestamp DESC
                  LIMIT :lim"""
        ), params_sa).mappings().fetchall()
        sa.close()
        out = []
        for r in rows:
            d = dict(r)
            # SQLite stored JSON as text — best effort parse back for consistency
            ar = d.get("args_redacted")
            if isinstance(ar, str):
                try: d["args_redacted"] = json.loads(ar)
                except Exception: pass
            d["was_planned"] = bool(d.get("was_planned"))
            out.append(d)
        return out
    except Exception as e:
        log.warning("list_actions (SQLite) failed: %s", e)
        return []
