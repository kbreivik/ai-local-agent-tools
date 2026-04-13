"""Frontend error reporting endpoint — receives client-side crash reports."""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/errors", tags=["errors"])


class FrontendError(BaseModel):
    message: str = ""
    stack: str = ""
    component_stack: str = ""
    url: str = ""
    version: str = ""
    user_agent: str = ""


@router.post("/frontend")
async def report_frontend_error(err: FrontendError):
    """Receive a JS crash report from the browser.

    No auth required — the crash may have destroyed the auth state.
    Rate-limited by the browser (one report per crash event).
    Logs to server log + audit_log.
    """
    log.error(
        "FRONTEND CRASH | version=%s | %s | url=%s\n%s\n%s",
        err.version or "unknown",
        err.message[:200],
        err.url,
        err.stack[:500] if err.stack else "(no stack)",
        err.component_stack[:500] if err.component_stack else "(no component stack)",
    )
    try:
        from api.db import queries as q
        from api.db.base import get_engine
        async with get_engine().begin() as conn:
            await q.create_audit_entry(
                conn,
                event_type="frontend_crash",
                entity_id="browser",
                entity_type="frontend",
                detail={
                    "message": err.message[:500],
                    "stack": err.stack[:1000],
                    "component_stack": err.component_stack[:500],
                    "url": err.url,
                    "version": err.version,
                },
                source="browser",
            )
    except Exception as e:
        log.debug("frontend error audit write failed: %s", e)
    return {"received": True, "ts": datetime.now(timezone.utc).isoformat()}
