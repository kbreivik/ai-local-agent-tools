"""Auth endpoints: login, me, logout."""
import time
from typing import Optional
from collections import defaultdict
from fastapi import APIRouter, HTTPException, Depends, Request, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from api.auth import authenticate, create_token, get_current_user, get_user_role

_login_attempts: dict[str, list[float]] = defaultdict(list)
_RATE_LIMIT = 5
_RATE_WINDOW = 60.0

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest, request: Request, response: Response):
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    _login_attempts[ip] = [t for t in _login_attempts[ip] if now - t < _RATE_WINDOW]
    if len(_login_attempts[ip]) >= _RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again later.")
    _login_attempts[ip].append(now)
    user = authenticate(req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_token(user["username"], role=user["role"])

    # Set httpOnly cookie — JS cannot read this
    response.set_cookie(
        key="hp1_auth",
        value=token,
        httponly=True,
        samesite="strict",
        secure=False,        # set True when behind HTTPS
        max_age=86400 * 7,   # 7 days
        path="/",
    )
    return LoginResponse(access_token=token, username=user["username"])


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(key="hp1_auth", path="/")
    return {"status": "ok"}


@router.get("/me")
async def me(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False)),
    user: str = Depends(get_current_user),
):
    role = get_user_role(creds.credentials) if creds else "stormtrooper"
    return {"username": user, "role": role}
