"""known_facts — persistent, weighted, contradiction-aware knowledge store.

Introduced in v2.35.0. Collectors write facts on every successful poll; the
store deduplicates identical reads, appends history on value change, tracks
cross-source contradictions, and computes a deterministic confidence score
for every row.

Tables:
  known_facts_current                   — live value, 1 row per (fact_key, source)
  known_facts_history                   — append-only on value change
  known_facts_locks                     — admin-asserted "don't overwrite" on keys
  known_facts_conflicts                 — collector disagrees with a locked fact
  known_facts_permissions               — user/role grants for admin ops
  known_facts_refresh_schedule          — per-key-pattern expected poll cadence
  facts_audit_log                       — admin action audit log
  known_facts_keywords                  — v2.35.1 preflight keyword corpus
  known_facts_keyword_suggestions       — v2.35.1 auto-proposed keywords from tier-3 LLM

This module is sync-only, never raises into callers, and no-ops on SQLite.
"""
from __future__ import annotations

import json
import logging
import math
import os
from datetime import datetime, timezone, timedelta

log = logging.getLogger(__name__)


_DDL_PG = """
CREATE TABLE IF NOT EXISTS known_facts_current (
    fact_key         TEXT NOT NULL,
    source           TEXT NOT NULL,
    fact_value       JSONB NOT NULL,
    first_seen       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_verified    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    verify_count     INT NOT NULL DEFAULT 1,
    contradicts      JSONB NOT NULL DEFAULT '[]'::jsonb,
    confidence       FLOAT NOT NULL DEFAULT 0.5,
    metadata         JSONB NOT NULL DEFAULT '{}'::jsonb,
    change_detected  BOOLEAN NOT NULL DEFAULT FALSE,
    change_flagged_at TIMESTAMPTZ,
    PRIMARY KEY (fact_key, source)
);
CREATE INDEX IF NOT EXISTS idx_known_facts_current_key
    ON known_facts_current(fact_key);
CREATE INDEX IF NOT EXISTS idx_known_facts_current_confidence
    ON known_facts_current(confidence DESC)
    WHERE confidence >= 0.5;
CREATE INDEX IF NOT EXISTS idx_known_facts_current_last_verified
    ON known_facts_current(last_verified DESC);
CREATE INDEX IF NOT EXISTS idx_known_facts_current_change_detected
    ON known_facts_current(change_flagged_at DESC)
    WHERE change_detected = TRUE;

CREATE TABLE IF NOT EXISTS known_facts_history (
    id           BIGSERIAL PRIMARY KEY,
    fact_key     TEXT NOT NULL,
    source       TEXT NOT NULL,
    prior_value  JSONB NOT NULL,
    new_value    JSONB NOT NULL,
    changed_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    changed_by   TEXT NOT NULL DEFAULT 'collector',
    metadata     JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_known_facts_history_key
    ON known_facts_history(fact_key, changed_at DESC);
CREATE INDEX IF NOT EXISTS idx_known_facts_history_changed_at
    ON known_facts_history(changed_at DESC);

CREATE TABLE IF NOT EXISTS known_facts_locks (
    fact_key       TEXT PRIMARY KEY,
    locked_value   JSONB NOT NULL,
    locked_by      TEXT NOT NULL,
    locked_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    note           TEXT NOT NULL DEFAULT '',
    last_ack_by    TEXT,
    last_ack_at    TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS known_facts_conflicts (
    id             BIGSERIAL PRIMARY KEY,
    fact_key       TEXT NOT NULL,
    locked_value   JSONB NOT NULL,
    offered_source TEXT NOT NULL,
    offered_value  JSONB NOT NULL,
    offered_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at    TIMESTAMPTZ,
    resolved_by    TEXT,
    resolution     TEXT,
    notes          TEXT
);
CREATE INDEX IF NOT EXISTS idx_known_facts_conflicts_pending
    ON known_facts_conflicts(offered_at DESC)
    WHERE resolved_at IS NULL;

CREATE TABLE IF NOT EXISTS known_facts_permissions (
    id            BIGSERIAL PRIMARY KEY,
    grantee_type  TEXT NOT NULL CHECK (grantee_type IN ('user','role')),
    grantee_id    TEXT NOT NULL,
    action        TEXT NOT NULL,
    fact_pattern  TEXT NOT NULL,
    granted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    granted_by    TEXT NOT NULL,
    expires_at    TIMESTAMPTZ,
    revoked       BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_known_facts_permissions_grantee
    ON known_facts_permissions(grantee_type, grantee_id)
    WHERE revoked = FALSE;

CREATE TABLE IF NOT EXISTS known_facts_refresh_schedule (
    pattern       TEXT PRIMARY KEY,
    cadence_sec   INT NOT NULL,
    description   TEXT NOT NULL DEFAULT '',
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by    TEXT NOT NULL DEFAULT 'system'
);

CREATE TABLE IF NOT EXISTS facts_audit_log (
    id           BIGSERIAL PRIMARY KEY,
    action       TEXT NOT NULL,
    fact_key     TEXT,
    actor        TEXT NOT NULL,
    at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    detail       JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_facts_audit_log_at
    ON facts_audit_log(at DESC);

-- v2.35.1 preflight keyword corpus (DB-editable extension of hardcoded defaults)
CREATE TABLE IF NOT EXISTS known_facts_keywords (
    keyword             TEXT PRIMARY KEY,
    resolver_name       TEXT NOT NULL,
    default_window_min  INT,
    description         TEXT NOT NULL DEFAULT '',
    active              BOOLEAN NOT NULL DEFAULT TRUE,
    added_by            TEXT NOT NULL DEFAULT 'system',
    added_at            TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS known_facts_keyword_suggestions (
    id                  BIGSERIAL PRIMARY KEY,
    proposed_keyword    TEXT,
    raw_task            TEXT NOT NULL,
    raw_proposal        JSONB NOT NULL DEFAULT '{}'::jsonb,
    status              TEXT NOT NULL DEFAULT 'pending',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed_at         TIMESTAMPTZ,
    reviewed_by         TEXT
);
CREATE INDEX IF NOT EXISTS idx_known_facts_keyword_suggestions_pending
    ON known_facts_keyword_suggestions(created_at DESC)
    WHERE status = 'pending';
"""


