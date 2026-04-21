# CC PROMPT — v2.37.1 — Escalations split-brain fix + RECENT `direct:` filter

## What this does

Two post-ship fixes from v2.37.0 verification:

### 1. Escalations split-brain — HISTORY view is broken

Symptom: the amber ESCALATED banner correctly shows unacknowledged
escalations, but the Logs → Escalations sub-tab is always empty, even
immediately after an escalation fires. Ack'ing the banner and checking
Logs doesn't show the row either.

Root cause: two escalation tables exist in parallel, and the agent
runtime writes to one while the Logs UI reads from the other.

| | Banner (works ✓) | Logs → Escalations (empty ✗) |
|---|---|---|
| Frontend fetch | `GET /api/escalations?unacked_only=true` | `GET /api/logs/escalations?limit=50` |
| Backend router | `api/routers/escalations.py` | `api/routers/logs.py` → `api/db/queries.py::get_escalations` |
| Table | `agent_escalations` (psycopg, `acknowledged` / `acknowledged_at`) | `escalations` (SQLAlchemy, `resolved` / `resolved_at` / `timestamp`) |
| Agent runtime writes? | **YES** — `record_escalation()` writes here on every escalation, external-AI failure, halt, etc. | **NO** — `create_escalation()` exists in `api/db/queries.py` but nothing calls it at runtime |

Example trace proving this: session `6d2219b9` (filebeat task, 2026-04-21
12:55). Agent hit budget-cap, escalated to Claude Sonnet, external AI
failed with HTTP 401. Banner correctly shows the unack'd row. Logs →
Escalations view shows 0 rows.

**Fix — Option A (thin):** Rewire `/api/logs/escalations` endpoints to
read from the canonical `agent_escalations` table instead of the dead
SQLAlchemy `escalations` table. Map the column names so the frontend
doesn't change (`acknowledged`→`resolved`, `acknowledged_at`→
`resolved_at`, `created_at`→`timestamp`). Zero changes to runtime write
path — `record_escalation()` keeps writing where it always has.

The dead SQLAlchemy `escalations` table stays in place (ALTER/DROP is
out of scope for this fix — if anything still queries it we don't
want a migration surprise). Future cleanup: v2.38 can drop the
SQLAlchemy model + migration after a deprecation pass.

### 2. RECENT pollutes with `direct:` TOOLBOX fires

v2.37.0 ships a RECENT section showing the N most recent unique tasks.
Tool-dispatched operations are logged with task-text prefix `direct:`
(e.g. `direct:container_networks`). These show up in RECENT but
clicking one fills the task textarea with a string the agent can't
meaningfully replay — it's a tool-ID, not a task.

**Fix:** Add `AND label NOT LIKE 'direct:%'` to the `/api/logs/operations/recent`
endpoint WHERE clause. Direct tool fires will show up in Logs →
Operations (where they belong) but not in the click-to-refill RECENT
panel.

Version bump: 2.37.0 → 2.37.1 (`.x.1` — tightly-scoped fixes, two files,
no new subsystem).

---

## Change 1 — `api/routers/logs.py` — Escalations endpoints rewire

Find the current Escalations section (around line 213):

```python
# ── Escalations ───────────────────────────────────────────────────────────────

@router.get("/escalations")
async def get_escalations(limit: int = Query(50, ge=1, le=500)):
    async with get_engine().connect() as conn:
        rows = await q.get_escalations(conn, limit=limit)
    return {"escalations": rows}


@router.post("/escalations/{esc_id}/resolve")
async def resolve_escalation(esc_id: str):
    async with get_engine().begin() as conn:
        ok = await q.resolve_escalation(conn, esc_id)
    if not ok:
        raise HTTPException(404, f"Escalation '{esc_id}' not found")
    return {"resolved": True, "id": esc_id}
```

Replace with:

