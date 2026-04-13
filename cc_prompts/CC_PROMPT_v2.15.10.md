# CC PROMPT — v2.15.10 — Escalation visibility: persistent banner + acknowledge

## What this does

Agent escalations currently only appear in the output panel text stream.
If you're not watching the agent run, you miss them entirely. There's no
dashboard notification, no toast, nothing on the main view.

This adds a persistent amber banner at the top of the dashboard that:
- Appears when any agent session escalates
- Shows the escalation reason
- Stays until explicitly acknowledged
- Logs the dismissal as an event

Version bump: 2.15.9 → 2.15.10 (UI feature, x.x.1)

---

## Change 1 — Backend: POST /api/escalations endpoint

Create `api/routers/escalations.py`:

```python
"""Escalation tracking — store and serve unacknowledged agent escalations."""
import json
import logging
import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from api.auth import get_current_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/escalations", tags=["escalations"])

_DDL = """
CREATE TABLE IF NOT EXISTS agent_escalations (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    operation_id    TEXT,
    reason          TEXT NOT NULL,
    severity        TEXT DEFAULT 'warning',
    acknowledged    BOOLEAN DEFAULT FALSE,
    acknowledged_at TIMESTAMPTZ,
    acknowledged_by TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_escalations_session ON agent_escalations(session_id);
CREATE INDEX IF NOT EXISTS idx_escalations_acked   ON agent_escalations(acknowledged);
"""

_initialized = False

def init_escalations():
    global _initialized
    if _initialized: return
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        for stmt in _DDL.strip().split(";"):
            s = stmt.strip()
            if s: cur.execute(s)
        cur.close(); conn.close()
        _initialized = True
        log.info("agent_escalations table ready")
    except Exception as e:
        log.warning("agent_escalations init failed: %s", e)


def record_escalation(session_id: str, reason: str, operation_id: str = "",
                      severity: str = "warning") -> str:
    """Store an escalation. Returns the escalation ID."""
    eid = str(uuid.uuid4())
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO agent_escalations
               (id, session_id, operation_id, reason, severity)
               VALUES (%s, %s, %s, %s, %s)""",
            (eid, session_id, operation_id or None, reason[:1000], severity)
        )
        conn.commit(); cur.close(); conn.close()
    except Exception as e:
        log.warning("record_escalation failed: %s", e)
    return eid


@router.get("")
async def list_escalations(
    unacked_only: bool = True,
    limit: int = 20,
    _: str = Depends(get_current_user)
):
    """List escalations, unacknowledged first."""
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        where = "WHERE acknowledged = FALSE" if unacked_only else ""
        cur.execute(f"""
            SELECT id, session_id, operation_id, reason, severity,
                   acknowledged, acknowledged_at, acknowledged_by, created_at
            FROM agent_escalations
            {where}
            ORDER BY created_at DESC
            LIMIT %s
        """, (limit,))
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.close(); conn.close()
        for r in rows:
            for k in ('acknowledged_at', 'created_at'):
                if r.get(k):
                    try: r[k] = r[k].isoformat()
                    except: pass
        return {"escalations": rows, "count": len(rows)}
    except Exception as e:
        return {"escalations": [], "count": 0, "error": str(e)}


@router.post("/{escalation_id}/acknowledge")
async def acknowledge_escalation(
    escalation_id: str,
    user: str = Depends(get_current_user)
):
    """Acknowledge an escalation — clears it from the banner."""
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            UPDATE agent_escalations
            SET acknowledged = TRUE,
                acknowledged_at = NOW(),
                acknowledged_by = %s
            WHERE id = %s
        """, (user, escalation_id))
        updated = cur.rowcount
        conn.commit(); cur.close(); conn.close()
        return {"status": "ok" if updated else "error",
                "message": "Acknowledged" if updated else "Not found"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/acknowledge-all")
async def acknowledge_all_escalations(user: str = Depends(get_current_user)):
    """Acknowledge all outstanding escalations."""
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            UPDATE agent_escalations
            SET acknowledged = TRUE, acknowledged_at = NOW(), acknowledged_by = %s
            WHERE acknowledged = FALSE
        """, (user,))
        n = cur.rowcount
        conn.commit(); cur.close(); conn.close()
        return {"status": "ok", "acknowledged": n}
    except Exception as e:
        return {"status": "error", "message": str(e)}
```

