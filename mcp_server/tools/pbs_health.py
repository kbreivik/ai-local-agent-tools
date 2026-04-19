"""PBS datastore health tool — read-only, collector-sourced.

Reads the most recent status_snapshots row for component='pbs' (written by
the PBSCollector every PBS_POLL_INTERVAL seconds — default 60s) and
returns a per-datastore health summary: usage pct, GC status, and a
HEALTHY/DEGRADED/CRITICAL flag. Also cross-references infra_inventory
rows with platform='pbs_backup' to surface the freshest backup
timestamp per datastore when available.

Sync-only, no live PBS API call is made.

v2.35.15 — DB access uses a self-contained per-call engine with
pool_pre_ping=True instead of the shared singleton. This guarantees
the tool does not reuse a stale pooled connection (the singleton can
outlive a DB reconnect across the agent loop's event loop) and that
the tool is invocable from any sync context — including inside an
already-running event loop — without asyncio.run_until_complete
entanglement.
"""
import json
import logging
import os
import time

log = logging.getLogger(__name__)


def _build_sync_db_url() -> str:
    """Return a synchronous-driver DB URL, mirroring api/db/base._build_url
    but substituting sync drivers for any async ones. Empty string if no
    DATABASE_URL is set and no SQLite default resolvable."""
    url = os.environ.get("DATABASE_URL", "") or ""
    if url:
        return (
            url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
               .replace("postgresql+asyncpg", "postgresql+psycopg2")
               .replace("sqlite+aiosqlite", "sqlite")
        )
    # Fallback to the project's default sqlite path via api/db/base
    try:
        from api.db.base import _build_url
        return _build_url().replace("sqlite+aiosqlite", "sqlite")
    except Exception:
        return ""


def _parse_state(state) -> dict:
    """status_snapshots.state may be a dict (PG JSONB) or a JSON string
    (SQLite)."""
    if isinstance(state, dict):
        return state
    if isinstance(state, str) and state.strip():
        try:
            return json.loads(state)
        except Exception:
            return {}
    return {}


def pbs_datastore_health() -> dict:
    """Return a health snapshot of every PBS datastore.

    Returns {status, message, data: {datastores: [...], summary: str}}.
    Sourced from the most recent PBS collector snapshot — no live API
    call. Flag per datastore: HEALTHY (<85%), DEGRADED (>=85%),
    CRITICAL (>=95%). Also includes the freshest backup age per
    datastore when infra_inventory has pbs_backup rows for it.
    """
    db_url = _build_sync_db_url()
    if not db_url:
        return {
            "status": "error",
            "message": "DATABASE_URL not configured",
            "data": {},
        }
    try:
        from sqlalchemy import create_engine, text
        eng = create_engine(db_url, pool_pre_ping=True, pool_size=1)
        try:
            with eng.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT state, timestamp FROM status_snapshots "
                        "WHERE component = 'pbs' "
                        "ORDER BY timestamp DESC LIMIT 1"
                    )
                ).mappings().first()
        finally:
            eng.dispose()
    except Exception as e:
        return {
            "status": "error",
            "message": f"PBS snapshot query failed: {e}",
            "data": {},
        }

    if not row:
        return {
            "status": "ok",
            "message": "No PBS snapshots found. Check that a PBS "
                       "connection is configured and the PBS collector "
                       "has polled at least once.",
            "data": {"datastores": [], "summary": "no snapshots"},
        }

    state = _parse_state(row["state"])
    raw_datastores = state.get("datastores") or []

    if not raw_datastores:
        return {
            "status": "ok",
            "message": "PBS snapshot has no datastores — PBS may be "
                       "unconfigured or unreachable.",
            "data": {"datastores": [], "summary": "no datastores",
                     "snapshot_ts": str(row["timestamp"])},
        }

    # Build backup-age lookup from infra_inventory (platform='pbs_backup').
    backup_age: dict[str, float] = {}
    try:
        from api.db.infra_inventory import list_inventory
        now = time.time()
        for r in (list_inventory(platform="pbs_backup") or []):
            meta = r.get("meta") or {}
            ds = meta.get("datastore")
            ts = int(meta.get("last_backup_ts") or 0)
            if not ds or not ts:
                continue
            age_h = (now - ts) / 3600.0
            prev = backup_age.get(ds)
            if prev is None or age_h < prev:
                backup_age[ds] = age_h
    except Exception as e:
        log.debug("pbs_datastore_health: backup-age lookup failed: %s", e)

    enriched: list[dict] = []
    degraded = 0
    for ds in raw_datastores:
        name = ds.get("name") or "unknown"
        pct = ds.get("usage_pct") or 0.0
        try:
            pct = float(pct)
        except (TypeError, ValueError):
            pct = 0.0
        flag = "HEALTHY"
        if pct >= 95:
            flag = "CRITICAL"
            degraded += 1
        elif pct >= 85:
            flag = "DEGRADED"
            degraded += 1
        age_h = backup_age.get(name)
        enriched.append({
            "name": name,
            "used_gb": ds.get("used_gb"),
            "total_gb": ds.get("total_gb"),
            "usage_pct": round(pct, 1),
            "gc_status": ds.get("gc_status") or "",
            "last_backup_age_hours": round(age_h, 1) if age_h is not None else None,
            "flag": flag,
        })

    tasks = state.get("tasks") or {}
    summary = (
        f"{len(enriched)} datastores, {degraded} flagged "
        f"({'all healthy' if degraded == 0 else 'attention needed'}); "
        f"recent tasks: {tasks.get('recent_count', 0)} total, "
        f"{tasks.get('failed_count', 0)} failed"
    )

    return {
        "status": "ok",
        "message": summary,
        "data": {
            "datastores": enriched,
            "tasks": tasks,
            "summary": summary,
            "snapshot_ts": str(row["timestamp"]),
        },
    }
