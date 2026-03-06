"""GET /api/alerts — recent alert notifications."""
from fastapi import APIRouter, Query
from api.alerts import get_recent, dismiss, dismiss_all

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("/recent")
async def recent_alerts(
    limit: int = Query(20, ge=1, le=100),
    include_dismissed: bool = Query(False),
):
    return {"alerts": get_recent(limit=limit, include_dismissed=include_dismissed)}


@router.post("/{alert_id}/dismiss")
async def dismiss_alert(alert_id: str):
    ok = dismiss(alert_id)
    return {"dismissed": ok, "id": alert_id}


@router.post("/dismiss-all")
async def dismiss_all_alerts():
    count = dismiss_all()
    return {"dismissed": count}
