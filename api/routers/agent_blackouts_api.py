"""Blackout CRUD endpoints. Role-gated to sith_lord + imperial_officer."""
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import get_current_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agent/blackouts", tags=["agent-blackouts"])

_PRIVILEGED = frozenset({"sith_lord", "imperial_officer"})


def _user_role(username: str) -> str:
    try:
        from api.users import get_user_by_username
        row = get_user_by_username(username)
        if row and row.get("role"):
            return row["role"]
    except Exception:
        pass
    import os
    if username == os.environ.get("ADMIN_USER", "admin"):
        return "sith_lord"
    return "stormtrooper"


def _gate(user: str) -> None:
    if _user_role(user) not in _PRIVILEGED:
        raise HTTPException(403, "Blackout management requires imperial_officer or sith_lord role.")


class BlackoutCreate(BaseModel):
    label:             str = Field(max_length=120)
    reason:            str = Field(default="", max_length=500)
    enabled:           bool = True
    starts_at:         str | None = None
    ends_at:           str | None = None
    recurring_cron:    str | None = None
    duration_minutes:  int | None = None
    applies_to:        list[str] = Field(default_factory=list)


@router.get("")
async def list_blackouts_api(user: str = Depends(get_current_user)):
    _gate(user)
    from api.db.agent_blackouts import list_blackouts
    return {"blackouts": list_blackouts()}


@router.post("")
async def create_blackout_api(req: BlackoutCreate, user: str = Depends(get_current_user)):
    _gate(user)
    from api.db.agent_blackouts import create_blackout
    bid = create_blackout(**req.model_dump(), created_by=user)
    if not bid:
        raise HTTPException(500, "Failed to create blackout")
    return {"id": bid, "status": "ok"}


@router.delete("/{bid}")
async def delete_blackout_api(bid: str, user: str = Depends(get_current_user)):
    _gate(user)
    from api.db.agent_blackouts import delete_blackout
    if not delete_blackout(bid):
        raise HTTPException(404, "Not found")
    return {"status": "ok"}


@router.post("/{bid}/toggle")
async def toggle_blackout_api(bid: str, enabled: bool, user: str = Depends(get_current_user)):
    _gate(user)
    from api.db.agent_blackouts import set_enabled
    if not set_enabled(bid, enabled):
        raise HTTPException(404, "Not found")
    return {"status": "ok", "enabled": enabled}


@router.get("/active")
async def active_blackout_api(tool_name: str = "", _: str = Depends(get_current_user)):
    """Return the currently-active blackout matching `tool_name`, or null."""
    from api.db.agent_blackouts import check_active_blackout
    return {"active": check_active_blackout(tool_name=tool_name)}
