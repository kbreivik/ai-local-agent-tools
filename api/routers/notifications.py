"""Notification channels, rules, and log API."""
from fastapi import APIRouter, Depends, Query
from api.auth import get_current_user

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("/channels")
async def get_channels(_: str = Depends(get_current_user)):
    """List all notification channels."""
    from api.db.notifications import list_channels
    return {"channels": list_channels()}


@router.post("/channels")
async def create_channel_endpoint(req: dict, _: str = Depends(get_current_user)):
    """Create email or webhook channel."""
    from api.db.notifications import create_channel
    name = req.get("name", "")
    ch_type = req.get("type", "")
    config = req.get("config", {})
    if not name or not ch_type:
        return {"status": "error", "message": "name and type required"}
    cid = create_channel(name, ch_type, config)
    if cid:
        return {"status": "ok", "id": cid}
    return {"status": "error", "message": "Failed to create channel"}


@router.delete("/channels/{channel_id}")
async def delete_channel_endpoint(channel_id: str, _: str = Depends(get_current_user)):
    from api.db.notifications import delete_channel
    ok = delete_channel(channel_id)
    return {"status": "ok" if ok else "error"}


@router.get("/rules")
async def get_rules(_: str = Depends(get_current_user)):
    from api.db.notifications import list_rules
    return {"rules": list_rules()}


@router.post("/rules")
async def create_rule_endpoint(req: dict, _: str = Depends(get_current_user)):
    """Route event_type → channel_id."""
    from api.db.notifications import create_rule
    channel_id = req.get("channel_id", "")
    event_type = req.get("event_type", "")
    min_severity = req.get("min_severity", "warning")
    if not channel_id or not event_type:
        return {"status": "error", "message": "channel_id and event_type required"}
    rid = create_rule(channel_id, event_type, min_severity)
    if rid:
        return {"status": "ok", "id": rid}
    return {"status": "error", "message": "Failed to create rule"}


@router.get("/log")
async def get_notification_log(limit: int = Query(50, ge=1, le=200),
                                _: str = Depends(get_current_user)):
    """Recent notification delivery history."""
    from api.db.notifications import get_log
    return {"log": get_log(limit=limit)}


@router.post("/test/{channel_id}")
async def test_channel(channel_id: str, _: str = Depends(get_current_user)):
    """Send a test notification to verify channel config."""
    from api.notifications import dispatch_notification
    notified = await dispatch_notification(
        "test", "[DEATHSTAR] Test notification",
        "This is a test notification from DEATHSTAR.", {}
    )
    return {"status": "ok", "notified": notified}
