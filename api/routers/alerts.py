"""GET /api/alerts — recent alert notifications."""
from fastapi import APIRouter, Depends, Query
from api.auth import get_current_user
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


@router.post("/test-webhook")
async def test_webhook(_: str = Depends(get_current_user)):
    """
    Send a synthetic test alert to the configured webhook URL.
    Returns success/failure without adding to the real alert ring buffer.
    """
    from api.settings_manager import get_setting
    import httpx
    from datetime import datetime, timezone

    url = (get_setting("notificationWebhookUrl") or {}).get("value", "").strip()
    if not url:
        return {"ok": False, "message": "No webhook URL configured. Set it in Settings → Notifications."}

    payload = {
        "platform": "deathstar",
        "severity": "info",
        "component": "test",
        "message": "DEATHSTAR webhook test — if you see this, notifications are working.",
        "prev_health": None,
        "health": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "connection_label": "",
        "connection_id": "",
    }

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.post(url, json=payload)
        if r.status_code < 300:
            return {"ok": True, "message": f"Delivered — HTTP {r.status_code}"}
        else:
            return {"ok": False, "message": f"Webhook returned HTTP {r.status_code}"}
    except httpx.TimeoutException:
        return {"ok": False, "message": "Timed out (8s) — check the URL is reachable"}
    except Exception as e:
        return {"ok": False, "message": str(e)[:120]}
