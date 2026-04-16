# CC PROMPT — v2.31.2 — feat(security): agent_actions audit table for destructive tool calls

## What this does
Creates a forensic audit trail for every destructive/remote-execution tool call the agent
makes. Today we log tool calls to `operations`/`tool_calls` for debugging, but there's no
immutable, redacted, append-only record answering "what did the agent actually do, when,
on whose behalf, was it planned?". That's this prompt.

Four changes across four files:

1. **NEW** `api/db/agent_actions.py` — table DDL, `write_action()`, `list_actions()`,
   arg-redaction helper, and a `BLAST_RADIUS` mapping
2. **NEW** `api/routers/agent_actions_api.py` — `GET /api/agent/actions` (authed)
3. **EDIT** `api/routers/agent.py` — wrap the tool-execution path with one `write_action()`
   call for any tool in `AUDITED_TOOLS`
4. **EDIT** `api/main.py` — call `init_agent_actions()` in lifespan, register the router

No UI in this version — a "Recent Actions" tab comes in v2.31.3. Version bump: v2.31.1 → v2.31.2

---

## Change 1 — api/db/agent_actions.py — NEW FILE

Create this file in full:

```python
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
```

---

## Change 2 — api/routers/agent_actions_api.py — NEW FILE

Create this file in full. Role gating is enforced via `get_current_user` + role
lookup through the users table (same pattern as other protected endpoints).

```python
"""Read-only API for the agent_actions audit log.

Only sith_lord and imperial_officer roles can read the audit trail.
Stormtroopers and droids get 403.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth import get_current_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agent/actions", tags=["agent-actions"])

_PRIVILEGED_ROLES = frozenset({"sith_lord", "imperial_officer"})


def _user_role(username: str) -> str:
    """Resolve the role for a username. Falls back to 'stormtrooper' if unknown.

    sith_lord for the env-var admin (matches api/auth.authenticate), otherwise
    look up the role from the users table.
    """
    try:
        from api.users import get_user_by_username
        row = get_user_by_username(username)
        if row and row.get("role"):
            return row["role"]
    except Exception:
        pass
    # env-var admin fallback — see api/auth.authenticate()
    import os
    if username == os.environ.get("ADMIN_USER", "admin"):
        return "sith_lord"
    return "stormtrooper"


@router.get("")
async def list_agent_actions(
    session_id: str = Query("", max_length=128),
    tool_name:  str = Query("", max_length=128),
    user_filter: str = Query("", alias="user", max_length=128),
    since:      str = Query("", max_length=64, description="ISO timestamp lower bound"),
    limit:      int = Query(100, ge=1, le=500),
    user: str = Depends(get_current_user),
):
    """Return audit rows. Authorised roles only."""
    role = _user_role(user)
    if role not in _PRIVILEGED_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Audit log access requires imperial_officer or sith_lord role.",
        )
    from api.db.agent_actions import list_actions
    rows = list_actions(
        session_id=session_id,
        tool_name=tool_name,
        owner_user=user_filter,
        since_iso=since,
        limit=limit,
    )
    return {"count": len(rows), "actions": rows}
```

---

## Change 3 — api/routers/agent.py — wire audit write into the tool loop

Find the section inside `_run_single_agent_step` where the tool call result is
logged and streamed. The existing block looks like:

```python
                duration_ms = int((time.monotonic() - t0) * 1000)
                result_status = result.get("status", "error") if isinstance(result, dict) else "error"
                result_msg = result.get("message", "") if isinstance(result, dict) else str(result)

                # Store tool execution in memory (non-blocking)
                _mem_after(fn_name, fn_args, result, result_status, duration_ms)

                # Log to SQLite
                await logger_mod.log_tool_call(
                    operation_id, fn_name, fn_args, result,
                    _lm_model(), duration_ms
                )
```

**Immediately after** the `await logger_mod.log_tool_call(...)` call and **before**
the `# Stream to GUI` comment, insert:

```python
                # Immutable audit row for destructive / remote-exec tools (v2.31.2)
                try:
                    from api.db.agent_actions import write_action, is_audited
                    if is_audited(fn_name):
                        write_action(
                            session_id=session_id,
                            operation_id=operation_id,
                            task_id=session_id,           # no separate task_id today
                            tool_name=fn_name,
                            args=fn_args,
                            result_status=result_status,
                            result_summary=result_msg,
                            duration_ms=duration_ms,
                            owner_user=owner_user,
                            was_planned=plan_action_called,
                        )
                except Exception as _ae:
                    log.debug("agent_actions write failed: %s", _ae)
```

Do not touch any other code in this function. The added block is a pure side
effect — if it raises, the agent continues normally.

---

## Change 4 — api/main.py — init table + register router

**4a.** Add the import near the other router imports (alongside
`from api.routers.escalations import ...`):

```python
from api.routers.agent_actions_api import router as agent_actions_router
```

**4b.** Inside the lifespan, add an init call. Find the existing block:

```python
    # Initialize agent_escalations table
    try:
        init_escalations()
    except Exception as e:
        _log.debug("Escalations table init skipped: %s", e)
```

Add immediately after it:

```python
    # Initialize agent_actions audit table
    try:
        from api.db.agent_actions import init_agent_actions
        init_agent_actions()
    except Exception as e:
        _log.debug("agent_actions init skipped: %s", e)
```

**4c.** Register the router. Find the existing `app.include_router(escalations_router)`
line in the router registration block and add right after it:

```python
app.include_router(agent_actions_router)
```

---

## Version bump
- Update `VERSION` in `api/constants.py`: `v2.31.1` → `v2.31.2`
- Update root `/VERSION` file: `2.31.1` → `2.31.2`

## Commit
```
git add -A
git commit -m "feat(security): v2.31.2 agent_actions audit table for destructive tool calls"
git push origin main
```

---

## How to test after deploy

After `docker compose pull hp1_agent && docker compose up -d hp1_agent`:

1. **Table exists** — no errors in the logs at startup:
   ```
   docker logs hp1_agent 2>&1 | grep -i "agent_actions"
   ```
   Expect: `agent_actions table ready (PostgreSQL)`.

2. **Route exists** — 401/403 proves the route is mounted, not 404:
   ```bash
   curl -s http://192.168.199.10:8000/api/agent/actions
   # expect: {"detail":"Not authenticated"}
   ```

3. **Authed read works** — with the cookie from the login step used earlier:
   ```bash
   curl -s -b /tmp/hp1.cookies http://192.168.199.10:8000/api/agent/actions | python3 -m json.tool
   # expect: {"count": 0, "actions": []}  on a fresh deploy
   ```

4. **Write path fires** — run a harmless read-only audited tool through the agent
   (e.g. an observe task that triggers `swarm_node_status` or a `vm_exec` for
   `uptime`). Then:
   ```bash
   curl -s -b /tmp/hp1.cookies "http://192.168.199.10:8000/api/agent/actions?limit=5" | python3 -m json.tool
   ```
   Should show at least one row with the tool name, blast_radius, and a
   redacted args blob.

5. **Redaction works** — verify that if any audited tool received an arg named
   like `password`, `token`, `secret`, or `api_key`, the stored `args_redacted`
   contains `***REDACTED***` in place of the value. A quick way to test:
   ```sql
   SELECT tool_name, args_redacted::text FROM agent_actions ORDER BY timestamp DESC LIMIT 3;
   ```
   No plaintext secrets should be visible.

6. **Role gating** — create a stormtrooper user (or log in as one) and confirm
   the endpoint returns 403:
   ```json
   {"detail":"Audit log access requires imperial_officer or sith_lord role."}
   ```

If any of the above fails, do not proceed to v2.31.3.
