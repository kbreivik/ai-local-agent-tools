"""Lock status endpoint."""
from fastapi import APIRouter, Depends
from api.auth import get_current_user
from api.lock import plan_lock

router = APIRouter(prefix="/api/lock", tags=["lock"])


@router.get("/status")
async def lock_status(user: str = Depends(get_current_user)):
    info = plan_lock.get_info()
    if info is None:
        return {"locked": False}
    return info


@router.post("/force-release")
async def force_release_lock(user: str = Depends(get_current_user)):
    """Admin-only: force-release a stuck lock."""
    released = await plan_lock.force_release()
    return {"released": released}
