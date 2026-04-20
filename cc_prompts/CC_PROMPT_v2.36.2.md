# CC PROMPT — v2.36.2 — External AI Router: confirmation gate

## What this does

Adds the `requireConfirmation` gate — an operator-visible modal that blocks
the agent loop between "router decided to escalate" and "external AI call
actually made." Reuses the v2.35.1 `awaiting_clarification` pattern:
`operations.status = 'awaiting_external_ai_confirm'`, WebSocket event, new
endpoint pair to resume/cancel, background task for timeout auto-cancel.

Version bump: 2.36.1 → 2.36.2.

---

## Why

User sovereignty: Claude/OpenAI/Grok calls cost money and can touch user data.
The `requireConfirmation` toggle was UI-only pre-v2.36 (no Python consumer);
v2.36.2 makes it real. Modal is the LAST chance to stop an escalation before
tokens leave the building.

Same pattern as plan_action (v2.33.6) and preflight disambiguation (v2.35.1)
so operators recognise it immediately.

---

## Change 1 — `api/agents/external_ai_confirmation.py` — new module

Create new file:

```python
"""External AI confirmation gate — the wait primitive for v2.36.2.

Mirrors api/confirmation.py (plan_action) and api/clarification.py (preflight
disambiguation). Keys on session_id. wait_for_confirmation blocks on an
asyncio.Event with a timeout; resolve_confirmation fires the event.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class _PendingConfirm:
    event: asyncio.Event
    decision: str = "pending"   # 'approved' | 'rejected' | 'timeout'
    created_at: float = 0.0


_pending: dict[str, _PendingConfirm] = {}


def _cleanup_stale(ttl_s: int = 900) -> None:
    """Drop entries older than ttl_s so zombie sessions don't leak."""
    cutoff = time.monotonic() - ttl_s
    stale = [k for k, p in _pending.items() if p.created_at < cutoff]
    for k in stale:
        _pending.pop(k, None)


async def wait_for_confirmation(session_id: str, timeout_s: int = 300) -> str:
    """Block until the user approves/rejects, or timeout_s elapses.

    Returns one of 'approved' | 'rejected' | 'timeout'. Safe to call
    concurrently for different session_ids; calling twice for the same
    session_id without an intervening resolve returns the cached decision
    of the first wait.
    """
    _cleanup_stale()
    pending = _pending.get(session_id)
    if pending is None:
        pending = _PendingConfirm(
            event=asyncio.Event(),
            created_at=time.monotonic(),
        )
        _pending[session_id] = pending
    try:
        await asyncio.wait_for(pending.event.wait(), timeout=timeout_s)
        return pending.decision
    except asyncio.TimeoutError:
        pending.decision = "timeout"
        pending.event.set()   # unblock any concurrent waiters
        return "timeout"
    finally:
        # Leave the entry briefly so late resolve_confirmation calls don't
        # crash; it'll be cleaned up by _cleanup_stale on next call.
        pass


def resolve_confirmation(session_id: str, approved: bool) -> bool:
    """Called by the /confirm-external endpoint. Returns True if the session
    had a pending wait, False otherwise (stale call)."""
    pending = _pending.get(session_id)
    if pending is None:
        return False
    pending.decision = "approved" if approved else "rejected"
    pending.event.set()
    return True


def has_pending(session_id: str) -> bool:
    return session_id in _pending and _pending[session_id].decision == "pending"
```

---

## Change 2 — `api/routers/agent.py` — add the two new endpoints

**After** the existing `@router.post("/preflight/cancel")` endpoint, add:

```python
class ExternalConfirmRequest(BaseModel):
    session_id: str
    approved: bool


class ExternalConfirmCancelRequest(BaseModel):
    session_id: str


@router.post("/operations/{operation_id}/confirm-external")
async def confirm_external_ai(
    operation_id: str,
    req: ExternalConfirmRequest,
    user: str = Depends(get_current_user),
):
    """Resolve a pending external-AI confirmation prompt.

    v2.36.2 — operator approves or rejects the escalation. Router-decision
    rationale (rule_fired, reason) was broadcast to the GUI when the gate
    opened; this endpoint just closes it.
    """
    from api.agents.external_ai_confirmation import resolve_confirmation
    ok = resolve_confirmation(req.session_id, req.approved)
    if not ok:
        return {
            "status": "error",
            "message": f"No pending external-AI confirmation for session '{req.session_id}'",
        }

    # Flip DB status back to running / cancelled so the UI reflects reality
    # even before the agent loop writes its terminal row.
    try:
        from api.db.base import get_engine as _ge
        from sqlalchemy import text as _t
        new_status = "running" if req.approved else "cancelled"
        async with _ge().begin() as conn:
            await conn.execute(
                _t("UPDATE operations SET status=:st "
                   "WHERE session_id=:sid AND status='awaiting_external_ai_confirm'"),
                {"st": new_status, "sid": req.session_id},
            )
    except Exception as e:
        log.debug("confirm_external_ai DB update failed: %s", e)

    try:
        await manager.broadcast({
            "type": "external_ai_confirm_resolved",
            "session_id": req.session_id,
            "approved": req.approved,
            "actor": user,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    except Exception:
        pass

    try:
        from api.metrics import EXTERNAL_AI_CONFIRM_OUTCOME
        EXTERNAL_AI_CONFIRM_OUTCOME.labels(
            outcome="approved" if req.approved else "rejected",
        ).inc()
    except Exception:
        pass

    return {"status": "ok", "message": "approved" if req.approved else "rejected"}
```

