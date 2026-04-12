from fastapi import APIRouter, Depends
from api.auth import get_current_user

router = APIRouter(prefix="/api/credential-profiles", tags=["credential_profiles"])


@router.get("")
async def list_credential_profiles(_: str = Depends(get_current_user)):
    from api.db.credential_profiles import list_profiles
    return {"profiles": list_profiles()}


@router.post("")
async def create_credential_profile(req: dict, _: str = Depends(get_current_user)):
    from api.db.credential_profiles import create_profile
    name = req.get("name", "")
    auth_type = req.get("auth_type", "ssh_key")
    credentials = req.get("credentials", {})
    if not name:
        return {"status": "error", "message": "name required"}
    return create_profile(name, auth_type, credentials)


@router.put("/{profile_id}")
async def update_credential_profile(profile_id: str, req: dict, _: str = Depends(get_current_user)):
    from api.db.credential_profiles import update_profile
    return update_profile(profile_id, name=req.get("name"), credentials=req.get("credentials"))


@router.delete("/{profile_id}")
async def delete_credential_profile(profile_id: str, _: str = Depends(get_current_user)):
    from api.db.credential_profiles import delete_profile
    return delete_profile(profile_id)