_KEYWORD_SEEDS: list[tuple[str, str, int | None, str]] = [
    ("restarted",  "_lookup_recent_restart_actions", None, "recent service/vm restart ops"),
    ("restart",    "_lookup_recent_restart_actions", None, "recent service/vm restart ops"),
    ("rebooted",   "_lookup_recent_reboot_actions",  None, "recent VM/host reboots"),
    ("reboot",     "_lookup_recent_reboot_actions",  None, "recent VM/host reboots"),
    ("upgraded",   "_lookup_recent_upgrade_actions", 1440, "recent image pulls + service updates"),
    ("upgrade",    "_lookup_recent_upgrade_actions", 1440, "recent image pulls + service updates"),
    ("degraded",   "_lookup_degraded_entities",      None, "entities in Degraded state"),
    ("failing",    "_lookup_failing_entities",       None, "entities in Failed/Failing state"),
    ("offline",    "_lookup_offline_entities",       None, "entities marked Down/Offline"),
    ("broken",     "_lookup_recent_errors",          None, "recent error-level events"),
    ("crashed",    "_lookup_recent_crashes",         None, "recent crash/OOM/exit signals"),
    ("alerting",   "_lookup_alerting_entities",      None, "alerts currently firing"),
    ("deployed",   "_lookup_recent_deployments",     1440, "recent deploy actions"),
    ("scaled",     "_lookup_recent_scale_events",    None, "recent scale events"),
]


_SCHEDULE_SEEDS: list[tuple[str, int, str]] = [
    ("prod.proxmox.vm.*.status",        60,    "VM status changes fast"),
    ("prod.proxmox.vm.*.node",          300,   "VM placement changes occasionally"),
    ("prod.swarm.service.*.placement",  30,    "Orchestrator moves services"),
    ("prod.swarm.service.*.replicas",   30,    "Scale events"),
    ("prod.kafka.broker.*.host",        3600,  "Rarely changes"),
    ("prod.kafka.broker.*.port",        3600,  "Rarely changes"),
    ("prod.kafka.topic.*.partitions",   600,   "Topic topology stable"),
    ("prod.container.*.ip",             300,   "DHCP rare"),
    ("prod.container.*.id",             86400, "Event-driven; poll only for GC"),
    ("prod.manual.*",                   86400, "Refresh reminder only"),
    ("*",                               300,   "Default fallback"),
]


_DEFAULT_SOURCE_WEIGHTS = {
    "manual":                 1.0,
    "proxmox_collector":      0.9,
    "swarm_collector":        0.9,
    "docker_agent_collector": 0.85,
    "pbs_collector":          0.85,
    "fortiswitch_collector":  0.85,
    "kafka_collector":        0.8,
    "agent_observation":      0.5,
    "rag_extraction":         0.4,
}


_DEFAULT_HALF_LIVES_HOURS = {
    "manual":            720.0,
    "agent_observation": 24.0,
    "rag_extraction":    720.0,
}


_initialized = False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ts() -> str:
    return _now().isoformat()


def _is_pg() -> bool:
    return "postgres" in os.environ.get("DATABASE_URL", "")


def _default_source_weight(source: str) -> float:
    return _DEFAULT_SOURCE_WEIGHTS.get(source, 0.6)


def _half_life_for_source(source: str, settings: dict | None = None,
                          age_hours: float = 0.0,
                          metadata: dict | None = None) -> float:
    """Return decay half-life in hours for a source.

    Manual facts use a phased schedule:
      - within 30 days of last_verified: phase1 (720h, gentle)
      - beyond 30 days: phase2 (1440h, steeper)

    v2.35.2 — volatile metadata overrides source default. Facts produced by
    short-lived probes (e.g. container_tcp_probe reachability) should age out
    quickly even though the source weight is agent_observation.
    """
    s = settings or {}
    if metadata and metadata.get("volatile"):
        return float(s.get("factHalfLifeHours_agent_volatile", 2.0))
    if source == "manual":
        phase1 = float(s.get("factHalfLifeHours_manual_phase1", 720.0))
        phase2 = float(s.get("factHalfLifeHours_manual_phase2", 1440.0))
        return phase1 if age_hours < 720.0 else phase2
    if source == "agent_observation":
        return float(s.get("factHalfLifeHours_agent",
                           _DEFAULT_HALF_LIVES_HOURS.get("agent_observation", 24.0)))
    if source == "rag_extraction":
        return float(s.get("factHalfLifeHours_rag",
                           _DEFAULT_HALF_LIVES_HOURS.get("rag_extraction", 720.0)))
    # All collectors
    return float(s.get("factHalfLifeHours_collector", 168.0))


def _get_facts_settings() -> dict:
    """Pull facts-related settings from the settings store. Best-effort."""
    out: dict = {}
    try:
        from mcp_server.tools.skills.storage import get_backend
        be = get_backend()
        keys = [
            "factInjectionThreshold", "factInjectionMaxRows",
            "factHalfLifeHours_collector", "factHalfLifeHours_agent",
            "factHalfLifeHours_manual_phase1", "factHalfLifeHours_manual_phase2",
            "factHalfLifeHours_agent_volatile",
            "factVerifyCountCap",
            # v2.35.3 — fact-age rejection
            "factAgeRejectionMode", "factAgeRejectionMaxAgeMin",
            "factAgeRejectionMinConfidence",
            # v2.35.4 — runbook injection / classifier
            "runbookInjectionMode", "runbookClassifierMode",
        ]
        for s in _DEFAULT_SOURCE_WEIGHTS:
            keys.append(f"factSourceWeight_{s}")
        for k in keys:
            v = be.get_setting(k)
            if v is not None and str(v).strip() != "":
                try:
                    out[k] = float(v) if "." in str(v) or k.startswith("factSourceWeight_") else (
                        int(v) if str(v).lstrip("-").isdigit() else v
                    )
                except (ValueError, TypeError):
                    out[k] = v
    except Exception:
        pass
    return out