```python
# ── Escalations ───────────────────────────────────────────────────────────────
#
# v2.37.1 — reads from agent_escalations (the canonical table the agent
# runtime writes to via api.routers.escalations.record_escalation).
# The SQLAlchemy `escalations` table (api/db/models.py) is unused at
# runtime and left in place for now; v2.38+ will drop it.
#
# Column mapping for UI compatibility:
#   agent_escalations.acknowledged    → response.resolved
#   agent_escalations.acknowledged_at → response.resolved_at
#   agent_escalations.created_at      → response.timestamp
#   agent_escalations.reason          → response.reason
#
# Unlike /api/escalations (banner feed, unacked_only=true by default),
# /api/logs/escalations returns ALL escalations by default — the Logs
# view is history, not active alerts.

@router.get("/escalations")
async def get_escalations(
    limit: int = Query(50, ge=1, le=500),
    include_resolved: bool = Query(True, description=(
        "Include acknowledged escalations (default True — Logs is history)"
    )),
):
    import os
    if "postgres" not in os.environ.get("DATABASE_URL", ""):
        return {"escalations": []}
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        where = "" if include_resolved else "WHERE acknowledged = FALSE"
        cur.execute(
            f"""
            SELECT id, session_id, operation_id, reason, severity,
                   acknowledged, acknowledged_at, acknowledged_by, created_at
            FROM agent_escalations
            {where}
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.close(); conn.close()
        # Map columns to the shape the frontend (LogTable EscView) expects
        mapped = []
        for r in rows:
            ack_at = r.get("acknowledged_at")
            created = r.get("created_at")
            mapped.append({
                "id":            r["id"],
                "session_id":    r.get("session_id"),
                "operation_id":  r.get("operation_id"),
                "reason":        r.get("reason"),
                "severity":      r.get("severity") or "warning",
                "resolved":      bool(r.get("acknowledged", False)),
                "resolved_at":   ack_at.isoformat() if ack_at else None,
                "resolved_by":   r.get("acknowledged_by"),
                "timestamp":     created.isoformat() if created else None,
                # Context is not stored in agent_escalations; frontend
                # tolerates a missing/empty context object.
                "context":       {},
            })
        return {"escalations": mapped}
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(
            "get_escalations (v2.37.1 logs endpoint) failed: %s", e
        )
        return {"escalations": [], "error": str(e)}


@router.post("/escalations/{esc_id}/resolve")
async def resolve_escalation(
    esc_id: str,
    user: str = Depends(get_current_user),
):
    import os
    if "postgres" not in os.environ.get("DATABASE_URL", ""):
        raise HTTPException(503, "Postgres required")
    try:
        from api.connections import _get_conn
        from datetime import datetime, timezone
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE agent_escalations
            SET acknowledged = TRUE,
                acknowledged_at = %s,
                acknowledged_by = %s
            WHERE id = %s
              AND acknowledged = FALSE
            """,
            (datetime.now(timezone.utc), user, esc_id),
        )
        updated = cur.rowcount
        conn.commit(); cur.close(); conn.close()
        if updated == 0:
            # Already resolved or not found — treat not-found as 404
            raise HTTPException(404, f"Escalation '{esc_id}' not found or already resolved")
        return {"resolved": True, "id": esc_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Resolve failed: {e}")
```

Import note: `Depends` and `get_current_user` are already imported at
the top of the file, so the `user: str = Depends(get_current_user)`
parameter on the resolve endpoint just works. No new imports needed.

**Scope guard:** do NOT touch `api/routers/escalations.py` or the
banner — they already work correctly. Do NOT touch
`api/db/queries.py::get_escalations` / `create_escalation` /
`resolve_escalation` — they're now orphaned helpers but removing them
is out of v2.37.1 scope.

---

## Change 2 — `api/routers/logs.py` — RECENT filters out `direct:` fires

Find the `/operations/recent` WHERE clause (around line 90):

```python
                    WHERE label IS NOT NULL
                      AND label <> ''
                      AND owner_user = :user
                      AND (parent_session_id IS NULL OR parent_session_id = '')
                      AND started_at > NOW() - INTERVAL '30 days'
```

Add one line:

```python
                    WHERE label IS NOT NULL
                      AND label <> ''
                      AND label NOT LIKE 'direct:%'
                      AND owner_user = :user
                      AND (parent_session_id IS NULL OR parent_session_id = '')
                      AND started_at > NOW() - INTERVAL '30 days'
```

Also update the docstring — in the "Excludes" bullet list add one item:

