"""Display aliases API — get/set/delete entity display name overrides."""
import re
from fastapi import APIRouter, Depends, HTTPException
from api.auth import get_current_user

router = APIRouter(prefix="/api/display-aliases", tags=["display_aliases"])

# Allowed entity_id prefix patterns — guards against injection
_ENTITY_ID_RE = re.compile(r'^[\w\-:\.]+$')


def _validate_entity_id(entity_id: str) -> None:
    if not entity_id or len(entity_id) > 200 or not _ENTITY_ID_RE.match(entity_id):
        raise HTTPException(400, "Invalid entity_id format")


@router.get("")
async def list_display_aliases(_: str = Depends(get_current_user)):
    from api.db.display_aliases import list_aliases
    return {"aliases": list_aliases()}


@router.get("/{entity_id:path}")
async def get_display_alias(entity_id: str, _: str = Depends(get_current_user)):
    _validate_entity_id(entity_id)
    from api.db.display_aliases import get_alias
    alias = get_alias(entity_id)
    return {"entity_id": entity_id, "alias": alias}


@router.put("/{entity_id:path}")
async def set_display_alias(entity_id: str, req: dict, _: str = Depends(get_current_user)):
    _validate_entity_id(entity_id)
    alias = str(req.get("alias", "")).strip()
    origin = str(req.get("origin", "")).strip()
    if not alias:
        raise HTTPException(400, "alias must be non-empty")
    if len(alias) > 100:
        raise HTTPException(400, "alias max 100 characters")
    from api.db.display_aliases import set_alias
    ok = set_alias(entity_id, alias, origin)
    if not ok:
        raise HTTPException(500, "Failed to save alias")
    return {"status": "ok", "entity_id": entity_id, "alias": alias}


@router.delete("/{entity_id:path}")
async def delete_display_alias(entity_id: str, _: str = Depends(get_current_user)):
    _validate_entity_id(entity_id)
    from api.db.display_aliases import delete_alias, get_alias
    # Return the alias before deleting so caller knows what was cleared
    old = get_alias(entity_id)
    delete_alias(entity_id)
    return {"status": "ok", "entity_id": entity_id, "cleared_alias": old}
