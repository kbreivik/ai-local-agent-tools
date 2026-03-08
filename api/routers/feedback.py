"""POST /api/feedback — record thumbs up/down on a completed agent run."""
import logging

from fastapi import APIRouter
from pydantic import BaseModel

import api.logger as logger_mod
from api.db.base import get_engine
from api.db import queries as q

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/feedback", tags=["feedback"])


class FeedbackRequest(BaseModel):
    session_id: str
    rating: str  # "thumbs_up" | "thumbs_down"


@router.post("")
async def submit_feedback(req: FeedbackRequest):
    """Record operator feedback on a completed agent session."""
    if req.rating not in ("thumbs_up", "thumbs_down"):
        return {"status": "error", "message": "rating must be thumbs_up or thumbs_down"}

    # Look up the operation to get task label and final answer
    async with get_engine().begin() as conn:
        op = await q.get_operation_by_session(conn, req.session_id)

    if not op:
        return {"status": "error", "message": f"No operation found for session '{req.session_id}'"}

    # Write feedback to DB
    await logger_mod.set_operation_feedback(req.session_id, req.rating)

    # For thumbs_up — store a golden example engram in MuninnDB so future runs
    # activate it as positive context. No MuninnDB write for thumbs_down
    # (bad examples would pollute memory; DB record is sufficient).
    if req.rating == "thumbs_up":
        task_label  = op.get("label") or ""
        final_answer = op.get("final_answer") or ""
        if task_label and final_answer:
            try:
                from api.memory.client import get_client as _get_mem
                mem = _get_mem()
                concept = f"golden:{req.session_id[:8]}"
                content = (
                    f"[golden-example]\n"
                    f"Task: {task_label}\n\n"
                    f"Answer: {final_answer[:800]}"
                )
                await mem.store(concept, content, tags=["golden", "feedback", "thumbs_up"])
                log.info("Stored golden engram for session %s", req.session_id)
            except Exception as e:
                log.warning("MuninnDB golden engram store failed: %s", e)

    return {"status": "ok", "rating": req.rating, "session_id": req.session_id}