def compute_confidence(row: dict, settings: dict | None = None) -> float:
    """Deterministic confidence score in [0.0, 1.0].

    See PHASE_v2.35_SPEC.md for rationale.
    """
    s = settings if settings is not None else _get_facts_settings()

    source = row.get("source", "unknown")
    weight_key = f"factSourceWeight_{source}"
    base = float(s.get(weight_key, _default_source_weight(source)))

    last_verified = row.get("last_verified")
    if isinstance(last_verified, str):
        try:
            last_verified = datetime.fromisoformat(last_verified.replace("Z", "+00:00"))
        except Exception:
            last_verified = _now()
    elif last_verified is None:
        last_verified = _now()
    if last_verified.tzinfo is None:
        last_verified = last_verified.replace(tzinfo=timezone.utc)

    hours_since = max(0.0, (_now() - last_verified).total_seconds() / 3600.0)
    row_metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else None
    half_life = _half_life_for_source(source, s, age_hours=hours_since,
                                      metadata=row_metadata)
    age_factor = 0.5 ** (hours_since / half_life) if half_life > 0 else 1.0

    cap = int(s.get("factVerifyCountCap", 10))
    vc = min(int(row.get("verify_count", 1)), cap)
    verify_boost = min(0.2, 0.05 * math.log2(vc + 1))

    penalty = 0.0
    for c in row.get("contradicts", []) or []:
        c_source = c.get("source", "unknown") if isinstance(c, dict) else "unknown"
        c_weight = float(s.get(f"factSourceWeight_{c_source}",
                               _default_source_weight(c_source)))
        penalty = max(penalty, 0.1 * c_weight)

    return max(0.0, min(1.0, base * age_factor + verify_boost - penalty))


def _json_dumps(value) -> str:
    return json.dumps(value, default=str, sort_keys=True)


def _values_equal(a, b) -> bool:
    """Compare two JSON-serialisable values for upsert equality.

    Normalises via json canonical form so dicts with different key orderings
    are still considered equal.
    """
    try:
        return _json_dumps(a) == _json_dumps(b)
    except Exception:
        return a == b


def init_known_facts() -> bool:
    """Create tables + seed refresh schedule defaults. Idempotent."""
    global _initialized
    if _initialized:
        return True
    if not _is_pg():
        _initialized = True
        return True
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        if conn is None:
            return False
        conn.autocommit = True
        cur = conn.cursor()
        for stmt in _DDL_PG.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                cur.execute(stmt)
        # Seed schedule defaults (idempotent via ON CONFLICT DO NOTHING)
        for pattern, cadence, desc in _SCHEDULE_SEEDS:
            cur.execute(
                "INSERT INTO known_facts_refresh_schedule (pattern, cadence_sec, description) "
                "VALUES (%s, %s, %s) ON CONFLICT (pattern) DO NOTHING",
                (pattern, cadence, desc),
            )
        # v2.35.1 — seed keyword corpus from hardcoded defaults
        for kw, resolver, win, desc in _KEYWORD_SEEDS:
            cur.execute(
                "INSERT INTO known_facts_keywords "
                "(keyword, resolver_name, default_window_min, description, active, added_by) "
                "VALUES (%s, %s, %s, %s, TRUE, 'system') "
                "ON CONFLICT (keyword) DO NOTHING",
                (kw, resolver, win, desc),
            )
        cur.close()
        conn.close()
        _initialized = True
        log.info("known_facts tables ready")
        return True
    except Exception as e:
        log.warning("known_facts init failed: %s", e)
        return False


def _fetch_lock(cur, fact_key: str) -> dict | None:
    cur.execute(
        "SELECT fact_key, locked_value, locked_by, locked_at, note FROM known_facts_locks "
        "WHERE fact_key = %s",
        (fact_key,),
    )
    row = cur.fetchone()
    if not row:
        return None
    return {
        "fact_key": row[0],
        "locked_value": row[1],
        "locked_by": row[2],
        "locked_at": row[3].isoformat() if hasattr(row[3], "isoformat") else row[3],
        "note": row[4],
    }


def _record_conflict(cur, fact_key: str, locked_value, offered_source: str, offered_value) -> None:
    cur.execute(
        "INSERT INTO known_facts_conflicts "
        "(fact_key, locked_value, offered_source, offered_value) "
        "VALUES (%s, %s::jsonb, %s, %s::jsonb)",
        (fact_key, _json_dumps(locked_value), offered_source, _json_dumps(offered_value)),
    )


def _merge_contradicts(cur, fact_key: str, new_source: str, new_value) -> list[dict]:
    """Detect cross-source contradictions and append to each row's contradicts.

    Returns the list of other-source rows found to disagree with the new value.
    """
    cur.execute(
        "SELECT source, fact_value, contradicts FROM known_facts_current "
        "WHERE fact_key = %s AND source <> %s",
        (fact_key, new_source),
    )
    other_rows = cur.fetchall()
    disagreements = []
    for other_source, other_value, other_contradicts in other_rows:
        if _values_equal(new_value, other_value):
            continue
        disagreements.append({"source": other_source, "value": other_value})

        # Append ourselves to the other row's contradicts
        prev = other_contradicts if isinstance(other_contradicts, list) else (other_contradicts or [])
        updated_other = list(prev) + [{
            "source": new_source,
            "value": new_value,
            "seen_at": _ts(),
        }]
        cur.execute(
            "UPDATE known_facts_current SET contradicts = %s::jsonb "
            "WHERE fact_key = %s AND source = %s",
            (_json_dumps(updated_other), fact_key, other_source),
        )
    return disagreements


