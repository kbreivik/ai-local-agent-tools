"""Maintenance mode API endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from api.auth import get_current_user
from api.db.entity_maintenance import (
    set_maintenance, clear_maintenance, list_maintenance
)

router = APIRouter(prefix="/api/maintenance", tags=["maintenance"])


class MaintenanceRequest(BaseModel):
    reason: str = ""
    expires_at: Optional[str] = None


@router.get("")
async def get_all_maintenance(_: str = Depends(get_current_user)):
    """List all entities currently in maintenance."""
    return {"maintenance": list_maintenance()}


@router.post("/{entity_id:path}")
async def set_entity_maintenance(
    entity_id: str,
    body: MaintenanceRequest,
    user: str = Depends(get_current_user),
):
    """Set an entity in maintenance mode."""
    from datetime import datetime
    expires = None
    if body.expires_at:
        try:
            expires = datetime.fromisoformat(body.expires_at.replace("Z", "+00:00"))
        except Exception:
            raise HTTPException(400, "Invalid expires_at format — use ISO 8601")
    result = set_maintenance(entity_id, reason=body.reason, set_by=user, expires_at=expires)
    if not result.get("ok"):
        raise HTTPException(500, result.get("error", "Failed"))
    return result


@router.delete("/{entity_id:path}")
async def clear_entity_maintenance(
    entity_id: str,
    _: str = Depends(get_current_user),
):
    """Remove an entity from maintenance mode."""
    result = clear_maintenance(entity_id)
    if not result.get("ok"):
        raise HTTPException(500, result.get("error", "Failed"))
    return result
