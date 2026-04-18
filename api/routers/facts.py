"""/api/facts — read + admin endpoints for the known_facts store.

v2.35.0   — read endpoints + admin stubs.
v2.35.0.1 — lock management, conflict resolution, permission management,
            manual refresh, audit log, all gated by the permission model
            in api/security/facts_permissions.py.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Body

from api.auth import get_current_user
from api.db.known_facts import (
    compute_confidence,
    create_lock_row,
    get_conflict,
    get_confident_facts,
    get_fact,
    get_fact_history,
    get_lock,
    get_pending_conflicts,
    get_recently_changed,
    get_stale_facts,
    get_summary_stats,
    list_all_locks,
    list_audit_log,
    list_refresh_schedule_rows,
    mark_conflict_resolved,
    refresh_manual_fact_timestamp,
    remove_lock_row,
    sample_fact_rows,
    update_lock,
    write_audit,
)
from api.security.facts_permissions import (
    dynamic_permission_check,
    grant_permission,
    list_permissions,
    require_role,
    revoke_permission,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/facts", tags=["facts"])


def _bump_lock_metric(action: str) -> None:
    try:
        from api.metrics import FACTS_LOCK_EVENTS_COUNTER
        FACTS_LOCK_EVENTS_COUNTER.labels(action=action).inc()
    except Exception:
        pass


# ── Read endpoints ───────────────────────────────────────────────────────────

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


# ── Lock management (v2.35.0.1) ──────────────────────────────────────────────

@router.get("/locks")
async def list_locks(user: str = Depends(get_current_user)):
    """Read-only to any authenticated user."""
    return {"locks": list_all_locks()}


@router.post("/locks")
async def create_lock(
    body: dict = Body(...),
    user: str = Depends(get_current_user),
):
    """Body: {fact_key, locked_value, note}. Permission-gated on fact_key."""
    fact_key = (body or {}).get("fact_key") or ""
    if not fact_key:
        raise HTTPException(400, "fact_key required")
    dynamic_permission_check(user, "lock", fact_key)
    lock = create_lock_row(
        fact_key=fact_key,
        locked_value=body.get("locked_value"),
        note=body.get("note", ""),
        locked_by=user,
    )
    write_audit("lock_created", fact_key=fact_key, actor=user, detail=body)
    _bump_lock_metric("created")
    return {"ok": True, "lock": lock}


@router.delete("/locks/{fact_key:path}")
async def remove_lock(fact_key: str, user: str = Depends(get_current_user)):
    dynamic_permission_check(user, "unlock", fact_key)
    remove_lock_row(fact_key)
    write_audit("lock_removed", fact_key=fact_key, actor=user)
    _bump_lock_metric("removed")
    return {"ok": True}


# Legacy single-key endpoints kept for backwards-compat with earlier skills.

@router.post("/lock/{fact_key:path}")
async def lock_fact_legacy(
    fact_key: str,
    body: dict | None = Body(None),
    user: str = Depends(get_current_user),
):
    dynamic_permission_check(user, "lock", fact_key)
    locked_value = (body or {}).get("locked_value")
    note = (body or {}).get("note", "")
    lock = create_lock_row(fact_key, locked_value, note, user)
    write_audit("lock_created", fact_key=fact_key, actor=user, detail=body or {})
    _bump_lock_metric("created")
    return {"ok": True, "lock": lock}


@router.delete("/lock/{fact_key:path}")
async def unlock_fact_legacy(fact_key: str, user: str = Depends(get_current_user)):
    dynamic_permission_check(user, "unlock", fact_key)
    remove_lock_row(fact_key)
    write_audit("lock_removed", fact_key=fact_key, actor=user)
    _bump_lock_metric("removed")
    return {"ok": True}


# ── Conflict resolution ──────────────────────────────────────────────────────

@router.post("/conflicts/{conflict_id}/resolve")
async def resolve_conflict_endpoint(
    conflict_id: int,
    body: dict = Body(...),
    user: str = Depends(get_current_user),
):
    """body: {resolution: 'keep_lock'|'accept_collector'|'edit_lock', new_value?}"""
    conflict = get_conflict(conflict_id)
    if not conflict:
        raise HTTPException(404, "Conflict not found")
    fact_key = conflict.get("fact_key", "")
    dynamic_permission_check(user, "unlock", fact_key)

    resolution = (body or {}).get("resolution")
    if resolution == "keep_lock":
        mark_conflict_resolved(conflict_id, user, "keep_lock")
    elif resolution == "accept_collector":
        update_lock(fact_key, conflict.get("offered_value"), user)
        mark_conflict_resolved(conflict_id, user, "accept_collector")
    elif resolution == "edit_lock":
        if "new_value" not in (body or {}):
            raise HTTPException(400, "edit_lock requires new_value")
        update_lock(fact_key, body["new_value"], user)
        mark_conflict_resolved(
            conflict_id, user, "edit_lock", {"new_value": body["new_value"]}
        )
    else:
        raise HTTPException(400, f"Unknown resolution: {resolution}")

    write_audit(
        "conflict_resolved", fact_key=fact_key, actor=user,
        detail={"resolution": resolution},
    )
    return {"ok": True}


# ── Permission management (sith_lord-only writes) ────────────────────────────

@router.get("/permissions")
async def list_perms_endpoint(user: str = Depends(get_current_user)):
    return {"permissions": list_permissions()}


@router.post("/permissions")
async def grant_perm_endpoint(
    body: dict = Body(...),
    user: str = Depends(require_role("sith_lord")),
):
    for required in ("grantee_type", "grantee_id", "action", "fact_pattern"):
        if not body.get(required):
            raise HTTPException(400, f"{required} required")
    pid = grant_permission(
        grantee_type=body["grantee_type"],
        grantee_id=body["grantee_id"],
        action=body["action"],
        fact_pattern=body["fact_pattern"],
        granted_by=user,
        expires_at=body.get("expires_at"),
    )
    write_audit("permission_granted", fact_key=None, actor=user, detail=body)
    return {"ok": True, "permission_id": pid}


@router.delete("/permissions/{permission_id}")
async def revoke_perm_endpoint(
    permission_id: int,
    user: str = Depends(require_role("sith_lord")),
):
    revoke_permission(permission_id, revoked_by=user)
    write_audit(
        "permission_revoked", fact_key=None, actor=user,
        detail={"permission_id": permission_id},
    )
    return {"ok": True}


# ── Manual fact refresh ──────────────────────────────────────────────────────

@router.post("/key/{fact_key:path}/refresh")
async def refresh_manual_fact(
    fact_key: str,
    user: str = Depends(get_current_user),
):
    dynamic_permission_check(user, "manual_write", fact_key)
    refresh_manual_fact_timestamp(fact_key, actor=user)
    write_audit("manual_refresh", fact_key=fact_key, actor=user)
    return {"ok": True}


# ── Audit log ────────────────────────────────────────────────────────────────

@router.get("/audit")
async def list_audit(
    limit: int = Query(100, ge=1, le=500),
    user: str = Depends(get_current_user),
):
    return {"entries": list_audit_log(limit=limit)}


# ── Key detail last to avoid shadowing /conflicts, /locks, etc. ──────────────

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