def upsert_fact(
    fact_key: str,
    source: str,
    value,
    metadata: dict | None = None,
    actor: str = "collector",
) -> dict:
    """Upsert a single fact.

    Returns {action, prior_value, new_value, confidence} (keys vary).
    Action is one of: 'insert', 'touch', 'change', 'conflict', 'noop'.
    Never raises.
    """
    if not _is_pg() or not fact_key or not source:
        return {"action": "noop"}
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        if conn is None:
            return {"action": "noop"}
        cur = conn.cursor()

        lock = _fetch_lock(cur, fact_key)
        if lock and not _values_equal(lock["locked_value"], value):
            _record_conflict(cur, fact_key, lock["locked_value"], source, value)
            conn.commit()
            cur.close(); conn.close()
            return {"action": "conflict", "locked_value": lock["locked_value"],
                    "offered_value": value}

        cur.execute(
            "SELECT fact_value, verify_count, first_seen, contradicts "
            "FROM known_facts_current WHERE fact_key = %s AND source = %s",
            (fact_key, source),
        )
        existing = cur.fetchone()

        disagreements = _merge_contradicts(cur, fact_key, source, value)

        now_iso = _ts()
        md_json = _json_dumps(metadata or {})

        if existing is None:
            row_for_conf = {
                "source": source,
                "last_verified": _now(),
                "verify_count": 1,
                "contradicts": disagreements,
                "metadata": metadata or {},
            }
            confidence = compute_confidence(row_for_conf)
            cur.execute(
                "INSERT INTO known_facts_current "
                "(fact_key, source, fact_value, first_seen, last_verified, "
                " verify_count, contradicts, confidence, metadata, "
                " change_detected, change_flagged_at) "
                "VALUES (%s, %s, %s::jsonb, %s, %s, 1, %s::jsonb, %s, %s::jsonb, TRUE, %s)",
                (
                    fact_key, source, _json_dumps(value),
                    now_iso, now_iso,
                    _json_dumps(disagreements),
                    confidence, md_json,
                    now_iso,
                ),
            )
            conn.commit(); cur.close(); conn.close()
            result = {"action": "insert", "prior_value": None,
                      "new_value": value, "confidence": confidence}
            if disagreements:
                result["contradict"] = True
            return result

        prior_value, prior_vc, first_seen, prior_contradicts = existing
        if _values_equal(prior_value, value):
            # Touch
            new_vc = int(prior_vc or 1) + 1
            row_for_conf = {
                "source": source,
                "last_verified": _now(),
                "verify_count": new_vc,
                "contradicts": disagreements,
                "metadata": metadata or {},
            }
            confidence = compute_confidence(row_for_conf)
            cur.execute(
                "UPDATE known_facts_current SET "
                "last_verified = %s, verify_count = %s, confidence = %s, "
                "contradicts = %s::jsonb, metadata = %s::jsonb "
                "WHERE fact_key = %s AND source = %s",
                (now_iso, new_vc, confidence,
                 _json_dumps(disagreements), md_json,
                 fact_key, source),
            )
            conn.commit(); cur.close(); conn.close()
            return {"action": "touch", "new_value": value,
                    "confidence": confidence, "verify_count": new_vc}

        # Value changed
        cur.execute(
            "INSERT INTO known_facts_history "
            "(fact_key, source, prior_value, new_value, changed_by, metadata) "
            "VALUES (%s, %s, %s::jsonb, %s::jsonb, %s, %s::jsonb)",
            (fact_key, source, _json_dumps(prior_value), _json_dumps(value),
             actor, md_json),
        )
        row_for_conf = {
            "source": source,
            "last_verified": _now(),
            "verify_count": 1,
            "contradicts": disagreements,
            "metadata": metadata or {},
        }
        confidence = compute_confidence(row_for_conf)
        cur.execute(
            "UPDATE known_facts_current SET "
            "fact_value = %s::jsonb, last_verified = %s, verify_count = 1, "
            "confidence = %s, contradicts = %s::jsonb, metadata = %s::jsonb, "
            "change_detected = TRUE, change_flagged_at = %s "
            "WHERE fact_key = %s AND source = %s",
            (_json_dumps(value), now_iso, confidence,
             _json_dumps(disagreements), md_json, now_iso,
             fact_key, source),
        )
        conn.commit(); cur.close(); conn.close()
        result = {"action": "change", "prior_value": prior_value,
                  "new_value": value, "confidence": confidence}
        if disagreements:
            result["contradict"] = True
        return result
    except Exception as e:
        log.debug("upsert_fact failed for %s/%s: %s", fact_key, source, e)
        return {"action": "noop", "error": str(e)}


def batch_upsert_facts(facts: list[dict], actor: str = "collector") -> dict:
    """Batch-upsert. Returns totals per action kind."""
    totals = {"insert": 0, "touch": 0, "change": 0, "conflict": 0,
              "contradict": 0, "noop": 0}
    if not facts:
        return totals
    for f in facts:
        fk = f.get("fact_key") or ""
        src = f.get("source") or ""
        val = f.get("value")
        if not fk or not src:
            totals["noop"] += 1
            continue
        r = upsert_fact(
            fact_key=fk, source=src, value=val,
            metadata=f.get("metadata"),
            actor=actor,
        )
        act = r.get("action", "noop")
        totals[act] = totals.get(act, 0) + 1
        if r.get("contradict"):
            totals["contradict"] += 1
    return totals


def _pattern_to_like(pattern: str) -> str:
    return pattern.replace("*", "%")


def _rows_to_dicts(cur) -> list[dict]:
    cols = [d[0] for d in cur.description]
    out = []
    for r in cur.fetchall():
        d = dict(zip(cols, r))
        for k, v in list(d.items()):
            if hasattr(v, "isoformat"):
                d[k] = v.isoformat()
        out.append(d)
    return out


