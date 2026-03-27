"""JWT authentication — single admin user, bcrypt hashed."""
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt as _pyjwt  # PyJWT — already installed
from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# ── Config ────────────────────────────────────────────────────────────────────
SECRET_KEY = os.environ.get("JWT_SECRET", "hp1-jwt-secret-change-in-prod-2026")
ALGORITHM  = "HS256"
EXPIRE_HOURS = int(os.environ.get("JWT_EXPIRE_HOURS", "24"))

_ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
_ADMIN_PASS = os.environ.get("ADMIN_PASSWORD", "superduperadmin")

# Pre-hash the password at module load (or use env-provided hash)
_STORED_HASH: bytes = bcrypt.hashpw(_ADMIN_PASS.encode(), bcrypt.gensalt())

import logging as _log_module
_auth_log = _log_module.getLogger(__name__)

_INSECURE_JWT_DEFAULT = "hp1-jwt-secret-change-in-prod-2026"
_INSECURE_PASS_DEFAULT = "superduperadmin"


def check_secrets() -> None:
    """Log CRITICAL warnings when known insecure defaults are in use.

    Called from the app lifespan — never at module import time.
    Does NOT raise; homelab may intentionally use defaults on a trusted LAN.
    """
    if SECRET_KEY == _INSECURE_JWT_DEFAULT:
        _auth_log.critical(
            "SECURITY: JWT_SECRET is set to the insecure default value. "
            "Set JWT_SECRET env var to a strong random secret before exposing this service."
        )
    if _ADMIN_PASS == _INSECURE_PASS_DEFAULT:
        _auth_log.critical(
            "SECURITY: ADMIN_PASSWORD is set to the insecure default 'superduperadmin'. "
            "Set ADMIN_PASSWORD env var to a strong password before exposing this service."
        )


def verify_password(plain: str) -> bool:
    return bcrypt.checkpw(plain.encode(), _STORED_HASH)


def authenticate(username: str, password: str) -> Optional[str]:
    """Return username if credentials valid, else None."""
    if username == _ADMIN_USER and verify_password(password):
        return username
    return None


def create_token(username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=EXPIRE_HOURS)
    payload = {"sub": username, "exp": expire}
    return _pyjwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> str:
    """Return username or raise HTTPException 401."""
    try:
        payload = _pyjwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if not username:
            raise HTTPException(status_code=401, detail="Invalid token")
        return username
    except _pyjwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


# ── FastAPI dependency ────────────────────────────────────────────────────────
_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> str:
    if not creds:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return decode_token(creds.credentials)


async def optional_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> Optional[str]:
    """Return username or None (for endpoints that work with or without auth)."""
    if not creds:
        return None
    try:
        return decode_token(creds.credentials)
    except HTTPException:
        return None
