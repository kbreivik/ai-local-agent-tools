"""User + API token CRUD endpoints."""
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from api.auth import get_current_user

router = APIRouter(prefix="/api", tags=["users"])
log = logging.getLogger(__name__)


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "stormtrooper"

class UpdateUserRequest(BaseModel):
    role: str | None = None
    enabled: bool | None = None
    password: str | None = None

class CreateTokenRequest(BaseModel):
    name: str
    role: str = "droid"
    expires_at: str | None = None


# ── Users ────────────────────────────────────────────────────────────────────

@router.get("/users")
def get_users(_: str = Depends(get_current_user)):
    from api.users import list_users
    return {"status": "ok", "data": list_users()}


@router.get("/users/me")
def get_me(user: str = Depends(get_current_user)):
    return {"status": "ok", "data": {"username": user}}


@router.post("/users")
def create(req: CreateUserRequest, _: str = Depends(get_current_user)):
    from api.users import create_user
    result = create_user(req.username, req.password, req.role)
    if result["status"] != "ok":
        raise HTTPException(400, result["message"])
    return result


@router.put("/users/{user_id}")
def update(user_id: str, req: UpdateUserRequest, _: str = Depends(get_current_user)):
    from api.users import update_user
    result = update_user(user_id, role=req.role, enabled=req.enabled, password=req.password)
    if result["status"] != "ok":
        raise HTTPException(400, result["message"])
    return result


@router.delete("/users/{user_id}")
def delete(user_id: str, user: str = Depends(get_current_user)):
    from api.users import list_users, delete_user
    # Prevent deleting own account
    users = list_users()
    target = next((u for u in users if u["id"] == user_id), None)
    if target and target["username"] == user:
        raise HTTPException(400, "Cannot delete your own account")
    result = delete_user(user_id)
    if result["status"] != "ok":
        raise HTTPException(404, result["message"])
    return result


# ── API Tokens ───────────────────────────────────────────────────────────────

@router.get("/tokens")
def get_tokens(_: str = Depends(get_current_user)):
    from api.users import list_api_tokens
    return {"status": "ok", "data": list_api_tokens()}


@router.post("/tokens")
def create_token(req: CreateTokenRequest, user: str = Depends(get_current_user)):
    from api.users import create_api_token, list_users
    # Find user_id for the current user
    users = list_users()
    current = next((u for u in users if u["username"] == user), None)
    user_id = current["id"] if current else None
    result = create_api_token(req.name, req.role, user_id, req.expires_at)
    if result["status"] != "ok":
        raise HTTPException(400, result["message"])
    return result


@router.delete("/tokens/{token_id}")
def revoke(token_id: str, _: str = Depends(get_current_user)):
    from api.users import revoke_api_token
    result = revoke_api_token(token_id)
    if result["status"] != "ok":
        raise HTTPException(404, result["message"])
    return result