def get_fact(fact_key: str, min_confidence: float = 0.0) -> list[dict]:
    """Return all rows for a fact_key across sources, above min_confidence."""
    if not _is_pg() or not fact_key:
        return []
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        if conn is None:
            return []
        cur = conn.cursor()
        cur.execute(
            "SELECT fact_key, source, fact_value, first_seen, last_verified, "
            "verify_count, contradicts, confidence, metadata, change_detected, "
            "change_flagged_at FROM known_facts_current "
            "WHERE fact_key = %s AND confidence >= %s "
            "ORDER BY confidence DESC, last_verified DESC",
            (fact_key, min_confidence),
        )
        rows = _rows_to_dicts(cur)
        cur.close(); conn.close()
        return rows
    except Exception as e:
        log.debug("get_fact failed: %s", e)
        return []


def get_confident_facts(
    pattern: str | None = None,
    min_confidence: float = 0.7,
    max_rows: int = 40,
) -> list[dict]:
    """Return top rows above threshold, optionally filtered by pattern."""
    if not _is_pg():
        return []
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        if conn is None:
            return []
        cur = conn.cursor()
        if pattern:
            cur.execute(
                "SELECT fact_key, source, fact_value, first_seen, last_verified, "
                "verify_count, contradicts, confidence, metadata, change_detected, "
                "change_flagged_at FROM known_facts_current "
                "WHERE fact_key LIKE %s AND confidence >= %s "
                "ORDER BY confidence DESC, last_verified DESC LIMIT %s",
                (_pattern_to_like(pattern), min_confidence, max_rows),
            )
        else:
            cur.execute(
                "SELECT fact_key, source, fact_value, first_seen, last_verified, "
                "verify_count, contradicts, confidence, metadata, change_detected, "
                "change_flagged_at FROM known_facts_current "
                "WHERE confidence >= %s "
                "ORDER BY confidence DESC, last_verified DESC LIMIT %s",
                (min_confidence, max_rows),
            )
        rows = _rows_to_dicts(cur)
        cur.close(); conn.close()
        return rows
    except Exception as e:
        log.debug("get_confident_facts failed: %s", e)
        return []


def get_fact_history(fact_key: str, limit: int = 50) -> list[dict]:
    """Return history rows for a fact_key, newest first."""
    if not _is_pg() or not fact_key:
        return []
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        if conn is None:
            return []
        cur = conn.cursor()
        cur.execute(
            "SELECT id, fact_key, source, prior_value, new_value, changed_at, "
            "changed_by, metadata FROM known_facts_history "
            "WHERE fact_key = %s ORDER BY changed_at DESC LIMIT %s",
            (fact_key, limit),
        )
        rows = _rows_to_dicts(cur)
        cur.close(); conn.close()
        return rows
    except Exception as e:
        log.debug("get_fact_history failed: %s", e)
        return []


def get_pending_conflicts() -> list[dict]:
    """Unresolved conflicts for Dashboard badge + review UI."""
    if not _is_pg():
        return []
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        if conn is None:
            return []
        cur = conn.cursor()
        cur.execute(
            "SELECT id, fact_key, locked_value, offered_source, offered_value, offered_at "
            "FROM known_facts_conflicts WHERE resolved_at IS NULL "
            "ORDER BY offered_at DESC LIMIT 200"
        )
        rows = _rows_to_dicts(cur)
        cur.close(); conn.close()
        return rows
    except Exception as e:
        log.debug("get_pending_conflicts failed: %s", e)
        return []


def get_recently_changed(hours: int = 24) -> list[dict]:
    """Rows with change_detected=TRUE and change_flagged_at within window."""
    if not _is_pg():
        return []
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        if conn is None:
            return []
        cur = conn.cursor()
        cur.execute(
            "SELECT fact_key, source, fact_value, last_verified, change_flagged_at, "
            "confidence FROM known_facts_current "
            "WHERE change_detected = TRUE "
            "  AND change_flagged_at >= NOW() - INTERVAL '%s hours' "
            "ORDER BY change_flagged_at DESC LIMIT 500" % int(hours)
        )
        rows = _rows_to_dicts(cur)
        cur.close(); conn.close()
        return rows
    except Exception as e:
        log.debug("get_recently_changed failed: %s", e)
        return []


def clear_change_flag(fact_key: str, source: str) -> None:
    """Reset change_detected after UI ack or after TTL expiry."""
    if not _is_pg() or not fact_key or not source:
        return
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        if conn is None:
            return
        cur = conn.cursor()
        cur.execute(
            "UPDATE known_facts_current SET change_detected = FALSE, "
            "change_flagged_at = NULL WHERE fact_key = %s AND source = %s",
            (fact_key, source),
        )
        conn.commit(); cur.close(); conn.close()
    except Exception as e:
        log.debug("clear_change_flag failed: %s", e)


def list_refresh_schedule_rows() -> list[dict]:
    """Return the full refresh-cadence table."""
    if not _is_pg():
        return []
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        if conn is None:
            return []
        cur = conn.cursor()
        cur.execute(
            "SELECT pattern, cadence_sec, description, updated_at, updated_by "
            "FROM known_facts_refresh_schedule ORDER BY pattern ASC"
        )
        rows = _rows_to_dicts(cur)
        cur.close(); conn.close()
        return rows
    except Exception as e:
        log.debug("list_refresh_schedule_rows failed: %s", e)
        return []