---

## Change 3 — helper fn `wait_for_external_ai_confirmation` in `api/routers/agent.py`

Add this helper just above `_run_single_agent_step` so v2.36.3 can call
it cleanly. It wraps the low-level wait primitive with the broadcast,
DB status flip, and timeout metric.

```python
async def wait_for_external_ai_confirmation(
    *,
    session_id: str,
    operation_id: str,
    provider: str,
    model: str,
    rule_fired: str,
    reason: str,
    output_mode: str,
) -> str:
    """Gate the agent loop on operator approval before calling external AI.

    v2.36.2. Broadcasts `external_ai_confirm_pending` to the GUI with the
    router rationale + provider/model, flips operations.status, waits up
    to `externalConfirmTimeoutSeconds` for a /confirm-external call,
    returns one of 'approved'|'rejected'|'timeout'.

    If requireConfirmation is false, returns 'approved' without waiting.
    """
    from mcp_server.tools.skills.storage import get_backend
    try:
        require = get_backend().get_setting("requireConfirmation")
    except Exception:
        require = True
    if require is None:
        require = True
    # Normalise truthy forms from storage backend
    if isinstance(require, str):
        require = require.strip().lower() in ("1", "true", "yes", "on")

    if not require:
        return "approved"

    # Read timeout (operator-tunable)
    try:
        timeout_s = int(get_backend().get_setting("externalConfirmTimeoutSeconds") or 300)
    except Exception:
        timeout_s = 300

    # Flip DB status
    try:
        from api.db.base import get_engine as _ge
        from sqlalchemy import text as _t
        async with _ge().begin() as conn:
            await conn.execute(
                _t("UPDATE operations SET status='awaiting_external_ai_confirm' "
                   "WHERE session_id=:sid"),
                {"sid": session_id},
            )
    except Exception as e:
        log.debug("wait_for_external_ai_confirmation DB flip failed: %s", e)

    await manager.broadcast({
        "type": "external_ai_confirm_pending",
        "session_id": session_id,
        "operation_id": operation_id,
        "provider": provider,
        "model": model,
        "rule_fired": rule_fired,
        "reason": reason,
        "output_mode": output_mode,
        "timeout_s": timeout_s,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    await manager.send_line(
        "step",
        f"[external-ai] Awaiting operator approval — {provider}/{model}, "
        f"rule={rule_fired}, mode={output_mode} (timeout {timeout_s}s)",
        status="warning", session_id=session_id,
    )

    from api.agents.external_ai_confirmation import wait_for_confirmation
    decision = await wait_for_confirmation(session_id, timeout_s=timeout_s)

    if decision == "timeout":
        try:
            from api.metrics import EXTERNAL_AI_CONFIRM_OUTCOME
            EXTERNAL_AI_CONFIRM_OUTCOME.labels(outcome="timeout").inc()
        except Exception:
            pass
        try:
            from api.db.base import get_engine as _ge
            from sqlalchemy import text as _t
            async with _ge().begin() as conn:
                await conn.execute(
                    _t("UPDATE operations SET status='cancelled', "
                       "final_answer='External AI escalation timed out waiting for approval.' "
                       "WHERE session_id=:sid "
                       "AND status='awaiting_external_ai_confirm'"),
                    {"sid": session_id},
                )
        except Exception:
            pass
        await manager.send_line(
            "halt",
            f"[external-ai] Approval timed out after {timeout_s}s — cancelling",
            status="failed", session_id=session_id,
        )

    return decision
```

---

## Change 4 — `tests/test_external_ai_confirmation.py`