```python
    """...
    Excludes:
      - Sub-agent operations (parent_session_id set to a non-empty value)
      - Operations with empty or null task text
      - Direct tool fires (label starts with 'direct:') — these are
        TOOLBOX dispatches that bypass the agent. They'd be re-dispatched
        via the task textarea, which is an agent path they can't replay.
        Visible in Logs → Operations instead.
      - Operations older than 30 days (noise floor)
    """
```

---

## Change 3 — Tests

### 3a — `tests/test_logs_escalations_endpoint.py` (NEW)

```python
"""v2.37.1 — /api/logs/escalations reads from agent_escalations.

Regression test for the split-brain bug where record_escalation wrote
to agent_escalations but the Logs view read from the orphaned SQLAlchemy
`escalations` table.
"""
import os
import uuid
import pytest

pg_only = pytest.mark.skipif(
    "postgres" not in os.environ.get("DATABASE_URL", ""),
    reason="Postgres required for this test",
)


@pg_only
def test_logs_escalations_returns_rows_written_by_record_escalation(test_client):
    """Seed agent_escalations directly (simulating record_escalation),
    then hit the logs endpoint and assert the row appears."""
    from api.routers.escalations import record_escalation, init_escalations
    init_escalations()

    reason = f"v2.37.1 regression test {uuid.uuid4()}"
    eid = record_escalation(
        session_id="test-session-v2371",
        reason=reason,
        operation_id="",
        severity="critical",
    )
    assert eid

    r = test_client.get("/api/logs/escalations?limit=50")
    assert r.status_code == 200
    data = r.json()
    assert "escalations" in data
    matching = [e for e in data["escalations"] if e["id"] == eid]
    assert len(matching) == 1, (
        f"expected exactly one row for id={eid}, got {len(matching)}; "
        f"full response: {data}"
    )
    row = matching[0]
    # Shape match — fields frontend EscView expects
    assert row["reason"] == reason
    assert row["severity"] == "critical"
    assert row["resolved"] is False            # acknowledged=False → resolved=False
    assert row["resolved_at"] is None
    assert row["timestamp"] is not None         # created_at → timestamp
    assert "context" in row                     # empty dict, frontend tolerates


@pg_only
def test_logs_escalations_resolve_marks_agent_escalations_acked(test_client):
    """POST /resolve should set acknowledged=TRUE on the underlying row."""
    from api.routers.escalations import record_escalation, init_escalations
    init_escalations()
    eid = record_escalation(
        session_id="test-resolve-v2371",
        reason=f"resolve-test {uuid.uuid4()}",
        operation_id="",
        severity="warning",
    )

    r = test_client.post(f"/api/logs/escalations/{eid}/resolve")
    assert r.status_code == 200
    assert r.json()["resolved"] is True

    # Second resolve should 404 (already acknowledged)
    r2 = test_client.post(f"/api/logs/escalations/{eid}/resolve")
    assert r2.status_code == 404

    # Verify via list that resolved=True now reflected
    r3 = test_client.get("/api/logs/escalations?limit=50")
    row = next(e for e in r3.json()["escalations"] if e["id"] == eid)
    assert row["resolved"] is True
    assert row["resolved_at"] is not None


@pg_only
def test_logs_escalations_include_resolved_default_true(test_client):
    """Logs view is history — must include resolved by default."""
    from api.routers.escalations import record_escalation, init_escalations
    init_escalations()
    eid = record_escalation(
        session_id="test-history-v2371",
        reason=f"history-test {uuid.uuid4()}",
        operation_id="",
        severity="warning",
    )
    test_client.post(f"/api/logs/escalations/{eid}/resolve")

    # Default (no query param) — resolved row should be present
    r = test_client.get("/api/logs/escalations?limit=50")
    ids = [e["id"] for e in r.json()["escalations"]]
    assert eid in ids, "Logs endpoint must include resolved by default"

    # Explicit include_resolved=false — resolved row should be absent
    r2 = test_client.get("/api/logs/escalations?limit=50&include_resolved=false")
    ids2 = [e["id"] for e in r2.json()["escalations"]]
    assert eid not in ids2
```

### 3b — `tests/test_recent_operations_direct_filter.py` (NEW)