Register in `api/main.py`:
```python
from api.routers.escalations import router as escalations_router, init_escalations
app.include_router(escalations_router)
# In startup:
init_escalations()
```

---

## Change 2 — Agent loop: call record_escalation when agent escalates

In `api/routers/agent.py`, find the section where `escalate` tool is called
and the loop halts. After the escalate tool result is stored, record it:

```python
# In the tool execution block, after invoking "escalate":
if fn_name == "escalate" and result_status != "blocked":
    # Record in persistent escalation table for dashboard visibility
    try:
        from api.routers.escalations import record_escalation
        esc_reason = result_msg or fn_args.get("reason", "Agent escalated")
        record_escalation(
            session_id=session_id,
            reason=esc_reason[:500],
            operation_id=operation_id,
            severity="warning",
        )
    except Exception as _re:
        log.debug("record_escalation failed: %s", _re)
```

Also record when the agent halts due to a tool returning `degraded`/`failed`:
```python
# In the HALT block (where final_status = "escalated"):
try:
    from api.routers.escalations import record_escalation
    record_escalation(
        session_id=session_id,
        reason=f"{fn_name} returned {result_status}: {result_msg[:200]}",
        operation_id=operation_id,
        severity="critical" if result_status == "failed" else "warning",
    )
except Exception: pass
```

---

## Change 3 — WebSocket: broadcast escalation_recorded event

After `record_escalation()` is called, broadcast a WebSocket event so the
frontend can update immediately without waiting for a poll:

```python
await manager.broadcast({
    "type": "escalation_recorded",
    "session_id": session_id,
    "reason": esc_reason[:200],
    "severity": "warning",
    "timestamp": datetime.now(timezone.utc).isoformat(),
})
```

---

## Change 4 — Frontend: EscalationBanner component

Create `gui/src/components/EscalationBanner.jsx`:

