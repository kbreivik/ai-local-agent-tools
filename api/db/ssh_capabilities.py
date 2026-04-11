"""SSH capability map — current-state view of credential→host pairs.

One row per (connection_id, target_host) pair. Upserted on every
ssh_connection_log write. Never grows unbounded.
"""
import logging
import os
from datetime import datetime, timezone

log = logging.getLogger(__name__)

_DDL_PG = """
CREATE TABLE IF NOT EXISTS ssh_capabilities (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    connection_id           TEXT NOT NULL,
    credential_source_id    TEXT,
    target_host             TEXT NOT NULL,
    target_port             INTEGER NOT NULL DEFAULT 22,
    resolved_label          TEXT,
    username                TEXT,
    jump_host               TEXT,
    jump_connection_id      TEXT,
    verified                BOOLEAN DEFAULT false,
    first_seen              TIMESTAMPTZ DEFAULT NOW(),
    last_success            TIMESTAMPTZ,
    last_attempt            TIMESTAMPTZ DEFAULT NOW(),
    last_failure            TIMESTAMPTZ,
    last_error              TEXT,
    attempts_7d             INTEGER DEFAULT 0,
    successes_7d            INTEGER DEFAULT 0,
    failures_7d             INTEGER DEFAULT 0,
    avg_latency_ms          INTEGER,
    new_host_alert          BOOLEAN DEFAULT false,
    new_host_alerted_at     TIMESTAMPTZ,
    UNIQUE(connection_id, target_host)
);
CREATE INDEX IF NOT EXISTS idx_ssh_cap_connection_id ON ssh_capabilities(connection_id);
CREATE INDEX IF NOT EXISTS idx_ssh_cap_target_host   ON ssh_capabilities(target_host);
CREATE INDEX IF NOT EXISTS idx_ssh_cap_verified      ON ssh_capabilities(verified);
CREATE INDEX IF NOT EXISTS idx_ssh_cap_last_success  ON ssh_capabilities(last_success DESC);
"""

_DDL_SQLITE = """
CREATE TABLE IF NOT EXISTS ssh_capabilities (
    id                      TEXT PRIMARY KEY,
    connection_id           TEXT NOT NULL,
    credential_source_id    TEXT,
    target_host             TEXT NOT NULL,
    target_port             INTEGER NOT NULL DEFAULT 22,
    resolved_label          TEXT,
    username                TEXT,
    jump_host               TEXT,
    jump_connection_id      TEXT,
    verified                INTEGER DEFAULT 0,
    first_seen              TEXT DEFAULT (datetime('now')),
    last_success            TEXT,
    last_attempt            TEXT DEFAULT (datetime('now')),
    last_failure            TEXT,
    last_error              TEXT,
    attempts_7d             INTEGER DEFAULT 0,
    successes_7d            INTEGER DEFAULT 0,
    failures_7d             INTEGER DEFAULT 0,
    avg_latency_ms          INTEGER,
    new_host_alert          INTEGER DEFAULT 0,
    new_host_alerted_at     TEXT,
    UNIQUE(connection_id, target_host)
);
"""

_initialized = False

def _ts(): return datetime.now(timezone.utc).isoformat()
def _is_pg(): return "postgres" in os.environ.get("DATABASE_URL", "")


def init_capabilities():
    global _initialized
    if _initialized:
        return True
    if _is_pg():
        try:
            from api.connections import _get_conn
            conn = _get_conn()
            conn.autocommit = True
            cur = conn.cursor()
            for stmt in _DDL_PG.strip().split(";"):
                s = stmt.strip()
                if s: cur.execute(s)
            cur.close(); conn.close()
            _initialized = True
            log.info("ssh_capabilities table ready (PostgreSQL)")
            return True
        except Exception as e:
            log.warning("ssh_capabilities init (PG) failed: %s", e)
    try:
        from api.connections import _get_sa_conn
        from sqlalchemy import text as _t
        sa = _get_sa_conn()
        if sa:
            sa.execute(_t(_DDL_SQLITE)); sa.commit(); sa.close()
            _initialized = True
            return True
    except Exception as e:
        log.warning("ssh_capabilities init (SQLite) failed: %s", e)
    return False


