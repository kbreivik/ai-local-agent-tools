# CC PROMPT — v2.31.10 — feat(security): maintenance / blackout windows

## What this does
Adds the ability to block destructive agent actions during operator-defined
windows (e.g. "no Kafka restarts between 02:00–04:00 Sunday during PBS backup").
Today `plan_action` has no time-aware gate — if an on-call operator runs a
remediation task overnight that coincides with a backup, the agent will
happily fire destructive tool calls.

This prompt adds:
- `agent_blackouts` table — operator-defined windows
- `plan_action` check that returns `status: blocked` when any matching
  blackout is active
- CRUD API endpoints (sith_lord + imperial_officer only)
- No UI this round — CRUD via curl, UI can follow as v2.31.x later

Three changes.

---

## Change 1 — api/db/agent_blackouts.py — NEW FILE

```python
"""agent_blackouts — operator-defined windows during which destructive agent
actions are blocked.

Each row defines a recurring or one-off window. `applies_to` narrows the scope:
  - empty list (or NULL) = all destructive tools
  - ["kafka_exec", "swarm_service_force_update"] = only those tools
The match against a task's destructive tool is done at plan_action time.

Tables are intentionally simple — no RRULE complexity. Either:
  * `starts_at` + `ends_at` (UTC, one-shot window), or
  * `recurring_cron` (5-field cron, UTC) + `duration_minutes`

If both are present, both must be satisfied for the blackout to be active.
If neither is present, the row is inactive.
"""
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

_DDL_PG = """
CREATE TABLE IF NOT EXISTS agent_blackouts (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    label             TEXT NOT NULL,
    reason            TEXT NOT NULL DEFAULT '',
    enabled           BOOLEAN NOT NULL DEFAULT TRUE,
    starts_at         TIMESTAMPTZ,
    ends_at           TIMESTAMPTZ,
    recurring_cron    TEXT,
    duration_minutes  INTEGER,
    applies_to        JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_by        TEXT NOT NULL DEFAULT '',
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    updated_at        TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_agent_blackouts_enabled ON agent_blackouts(enabled);
"""

_DDL_SQLITE = """
CREATE TABLE IF NOT EXISTS agent_blackouts (
    id                TEXT PRIMARY KEY,
    label             TEXT NOT NULL,
    reason            TEXT NOT NULL DEFAULT '',
    enabled           INTEGER NOT NULL DEFAULT 1,
    starts_at         TEXT,
    ends_at           TEXT,
    recurring_cron    TEXT,
    duration_minutes  INTEGER,
    applies_to        TEXT NOT NULL DEFAULT '[]',
    created_by        TEXT NOT NULL DEFAULT '',
    created_at        TEXT DEFAULT (datetime('now')),
    updated_at        TEXT DEFAULT (datetime('now'))
);
"""

_initialized = False


def _pg_dsn() -> str:
    return os.environ.get("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")


def _pg_conn():
    dsn = _pg_dsn()
    if not dsn:
        return None
    try:
        import psycopg2
        return psycopg2.connect(dsn)
    except Exception:
        return None


def init_agent_blackouts() -> bool:
    global _initialized
    if _initialized:
        return True
    conn = _pg_conn()
    if conn:
        try:
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute(_DDL_PG)
            cur.close(); conn.close()
            _initialized = True
            log.info("agent_blackouts table ready (PostgreSQL)")
            return True
        except Exception as e:
            log.warning("agent_blackouts init (PG) failed: %s", e)
            try: conn.close()
            except Exception: pass
    try:
        from api.db.base import get_sync_engine
        from sqlalchemy import text as _t
        with get_sync_engine().connect() as sa:
            sa.execute(_t(_DDL_SQLITE))
            sa.commit()
        _initialized = True
        log.info("agent_blackouts table ready (SQLite)")
        return True
    except Exception as e:
        log.warning("agent_blackouts init (SQLite) failed: %s", e)
        return False


# ── Cron matching (pure Python, no deps) ──────────────────────────────────────

def _cron_matches(cron_expr: str, dt: datetime) -> bool:
    """Minimal 5-field cron matcher (minute hour dom month dow). UTC.
    Supports '*', '*/N', 'A-B', 'A,B,C'. No month/dow names, no '@yearly'.

    Returns True if dt matches the cron expression.
    """
    if not cron_expr or not cron_expr.strip():
        return False
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        return False
    minute, hour, dom, month, dow = parts
    # Map dt fields
    vals = [dt.minute, dt.hour, dt.day, dt.month, dt.isoweekday() % 7]  # dow: 0=Sun
    ranges = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]

    def _match_field(expr: str, val: int, lo: int, hi: int) -> bool:
        if expr == "*":
            return True
        for piece in expr.split(","):
            if "/" in piece:
                base, step = piece.split("/")
                step_i = int(step)
                if base == "*":
                    return (val - lo) % step_i == 0
                # A-B/N or A/N
                if "-" in base:
                    a, b = base.split("-")
                    a_i, b_i = int(a), int(b)
                    if a_i <= val <= b_i and (val - a_i) % step_i == 0:
                        return True
                else:
                    a_i = int(base)
                    if val >= a_i and (val - a_i) % step_i == 0:
                        return True
            elif "-" in piece:
                a, b = piece.split("-")
                if int(a) <= val <= int(b):
                    return True
            else:
                if int(piece) == val:
                    return True
        return False

    for expr, v, (lo, hi) in zip([minute, hour, dom, month, dow], vals, ranges):
        if not _match_field(expr, v, lo, hi):
            return False
    return True


# ── Public API ────────────────────────────────────────────────────────────────

def check_active_blackout(tool_name: str = "", now: datetime | None = None) -> dict | None:
    """Return the first matching active blackout row, or None.

    `tool_name`: if provided, only blackouts whose `applies_to` is empty OR
    contains this name match. If empty, any blackout matches.
    """
    now = now or datetime.now(timezone.utc)
    conn = _pg_conn()
    rows: list[dict] = []
    if conn:
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, label, reason, starts_at, ends_at, recurring_cron, "
                "duration_minutes, applies_to FROM agent_blackouts "
                "WHERE enabled = TRUE"
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            cur.close(); conn.close()
        except Exception as e:
            log.debug("check_active_blackout (PG) failed: %s", e)
            try: conn.close()
            except Exception: pass
    else:
        try:
            from api.db.base import get_sync_engine
            from sqlalchemy import text as _t
            with get_sync_engine().connect() as sa:
                res = sa.execute(_t(
                    "SELECT id, label, reason, starts_at, ends_at, recurring_cron, "
                    "duration_minutes, applies_to FROM agent_blackouts "
                    "WHERE enabled = 1"
                )).mappings().fetchall()
                rows = [dict(r) for r in res]
        except Exception as e:
            log.debug("check_active_blackout (SQLite) failed: %s", e)
            return None

    for r in rows:
        applies = r.get("applies_to") or []
        if isinstance(applies, str):
            try: applies = json.loads(applies)
            except Exception: applies = []
        if applies and tool_name and tool_name not in applies:
            continue

        # Window check: prefer one-shot if present
        active = False
        sa_, ea_ = r.get("starts_at"), r.get("ends_at")
        if sa_ and ea_:
            try:
                sa_dt = sa_ if isinstance(sa_, datetime) else datetime.fromisoformat(str(sa_).replace("Z", "+00:00"))
                ea_dt = ea_ if isinstance(ea_, datetime) else datetime.fromisoformat(str(ea_).replace("Z", "+00:00"))
                if sa_dt.tzinfo is None: sa_dt = sa_dt.replace(tzinfo=timezone.utc)
                if ea_dt.tzinfo is None: ea_dt = ea_dt.replace(tzinfo=timezone.utc)
                if sa_dt <= now <= ea_dt:
                    active = True
            except Exception:
                pass

        if not active and r.get("recurring_cron") and r.get("duration_minutes"):
            # A recurring cron window is considered active if *any* minute in
            # the past `duration_minutes` matched. Cheap scan.
            try:
                dur = int(r["duration_minutes"])
                for delta in range(0, dur + 1):
                    if _cron_matches(r["recurring_cron"], now - timedelta(minutes=delta)):
                        active = True
                        break
            except Exception:
                pass

        if active:
            return {
                "id":     str(r.get("id", "")),
                "label":  r.get("label", ""),
                "reason": r.get("reason", ""),
                "applies_to": applies,
            }
    return None


def list_blackouts() -> list[dict]:
    conn = _pg_conn()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM agent_blackouts ORDER BY created_at DESC")
            cols = [d[0] for d in cur.description]
            out = [dict(zip(cols, r)) for r in cur.fetchall()]
            cur.close(); conn.close()
            for r in out:
                for k in ("starts_at", "ends_at", "created_at", "updated_at"):
                    if r.get(k):
                        try: r[k] = r[k].isoformat()
                        except Exception: pass
                r["id"] = str(r["id"])
                if isinstance(r.get("applies_to"), str):
                    try: r["applies_to"] = json.loads(r["applies_to"])
                    except Exception: pass
            return out
        except Exception as e:
            log.warning("list_blackouts failed: %s", e)
    return []


def create_blackout(**fields) -> str:
    bid = str(uuid.uuid4())
    conn = _pg_conn()
    if not conn:
        return ""
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO agent_blackouts
                (id, label, reason, enabled, starts_at, ends_at,
                 recurring_cron, duration_minutes, applies_to, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
        """, (
            bid, fields.get("label", ""), fields.get("reason", ""),
            bool(fields.get("enabled", True)),
            fields.get("starts_at"), fields.get("ends_at"),
            fields.get("recurring_cron"), fields.get("duration_minutes"),
            json.dumps(fields.get("applies_to") or []),
            fields.get("created_by", ""),
        ))
        conn.commit(); cur.close(); conn.close()
        return bid
    except Exception as e:
        log.warning("create_blackout failed: %s", e)
        try: conn.close()
        except Exception: pass
        return ""


def delete_blackout(bid: str) -> bool:
    conn = _pg_conn()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM agent_blackouts WHERE id = %s", (bid,))
        n = cur.rowcount
        conn.commit(); cur.close(); conn.close()
        return n > 0
    except Exception as e:
        log.warning("delete_blackout failed: %s", e)
        try: conn.close()
        except Exception: pass
        return False


def set_enabled(bid: str, enabled: bool) -> bool:
    conn = _pg_conn()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute("UPDATE agent_blackouts SET enabled = %s, updated_at = NOW() WHERE id = %s",
                    (enabled, bid))
        n = cur.rowcount
        conn.commit(); cur.close(); conn.close()
        return n > 0
    except Exception as e:
        log.warning("set_enabled failed: %s", e)
        try: conn.close()
        except Exception: pass
        return False
```

