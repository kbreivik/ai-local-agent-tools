"""/api/facts — read + preview endpoints for the known_facts store (v2.35.0).

Admin-action endpoints (lock, unlock, accept_collector, edit_lock, grant) are
stubbed as 501 until v2.35.0.1 ships the UI that consumes them. The permission
model is documented in PHASE_v2.35_SPEC.md.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Body

from api.auth import get_current_user
from api.db.known_facts import (
    get_confident_facts,
    get_fact,
    get_fact_history,
    get_lock,
    get_pending_conflicts,
    get_recently_changed,
    get_stale_facts,
    get_summary_stats,
    list_refresh_schedule_rows,
    sample_fact_rows,
    compute_confidence,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/facts", tags=["facts"])


@router.get("")
async def list_facts(
    pattern: str | None = Query(None, description="LIKE-style pattern with * wildcards"),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    max_rows: int = Query(200, ge=1, le=1000),
    user: str = Depends(get_current_user),
):
    """List facts, optionally filtered."""
    rows = get_confident_facts(
        pattern=pattern, min_confidence=min_confidence, max_rows=max_rows
    )
    return {"facts": rows, "count": len(rows)}


@router.get("/conflicts")
async def list_conflicts(user: str = Depends(get_current_user)):
    """Pending conflicts (Dashboard badge + review UI)."""
    return {"conflicts": get_pending_conflicts()}


@router.get("/changed")
async def list_recent_changes(
    hours: int = Query(24, ge=1, le=168),
    user: str = Depends(get_current_user),
):
    """Facts with change_detected=TRUE within window."""
    return {"changes": get_recently_changed(hours)}


@router.get("/stale")
async def list_stale_facts(user: str = Depends(get_current_user)):
    """Facts past their expected refresh cadence."""
    return {"stale": get_stale_facts()}


@router.get("/summary")
async def facts_summary(user: str = Depends(get_current_user)):
    """Dashboard widget payload: counts by tier + last refresh + top changed."""
    return get_summary_stats()


@router.get("/schedule")
async def list_refresh_schedule(user: str = Depends(get_current_user)):
    """Refresh cadence table for Settings UI."""
    return {"schedule": list_refresh_schedule_rows()}


@router.post("/settings/preview")
async def preview_confidence(
    body: dict = Body(...),
    user: str = Depends(get_current_user),
):
    """Score sample facts against hypothetical settings for live preview."""
    hypothetical = body.get("settings", {}) if isinstance(body, dict) else {}
    samples = sample_fact_rows(n=10)
    scored = []
    for row in samples:
        scored.append({**row, "confidence": compute_confidence(row, hypothetical)})
    return {"preview": scored}


# --- Admin endpoints — stubbed until v2.35.0.1 ---

@router.post("/lock/{fact_key:path}")
async def lock_fact(fact_key: str, user: str = Depends(get_current_user)):
    """TODO v2.35.0.1: create an admin-assert lock on a fact key."""
    raise HTTPException(status_code=501, detail="Lock endpoint ships in v2.35.0.1")


@router.delete("/lock/{fact_key:path}")
async def unlock_fact(fact_key: str, user: str = Depends(get_current_user)):
    """TODO v2.35.0.1: remove an admin lock."""
    raise HTTPException(status_code=501, detail="Unlock endpoint ships in v2.35.0.1")


@router.post("/conflicts/{conflict_id}/resolve")
async def resolve_conflict(
    conflict_id: int,
    body: dict = Body(...),
    user: str = Depends(get_current_user),
):
    """TODO v2.35.0.1: keep_lock | accept_collector | edit_lock."""
    raise HTTPException(status_code=501, detail="Conflict resolution ships in v2.35.0.1")


@router.post("/permissions")
async def grant_permission(
    body: dict = Body(...),
    user: str = Depends(get_current_user),
):
    """TODO v2.35.0.1: grant fact-admin permission to a user or role."""
    raise HTTPException(status_code=501, detail="Permission grants ship in v2.35.0.1")


# --- Key detail last to avoid shadowing sub-routes above (/conflicts etc.) ---

@router.get("/key/{fact_key:path}")
async def get_fact_detail(fact_key: str, user: str = Depends(get_current_user)):
    """All rows for one fact_key, across sources. Includes history."""
    current_rows = get_fact(fact_key)
    history = get_fact_history(fact_key, limit=50)
    lock = get_lock(fact_key)
    return {
        "fact_key": fact_key,
        "sources": current_rows,
        "history": history,
        "lock": lock,
    }