def upsert_capability(*, connection_id, target_host, target_port=22, outcome,
                      duration_ms=0, error_message="", credential_source_id="",
                      username="", jump_host="", jump_connection_id="", resolved_label=""):
    """Upsert one capability record. Called after every ssh_log write_log(). Never raises."""
    if not connection_id or not target_host:
        return
    if not _is_pg():
        return
    ts = _ts()
    success = (outcome == "success")
    try:
        import uuid
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM ssh_capabilities WHERE connection_id = %s AND verified = true", (connection_id,))
        prior_successes = cur.fetchone()[0]
        is_new_host = (success and prior_successes == 0)
        cur.execute("""
            INSERT INTO ssh_capabilities (
                id, connection_id, credential_source_id, target_host, target_port,
                resolved_label, username, jump_host, jump_connection_id,
                verified, first_seen, last_attempt, last_success, last_failure, last_error,
                attempts_7d, successes_7d, failures_7d, avg_latency_ms,
                new_host_alert, new_host_alerted_at
            ) VALUES (%s,%s,%s,%s,%s, %s,%s,%s,%s, %s,%s,%s,%s,%s,%s, 1,%s,%s,%s, %s,%s)
            ON CONFLICT (connection_id, target_host) DO UPDATE SET
                last_attempt   = EXCLUDED.last_attempt,
                last_success   = CASE WHEN EXCLUDED.verified THEN EXCLUDED.last_attempt ELSE ssh_capabilities.last_success END,
                last_failure   = CASE WHEN NOT EXCLUDED.verified THEN EXCLUDED.last_attempt ELSE ssh_capabilities.last_failure END,
                last_error     = CASE WHEN NOT EXCLUDED.verified THEN EXCLUDED.last_error ELSE ssh_capabilities.last_error END,
                verified       = CASE WHEN EXCLUDED.verified THEN true ELSE ssh_capabilities.verified END,
                attempts_7d    = ssh_capabilities.attempts_7d + 1,
                successes_7d   = ssh_capabilities.successes_7d + EXCLUDED.successes_7d,
                failures_7d    = ssh_capabilities.failures_7d + EXCLUDED.failures_7d,
                avg_latency_ms = CASE WHEN EXCLUDED.verified AND EXCLUDED.avg_latency_ms > 0
                    THEN (COALESCE(ssh_capabilities.avg_latency_ms, 0) + EXCLUDED.avg_latency_ms) / 2
                    ELSE ssh_capabilities.avg_latency_ms END,
                resolved_label = COALESCE(EXCLUDED.resolved_label, ssh_capabilities.resolved_label),
                username       = COALESCE(EXCLUDED.username, ssh_capabilities.username)
        """, (
            str(uuid.uuid4()), connection_id, credential_source_id or None, target_host, target_port,
            resolved_label or None, username or None, jump_host or None, jump_connection_id or None,
            success, ts, ts,
            ts if success else None, ts if not success else None,
            error_message[:300] if not success else None,
            1 if success else 0, 0 if success else 1,
            duration_ms if success and duration_ms else None,
            is_new_host, ts if is_new_host else None,
        ))
        conn.commit(); cur.close(); conn.close()
    except Exception as e:
        log.debug("upsert_capability failed (non-fatal): %s", e)


def query_capabilities(connection_id="", target_host="", verified_only=False, days=7, alerts_only=False):
    if not _is_pg():
        return []
    conditions = []
    params = []
    if connection_id:
        conditions.append("connection_id = %s"); params.append(connection_id)
    if target_host:
        conditions.append("target_host = %s"); params.append(target_host)
    if verified_only:
        conditions.append("verified = true")
    if alerts_only:
        conditions.append("new_host_alert = true")
    if days:
        conditions.append("last_attempt >= NOW() - INTERVAL '%s days'"); params.append(days)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    sql = f"""SELECT *, CASE WHEN attempts_7d > 0 THEN ROUND(successes_7d::numeric / attempts_7d * 100)
              ELSE 0 END AS success_rate_pct FROM ssh_capabilities {where} ORDER BY last_attempt DESC LIMIT 200"""
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        cur.close(); conn.close()
        for r in rows:
            for k, v in r.items():
                if hasattr(v, 'isoformat'): r[k] = v.isoformat()
        return rows
    except Exception as e:
        log.debug("query_capabilities failed: %s", e)
        return []


def get_capability_summary():
    if not _is_pg():
        return {}
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) AS total_pairs,
                   COUNT(*) FILTER (WHERE verified = true) AS verified_pairs,
                   COUNT(*) FILTER (WHERE new_host_alert = true) AS new_host_alerts,
                   COUNT(*) FILTER (WHERE last_success >= NOW() - INTERVAL '24 hours') AS active_24h,
                   COUNT(*) FILTER (WHERE last_success >= NOW() - INTERVAL '7 days') AS active_7d,
                   COUNT(*) FILTER (WHERE verified = true AND last_success < NOW() - INTERVAL '24 hours') AS stale_verified,
                   COUNT(DISTINCT connection_id) AS distinct_credentials,
                   COUNT(DISTINCT target_host) AS distinct_hosts
            FROM ssh_capabilities
        """)
        row = cur.fetchone()
        cols = [d[0] for d in cur.description]
        cur.close(); conn.close()
        return dict(zip(cols, row)) if row else {}
    except Exception as e:
        log.debug("get_capability_summary failed: %s", e)
        return {}