def get_stale_facts(pattern: str | None = None) -> list[dict]:
    """Facts past their expected refresh cadence.

    Matches each fact against known_facts_refresh_schedule. The most-specific
    pattern wins (longest matched pattern ignoring '*').
    """
    if not _is_pg():
        return []
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        if conn is None:
            return []
        cur = conn.cursor()
        schedule = list_refresh_schedule_rows()
        # Sort so more specific patterns (fewer wildcards, longer prefix) match first
        schedule_sorted = sorted(
            schedule,
            key=lambda s: (s["pattern"].count("*"), -len(s["pattern"])),
        )

        if pattern:
            cur.execute(
                "SELECT fact_key, source, last_verified, confidence "
                "FROM known_facts_current WHERE fact_key LIKE %s "
                "ORDER BY last_verified ASC LIMIT 5000",
                (_pattern_to_like(pattern),),
            )
        else:
            cur.execute(
                "SELECT fact_key, source, last_verified, confidence "
                "FROM known_facts_current "
                "ORDER BY last_verified ASC LIMIT 5000"
            )
        rows = _rows_to_dicts(cur)
        cur.close(); conn.close()

        now = _now()
        stale = []
        for r in rows:
            lv = r["last_verified"]
            if isinstance(lv, str):
                try:
                    lv_dt = datetime.fromisoformat(lv.replace("Z", "+00:00"))
                except Exception:
                    continue
            else:
                lv_dt = lv
            if lv_dt.tzinfo is None:
                lv_dt = lv_dt.replace(tzinfo=timezone.utc)
            age = (now - lv_dt).total_seconds()
            # Find matching schedule pattern
            cadence = 300
            for s in schedule_sorted:
                like = _pattern_to_like(s["pattern"])
                # SQL LIKE semantics — use a simple regex
                import re
                regex = "^" + like.replace("%", ".*") + "$"
                if re.match(regex, r["fact_key"]):
                    cadence = int(s["cadence_sec"])
                    break
            if age > cadence * 2:  # stale = 2x cadence
                stale.append({**r, "age_seconds": int(age), "cadence_sec": cadence})
        return stale
    except Exception as e:
        log.debug("get_stale_facts failed: %s", e)
        return []


def get_lock(fact_key: str) -> dict | None:
    """Return lock row for fact_key or None."""
    if not _is_pg() or not fact_key:
        return None
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        if conn is None:
            return None
        cur = conn.cursor()
        result = _fetch_lock(cur, fact_key)
        cur.close(); conn.close()
        return result
    except Exception as e:
        log.debug("get_lock failed: %s", e)
        return None


def sample_fact_rows(n: int = 10) -> list[dict]:
    """Return a small sample of current rows for Settings preview panel."""
    if not _is_pg():
        return []
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        if conn is None:
            return []
        cur = conn.cursor()
        cur.execute(
            "SELECT fact_key, source, fact_value, last_verified, verify_count, "
            "contradicts FROM known_facts_current "
            "ORDER BY last_verified DESC LIMIT %s",
            (n,),
        )
        rows = _rows_to_dicts(cur)
        cur.close(); conn.close()
        return rows
    except Exception as e:
        log.debug("sample_fact_rows failed: %s", e)
        return []


def get_summary_stats() -> dict:
    """Dashboard widget payload: counts by tier, last refresh, top changed."""
    if not _is_pg():
        return {"total": 0, "by_tier": {}, "pending_conflicts": 0,
                "recently_changed": [], "last_refresh": None}
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        if conn is None:
            return {"total": 0, "by_tier": {}, "pending_conflicts": 0,
                    "recently_changed": [], "last_refresh": None}
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM known_facts_current")
        total = int(cur.fetchone()[0])

        tiers = {}
        for label, lo, hi in [
            ("very_high", 0.9, 1.01),
            ("high",      0.7, 0.9),
            ("medium",    0.5, 0.7),
            ("low",       0.3, 0.5),
            ("reject",    0.0, 0.3),
        ]:
            cur.execute(
                "SELECT COUNT(*) FROM known_facts_current "
                "WHERE confidence >= %s AND confidence < %s",
                (lo, hi),
            )
            tiers[label] = int(cur.fetchone()[0])

        cur.execute(
            "SELECT COUNT(*) FROM known_facts_conflicts WHERE resolved_at IS NULL"
        )
        pending_conflicts = int(cur.fetchone()[0])

        cur.execute(
            "SELECT MAX(last_verified) FROM known_facts_current"
        )
        last_refresh_row = cur.fetchone()
        last_refresh = last_refresh_row[0].isoformat() if last_refresh_row and last_refresh_row[0] else None

        cur.execute(
            "SELECT fact_key, source, last_verified, change_flagged_at "
            "FROM known_facts_current WHERE change_detected = TRUE "
            "ORDER BY change_flagged_at DESC LIMIT 3"
        )
        recent = _rows_to_dicts(cur)
        cur.close(); conn.close()
        return {
            "total": total,
            "by_tier": tiers,
            "pending_conflicts": pending_conflicts,
            "recently_changed": recent,
            "last_refresh": last_refresh,
        }
    except Exception as e:
        log.debug("get_summary_stats failed: %s", e)
        return {"total": 0, "by_tier": {}, "pending_conflicts": 0,
                "recently_changed": [], "last_refresh": None}


# ── v2.35.0.1 admin helpers ──────────────────────────────────────────────────


def list_all_locks() -> list[dict]:
    """Return all current locks (admin UI)."""
    if not _is_pg():
        return []
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        if conn is None:
            return []
        cur = conn.cursor()
        cur.execute(
            "SELECT fact_key, locked_value, locked_by, locked_at, note, "
            "last_ack_by, last_ack_at FROM known_facts_locks "
            "ORDER BY locked_at DESC"
        )
        rows = _rows_to_dicts(cur)
        cur.close(); conn.close()
        return rows
    except Exception as e:
        log.debug("list_all_locks failed: %s", e)
        return []


def create_lock_row(fact_key: str, locked_value, note: str, locked_by: str) -> dict:
    """Create or replace a lock on fact_key."""
    if not _is_pg() or not fact_key:
        return {}
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        if conn is None:
            return {}
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO known_facts_locks (fact_key, locked_value, locked_by, note) "
            "VALUES (%s, %s::jsonb, %s, %s) "
            "ON CONFLICT (fact_key) DO UPDATE SET "
            " locked_value = EXCLUDED.locked_value, "
            " locked_by = EXCLUDED.locked_by, "
            " locked_at = NOW(), "
            " note = EXCLUDED.note",
            (fact_key, _json_dumps(locked_value), locked_by, note or ""),
        )
        conn.commit()
        result = _fetch_lock(cur, fact_key) or {}
        cur.close(); conn.close()
        return result
    except Exception as e:
        log.warning("create_lock_row failed: %s", e)
        return {}


