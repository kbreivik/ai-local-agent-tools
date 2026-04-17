"""
GET /api/entities        — canonical per-resource health list (auth required)
GET /api/entities/health — global rollup status (no auth)
GET /api/entities/section/{section} — filtered by section (auth required)
"""
import json
import logging
import time as _time

from fastapi import APIRouter, Depends

from api.auth import get_current_user
from api.db.base import get_engine
from api.db import queries as q

router = APIRouter(prefix="/api/entities", tags=["entities"])
log = logging.getLogger(__name__)

_STATUS_PRIORITY = ["error", "degraded", "unknown", "maintenance", "healthy"]

# ── Entity-by-ID cache ────────────────────────────────────────────────────────
# Keyed by entity_id string. TTL matches poll interval (30s) so data stays fresh.
_entity_cache: dict[str, tuple[dict, float]] = {}  # entity_id → (entity_dict, monotonic_ts)
_ENTITY_CACHE_TTL = 30.0


def _entity_id_to_component(entity_id: str) -> str | None:
    """Map entity_id prefix to collector component name.
    Returns None for bare labels (e.g. vm_host labels like 'ds-docker-worker-01')
    which require a fallback full scan."""
    _PREFIX_MAP = {
        "proxmox_vms":       "proxmox_vms",
        "docker":            "docker_agent01",
        "swarm":             "swarm",
        "external_services": "external_services",
        "unifi":             "unifi",
        "pbs":               "pbs",
        "truenas":           "truenas",
        "fortigate":         "fortigate",
        "kafka":             "kafka_cluster",
        "elasticsearch":     "elasticsearch",
    }


async def _build_entities() -> list[dict]:
    from api.collectors.manager import manager
    result: list[dict] = []
    async with get_engine().connect() as conn:
        for component, collector in manager._collectors.items():
            try:
                snap = await q.get_latest_snapshot(conn, component)
                if not snap:
                    continue
                state = snap.get("state") or {}
                if isinstance(state, str):
                    try:
                        state = json.loads(state)
                    except Exception:
                        continue
                entities = collector.to_entities(state)
                ts = snap.get("timestamp")
                for e in entities:
                    d = e.to_dict()
                    if ts:
                        d["last_seen"] = ts if isinstance(ts, str) else ts.isoformat()
                    result.append(d)
            except Exception as exc:
                log.warning("to_entities failed for %s: %s", component, exc)
    # Tag entities with has_drift so the GUI can render the ⚠ badge without
    # an N+1 per-card fetch. Single set lookup over the last 24h.
    try:
        from api.db.drift_events import entities_with_drift
        drift_ids = entities_with_drift(hours=24)
        for d in result:
            d["has_drift"] = d.get("id") in drift_ids
    except Exception as exc:
        log.debug("has_drift tagging skipped: %s", exc)
    return result


def _rollup(entities: list[dict]) -> str:
    active = [e for e in entities if e.get("status") != "maintenance"]
    if not active:
        return "unknown"
    return min(
        (e["status"] for e in active),
        key=lambda s: _STATUS_PRIORITY.index(s) if s in _STATUS_PRIORITY else 99,
        default="unknown",
    )


@router.get("/health")
async def entities_health():
    """Unauthenticated global health rollup."""
    try:
        entities = await _build_entities()
    except Exception as exc:
        log.warning("entities_health: %s", exc)
        return {"status": "unknown", "entity_count": 0, "error_count": 0}

    if not entities:
        return {"status": "unknown", "entity_count": 0, "error_count": 0}

    active = [e for e in entities if e.get("status") != "maintenance"]
    error_count = sum(1 for e in active if e["status"] == "error")
    section_summary: dict[str, dict] = {}
    for e in entities:
        sec = e.get("section", "UNKNOWN")
        entry = section_summary.setdefault(sec, {"total": 0, "error": 0, "degraded": 0, "healthy": 0})
        entry["total"] += 1
        st = e.get("status", "unknown")
        if st in entry:
            entry[st] += 1

    return {
        "status": _rollup(entities),
        "entity_count": len(entities),
        "error_count": error_count,
        "section_summary": section_summary,
    }