```python
"""v2.37.1 — /api/logs/operations/recent excludes 'direct:' tool fires."""
import os
import uuid
import pytest
from sqlalchemy import text

pg_only = pytest.mark.skipif(
    "postgres" not in os.environ.get("DATABASE_URL", ""),
    reason="Postgres required",
)


@pg_only
@pytest.mark.asyncio
async def test_recent_excludes_direct_tool_fires(postgres_engine, test_client):
    user = "testuser"
    # Seed a normal task and a direct: tool fire for the same user
    async with postgres_engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO operations (id, session_id, label, status, owner_user, started_at) VALUES "
            "(gen_random_uuid(), 's_normal', 'List all Swarm services', 'completed', :u, NOW()),"
            "(gen_random_uuid(), 's_direct', 'direct:container_networks', 'completed', :u, NOW())"
        ), {"u": user})

    r = test_client.get("/api/logs/operations/recent?limit=50")
    assert r.status_code == 200
    tasks = [i["task"] for i in r.json()["items"]]
    assert "List all Swarm services" in tasks
    assert not any(t.startswith("direct:") for t in tasks), (
        f"direct: tool fires must not appear in RECENT, got: {tasks}"
    )
```

### 3c — `tests/test_recent_tasks_wiring.py` (EXISTING — add guard)

Append to the existing file (keeps the v2.37.0 structural guards alive
and adds the v2.37.1 filter assertion):

```python
def test_recent_endpoint_filters_direct_prefix():
    """v2.37.1 — /api/logs/operations/recent must NOT include
    operations whose label starts with 'direct:' (TOOLBOX fires)."""
    p = REPO_ROOT / "api" / "routers" / "logs.py"
    src = p.read_text(encoding="utf-8")
    assert "label NOT LIKE 'direct:%'" in src, (
        "RECENT endpoint must filter out direct:-prefixed operations"
    )


def test_logs_escalations_reads_agent_escalations():
    """v2.37.1 — /api/logs/escalations must hit agent_escalations
    (canonical table), NOT the orphaned SQLAlchemy escalations table."""
    p = REPO_ROOT / "api" / "routers" / "logs.py"
    src = p.read_text(encoding="utf-8")
    # positive: reads from agent_escalations
    assert "FROM agent_escalations" in src, (
        "Logs escalations endpoint must read from agent_escalations"
    )
    # negative: no longer routes to q.get_escalations
    assert "q.get_escalations" not in src, (
        "v2.37.1 removed the q.get_escalations call from logs.py"
    )
    assert "q.resolve_escalation" not in src, (
        "v2.37.1 removed the q.resolve_escalation call from logs.py"
    )
```

---

## Change 4 — `VERSION`

```
2.37.1
```

---

## Verify

```bash
# Code state
grep -n "FROM agent_escalations" api/routers/logs.py             # 2+ (get + resolve)
grep -n "q.get_escalations" api/routers/logs.py                  # 0
grep -n "q.resolve_escalation" api/routers/logs.py               # 0
grep -n "label NOT LIKE 'direct:%'" api/routers/logs.py          # 1

# Tests pass
pytest tests/test_logs_escalations_endpoint.py -v
pytest tests/test_recent_operations_direct_filter.py -v
pytest tests/test_recent_tasks_wiring.py -v       # v2.37.0 + v2.37.1 guards

# v2.37.0 tests still pass (no regression)
pytest tests/test_recent_operations_endpoint.py -v
pytest tests/test_options_context_server_keys.py -v
```

---

## Commit

