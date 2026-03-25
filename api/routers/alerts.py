"""GET /api/alerts — recent alert notifications."""
from fastapi import APIRouter, Query
from api.alerts import get_recent, dismiss, dismiss_all, fire_alert, update_content

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


# ── Internal helpers (not HTTP endpoints) ─────────────────────────────────────

def create_alert_internal(
    concept: str, content: str, tags: list, severity: str = "warning"
) -> None:
    """Internal: create a new alert record. Called by collectors, not HTTP."""
    component = concept.replace("alert:", "")
    fire_alert(component, severity, content, source="collector")


def update_alert_content_internal(concept: str, content: str) -> None:
    """Internal: update content of the most recent undismissed alert for a concept."""
    component = concept.replace("alert:", "")
    update_content(component, content)


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