---

## Change 2 — api/routers/agent_blackouts_api.py — NEW FILE

```python
"""Blackout CRUD endpoints. Role-gated to sith_lord + imperial_officer."""
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import get_current_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agent/blackouts", tags=["agent-blackouts"])

_PRIVILEGED = frozenset({"sith_lord", "imperial_officer"})


def _user_role(username: str) -> str:
    try:
        from api.users import get_user_by_username
        row = get_user_by_username(username)
        if row and row.get("role"):
            return row["role"]
    except Exception:
        pass
    import os
    if username == os.environ.get("ADMIN_USER", "admin"):
        return "sith_lord"
    return "stormtrooper"


def _gate(user: str) -> None:
    if _user_role(user) not in _PRIVILEGED:
        raise HTTPException(403, "Blackout management requires imperial_officer or sith_lord role.")


class BlackoutCreate(BaseModel):
    label:             str = Field(max_length=120)
    reason:            str = Field(default="", max_length=500)
    enabled:           bool = True
    starts_at:         str | None = None
    ends_at:           str | None = None
    recurring_cron:    str | None = None
    duration_minutes:  int | None = None
    applies_to:        list[str] = Field(default_factory=list)


@router.get("")
async def list_blackouts_api(user: str = Depends(get_current_user)):
    _gate(user)
    from api.db.agent_blackouts import list_blackouts
    return {"blackouts": list_blackouts()}


@router.post("")
async def create_blackout_api(req: BlackoutCreate, user: str = Depends(get_current_user)):
    _gate(user)
    from api.db.agent_blackouts import create_blackout
    bid = create_blackout(**req.model_dump(), created_by=user)
    if not bid:
        raise HTTPException(500, "Failed to create blackout")
    return {"id": bid, "status": "ok"}


@router.delete("/{bid}")
async def delete_blackout_api(bid: str, user: str = Depends(get_current_user)):
    _gate(user)
    from api.db.agent_blackouts import delete_blackout
    if not delete_blackout(bid):
        raise HTTPException(404, "Not found")
    return {"status": "ok"}


@router.post("/{bid}/toggle")
async def toggle_blackout_api(bid: str, enabled: bool, user: str = Depends(get_current_user)):
    _gate(user)
    from api.db.agent_blackouts import set_enabled
    if not set_enabled(bid, enabled):
        raise HTTPException(404, "Not found")
    return {"status": "ok", "enabled": enabled}


@router.get("/active")
async def active_blackout_api(tool_name: str = "", _: str = Depends(get_current_user)):
    """Return the currently-active blackout matching `tool_name`, or null."""
    from api.db.agent_blackouts import check_active_blackout
    return {"active": check_active_blackout(tool_name=tool_name)}
```

