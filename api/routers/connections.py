"""CRUD endpoints for infrastructure connections."""
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import get_current_user

router = APIRouter(prefix="/api/connections", tags=["connections"])
log = logging.getLogger(__name__)


class CreateConnectionRequest(BaseModel):
    platform: str
    label: str
    host: str
    port: int = 443
    auth_type: str = "token"
    credentials: dict = Field(default_factory=dict)
    config: dict = Field(default_factory=dict)
    enabled: bool = True


class UpdateConnectionRequest(BaseModel):
    label: str | None = None
    host: str | None = None
    port: int | None = None
    auth_type: str | None = None
    credentials: dict | None = None
    config: dict | None = None
    enabled: bool | None = None


@router.get("")
def list_all(platform: str = "", _: str = Depends(get_current_user)):
    """List all connections (credentials masked)."""
    from api.connections import list_connections
    return {"status": "ok", "data": list_connections(platform)}


@router.get("/{connection_id}")
def get_one(connection_id: str, _: str = Depends(get_current_user)):
    """Get connection detail (credentials masked in response)."""
    from api.connections import get_connection
    conn = get_connection(connection_id)
    if not conn:
        raise HTTPException(404, "Connection not found")
    # Mask credentials in API response
    if conn.get("credentials"):
        conn["credentials"] = "***"
    return {"status": "ok", "data": conn}


@router.post("")
def create(req: CreateConnectionRequest, _: str = Depends(get_current_user)):
    """Create a new platform connection."""
    from api.connections import create_connection
    result = create_connection(
        platform=req.platform, label=req.label, host=req.host,
        port=req.port, auth_type=req.auth_type,
        credentials=req.credentials, config=req.config, enabled=req.enabled,
    )
    if result["status"] != "ok":
        raise HTTPException(400, result["message"])
    return result


@router.put("/{connection_id}")
def update(connection_id: str, req: UpdateConnectionRequest, _: str = Depends(get_current_user)):
    """Partial update of a connection."""
    from api.connections import update_connection
    kwargs = {k: v for k, v in req.model_dump().items() if v is not None}
    result = update_connection(connection_id, **kwargs)
    if result["status"] != "ok":
        raise HTTPException(400, result["message"])
    return result


@router.delete("/{connection_id}")
def delete(connection_id: str, _: str = Depends(get_current_user)):
    """Delete a connection."""
    from api.connections import delete_connection
    result = delete_connection(connection_id)
    if result["status"] != "ok":
        raise HTTPException(404, result["message"])
    return result


@router.post("/{connection_id}/test")
def test(connection_id: str, _: str = Depends(get_current_user)):
    """Test connectivity for a connection."""
    from api.connections import test_connection
    return test_connection(connection_id)
