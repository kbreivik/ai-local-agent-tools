"""GET/POST/DELETE /api/runbooks — manage saved runbooks."""
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from api.auth import get_current_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/runbooks", tags=["runbooks"])


class CreateRunbookRequest(BaseModel):
    title: str
    description: str = ""
    steps: list       # [{order, title, description, command, notes}]
    source: str = "manual_completion"
    proposal_id: str = ""
    tags: list = []


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


@router.get("/{runbook_id}")
def get_one(runbook_id: str, _: str = Depends(get_current_user)):
    from api.db.runbooks import list_runbooks
    rbs = [r for r in list_runbooks(limit=500) if r["id"] == runbook_id]
    if not rbs:
        raise HTTPException(404, "Runbook not found")
    return rbs[0]


@router.delete("/{runbook_id}")
def delete(runbook_id: str, _: str = Depends(get_current_user)):
    from api.db.runbooks import delete_runbook
    ok = delete_runbook(runbook_id)
    if not ok:
        raise HTTPException(404, "Runbook not found or delete failed")
    return {"status": "ok"}
