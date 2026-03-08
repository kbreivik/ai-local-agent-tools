"""Auth endpoints: login, me, logout."""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from api.auth import authenticate, create_token, get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest):
    user = authenticate(req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_token(user)
    return LoginResponse(access_token=token, username=user)


@router.get("/me")
async def me(user: str = Depends(get_current_user)):
    return {"username": user, "role": "admin"}
