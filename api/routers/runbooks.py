"""GET/POST/PUT/DELETE /api/runbooks — manage saved runbooks.

v2.35.4: extended with triage-classifier endpoints.
- /api/runbooks/triage           — list triage runbooks (classifier metadata)
- /api/runbooks/triage/test-match — run the classifier against a task string
- /api/runbooks/{id}             — PUT to update editable fields (sith_lord only)
"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from api.auth import get_current_user, get_current_user_and_role, role_meets

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/runbooks", tags=["runbooks"])


class CreateRunbookRequest(BaseModel):
    title: str
    description: str = ""
    steps: list = []  # [{order, title, description, command, notes}]
    source: str = "manual_completion"
    proposal_id: str = ""
    tags: list = []


class UpdateTriageRunbookRequest(BaseModel):
    title: Optional[str] = None
    body_md: Optional[str] = None
    triage_keywords: Optional[list] = None
    applies_to_agent_types: Optional[list] = None
    priority: Optional[int] = None
    is_active: Optional[bool] = None
    description: Optional[str] = None
    tags: Optional[list] = None


class TestMatchRequest(BaseModel):
    task: str
    agent_type: str = "research"


def _require_sith_lord(user_and_role: tuple[str, str]) -> str:
    username, role = user_and_role
    if not role_meets(role, "sith_lord"):
        raise HTTPException(403, "sith_lord role required")
    return username


@router.get("")
def list_all(_: str = Depends(get_current_user)):
    from api.db.runbooks import list_runbooks
    return {"runbooks": list_runbooks()}


@router.post("")
def create(body: CreateRunbookRequest, user: str = Depends(get_current_user)):
    from api.db.runbooks import create_runbook
    rid = create_runbook(
        title=body.title, description=body.description, steps=body.steps,
        source=body.source, proposal_id=body.proposal_id,
        tags=body.tags, created_by=user,
    )
    if not rid:
        raise HTTPException(500, "Failed to create runbook")
    return {"status": "ok", "id": rid}


# ── Triage runbook endpoints (v2.35.4) ────────────────────────────────────────

@router.get("/triage")
def list_triage(_: str = Depends(get_current_user)):
    """Return all runbooks with triage-classifier metadata (name set)."""
    from api.db.runbooks import list_triage_runbooks
    return {"status": "ok", "runbooks": list_triage_runbooks()}


@router.post("/triage/test-match")
def test_match(body: TestMatchRequest, _: str = Depends(get_current_user)):
    """Run the classifier against an arbitrary task — returns the matched
    runbook + score + matched_keywords, or null if no match.
    """
    try:
        from api.agents.runbook_classifier import select_runbook
        from api.db.known_facts import _get_facts_settings
        settings = _get_facts_settings() or {}
    except Exception as e:
        raise HTTPException(500, f"classifier load failed: {e}")

    hit = select_runbook(body.task, body.agent_type, settings)
    if not hit:
        return {"status": "ok", "match": None}
    rb = hit["runbook"]
    return {
        "status": "ok",
        "match": {
            "runbook_id":       rb.get("id"),
            "runbook_name":     rb.get("name"),
            "title":            rb.get("title"),
            "score":            hit["score"],
            "matched_keywords": hit.get("matched_keywords") or [],
            "priority":         rb.get("priority"),
            "agent_types":      rb.get("applies_to_agent_types"),
        },
    }


@router.put("/{runbook_id}")
def update_runbook(
    runbook_id: str,
    body: UpdateTriageRunbookRequest,
    user_and_role: tuple[str, str] = Depends(get_current_user_and_role),
):
    """Update editable fields on a runbook. Requires sith_lord role."""
    username = _require_sith_lord(user_and_role)
    # Validate priority range if provided
    if body.priority is not None and not (0 <= int(body.priority) <= 999):
        raise HTTPException(400, "priority must be in [0, 999]")
    from api.db.runbooks import update_triage_runbook, get_runbook_by_id
    existing = get_runbook_by_id(runbook_id)
    if not existing:
        raise HTTPException(404, "Runbook not found")
    ok = update_triage_runbook(
        runbook_id,
        title=body.title,
        body_md=body.body_md,
        triage_keywords=body.triage_keywords,
        applies_to_agent_types=body.applies_to_agent_types,
        priority=body.priority,
        is_active=body.is_active,
        description=body.description,
        tags=body.tags,
        edited_by=username,
    )
    if not ok:
        raise HTTPException(500, "Update failed")
    updated = get_runbook_by_id(runbook_id)
    return {"status": "ok", "runbook": updated}


@router.get("/{runbook_id}")
def get_one(runbook_id: str, _: str = Depends(get_current_user)):
    from api.db.runbooks import get_runbook_by_id, list_runbooks
    rb = get_runbook_by_id(runbook_id)
    if rb:
        return rb
    # Fallback to older no-triage-column format via list
    rbs = [r for r in list_runbooks(limit=500) if r["id"] == runbook_id]
    if not rbs:
        raise HTTPException(404, "Runbook not found")
    return rbs[0]


@router.delete("/{runbook_id}")
def delete(
    runbook_id: str,
    user_and_role: tuple[str, str] = Depends(get_current_user_and_role),
):
    _require_sith_lord(user_and_role)
    from api.db.runbooks import delete_runbook
    ok = delete_runbook(runbook_id)
    if not ok:
        raise HTTPException(404, "Runbook not found or delete failed")
    return {"status": "ok"}