def remove_lock_row(fact_key: str) -> None:
    if not _is_pg() or not fact_key:
        return
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        if conn is None:
            return
        cur = conn.cursor()
        cur.execute("DELETE FROM known_facts_locks WHERE fact_key=%s", (fact_key,))
        conn.commit()
        cur.close(); conn.close()
    except Exception as e:
        log.warning("remove_lock_row failed: %s", e)


def update_lock(fact_key: str, new_value, actor: str) -> None:
    """Update an existing lock's value + current row to new_value."""
    if not _is_pg() or not fact_key:
        return
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        if conn is None:
            return
        cur = conn.cursor()
        cur.execute(
            "UPDATE known_facts_locks SET locked_value=%s::jsonb, locked_by=%s, "
            "locked_at=NOW() WHERE fact_key=%s",
            (_json_dumps(new_value), actor, fact_key),
        )
        # Also reflect into current rows so agents see the reconciled value.
        cur.execute(
            "UPDATE known_facts_current SET fact_value=%s::jsonb, "
            "last_verified=NOW(), change_detected=TRUE, change_flagged_at=NOW() "
            "WHERE fact_key=%s",
            (_json_dumps(new_value), fact_key),
        )
        conn.commit()
        cur.close(); conn.close()
    except Exception as e:
        log.warning("update_lock failed: %s", e)


def get_conflict(conflict_id: int) -> dict | None:
    if not _is_pg() or not conflict_id:
        return None
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        if conn is None:
            return None
        cur = conn.cursor()
        cur.execute(
            "SELECT id, fact_key, locked_value, offered_source, offered_value, "
            "offered_at, resolved_at, resolved_by, resolution, notes "
            "FROM known_facts_conflicts WHERE id=%s",
            (conflict_id,),
        )
        row = cur.fetchone()
        if not row:
            cur.close(); conn.close()
            return None
        cols = [d[0] for d in cur.description]
        out = dict(zip(cols, row))
        for k, v in list(out.items()):
            if hasattr(v, "isoformat"):
                out[k] = v.isoformat()
        cur.close(); conn.close()
        return out
    except Exception as e:
        log.debug("get_conflict failed: %s", e)
        return None


def mark_conflict_resolved(
    conflict_id: int,
    actor: str,
    resolution: str,
    extra: dict | None = None,
) -> None:
    if not _is_pg() or not conflict_id:
        return
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        if conn is None:
            return
        cur = conn.cursor()
        cur.execute(
            "UPDATE known_facts_conflicts SET resolved_at=NOW(), "
            "resolved_by=%s, resolution=%s, notes=%s WHERE id=%s",
            (actor, resolution, _json_dumps(extra or {}), conflict_id),
        )
        conn.commit()
        cur.close(); conn.close()
    except Exception as e:
        log.warning("mark_conflict_resolved failed: %s", e)


def refresh_manual_fact_timestamp(fact_key: str, actor: str) -> None:
    """Re-assert last_verified for a manual fact (UI refresh button)."""
    if not _is_pg() or not fact_key:
        return
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        if conn is None:
            return
        cur = conn.cursor()
        cur.execute(
            "UPDATE known_facts_current SET last_verified=NOW(), "
            "verify_count = verify_count + 1 "
            "WHERE fact_key=%s AND source='manual'",
            (fact_key,),
        )
        conn.commit()
        cur.close(); conn.close()
    except Exception as e:
        log.warning("refresh_manual_fact_timestamp failed: %s", e)


def write_audit(action: str, fact_key: str | None, actor: str, detail: dict | None = None) -> None:
    """Append an entry to facts_audit_log."""
    if not _is_pg():
        return
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        if conn is None:
            return
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO facts_audit_log (action, fact_key, actor, detail) "
            "VALUES (%s, %s, %s, %s::jsonb)",
            (action, fact_key, actor, _json_dumps(detail or {})),
        )
        conn.commit()
        cur.close(); conn.close()
    except Exception as e:
        log.debug("write_audit failed: %s", e)


def list_audit_log(limit: int = 100) -> list[dict]:
    if not _is_pg():
        return []
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        if conn is None:
            return []
        cur = conn.cursor()
        cur.execute(
            "SELECT id, action, fact_key, actor, at, detail "
            "FROM facts_audit_log ORDER BY at DESC LIMIT %s",
            (int(limit),),
        )
        rows = _rows_to_dicts(cur)
        cur.close(); conn.close()
        return rows
    except Exception as e:
        log.debug("list_audit_log failed: %s", e)
        return []


def get_gauge_snapshot() -> dict:
    """Return the facts-related gauge values for Prometheus refresh loop."""
    snap = {
        "total": 0,
        "confident": 0,
        "pending_conflicts": 0,
        "stale_by_platform": {},
    }
    if not _is_pg():
        return snap
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        if conn is None:
            return snap
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM known_facts_current")
        snap["total"] = int(cur.fetchone()[0])

        settings = _get_facts_settings()
        threshold = float(settings.get("factInjectionThreshold", 0.7))
        cur.execute(
            "SELECT COUNT(*) FROM known_facts_current WHERE confidence >= %s",
            (threshold,),
        )
        snap["confident"] = int(cur.fetchone()[0])

        cur.execute(
            "SELECT COUNT(*) FROM known_facts_conflicts WHERE resolved_at IS NULL"
        )
        snap["pending_conflicts"] = int(cur.fetchone()[0])
        cur.close(); conn.close()

        stale = get_stale_facts()
        by_platform: dict[str, int] = {}
        for row in stale:
            fk = row.get("fact_key", "")
            parts = fk.split(".")
            platform = parts[1] if len(parts) >= 2 else "unknown"
            by_platform[platform] = by_platform.get(platform, 0) + 1
        snap["stale_by_platform"] = by_platform
    except Exception as e:
        log.debug("get_gauge_snapshot failed: %s", e)
    return snap


