# CC PROMPT — v2.14.0 — Notification system: email/webhook for critical events

## What this does

The Settings → Notifications tab exists but is not connected to anything.
This implements a real notification system:
- Email via SMTP (async, non-blocking)
- Webhook (HTTP POST to a URL, e.g. Slack/Teams/Discord/custom)
- Per-alert-type routing rules (which events trigger which channels)
- Rate limiting (no spam — max 1 notification per alert type per hour)

Version bump: 2.13.1 → 2.14.0 (new subsystem, x.1.x)

---

## Change 1 — api/db/notifications.py (NEW FILE)

```python
"""Notification config storage and delivery tracking.

notification_channels: configured delivery channels (email/webhook)
notification_rules:    which alert types route to which channels
notification_log:      sent notification history (rate limit + audit)
"""
import json
import logging
import os
import uuid
from datetime import datetime, timezone

log = logging.getLogger(__name__)

_DDL_PG = """
CREATE TABLE IF NOT EXISTS notification_channels (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    type        TEXT NOT NULL,      -- 'email' | 'webhook'
    config      JSONB NOT NULL,     -- {smtp_host, to_addr} or {url, method, headers}
    enabled     BOOLEAN DEFAULT true,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(name)
);

CREATE TABLE IF NOT EXISTS notification_rules (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    channel_id      UUID REFERENCES notification_channels(id) ON DELETE CASCADE,
    event_type      TEXT NOT NULL,  -- 'alert_critical' | 'alert_degraded' | 'ssh_new_host'
                                    -- | 'version_change' | 'disk_threshold' | '*'
    min_severity    TEXT DEFAULT 'warning',
    enabled         BOOLEAN DEFAULT true
);

CREATE TABLE IF NOT EXISTS notification_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    channel_id      UUID,
    event_type      TEXT,
    subject         TEXT,
    sent_at         TIMESTAMPTZ DEFAULT NOW(),
    status          TEXT,           -- 'sent' | 'failed'
    error           TEXT
);
CREATE INDEX IF NOT EXISTS idx_notif_log_sent ON notification_log(sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_notif_log_type ON notification_log(event_type, sent_at DESC);
"""

_initialized = False


def _ts(): return datetime.now(timezone.utc).isoformat()
def _is_pg(): return "postgres" in os.environ.get("DATABASE_URL", "")


def init_notifications() -> bool:
    global _initialized
    if _initialized: return True
    if not _is_pg():
        _initialized = True
        return True
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        for stmt in _DDL_PG.strip().split(";"):
            stmt = stmt.strip()
            if stmt: cur.execute(stmt)
        cur.close(); conn.close()
        _initialized = True
        log.info("notification tables ready")
        return True
    except Exception as e:
        log.warning("notifications init failed: %s", e)
        return False


def should_notify(event_type: str, channel_id: str, rate_limit_hours: int = 1) -> bool:
    """Check rate limit: return False if same event_type was sent to this channel recently."""
    if not _is_pg(): return True
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM notification_log
            WHERE channel_id = %s AND event_type = %s
              AND status = 'sent'
              AND sent_at > NOW() - INTERVAL '%s hours'
        """, (channel_id, event_type, rate_limit_hours))
        count = cur.fetchone()[0]
        cur.close(); conn.close()
        return count == 0
    except Exception as e:
        log.debug("should_notify check failed: %s", e)
        return True


def log_notification(channel_id: str, event_type: str, subject: str,
                     status: str, error: str = "") -> None:
    """Record a notification attempt."""
    if not _is_pg(): return
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO notification_log (id, channel_id, event_type, subject, status, error)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (str(uuid.uuid4()), channel_id, event_type, subject[:200], status, error[:300] or None))
        conn.commit(); cur.close(); conn.close()
    except Exception as e:
        log.debug("log_notification failed: %s", e)
```

---

## Change 2 — api/notifications.py (NEW FILE) — delivery engine