---

## Change 3 — api/routers/agent.py — enforce blackout in plan_action path

Find the `if fn_name == "plan_action":` branch inside `_run_single_agent_step`.
At the very top of that branch (before the `lock_ok = await plan_lock.acquire`
line), add:

```python
                        # v2.31.10 blackout gate
                        try:
                            from api.db.agent_blackouts import check_active_blackout
                            # Inspect the plan's proposed tool calls — we don't
                            # know them yet here (plan_action is the gate ITSELF),
                            # so check against any destructive action.
                            active_bo = check_active_blackout(tool_name="")
                        except Exception:
                            active_bo = None
                        if active_bo:
                            plan_action_called = True  # prevent re-trigger loop
                            result = {
                                "status":   "blocked",
                                "approved": False,
                                "message":  (f"Blocked by active blackout: "
                                             f"{active_bo.get('label','')} — "
                                             f"{active_bo.get('reason','')}"),
                                "data":     {"approved": False, "blackout": active_bo},
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            }
                            await manager.send_line(
                                "step",
                                f"[blackout] Plan blocked — {active_bo.get('label','')}",
                                status="warning", session_id=session_id,
                            )
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": json.dumps(result),
                            })
                            continue  # skip the real plan_action handling below
```

---

## Change 4 — api/main.py — wire init + router