```jsx
/**
 * EscalationBanner — persistent amber banner shown when agent escalates.
 * Sits at the top of the dashboard content area, below the drill bar.
 * Stays until explicitly acknowledged.
 */
import { useState, useEffect, useCallback } from 'react'
import { authHeaders } from '../api'

const BASE = import.meta.env.VITE_API_BASE ?? ''

export default function EscalationBanner() {
  const [escalations, setEscalations] = useState([])

  const fetchEscalations = useCallback(() => {
    fetch(`${BASE}/api/escalations?unacked_only=true&limit=5`, {
      headers: { ...authHeaders() }
    })
      .then(r => r.ok ? r.json() : { escalations: [] })
      .then(d => setEscalations(d.escalations || []))
      .catch(() => {})
  }, [])

  // Poll every 15 seconds + listen for WebSocket event
  useEffect(() => {
    fetchEscalations()
    const id = setInterval(fetchEscalations, 15000)

    // Also update immediately on WebSocket escalation_recorded event
    const handler = (e) => {
      if (e.detail?.type === 'escalation_recorded') fetchEscalations()
    }
    window.addEventListener('ds:ws-message', handler)

    return () => {
      clearInterval(id)
      window.removeEventListener('ds:ws-message', handler)
    }
  }, [fetchEscalations])

  const acknowledge = async (id) => {
    await fetch(`${BASE}/api/escalations/${id}/acknowledge`, {
      method: 'POST',
      headers: { ...authHeaders() }
    })
    setEscalations(prev => prev.filter(e => e.id !== id))
  }

  const acknowledgeAll = async () => {
    await fetch(`${BASE}/api/escalations/acknowledge-all`, {
      method: 'POST',
      headers: { ...authHeaders() }
    })
    setEscalations([])
  }

  if (escalations.length === 0) return null

  const latest = escalations[0]
  const extra  = escalations.length - 1

  return (
    <div style={{
      background: 'rgba(204,136,0,0.12)',
      borderBottom: '1px solid var(--amber)',
      padding: '8px 16px',
      display: 'flex',
      alignItems: 'center',
      gap: 10,
      flexShrink: 0,
    }}>
      {/* Pulsing dot */}
      <span style={{
        width: 8, height: 8, borderRadius: '50%',
        background: 'var(--amber)',
        boxShadow: '0 0 6px var(--amber)',
        animation: 'pulse 1.5s ease-in-out infinite',
        flexShrink: 0,
      }} />

      {/* Icon + label */}
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9,
                     color: 'var(--amber)', letterSpacing: 1, flexShrink: 0 }}>
        ⚑ ESCALATED
      </span>

      {/* Reason text */}
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10,
                     color: 'var(--text-2)', flex: 1, minWidth: 0 }}>
        {latest.reason?.slice(0, 160)}
        {extra > 0 && (
          <span style={{ color: 'var(--amber)', marginLeft: 6 }}>
            +{extra} more
          </span>
        )}
      </span>

      {/* Session link */}
      {latest.session_id && (
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 8,
                       color: 'var(--text-3)', flexShrink: 0 }}>
          session {latest.session_id.slice(0, 8)}
        </span>
      )}

      {/* Acknowledge buttons */}
      <button
        onClick={() => acknowledge(latest.id)}
        style={{
          padding: '2px 8px', fontSize: 9, fontFamily: 'var(--font-mono)',
          background: 'var(--amber-dim)', color: 'var(--amber)',
          border: '1px solid var(--amber)', borderRadius: 2,
          cursor: 'pointer', flexShrink: 0,
        }}
      >
        ACK
      </button>
      {escalations.length > 1 && (
        <button
          onClick={acknowledgeAll}
          style={{
            padding: '2px 8px', fontSize: 9, fontFamily: 'var(--font-mono)',
            background: 'transparent', color: 'var(--text-3)',
            border: '1px solid var(--border)', borderRadius: 2,
            cursor: 'pointer', flexShrink: 0,
          }}
        >
          ACK ALL ({escalations.length})
        </button>
      )}
    </div>
  )
}
```

---

## Change 5 — App.jsx: mount EscalationBanner in DashboardView

In `DashboardView`, inside the main flex container, add the banner
between the DrillDownBar and the scrollable content:

```jsx
import EscalationBanner from './components/EscalationBanner'

// In DashboardView render, after <DrillDownBar ... /> and before <div className="flex-1 overflow-auto ...">:
<EscalationBanner />
```

---

## Change 6 — App.jsx: forward WebSocket escalation events

In the WebSocket message handler (wherever `ws.onmessage` or the WS context
processes incoming messages), forward `escalation_recorded` events to the
window so EscalationBanner can react immediately:

```js
// In the WS message handler:
if (data.type === 'escalation_recorded') {
  window.dispatchEvent(new CustomEvent('ds:ws-message', { detail: data }))
}
```

---

## Version bump

Update VERSION: `2.15.9` → `2.15.10`

---

## Commit

```bash
git add -A
git commit -m "feat(ui): v2.15.10 escalation visibility — persistent banner + acknowledge

- agent_escalations table: stores all escalations with session/operation ID + reason
- record_escalation() called when agent escalates or halts on degraded tool result
- GET /api/escalations: list unacknowledged escalations
- POST /api/escalations/{id}/acknowledge: clear one
- POST /api/escalations/acknowledge-all: clear all
- EscalationBanner: persistent amber banner in dashboard, pulsing dot, reason text
- ACK button dismisses; ACK ALL clears all outstanding
- WebSocket: escalation_recorded event triggers immediate banner update (no wait for poll)
- Banner sits between DrillDownBar and dashboard content, zero height when no escalations"
git push origin main
```