```bash
git add -A
git commit -m "fix(logs): v2.37.1 escalations split-brain + RECENT direct: filter

Two post-ship fixes from v2.37.0 verification.

ESCALATIONS SPLIT-BRAIN: the Logs → Escalations sub-tab was always
empty because /api/logs/escalations queried an orphaned SQLAlchemy
\`escalations\` table while the agent runtime writes to the
\`agent_escalations\` table via record_escalation(). The amber banner
(different endpoint, same agent_escalations table) worked fine, which
is why the bug went unnoticed until a user ack'd the banner and then
couldn't find the history in Logs. Confirmed on session 6d2219b9
(filebeat task, 2026-04-21 12:55) — external-AI auth failure escalation
visible in banner, absent from Logs.

Fix rewires /api/logs/escalations (GET + POST /resolve) to read/write
\`agent_escalations\` directly via psycopg, mapping column names to the
shape the frontend EscView expects (acknowledged→resolved,
acknowledged_at→resolved_at, created_at→timestamp). Default now
includes resolved escalations (include_resolved=True) since Logs is a
history view, not an active alerts view — distinct semantics from the
banner which correctly defaults to unacked_only.

No changes to api/routers/escalations.py (banner + record_escalation
path) or to api/db/queries.py (orphaned SQLAlchemy helpers — leaving
for v2.38 cleanup pass to avoid migration surprise here).

RECENT \`direct:\` FILTER: v2.37.0 RECENT list included TOOLBOX
tool-dispatch operations (label='direct:container_networks' etc.),
but click-to-refill can't meaningfully replay a tool-ID through
the agent task path. Added AND label NOT LIKE 'direct:%' to the
/api/logs/operations/recent WHERE clause. Direct tool fires remain
visible in Logs → Operations where they belong.

3 new tests in tests/test_logs_escalations_endpoint.py cover
(a) record_escalation write → Logs endpoint read round-trip, (b)
POST /resolve marks agent_escalations.acknowledged=TRUE, (c)
include_resolved default True for history view. 1 new test in
tests/test_recent_operations_direct_filter.py seeds normal + direct:
operations and asserts only the former appears in RECENT. 2 new
structural guards in tests/test_recent_tasks_wiring.py lock in
the FROM agent_escalations + NOT LIKE 'direct:%' assertions.

External AI Calls view visibility (row missing despite ExternalAIError
path firing both record_escalation AND write_external_ai_call on the
same session) is a separate defect under investigation — queued for
v2.37.2 once docker logs confirm whether write_external_ai_call is
silently failing or the table is being read from the wrong pod."
git push origin main
```

---

## Deploy + smoke

```bash
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```

Smoke:

1. Hard-refresh browser. Open Logs → Escalations sub-tab.
2. Should now see the existing amber-banner escalation from session
   `6d2219b9` (external-AI auth failure) in the table.
3. Click Resolve on any unresolved row. It should flip to resolved
   state and persist across page reload.
4. Trigger a fresh escalation (easiest: any task that'll hit the
   budget cap + external-AI route enabled). Watch the row appear
   in both the banner and Logs → Escalations simultaneously.
5. Open the RECENT panel (task input area). The `direct:container_networks`
   row that was polluting RECENT should no longer appear. All other
   entries unchanged.
6. Click a RECENT row — textarea populates with the task text, no
   `direct:` rows to accidentally click.

---

## Scope guard — do NOT touch

- `api/routers/escalations.py` (banner endpoint at /api/escalations) — still correct, do not modify.
- `api/db/models.py` escalations Table / `api/db/queries.py` create_escalation / resolve_escalation — orphaned but leave for v2.38 cleanup pass.
- EscalationBanner.jsx — reads from /api/escalations, working fine.
- LogTable.jsx EscView — reads from /api/logs/escalations, no frontend change needed (we preserve the field shape).
- v2.37.0 code — this is a forward fix layered on top.
- External AI Calls view — diagnosis deferred to v2.37.2.

---

## v2.37.2 preview (do NOT bundle — separate commit)

External AI Calls view was also empty on session `6d2219b9` despite the
auth_error path calling both `record_escalation` (confirmed working via
banner) and `write_external_ai_call`. Possible causes:

- Silent exception in `write_external_ai_call` — check docker logs for
  `write_external_ai_call failed:` warning line
- Init race — `external_ai_calls` table DDL runs lazily on first write;
  a crash mid-init could leave the row unwritten
- The call path in `api/routers/agent.py` skips `write_external_ai_call`
  on auth_error (but not on other outcomes)

v2.37.2 will either log-upgrade `write_external_ai_call` to INFO on
success (so we can confirm the call fires) or patch the call-site in
`agent.py` if auth_error skips the write. Needs docker log sample first.

Paste for Kent to run once v2.37.1 is deployed:

```bash
docker logs hp1_ai_agent --since 1h 2>&1 | grep -iE 'external_ai|escalation' | tail -40
```