@router.get("")
async def list_entities(_: str = Depends(get_current_user)):
    """All current entities across all collectors."""
    return await _build_entities()


@router.get("/section/{section}")
async def entities_by_section(section: str, _: str = Depends(get_current_user)):
    """Entities for a specific section."""
    return [e for e in await _build_entities() if e.get("section") == section.upper()]


@router.get("/find/{entity_id:path}")
async def get_entity_by_id(entity_id: str, _: str = Depends(get_current_user)):
    """Fast single-entity lookup by ID.

    Strategy:
    1. Check in-memory cache (30s TTL — matches poll interval)
    2. Map entity_id prefix to collector component (1 DB query for that snapshot)
    3. Run to_entities() on that state, find the match
    4. Fallback: if prefix unknown (bare vm_host labels), scan all collectors

    Typically ~5ms vs ~300ms for GET /api/entities (full list).
    Returns the entity dict or null if not found.
    """
    # Cache hit
    if entity_id in _entity_cache:
        entity, cached_at = _entity_cache[entity_id]
        if _time.monotonic() - cached_at < _ENTITY_CACHE_TTL:
            return entity

    from api.collectors.manager import manager

    component = _entity_id_to_component(entity_id)

    if component:
        # Fast path: load only the relevant collector's snapshot
        async with get_engine().connect() as conn:
            snap = await q.get_latest_snapshot(conn, component)
        if not snap:
            return None
        state = snap.get("state") or {}
        if isinstance(state, str):
            try:
                state = json.loads(state)
            except Exception:
                return None
        collector = manager._collectors.get(component)
        if not collector:
            return None
        try:
            entities = collector.to_entities(state)
        except Exception as exc:
            log.warning("get_entity_by_id to_entities failed for %s: %s", component, exc)
            return None
        ts = snap.get("timestamp")
        for e in entities:
            d = e.to_dict()
            if ts:
                d["last_seen"] = ts if isinstance(ts, str) else ts.isoformat()
            if d.get("id") == entity_id:
                _entity_cache[entity_id] = (d, _time.monotonic())
                return d
    else:
        # Fallback: scan all collectors (handles bare vm_host labels, unknown types)
        result = await _build_entities()
        for entity in result:
            if entity.get("id") == entity_id:
                _entity_cache[entity_id] = (entity, _time.monotonic())
                return entity

    return None


@router.get("/{entity_id:path}/history")
async def entity_history(
    entity_id: str,
    hours: int = 48,
    _: str = Depends(get_current_user),
):
    """Return recent field changes and discrete events for one entity.

    entity_id is path-encoded (may contain colons, e.g. proxmox:hp1:100).
    hours: look-back window, default 48h, max 168h (7 days).
    """
    hours = min(max(1, hours), 168)
    from api.db.entity_history import get_changes, get_events
    changes = get_changes(entity_id, hours=hours, limit=50)
    events  = get_events(entity_id,  hours=hours, limit=50)
    return {
        "entity_id": entity_id,
        "hours":     hours,
        "changes":   changes,
        "events":    events,
    }


# Route ordering: `/drift/recent` must be declared BEFORE the path-captured
# `/{entity_id:path}/drift` below, otherwise FastAPI matches "drift" as an
# entity_id and the recent-drift endpoint becomes unreachable.
@router.get("/drift/recent")
async def drift_recent(
    hours: int = 24,
    _: str = Depends(get_current_user),
):
    """Recent drift events across all entities. Used by admin overview."""
    hours = min(max(1, hours), 168)
    from api.db.drift_events import recent_drift
    rows = recent_drift(hours=hours, limit=200)
    return {"since_hours": hours, "events": rows, "count": len(rows)}


@router.get("/{entity_id:path}/drift")
async def entity_drift(
    entity_id: str,
    _: str = Depends(get_current_user),
):
    """Drift events for one entity — what intentional config changed, when."""
    from api.db.drift_events import get_drift_for_entity
    rows = get_drift_for_entity(entity_id, limit=20)
    return {"entity_id": entity_id, "events": rows, "count": len(rows)}
