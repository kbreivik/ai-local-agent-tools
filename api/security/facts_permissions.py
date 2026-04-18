"""Facts permission model — v2.35.0.1.

Grantee types:
  user  — exact username match
  role  — exact role name match

Actions: 'lock', 'unlock', 'manual_write', 'grant', 'config_refresh_schedule',
         'config_source_weights'.

Fact patterns use glob-style '*' wildcards (translated to SQL LIKE '%').

Rules:
  1. sith_lord role always returns True.
  2. Grants matching (user=username) OR (role=user_role) are considered.
  3. Expired or revoked grants do not confer permission.
  4. An explicit user-level grant with revoked=TRUE overrides any
     role-level allow (explicit revoke wins over implicit role grant).
  5. A grant's fact_pattern must cover the requested fact_pattern — i.e.
     LIKE(requested, grant_pattern).
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import Depends, HTTPException

from api.auth import get_current_user

log = logging.getLogger(__name__)


def _is_pg() -> bool:
    return "postgres" in os.environ.get("DATABASE_URL", "")


def _get_conn():
    if not _is_pg():
        return None
    try:
        from api.connections import _get_conn
        return _get_conn()
    except Exception:
        return None


def _resolve_role(username: str) -> str:
    """Look up role from users table. Returns 'droid' if unknown."""
    try:
        from api.users import get_user_by_username
        u = get_user_by_username(username)
        if u and u.get("role"):
            return u["role"]
    except Exception:
        pass
    admin_user = os.environ.get("ADMIN_USER", "admin")
    if username == admin_user:
        return "sith_lord"
    return "droid"


def user_has_permission(
    username: str,
    user_role: str,
    action: str,
    fact_pattern: str,
) -> bool:
    """Return True if user may perform `action` on facts matching pattern."""
    if user_role == "sith_lord":
        return True
    if not username or not action or not fact_pattern:
        return False

    conn = _get_conn()
    if conn is None:
        return False
    try:
        cur = conn.cursor()
        # Explicit user-level revoke wins
        cur.execute(
            "SELECT COUNT(*) FROM known_facts_permissions "
            "WHERE grantee_type='user' AND grantee_id=%s "
            "  AND action=%s AND revoked=TRUE "
            "  AND %s LIKE REPLACE(fact_pattern, '*', '%%')",
            (username, action, fact_pattern),
        )
        if int(cur.fetchone()[0]) > 0:
            cur.close(); conn.close()
            return False

        cur.execute(
            "SELECT COUNT(*) FROM known_facts_permissions "
            "WHERE ((grantee_type='user' AND grantee_id=%s) "
            "    OR (grantee_type='role' AND grantee_id=%s)) "
            "  AND action=%s AND revoked=FALSE "
            "  AND (expires_at IS NULL OR expires_at > NOW()) "
            "  AND %s LIKE REPLACE(fact_pattern, '*', '%%')",
            (username, user_role, action, fact_pattern),
        )
        count = int(cur.fetchone()[0])
        cur.close(); conn.close()
        return count > 0
    except Exception as e:
        log.debug("user_has_permission failed: %s", e)
        try:
            conn.close()
        except Exception:
            pass
        return False


def require_permission(action: str, fact_pattern: str):
    """FastAPI dependency factory. Raises 403 if no permission.

    Pass fact_pattern='<dynamic>' if the checked key comes from the
    request body — then use `dynamic_permission_check()` inside the
    endpoint handler once the key is known.
    """
    async def _check(user: str = Depends(get_current_user)) -> str:
        if fact_pattern == "<dynamic>":
            return user
        role = _resolve_role(user)
        if not user_has_permission(user, role, action, fact_pattern):
            raise HTTPException(
                status_code=403,
                detail=f"Permission denied: {action} on {fact_pattern}",
            )
        return user
    return _check


def dynamic_permission_check(username: str, action: str, fact_key: str) -> None:
    """In-handler check once the fact_key is known. Raises 403 on denial."""
    role = _resolve_role(username)
    if not user_has_permission(username, role, action, fact_key):
        raise HTTPException(
            status_code=403,
            detail=f"Permission denied: {action} on {fact_key}",
        )


def require_role(minimum_role: str):
    """FastAPI dependency factory — require a minimum role."""
    from api.auth import role_meets

    async def _check(user: str = Depends(get_current_user)) -> str:
        role = _resolve_role(user)
        if not role_meets(role, minimum_role):
            raise HTTPException(
                status_code=403,
                detail=f"Requires role >= {minimum_role} (have {role})",
            )
        return user
    return _check


def grant_permission(
    grantee_type: str,
    grantee_id: str,
    action: str,
    fact_pattern: str,
    granted_by: str,
    expires_at: Optional[str] = None,
) -> int:
    """Insert a permission row. Returns new id (or 0 on failure)."""
    if grantee_type not in ("user", "role"):
        raise HTTPException(400, f"grantee_type must be 'user' or 'role'")
    conn = _get_conn()
    if conn is None:
        return 0
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO known_facts_permissions "
            "(grantee_type, grantee_id, action, fact_pattern, granted_by, expires_at) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (grantee_type, grantee_id, action, fact_pattern, granted_by, expires_at),
        )
        row = cur.fetchone()
        conn.commit()
        cur.close(); conn.close()
        return int(row[0]) if row else 0
    except Exception as e:
        log.warning("grant_permission failed: %s", e)
        try:
            conn.close()
        except Exception:
            pass
        return 0


def revoke_permission(permission_id: int, revoked_by: str) -> None:
    """Mark a grant revoked."""
    conn = _get_conn()
    if conn is None:
        return
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE known_facts_permissions SET revoked=TRUE WHERE id=%s",
            (permission_id,),
        )
        conn.commit()
        cur.close(); conn.close()
    except Exception as e:
        log.warning("revoke_permission failed: %s", e)
        try:
            conn.close()
        except Exception:
            pass


def list_permissions(
    grantee_type: Optional[str] = None,
    grantee_id: Optional[str] = None,
) -> list[dict]:
    """List permissions, optionally filtered."""
    conn = _get_conn()
    if conn is None:
        return []
    try:
        cur = conn.cursor()
        if grantee_type and grantee_id:
            cur.execute(
                "SELECT id, grantee_type, grantee_id, action, fact_pattern, "
                "granted_at, granted_by, expires_at, revoked "
                "FROM known_facts_permissions "
                "WHERE grantee_type=%s AND grantee_id=%s "
                "ORDER BY granted_at DESC",
                (grantee_type, grantee_id),
            )
        else:
            cur.execute(
                "SELECT id, grantee_type, grantee_id, action, fact_pattern, "
                "granted_at, granted_by, expires_at, revoked "
                "FROM known_facts_permissions "
                "ORDER BY granted_at DESC LIMIT 500"
            )
        cols = [d[0] for d in cur.description]
        out = []
        for r in cur.fetchall():
            d = dict(zip(cols, r))
            for k, v in list(d.items()):
                if hasattr(v, "isoformat"):
                    d[k] = v.isoformat()
            out.append(d)
        cur.close(); conn.close()
        return out
    except Exception as e:
        log.debug("list_permissions failed: %s", e)
        try:
            conn.close()
        except Exception:
            pass
        return []
