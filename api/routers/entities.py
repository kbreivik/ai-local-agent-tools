"""
GET /api/entities        — canonical per-resource health list (auth required)
GET /api/entities/health — global rollup status (no auth)
GET /api/entities/section/{section} — filtered by section (auth required)
"""
import json
import logging

from fastapi import APIRouter, Depends

from api.auth import get_current_user
from api.db.base import get_engine
from api.db import queries as q

router = APIRouter(prefix="/api/entities", tags=["entities"])
log = logging.getLogger(__name__)

_STATUS_PRIORITY = ["error", "degraded", "unknown", "maintenance", "healthy"]


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