```python
"""v2.36.2 — confirmation gate tests. No DB, no network."""
import asyncio
import pytest

from api.agents.external_ai_confirmation import (
    wait_for_confirmation, resolve_confirmation, has_pending,
    _pending,
)


@pytest.fixture(autouse=True)
def _clear_pending():
    """Ensure no state leaks between tests."""
    _pending.clear()
    yield
    _pending.clear()


@pytest.mark.asyncio
async def test_wait_returns_approved_when_resolved():
    async def resolver():
        await asyncio.sleep(0.05)
        assert resolve_confirmation("sess-A", approved=True) is True

    asyncio.create_task(resolver())
    result = await wait_for_confirmation("sess-A", timeout_s=2)
    assert result == "approved"


@pytest.mark.asyncio
async def test_wait_returns_rejected_when_resolved_false():
    async def resolver():
        await asyncio.sleep(0.05)
        resolve_confirmation("sess-B", approved=False)

    asyncio.create_task(resolver())
    result = await wait_for_confirmation("sess-B", timeout_s=2)
    assert result == "rejected"


@pytest.mark.asyncio
async def test_wait_returns_timeout_when_no_resolver():
    result = await wait_for_confirmation("sess-C", timeout_s=1)
    assert result == "timeout"


@pytest.mark.asyncio
async def test_resolve_unknown_session_returns_false():
    """Stale /confirm-external calls shouldn't crash the endpoint."""
    assert resolve_confirmation("never-waited", approved=True) is False


@pytest.mark.asyncio
async def test_has_pending_reflects_state():
    assert has_pending("sess-D") is False
    # Start a wait in the background
    async def waiter():
        await wait_for_confirmation("sess-D", timeout_s=2)
    task = asyncio.create_task(waiter())
    await asyncio.sleep(0.02)  # let the waiter register
    assert has_pending("sess-D") is True
    resolve_confirmation("sess-D", approved=True)
    await task
    # After resolve, decision is no longer 'pending'
    assert has_pending("sess-D") is False
```

---

## Change 5 — `VERSION`

```
2.36.2
```

---

## Verify

```bash
pytest tests/test_external_ai_confirmation.py -v
```

5 tests, all passing, <2s runtime (the timeout test waits 1s).

---

## Commit

```bash
git add -A
git commit -m "feat(agents): v2.36.2 External AI confirmation gate

The requireConfirmation toggle becomes real. When the v2.36.1 router decides
to escalate, the agent loop must now wait for explicit operator approval
via a new modal before any token leaves the building.

New module api/agents/external_ai_confirmation.py — mirrors the plan_action
and preflight-disambiguation wait primitives. wait_for_confirmation blocks on
an asyncio.Event with a timeout; resolve_confirmation fires the event.
Thread-safe per session_id, auto-cleans stale entries after 15 min.

New endpoint POST /api/agent/operations/{operation_id}/confirm-external:
body {session_id, approved}. Resolves the wait, broadcasts resolution, flips
operations.status back to running or cancelled accordingly. Emits
deathstar_external_ai_confirm_outcome_total{outcome=approved|rejected}.

Helper wait_for_external_ai_confirmation in api/routers/agent.py wraps the
low-level primitive with: requireConfirmation setting read, DB status flip
to awaiting_external_ai_confirm, WebSocket broadcast with rule/provider/
model/reason, timeout auto-cancel with final_answer stub, timeout metric.
v2.36.3 calls this helper immediately before the Claude/OpenAI/Grok call.

If requireConfirmation is false, the helper returns 'approved' immediately
without a wait — operator opts into the gate.

5 asyncio regression tests cover approved, rejected, timeout, stale resolve
(no wait), and has_pending lifecycle. No DB, no network."
git push origin main
```

---

## Deploy + smoke

```bash
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```

Cannot end-to-end test yet (no external AI client until v2.36.3), but
confirm the endpoint wiring:

```bash
curl -sS -X POST http://192.168.199.10:8000/api/agent/operations/fake/confirm-external \
  -H 'Content-Type: application/json' \
  -H "Cookie: hp1_auth_cookie=$(cat ~/.hp1_cookie)" \
  -d '{"session_id":"never-waited","approved":true}'
```

Should return `{"status":"error","message":"No pending external-AI confirmation..."}`
— proves the route is live and authenticated.

---

## Scope guard — do NOT touch

- `api/confirmation.py` (plan_action wait primitive) — different module, different
  key space. External AI has its own.
- Agent loop body — the `wait_for_external_ai_confirmation` helper is declared
  but not yet called from the loop. v2.36.3 wires the call site.
- UI — modal lives in v2.36.4. For v2.36.2 the WS event is emitted but the
  GUI will ignore the unknown `type` gracefully.
