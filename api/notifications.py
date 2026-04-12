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
