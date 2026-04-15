"""Card templates API — get/put type defaults and per-connection overrides."""
from fastapi import APIRouter, Depends, HTTPException
from api.auth import get_current_user, get_current_user_and_role, role_meets

router = APIRouter(prefix="/api/card-templates", tags=["card_templates"])

VALID_CARD_TYPES = {"container", "swarm_service", "proxmox_vm"}
VALID_SECTIONS   = {"header_sub", "collapsed", "expanded", "entity_only", "hidden"}
MAX_COLLAPSED    = 10
MAX_HEADER_SUB   = 1


def _validate_template(t: dict) -> str | None:
    """Validate template structure. Returns error string or None if valid."""
    if not isinstance(t, dict): return "Template must be a JSON object"
    for sec, fields in t.items():
        if sec not in VALID_SECTIONS: return f"Invalid section: {sec!r}"
        if not isinstance(fields, list): return f"Section {sec!r} must be an array"
        if not all(isinstance(f, str) for f in fields): return "All field keys must be strings"
    if len(t.get("collapsed", [])) > MAX_COLLAPSED:
        return f"Collapsed section max {MAX_COLLAPSED} fields"
    if len(t.get("header_sub", [])) > MAX_HEADER_SUB:
        return f"header_sub section max {MAX_HEADER_SUB} field"
    return None


@router.get("/defaults")
async def get_all_defaults(_: str = Depends(get_current_user)):
    """Return all type-level default templates."""
    from api.db.card_templates import DEFAULT_TEMPLATES, get_template
    result = {}
    for ct in VALID_CARD_TYPES:
        override = get_template('type', ct)
        result[ct] = override if override else DEFAULT_TEMPLATES.get(ct, {})
    return result


@router.get("/type/{card_type}")
async def get_type_template(card_type: str, _: str = Depends(get_current_user)):
    """Get the type-level default template for a card type."""
    if card_type not in VALID_CARD_TYPES:
        raise HTTPException(400, f"Invalid card_type. Valid: {sorted(VALID_CARD_TYPES)}")
    from api.db.card_templates import resolve_template
    return {"card_type": card_type, "template": resolve_template(card_type)}


@router.put("/type/{card_type}")
async def put_type_template(
    card_type: str, req: dict, user_role: tuple = Depends(get_current_user_and_role)
):
    """Update the type-level default template."""
    _, role = user_role
    if not role_meets(role, "imperial_officer"):
        raise HTTPException(403, "imperial_officer or above required")
    if card_type not in VALID_CARD_TYPES:
        raise HTTPException(400, f"Invalid card_type")
    template = req.get("template", {})
    err = _validate_template(template)
    if err:
        raise HTTPException(400, err)
    from api.db.card_templates import upsert_template
    ok = upsert_template('type', card_type, template)
    if not ok:
        raise HTTPException(500, "Failed to save template")
    return {"status": "ok", "card_type": card_type}


@router.get("/connection/{connection_id}")
async def get_connection_template(connection_id: str, _: str = Depends(get_current_user)):
    """Get effective template for a specific connection (override or type default)."""
    from api.db.card_templates import get_template
    override = get_template('connection', connection_id)
    return {
        "connection_id":  connection_id,
        "has_override":   override is not None,
        "template":       override,
    }


@router.put("/connection/{connection_id}")
async def put_connection_template(
    connection_id: str, req: dict, user_role: tuple = Depends(get_current_user_and_role)
):
    """Save a per-connection template override."""
    _, role = user_role
    if not role_meets(role, "imperial_officer"):
        raise HTTPException(403, "imperial_officer or above required")
    template = req.get("template", {})
    err = _validate_template(template)
    if err:
        raise HTTPException(400, err)
    from api.db.card_templates import upsert_template
    ok = upsert_template('connection', connection_id, template)
    if not ok:
        raise HTTPException(500, "Failed to save template")
    return {"status": "ok", "connection_id": connection_id}


@router.delete("/connection/{connection_id}")
async def delete_connection_template(
    connection_id: str, user_role: tuple = Depends(get_current_user_and_role)
):
    """Remove per-connection override — resets to type default."""
    _, role = user_role
    if not role_meets(role, "imperial_officer"):
        raise HTTPException(403, "imperial_officer or above required")
    from api.db.card_templates import delete_template
    delete_template('connection', connection_id)
    return {"status": "ok", "message": "Override cleared — using type default"}
