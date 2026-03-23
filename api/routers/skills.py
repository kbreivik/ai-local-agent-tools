"""GET /api/skills — skill registry endpoints for the GUI Skills tab."""
import json
from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel
from api.tool_registry import invoke_tool
from api.auth import get_current_user

router = APIRouter(prefix="/api/skills", tags=["skills"])


@router.get("")
def list_skills(
    category: str = Query("", description="Filter by category"),
    include_disabled: bool = Query(False),
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
def execute_skill(skill_name: str, params: dict = {}):
    """Execute a skill by name. Params are passed as keyword arguments."""
    try:
        check = invoke_tool("skill_info", {"name": skill_name})
        if check.get("status") != "ok":
            raise HTTPException(404, f"Skill '{skill_name}' not found")

        kwargs_json = json.dumps(params) if params else ""
        result = invoke_tool("skill_execute", {"name": skill_name, "kwargs_json": kwargs_json})
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/{skill_name}")
def get_skill(skill_name: str):
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
    from mcp_server.tools.skills.promoter import promote_skill as _promote
    result = _promote(skill_name, body.domain)
    if result["status"] == "error":
        msg = result.get("message", "")
        code = 400 if "not found" not in msg.lower() else 404
        raise HTTPException(code, msg)
    return result


@router.post("/{skill_name}/demote")
def demote_skill(skill_name: str, _: str = Depends(get_current_user)):
    """Remove a skill from the promoted state."""
    from mcp_server.tools.skills.promoter import demote_skill as _demote
    result = _demote(skill_name)
    if result["status"] == "error":
        raise HTTPException(404, result.get("message", "Not found"))
    return result


@router.delete("/{skill_name}")
def scrap_skill(skill_name: str, _: str = Depends(get_current_user)):
    """Scrap a skill — disable it and move file to holding area."""
    from mcp_server.tools.skills.promoter import scrap_skill as _scrap
    result = _scrap(skill_name)
    if result["status"] == "error":
        msg = result.get("message", "")
        if "not found" in msg.lower():
            code = 404
        else:
            code = 400
        raise HTTPException(code, msg)
    return result


@router.post("/{skill_name}/restore")
def restore_skill(skill_name: str, _: str = Depends(get_current_user)):
    """Restore a scrapped skill."""
    from mcp_server.tools.skills.promoter import restore_skill as _restore
    result = _restore(skill_name)
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