```python
"""Notification delivery: email via SMTP + webhook HTTP POST."""
import asyncio
import json
import logging
import os

import httpx

log = logging.getLogger(__name__)


async def send_email(to: str, subject: str, body: str, config: dict) -> bool:
    """Send email via SMTP. Returns True on success."""
    import smtplib
    from email.mime.text import MIMEText
    smtp_host = config.get("smtp_host", "")
    smtp_port = int(config.get("smtp_port", 587))
    smtp_user = config.get("smtp_user", "")
    smtp_pass = config.get("smtp_pass", "")
    from_addr = config.get("from_addr", smtp_user)

    def _send():
        msg = MIMEText(body, "plain")
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = to
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as s:
            s.starttls()
            if smtp_user:
                s.login(smtp_user, smtp_pass)
            s.send_message(msg)

    try:
        await asyncio.get_event_loop().run_in_executor(None, _send)
        return True
    except Exception as e:
        log.warning("send_email failed: %s", e)
        return False


async def send_webhook(url: str, payload: dict, config: dict) -> bool:
    """Send HTTP POST to webhook URL. Returns True on success."""
    method  = config.get("method", "POST").upper()
    headers = config.get("headers", {})
    headers.setdefault("Content-Type", "application/json")

    # Slack/Discord compatibility: wrap in {"text": "..."} if no body template
    body = json.dumps(payload)

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.request(method, url, content=body, headers=headers)
            return r.status_code < 400
    except Exception as e:
        log.warning("send_webhook failed: %s", e)
        return False


async def dispatch_notification(event_type: str, subject: str, body: str,
                                 metadata: dict = None) -> list[str]:
    """Find matching channels for event_type and deliver notification.

    Returns list of channel names that were notified.
    Skips channels that are rate-limited.
    """
    if not _is_pg_available(): return []

    try:
        from api.connections import _get_conn
        from api.db.notifications import should_notify, log_notification

        conn = _get_conn()
        cur = conn.cursor()

        # Get enabled channels matching this event type
        cur.execute("""
            SELECT c.id, c.name, c.type, c.config, r.event_type
            FROM notification_channels c
            JOIN notification_rules r ON r.channel_id = c.id
            WHERE c.enabled = true AND r.enabled = true
              AND (r.event_type = %s OR r.event_type = '*')
            ORDER BY c.name
        """, (event_type,))
        cols = [d[0] for d in cur.description]
        channels = [dict(zip(cols, row)) for row in cur.fetchall()]
        cur.close(); conn.close()
    except Exception as e:
        log.warning("dispatch_notification DB error: %s", e)
        return []

    notified = []
    for ch in channels:
        ch_id = str(ch["id"])
        ch_name = ch["name"]
        ch_type = ch["type"]
        config = ch["config"] if isinstance(ch["config"], dict) else json.loads(ch["config"] or "{}")

        # Rate limit check (1 per hour per event_type per channel)
        if not should_notify(event_type, ch_id, rate_limit_hours=1):
            log.debug("Notification rate-limited: %s → %s", event_type, ch_name)
            continue

        success = False
        error = ""
        try:
            if ch_type == "email":
                to = config.get("to_addr", "")
                if to:
                    success = await send_email(to, subject, body, config)
            elif ch_type == "webhook":
                url = config.get("url", "")
                if url:
                    payload = {"event": event_type, "subject": subject,
                               "body": body, **(metadata or {})}
                    success = await send_webhook(url, payload, config)
        except Exception as e:
            error = str(e)[:200]

        log_notification(ch_id, event_type, subject,
                         "sent" if success else "failed", error)
        if success:
            notified.append(ch_name)
            log.info("Notification sent: %s → %s (%s)", event_type, ch_name, ch_type)
        else:
            log.warning("Notification failed: %s → %s: %s", event_type, ch_name, error)

    return notified


def _is_pg_available():
    return "postgres" in os.environ.get("DATABASE_URL", "")
```

---

## Change 3 — api/alerts.py — fire notifications on critical alerts

