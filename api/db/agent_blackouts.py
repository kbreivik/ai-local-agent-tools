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