**4a.** Add import near other router imports:
```python
from api.routers.agent_blackouts_api import router as agent_blackouts_router
```

**4b.** In the lifespan, after `init_agent_actions()`, add:
```python
    try:
        from api.db.agent_blackouts import init_agent_blackouts
        init_agent_blackouts()
    except Exception as e:
        _log.debug("agent_blackouts init skipped: %s", e)
```

**4c.** In the router registration block, after `app.include_router(agent_actions_router)`:
```python
app.include_router(agent_blackouts_router)
```

---

## Commit
```
git add -A
git commit -m "feat(security): v2.31.10 maintenance / blackout windows"
git push origin main
```

---

## How to test

1. **Table ready**: `docker logs hp1_agent 2>&1 | grep -i "agent_blackouts"`
   → `agent_blackouts table ready (PostgreSQL)`.

2. **Create a blackout via curl** (authed):
   ```bash
   curl -s -b /tmp/hp1.cookies -X POST http://192.168.199.10:8000/api/agent/blackouts \
     -H 'Content-Type: application/json' \
     -d '{"label":"test","reason":"testing","starts_at":"2026-04-16T00:00:00Z","ends_at":"2099-01-01T00:00:00Z"}'
   ```
   Expect `{"id": "...", "status":"ok"}`.

3. **Active check**:
   ```bash
   curl -s -b /tmp/hp1.cookies http://192.168.199.10:8000/api/agent/blackouts/active
   ```
   Expect `{"active": {...}}` with the label.

4. **Plan gate fires** — run any destructive execute task. The agent should
   call `plan_action`, get `status: blocked`, and halt with a `[blackout]`
   line in Output.

5. **Delete the test blackout**:
   ```bash
   curl -s -b /tmp/hp1.cookies -X DELETE http://192.168.199.10:8000/api/agent/blackouts/<id>
   ```
   Re-run the same destructive task — should now plan normally.

6. **Role gate** — log in as a stormtrooper (or lower). POST should return 403.