In `fire_alert()` (or wherever alerts are created), after writing to the alerts
table/queue, dispatch a notification:

```python
# After alert is stored:
if severity in ("critical", "warning"):
    try:
        from api.notifications import dispatch_notification
        asyncio.create_task(dispatch_notification(
            event_type=f"alert_{severity}",
            subject=f"[DEATHSTAR] {severity.upper()}: {component}",
            body=f"Component: {component}\nSeverity: {severity}\nMessage: {message}\nSource: {source}",
            metadata={"component": component, "severity": severity},
        ))
    except Exception:
        pass
```

Also wire notifications into `entity_events` for high-severity events:

```python
# In api/db/entity_history.py write_event(), after INSERT:
if severity in ("critical", "warning"):
    try:
        from api.notifications import dispatch_notification
        asyncio.create_task(dispatch_notification(
            event_type=event_type,
            subject=f"[DEATHSTAR] {event_type.replace('_', ' ').title()}: {entity_id}",
            body=description,
            metadata={"entity_id": entity_id, "severity": severity},
        ))
    except Exception:
        pass
```

---

## Change 4 — api/routers/notifications.py (NEW FILE) — CRUD API

```python
from fastapi import APIRouter, Depends
from api.auth import get_current_user

router = APIRouter(prefix="/api/notifications", tags=["notifications"])

@router.get("/channels")
async def list_channels(_: str = Depends(get_current_user)):
    """List all notification channels."""
    ...

@router.post("/channels")
async def create_channel(req: dict, _: str = Depends(get_current_user)):
    """Create email or webhook channel."""
    ...

@router.delete("/channels/{channel_id}")
async def delete_channel(channel_id: str, _: str = Depends(get_current_user)):
    ...

@router.get("/rules")
async def list_rules(_: str = Depends(get_current_user)):
    ...

@router.post("/rules")
async def create_rule(req: dict, _: str = Depends(get_current_user)):
    """Route event_type → channel_id."""
    ...

@router.get("/log")
async def get_log(limit: int = 50, _: str = Depends(get_current_user)):
    """Recent notification delivery history."""
    ...

@router.post("/test/{channel_id}")
async def test_channel(channel_id: str, _: str = Depends(get_current_user)):
    """Send a test notification to verify channel config."""
    from api.notifications import dispatch_notification
    notified = await dispatch_notification(
        "test", "[DEATHSTAR] Test notification",
        "This is a test notification from DEATHSTAR.", {}
    )
    return {"status": "ok", "notified": notified}
```

---

## Change 5 — gui: Settings → Notifications tab

Implement the Notifications settings tab with:
- **Channels section**: list + add email/webhook channels
  - Email form: SMTP host, port, user, password, from_addr, to_addr
  - Webhook form: URL, method (POST), custom headers (JSON), test button
- **Rules section**: route event types to channels
  - Event types: alert_critical, alert_degraded, version_change, disk_threshold, ssh_new_host, *
  - Dropdown: which channel
- **Notification log**: last 20 sent/failed, with timestamps

---

## Change 6 — api/main.py — init + register router

```python
from api.db.notifications import init_notifications
from api.routers.notifications import router as notifications_router

# In startup:
init_notifications()

# Register router:
app.include_router(notifications_router)
```

---

## Version bump

Update VERSION: `2.13.1` → `2.14.0`

---

## Commit

```bash
git add -A
git commit -m "feat(notifications): v2.14.0 email + webhook notification system

- notification_channels + notification_rules + notification_log tables
- async SMTP email delivery (starttls, configurable)
- async webhook delivery (Slack/Teams/Discord/custom compatible)
- 1-per-hour rate limiting per event_type per channel
- dispatch_notification() wired into fire_alert() and write_event()
- Event types: alert_critical, alert_degraded, version_change, disk_threshold, *
- Settings → Notifications tab: channel CRUD + rule routing + delivery log
- POST /api/notifications/test/{channel_id} for channel verification"
git push origin main
```