# ── v2.35.2 agent_observation query helper (trace digest) ───────────────────

def get_facts_by_operation(operation_id: str, limit: int = 200) -> list[dict]:
    """Return agent_observation facts whose metadata.operation_id matches.

    Used by the trace digest renderer to surface which facts this run wrote
    to the known_facts store. Postgres only; safe no-op on SQLite.
    """
    if not _is_pg() or not operation_id:
        return []
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        if conn is None:
            return []
        cur = conn.cursor()
        cur.execute(
            "SELECT fact_key, source, fact_value, last_verified, confidence, metadata "
            "FROM known_facts_current "
            "WHERE source = 'agent_observation' "
            "  AND metadata ->> 'operation_id' = %s "
            "ORDER BY last_verified DESC LIMIT %s",
            (operation_id, int(limit)),
        )
        rows = _rows_to_dicts(cur)
        cur.close(); conn.close()
        return rows
    except Exception as e:
        log.debug("get_facts_by_operation failed: %s", e)
        return []


# ── v2.35.1 keyword corpus helpers ───────────────────────────────────────────

def list_keywords_rows(active_only: bool = True) -> list[dict]:
    if not _is_pg():
        return []
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        if conn is None:
            return []
        cur = conn.cursor()
        if active_only:
            cur.execute(
                "SELECT keyword, resolver_name, default_window_min, description, "
                "active, added_by, added_at FROM known_facts_keywords "
                "WHERE active = TRUE ORDER BY keyword ASC"
            )
        else:
            cur.execute(
                "SELECT keyword, resolver_name, default_window_min, description, "
                "active, added_by, added_at FROM known_facts_keywords "
                "ORDER BY keyword ASC"
            )
        rows = _rows_to_dicts(cur)
        cur.close(); conn.close()
        return rows
    except Exception as e:
        log.debug("list_keywords_rows failed: %s", e)
        return []


def upsert_keyword_row(keyword: str, resolver_name: str,
                       default_window_min: int | None,
                       description: str, active: bool, actor: str) -> dict:
    if not _is_pg() or not keyword or not resolver_name:
        return {}
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        if conn is None:
            return {}
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO known_facts_keywords "
            "(keyword, resolver_name, default_window_min, description, active, added_by) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (keyword) DO UPDATE SET "
            " resolver_name = EXCLUDED.resolver_name, "
            " default_window_min = EXCLUDED.default_window_min, "
            " description = EXCLUDED.description, "
            " active = EXCLUDED.active, "
            " added_by = EXCLUDED.added_by, "
            " added_at = NOW()",
            (keyword.lower().strip(), resolver_name, default_window_min,
             description or "", bool(active), actor),
        )
        conn.commit()
        cur.execute(
            "SELECT keyword, resolver_name, default_window_min, description, "
            "active, added_by, added_at FROM known_facts_keywords WHERE keyword=%s",
            (keyword.lower().strip(),),
        )
        rows = _rows_to_dicts(cur)
        cur.close(); conn.close()
        return rows[0] if rows else {}
    except Exception as e:
        log.warning("upsert_keyword_row failed: %s", e)
        return {}


def delete_keyword_row(keyword: str) -> None:
    if not _is_pg() or not keyword:
        return
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        if conn is None:
            return
        cur = conn.cursor()
        cur.execute("DELETE FROM known_facts_keywords WHERE keyword=%s",
                    (keyword.lower().strip(),))
        conn.commit()
        cur.close(); conn.close()
    except Exception as e:
        log.warning("delete_keyword_row failed: %s", e)


def record_keyword_suggestion(task: str, proposal) -> None:
    """Append a suggestion row for admin review (auto-propose from tier 3)."""
    if not _is_pg():
        return
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        if conn is None:
            return
        cur = conn.cursor()
        proposed_kw = None
        if isinstance(proposal, list) and proposal:
            proposed_kw = str(proposal[0])[:64]
        elif isinstance(proposal, str):
            proposed_kw = proposal[:64]
        cur.execute(
            "INSERT INTO known_facts_keyword_suggestions "
            "(proposed_keyword, raw_task, raw_proposal, status) "
            "VALUES (%s, %s, %s::jsonb, 'pending')",
            (proposed_kw, (task or "")[:1024], _json_dumps(proposal)),
        )
        conn.commit()
        cur.close(); conn.close()
    except Exception as e:
        log.debug("record_keyword_suggestion failed: %s", e)


def list_keyword_suggestions(status: str = "pending", limit: int = 100) -> list[dict]:
    if not _is_pg():
        return []
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        if conn is None:
            return []
        cur = conn.cursor()
        cur.execute(
            "SELECT id, proposed_keyword, raw_task, raw_proposal, status, "
            "created_at, reviewed_at, reviewed_by FROM known_facts_keyword_suggestions "
            "WHERE status = %s ORDER BY created_at DESC LIMIT %s",
            (status, int(limit)),
        )
        rows = _rows_to_dicts(cur)
        cur.close(); conn.close()
        return rows
    except Exception as e:
        log.debug("list_keyword_suggestions failed: %s", e)
        return []


def review_keyword_suggestion(suggestion_id: int, status: str, actor: str) -> None:
    if not _is_pg() or not suggestion_id:
        return
    if status not in ("accepted", "rejected", "dismissed"):
        return
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        if conn is None:
            return
        cur = conn.cursor()
        cur.execute(
            "UPDATE known_facts_keyword_suggestions SET status=%s, "
            "reviewed_at=NOW(), reviewed_by=%s WHERE id=%s",
            (status, actor, int(suggestion_id)),
        )
        conn.commit()
        cur.close(); conn.close()
    except Exception as e:
        log.warning("review_keyword_suggestion failed: %s", e)
