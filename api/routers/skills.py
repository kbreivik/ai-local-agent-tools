"""GET /api/skills — skill registry endpoints for the GUI Skills tab."""
import json
from fastapi import APIRouter, HTTPException, Query
from api.tool_registry import invoke_tool

router = APIRouter(prefix="/api/skills", tags=["skills"])


@router.get("")
def list_skills(
    category: str = Query("", description="Filter by category"),
    include_disabled: bool = Query(False),
):
    """Return all registered skills, optionally filtered by category."""
    result = invoke_tool("skill_list", {
        "category": category,
        "enabled_only": not include_disabled,
    })
    skills = result.get("data", {}).get("skills", [])
    return {"skills": skills, "count": len(skills)}


@router.post("/{skill_name}/execute")
def execute_skill(skill_name: str, params: dict = {}):
    """Execute a skill by name. Params are passed as keyword arguments."""
    listed = invoke_tool("skill_list", {"category": "", "enabled_only": False})
    names = {s["name"] for s in listed.get("data", {}).get("skills", [])}
    if skill_name not in names:
        raise HTTPException(404, f"Skill '{skill_name}' not found")

    kwargs_json = json.dumps(params) if params else ""
    result = invoke_tool("skill_execute", {"name": skill_name, "kwargs_json": kwargs_json})
    return result


@router.get("/{skill_name}")
def get_skill(skill_name: str):
    """Return metadata for a single skill."""
    listed = invoke_tool("skill_list", {"category": "", "enabled_only": False})
    skills = {s["name"]: s for s in listed.get("data", {}).get("skills", [])}
    if skill_name not in skills:
        raise HTTPException(404, f"Skill '{skill_name}' not found")
    return skills[skill_name]
