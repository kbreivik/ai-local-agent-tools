"""
Threshold-based alerting — no external dependencies.

Called by BaseCollector after each poll. When health worsens (lower → higher
severity), creates an alert, enqueues it in memory, and writes to audit_log.

GUI polls GET /api/alerts/recent every 10s for toast notifications.
"""
import logging
from collections import deque
from datetime import datetime, timezone

log = logging.getLogger(__name__)

# In-memory ring buffer — survives until API restart
_alerts: deque[dict] = deque(maxlen=200)

# Track previous health per component so we can detect transitions
_prev_health: dict[str, str] = {}

# Severity order — higher number = worse
_SEVERITY: dict[str, int] = {
    "healthy":       0,
    "ok":            0,
    "green":         0,
    "active":        0,
    "unconfigured":  0,
    "unknown":       1,
    "yellow":        2,
    "degraded":      2,
    "red":           3,
    "critical":      3,
    "error":         3,
}


def _sev(health: str) -> int:
    return _SEVERITY.get(health, 1)


async def _dispatch_webhook(alert: dict) -> None:
    """
    POST alert payload to the configured webhook URL.
    Non-blocking — caller uses asyncio.create_task().
    Silently swallows errors (webhook failure must never affect the platform).
    """
    try:
        from api.settings_manager import get_setting
        url = (get_setting("notificationWebhookUrl") or {}).get("value", "").strip()
        if not url:
            return

        payload = {
            "platform": "deathstar",
            "severity": alert.get("severity", "unknown"),
            "component": alert.get("component", ""),
            "message": alert.get("message", ""),
            "prev_health": alert.get("prev_health"),
            "health": alert.get("health"),
            "timestamp": alert.get("timestamp", ""),
            "connection_label": alert.get("connection_label", ""),
            "connection_id": alert.get("connection_id", ""),
        }

        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(url, json=payload)
            log.debug("Webhook dispatch → %s HTTP %d", url[:60], r.status_code)

    except Exception as e:
        log.debug("Webhook dispatch failed (non-critical): %s", e)


async def check_transition(component: str, current_health: str, **extra) -> None:
    """
    Called after every collector poll. Fires an alert if health worsened.
    Also fires a recovery alert when health improves from critical/error.
    Extra kwargs: connection_label, connection_id from collector state.
    """
    prev = _prev_health.get(component)
    _prev_health[component] = current_health

    if prev is None:
        return  # First poll — no transition yet

    prev_sev = _sev(prev)
    curr_sev = _sev(current_health)

    if curr_sev == prev_sev:
        return  # No change

    # Suppress non-critical collector noise while a test run is active.
    # (SSH load from test agents causes transient vm_hosts/network_ssh transitions
    # that are artefacts of the test, not real production incidents.)
    # Critical alerts (sev >= 3: error/critical) always fire.
    if curr_sev < 3:
        try:
            from api.routers.tests_api import test_run_active as _tra
            if _tra:
                log.debug(
                    "ALERT suppressed during test run: %s %s → %s",
                    component, prev, current_health,
                )
                return
        except ImportError:
            pass

    now = datetime.now(timezone.utc)
    alert_id = f"{component}_{now.timestamp():.0f}"

    # Use connection label if available, otherwise component name
    display_name = extra.get("connection_label") or component

    if curr_sev > prev_sev:
        severity = "critical" if curr_sev >= 3 else "warning"
        message = f"{display_name}: {prev} → {current_health}"
    else:
        severity = "info"
        message = f"{display_name}: recovered ({prev} → {current_health})"

    alert = {
        "id": alert_id,
        "component": display_name,
        "severity": severity,
        "message": message,
        "prev_health": prev,
        "health": current_health,
        "timestamp": now.isoformat(),
        "dismissed": False,
        "connection_label": extra.get("connection_label", ""),
        "connection_id": extra.get("connection_id", ""),
    }

    _alerts.appendleft(alert)
    log.warning("ALERT [%s] %s", severity.upper(), message)

    # Broadcast health change to all connected WebSocket clients
    try:
        from api.websocket import manager as _ws_mgr
        import asyncio as _asyncio
        _loop = None
        try:
            _loop = _asyncio.get_event_loop()
        except RuntimeError:
            pass
        if _loop and _loop.is_running():
            _asyncio.ensure_future(_ws_mgr.broadcast({
                "type":      "health_change",
                "component": component,
                "severity":  severity,
                "prev":      prev,
                "current":   current_health,
                "message":   message,
                "timestamp": now.isoformat(),
            }))
    except Exception as _e:
        log.debug("health_change broadcast failed: %s", _e)

    # Dispatch webhook notification (non-blocking)
    try:
        from api.settings_manager import get_setting
        notify_recovery = str(
            (get_setting("notifyOnRecovery") or {}).get("value", "false")
        ).lower() in ("true", "1", "yes")
        should_dispatch = severity in ("warning", "critical") or (severity == "info" and notify_recovery)
        if should_dispatch:
            import asyncio
            asyncio.create_task(_dispatch_webhook(alert))
    except Exception as _e:
        log.debug("Webhook dispatch scheduling failed: %s", _e)

    # Write to audit_log (non-blocking via logger queue)
    try:
        import api.logger as logger_mod
        await logger_mod.log_audit(
            event_type="alert",
            entity_id=component,
            entity_type="infrastructure",
            detail=alert,
            source="collector",
        )
    except Exception as e:
        log.debug("Alert audit write failed: %s", e)


def fire_alert(
    component: str,
    severity: str,
    message: str,
    source: str = "elastic",
) -> None:
    """
    Directly fire an alert (not via health transition).
    Used by ElasticAlerter for log-derived alerts.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    alert_id = f"{component}_{source}_{now.timestamp():.0f}"
    alert = {
        "id": alert_id,
        "component": component,
        "severity": severity,
        "message": message,
        "prev_health": None,
        "health": None,
        "timestamp": now.isoformat(),
        "dismissed": False,
        "source": source,
    }
    _alerts.appendleft(alert)
    log.warning("ALERT [%s/%s] %s", source.upper(), severity.upper(), message)

    try:
        import asyncio
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import api.logger as logger_mod
            loop.create_task(logger_mod.log_audit(
                event_type="alert",
                entity_id=component,
                entity_type="elasticsearch",
                detail=alert,
                source=source,
            ))
    except Exception:
        pass

    # Dispatch webhook notification (non-blocking, sync context)
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_dispatch_webhook(alert))
    except Exception as _e:
        log.debug("Webhook dispatch scheduling failed (fire_alert): %s", _e)


def update_content(component: str, content: str) -> bool:
    """Update the message of the most recent undismissed alert for a component."""
    for alert in _alerts:
        if alert["component"] == component and not alert["dismissed"]:
            alert["message"] = content
            return True
    return False


def get_recent(limit: int = 20, include_dismissed: bool = False) -> list[dict]:
    alerts = list(_alerts)[:limit]
    if not include_dismissed:
        alerts = [a for a in alerts if not a["dismissed"]]
    return alerts


def dismiss(alert_id: str) -> bool:
    for alert in _alerts:
        if alert["id"] == alert_id:
            alert["dismissed"] = True
            return True
    return False


def dismiss_all() -> int:
    count = 0
    for alert in _alerts:
        if not alert["dismissed"]:
            alert["dismissed"] = True
            count += 1
    return count
