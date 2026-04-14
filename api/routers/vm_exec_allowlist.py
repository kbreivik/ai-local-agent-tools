"""GET/POST/DELETE /api/vm-exec-allowlist — manage the vm_exec command allowlist."""
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from api.auth import get_current_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/vm-exec-allowlist", tags=["vm-exec-allowlist"])


class AddPatternRequest(BaseModel):
    pattern: str
    description: str
    scope: str = "permanent"   # 'permanent' | 'session'
    session_id: str = ""


@router.get("")
def list_allowlist(_: str = Depends(get_current_user)):
    from api.db.vm_exec_allowlist import list_all
    return {"patterns": list_all(include_base=True)}


@router.post("")
def add_pattern(body: AddPatternRequest, user: str = Depends(get_current_user)):
    from api.db.vm_exec_allowlist import add_pattern as _add
    result = _add(body.pattern, body.description, body.scope,
                  body.session_id, added_by=user, approved_by=user)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "Failed to add pattern"))
    return {"status": "ok", "data": result}


@router.delete("/{pattern_id}")
def delete_pattern(pattern_id: str, user: str = Depends(get_current_user)):
    from api.db.vm_exec_allowlist import remove_pattern as _remove
    result = _remove(pattern_id, actor=user)
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "Failed to remove pattern"))
    return {"status": "ok", "data": result}
