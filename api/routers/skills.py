"""GET /api/skills — skill registry endpoints for the GUI Skills tab."""
import json
from fastapi import APIRouter, HTTPException, Query, Depends, Request
from pydantic import BaseModel
from api.tool_registry import invoke_tool
from api.auth import get_current_user


_PRIVILEGED = frozenset({"sith_lord", "imperial_officer"})


def _resolve_role(username: str) -> str:
    """Resolve the role for a username; matches api.routers.agent_actions_api."""
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


def require_role(*roles):
    """Dependency factory: require caller to have one of the given roles."""
    allowed = frozenset(roles)

    def _dep(username: str = Depends(get_current_user)) -> dict:
        role = _resolve_role(username)
        if role not in allowed:
            raise HTTPException(403, f"requires one of: {sorted(allowed)}")
        return {"username": username, "role": role}

    return _dep
from mcp_server.tools.skills.promoter import (
    promote_skill as _promote_skill,
    demote_skill as _demote_skill,
    scrap_skill as _scrap_skill,
    restore_skill as _restore_skill,
    purge_skill as _purge_skill,
)
from mcp_server.tools.skills.meta_tools import skill_regenerate as _skill_regenerate
from mcp_server.tools.skills.storage import get_backend

router = APIRouter(prefix="/api/skills", tags=["skills"])


