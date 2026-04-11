"""JWT authentication — single admin user, bcrypt hashed."""
import logging as _log_module
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt as _pyjwt  # PyJWT — already installed
from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

_auth_log = _log_module.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
_INSECURE_JWT_DEFAULT = "hp1-jwt-secret-change-in-prod-2026"
_INSECURE_PASS_DEFAULT = "superduperadmin"

_raw_jwt = os.environ.get("JWT_SECRET", "")
if not _raw_jwt or _raw_jwt == _INSECURE_JWT_DEFAULT:
    import hashlib
    import socket
    _hostname = socket.gethostname()
    SECRET_KEY = hashlib.sha256(f"hp1-agent-{_hostname}".encode()).hexdigest()
    _auth_log.warning(
        "JWT_SECRET not set — using hostname-derived fallback. "
        "Sessions survive restart but are not cryptographically random. "
        "Set JWT_SECRET env var for production security."
    )
else:
    SECRET_KEY = _raw_jwt

ALGORITHM  = "HS256"
EXPIRE_HOURS = int(os.environ.get("JWT_EXPIRE_HOURS", "24"))

_ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
_ADMIN_PASS = os.environ.get("ADMIN_PASSWORD", "superduperadmin")

# Pre-hash the password at module load (or use env-provided hash)
_STORED_HASH: bytes = bcrypt.hashpw(_ADMIN_PASS.encode(), bcrypt.gensalt())


def check_secrets() -> None:
    """Log CRITICAL warnings when known insecure defaults are in use.

    Called from the app lifespan — never at module import time.
    Does NOT raise; homelab may intentionally use defaults on a trusted LAN.
    """
    if _ADMIN_PASS == _INSECURE_PASS_DEFAULT:
        _auth_log.critical(
            "SECURITY: ADMIN_PASSWORD is set to the insecure default 'superduperadmin'. "
            "Set ADMIN_PASSWORD env var to a strong password before exposing this service."
        )


def verify_password(plain: str) -> bool:
    return bcrypt.checkpw(plain.encode(), _STORED_HASH)


def authenticate(username: str, password: str) -> Optional[str]:
    """Return username if credentials valid, else None.

    Checks users table first (multi-user), falls back to env var admin.
    """
    # Try users table first
    try:
        from api.users import authenticate_user
        user = authenticate_user(username, password)
        if user:
            return user["username"]
    except Exception:
        pass
    # Fallback: env var admin
    if username == _ADMIN_USER and verify_password(password):
        return username
    return None


def create_token(username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=EXPIRE_HOURS)
    payload = {"sub": username, "exp": expire}
    return _pyjwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def create_internal_token(expires_minutes: int = 5) -> str:
    """Create a short-lived internal JWT for skill → API calls.
    Uses the same secret as user JWTs. Skills should call this fresh each time."""
    try:
        payload = {
            "sub": "internal_skill",
            "role": "sith_lord",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=expires_minutes),
            "iat": datetime.now(timezone.utc),
        }
        return _pyjwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    except Exception:
        return ""


def decode_token(token: str) -> str:
    """Return username or raise HTTPException 401.

    Tries JWT first, then API token hash lookup.
    """
    # Try JWT
    try:
        payload = _pyjwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username:
            return username
    except _pyjwt.PyJWTError:
        pass
    # Try API token
    try:
        from api.users import authenticate_token
        result = authenticate_token(token)
        if result:
            return result["username"]
    except Exception:
        pass
    raise HTTPException(status_code=401, detail="Invalid or expired token")


# ── FastAPI dependency ────────────────────────────────────────────────────────
_bearer = HTTPBearer(auto_error=False)


_ROLE_RANK = {"sith_lord": 4, "imperial_officer": 3, "stormtrooper": 2, "droid": 1}


def get_user_role(token: str) -> str:
    """Extract role from JWT. Returns 'stormtrooper' on failure."""
    try:
        payload = _pyjwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        role = payload.get("role", "")
        if role:
            return role
        sub = payload.get("sub", "")
        if sub and sub != "internal_skill":
            try:
                from api.users import get_user_by_username
                user = get_user_by_username(sub)
                if user:
                    return user.get("role", "stormtrooper")
            except Exception:
                pass
        return "stormtrooper"
    except Exception:
        return "droid"


def role_meets(role: str, minimum: str) -> bool:
    """Return True if role >= minimum in the hierarchy."""
    return _ROLE_RANK.get(role, 0) >= _ROLE_RANK.get(minimum, 99)


async def get_current_user_and_role(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> tuple[str, str]:
    """FastAPI dependency — returns (username, role). Raises 401 if not authenticated."""
    if not creds:
        raise HTTPException(status_code=401, detail="Not authenticated")
    username = decode_token(creds.credentials)
    role = get_user_role(creds.credentials)
    return username, role


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
