"""Read-only API for the agent_actions audit log.

Only sith_lord and imperial_officer roles can read the audit trail.
Stormtroopers and droids get 403.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth import get_current_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/agent/actions", tags=["agent-actions"])

_PRIVILEGED_ROLES = frozenset({"sith_lord", "imperial_officer"})


def _user_role(username: str) -> str:
    """Resolve the role for a username. Falls back to 'stormtrooper' if unknown.

    sith_lord for the env-var admin (matches api/auth.authenticate), otherwise
    look up the role from the users table.
    """
    try:
        from api.users import get_user_by_username
        row = get_user_by_username(username)
        if row and row.get("role"):
            return row["role"]
    except Exception:
        pass
    # env-var admin fallback — see api/auth.authenticate()
    import os
    if username == os.environ.get("ADMIN_USER", "admin"):
        return "sith_lord"
    return "stormtrooper"


@router.get("")
async def list_agent_actions(
    session_id: str = Query("", max_length=128),
    tool_name:  str = Query("", max_length=128),
    user_filter: str = Query("", alias="user", max_length=128),
    since:      str = Query("", max_length=64, description="ISO timestamp lower bound"),
    limit:      int = Query(100, ge=1, le=500),
    user: str = Depends(get_current_user),
):
    """Return audit rows. Authorised roles only."""
    role = _user_role(user)
    if role not in _PRIVILEGED_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Audit log access requires imperial_officer or sith_lord role.",
        )
    from api.db.agent_actions import list_actions
    rows = list_actions(
        session_id=session_id,
        tool_name=tool_name,
        owner_user=user_filter,
        since_iso=since,
        limit=limit,
    )
    return {"count": len(rows), "actions": rows}