@router.get("")
def list_skills(
    category: str = Query("", description="Filter by category"),
    include_disabled: bool = Query(False),
    _: str = Depends(get_current_user),
):
    """Return all registered skills, optionally filtered by category."""
    try:
        result = invoke_tool("skill_list", {
            "category": category,
            "enabled_only": not include_disabled,
        })
        skills = result.get("data", {}).get("skills", [])
        return {"skills": skills, "count": len(skills)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/{skill_name}/execute")
def execute_skill(skill_name: str, params: dict = {}, _: str = Depends(get_current_user)):
    """Execute a skill by name. Params are passed as keyword arguments."""
    try:
        check = invoke_tool("skill_info", {"name": skill_name})
        if check.get("status") != "ok":
            raise HTTPException(404, f"Skill '{skill_name}' not found")

        params_json = json.dumps(params) if params else "{}"
        result = invoke_tool("skill_execute", {"name": skill_name, "params_json": params_json})
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/generation-log")
def list_generation_log(
    skill_name: str = Query("", description="Filter by skill name"),
    outcome: str = Query("", description="Filter by outcome: success | error | export"),
    limit: int = Query(50, ge=1, le=200, description="Max rows to return"),
    _: str = Depends(get_current_user),
):
    """Return skill generation trace log, newest first."""
    try:
        rows = get_backend().get_generation_log(skill_name=skill_name, outcome=outcome, limit=limit)
        return {"log": rows, "count": len(rows)}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/{skill_name}/generation-log")
def get_skill_generation_log(
    skill_name: str,
    _: str = Depends(get_current_user),
):
    """Return generation trace log for a specific skill, newest first."""
    try:
        rows = get_backend().get_generation_log(skill_name=skill_name, limit=50)
        return {"log": rows, "count": len(rows)}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/{skill_name}")
def get_skill(skill_name: str, _: str = Depends(get_current_user)):
    """Return metadata for a single skill."""
    try:
        result = invoke_tool("skill_info", {"name": skill_name})
        if result.get("status") != "ok":
            raise HTTPException(404, f"Skill '{skill_name}' not found")
        return result.get("data", {})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Lifecycle endpoints ────────────────────────────────────────────────────────


class PromoteRequest(BaseModel):
    domain: str  # kafka | swarm | proxmox | general


@router.post("/{skill_name}/promote")
def promote_skill(skill_name: str, body: PromoteRequest, _: str = Depends(get_current_user)):
    """Promote a skill to @mcp.tool() and assign it to an agent domain."""
    result = _promote_skill(skill_name, body.domain)
    if result["status"] == "error":
        msg = result.get("message", "")
        code = 400 if "not found" not in msg.lower() else 404
        raise HTTPException(code, msg)
    return result


@router.post("/{skill_name}/demote")
def demote_skill(skill_name: str, _: str = Depends(get_current_user)):
    """Remove a skill from the promoted state."""
    result = _demote_skill(skill_name)
    if result["status"] == "error":
        msg = result.get("message", "")
        code = 400 if "not found" not in msg.lower() else 404
        raise HTTPException(code, msg)
    return result


@router.delete("/{skill_name}")
def scrap_skill(skill_name: str, _: str = Depends(get_current_user)):
    """Scrap a skill — disable it and move file to holding area."""
    result = _scrap_skill(skill_name)
    if result["status"] == "error":
        msg = result.get("message", "")
        if "not found" in msg.lower():
            code = 404
        else:
            code = 400
        raise HTTPException(code, msg)
    return result


@router.post("/{skill_name}/regenerate")
def regenerate_skill(skill_name: str, _: str = Depends(get_current_user)):
    """Regenerate a skill from its description using the LLM, backing up the old version."""
    result = _skill_regenerate(None, skill_name)
    if result["status"] == "error":
        msg = result.get("message", "")
        raise HTTPException(404 if "not found" in msg.lower() else 400, msg)
    return result


@router.delete("/{skill_name}/purge")
def purge_skill(skill_name: str, _: str = Depends(get_current_user)):
    """Permanently delete a skill from the registry, bypassing starter-skill protection."""
    result = _purge_skill(skill_name)
    if result["status"] == "error":
        msg = result.get("message", "")
        raise HTTPException(404 if "not found" in msg.lower() else 400, msg)
    return result


@router.post("/{skill_name}/restore")
def restore_skill(skill_name: str, _: str = Depends(get_current_user)):
    """Restore a scrapped skill."""
    result = _restore_skill(skill_name)
    if result["status"] == "error":
        msg = result.get("message", "")
        if "not found" in msg.lower():
            code = 404
        elif "not scrapped" in msg.lower():
            code = 400
        else:
            code = 400
        raise HTTPException(code, msg)
    return result


# ── Auto-promoter: skill candidate endpoints (v2.33.4) ────────────────────────

from api.db.skill_candidates import list_candidates
from api.skills.auto_promoter import detect_candidates


@router.get("/candidates")
async def get_candidates(request: Request):
    return await list_candidates(request.app.state.pool)


@router.post("/candidates/{cid}/approve")
async def approve_candidate(cid: int, request: Request, user=Depends(require_role("sith_lord", "imperial_officer"))):
    pool = request.app.state.pool
    async with pool.acquire() as c:
        row = await c.fetchrow("SELECT * FROM skill_candidates WHERE id=$1", cid)
        if not row:
            raise HTTPException(404)
        # call existing skill_create to materialize
        from api.skills.generator import skill_create  # v2.13.0 entry
        new_skill_id = await skill_create(
            name=row["suggested_name"],
            description=row["suggested_description"],
            seed_tool=row["tool"],
            seed_args=row["sample_args"],
        )
        await c.execute("""
            UPDATE skill_candidates SET status='promoted', decided_at=NOW(),
              decided_by=$2, promoted_skill_id=$3 WHERE id=$1
        """, cid, user["username"], new_skill_id)
    return {"ok": True, "skill_id": new_skill_id}


@router.post("/candidates/{cid}/reject")
async def reject_candidate(cid: int, request: Request, user=Depends(require_role("sith_lord", "imperial_officer"))):
    async with request.app.state.pool.acquire() as c:
        await c.execute("""
            UPDATE skill_candidates SET status='rejected', decided_at=NOW(),
              decided_by=$2 WHERE id=$1
        """, cid, user["username"])
    return {"ok": True}


@router.post("/candidates/scan-now")
async def scan_now(request: Request, user=Depends(require_role("sith_lord"))):
    n = await detect_candidates(request.app.state.pool)
    return {"candidates_detected_or_updated": n}
