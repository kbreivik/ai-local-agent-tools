"""GET /api/external-ai/calls — list recent external AI calls for the UI.

v2.36.4. Read-only. Admin-gated (sith_lord + imperial_officer) because cost
data is sensitive.
"""
from fastapi import APIRouter, Depends, Query
from api.auth import get_current_user

router = APIRouter(prefix="/api/external-ai", tags=["external-ai"])


@router.get("/calls")
async def list_calls(limit: int = Query(50, ge=1, le=200),
                     _: str = Depends(get_current_user)):
    from api.db.external_ai_calls import list_recent_external_calls
    return {"calls": list_recent_external_calls(limit=limit)}
