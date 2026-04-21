# CC PROMPT — v2.37.2 — Trace picker shows session_id + agent_type populated

## What this does

Two tightly-scoped post-ship fixes from v2.37.1 verification.

### 1. Trace picker shows session_id (not operation.id)

Symptom: Kent runs a task, gets `session_id=9a23e276` in the task
banner and URLs. Opens Logs → Trace → operation picker, sees the
running operation show as `e1b0fd59 · ? · running`. He can't correlate
`9a23e276` to `e1b0fd59` at a glance and thinks the trace viewer is
showing a different operation than his current task.

Root cause: `gui/src/components/TraceView.jsx::OperationPicker` renders
`{(o.id || '').slice(0, 8)}` — the operation's primary-key UUID (first
8 chars). DEATHSTAR's schema has **two distinct identifiers** on the
`operations` table: `id` (UUID primary key, renders as `e1b0fd59-...`)
and `session_id` (TEXT, renders as `9a23e276-...`). They are 1:1 per
run but **different UUIDs**. Every other UI surface (task banner,
escalation banner, WebSocket event keys, Session Output view, deep
links) uses `session_id`; only the Trace picker uses `id`.

Fix: display `session_id` first 8 chars as the primary identifier in
the dropdown. Keep the `<option value={o.id}>` because the trace API
endpoint is `/api/logs/operations/{op_id}/trace` keyed on operation
ID — don't touch the backend contract. Filter still matches on both
`session_id` and `id` so either UUID form types can find the row.

### 2. `agent_type` populated in operations list (no more `?`)

Symptom: every row in the Trace picker and Operations view shows
`· ? ·` in the agent-type slot. Happens because `operations` table
has no `agent_type` column; the v2.37.0 `/api/logs/operations/recent`
endpoint COALESCEs it from `agent_llm_traces.agent_type` of step 0,
but the main `/api/logs/operations` list endpoint doesn't — it just
SELECTs `operations.*`.

Fix: add the same `agent_llm_traces`-subquery COALESCE pattern to
`api/db/queries.py::get_operations` so every row in the list has
`agent_type` populated. Matches the v2.37.0 /recent endpoint pattern
verbatim so maintenance is uniform.

Version bump: 2.37.1 → 2.37.2 (`.x.2` — minor display fix + query
enrichment, two files).

---

## Change 1 — `gui/src/components/TraceView.jsx` OperationPicker

Find lines 70-78:

```jsx
      <select
        className="text-xs bg-slate-800 border border-slate-700 rounded px-2 py-1 text-slate-200 flex-1"
        value={selected || ''}
        onChange={(e) => onChange(e.target.value || null)}
      >
        <option value="">— choose operation —</option>
        {visible.map((o) => (
          <option key={o.id} value={o.id}>
            {(o.id || '').slice(0, 8)} · {o.agent_type || '?'} · {o.status || '?'} ·{' '}
            {(o.task || '').slice(0, 60)}
          </option>
        ))}
      </select>
```

Replace with:

```jsx
      <select
        className="text-xs bg-slate-800 border border-slate-700 rounded px-2 py-1 text-slate-200 flex-1"
        value={selected || ''}
        onChange={(e) => onChange(e.target.value || null)}
      >
        <option value="">— choose operation —</option>
        {visible.map((o) => {
          // v2.37.2: primary identifier is session_id (what every other UI
          // surface — task banner, WS events, Session Output — uses). The
          // <option value> stays as operation.id because /api/logs/operations/
          // {op_id}/trace is keyed on operation.id.
          const sid = (o.session_id || o.id || '').slice(0, 8)
          return (
            <option key={o.id} value={o.id}>
              {sid} · {o.agent_type || '?'} · {o.status || '?'} ·{' '}
              {(o.label || o.task || '').slice(0, 60)}
            </option>
          )
        })}
      </select>
```

Also update the filter above it so filtering still matches both UUID
forms. Find lines 38-48:

```jsx
  const visible = useMemo(() => {
    const f = filter.trim().toLowerCase()
    if (!f) return opsList.slice(0, 50)
    return opsList
      .filter((o) =>
        [o.id, o.task, o.agent_type, o.status]
          .filter(Boolean)
          .join(' ')
          .toLowerCase()
          .includes(f),
      )
      .slice(0, 50)
  }, [opsList, filter])
```

Replace with:

```jsx
  const visible = useMemo(() => {
    const f = filter.trim().toLowerCase()
    if (!f) return opsList.slice(0, 50)
    return opsList
      .filter((o) =>
        // v2.37.2: also match on session_id so operators can paste either
        // UUID form (session from banner OR operation.id from URL) and find
        // the row. Also include `label` as an alias for task text.
        [o.id, o.session_id, o.task, o.label, o.agent_type, o.status]
          .filter(Boolean)
          .join(' ')
          .toLowerCase()
          .includes(f),
      )
      .slice(0, 50)
  }, [opsList, filter])
```

Update the input placeholder to match:

```jsx
      <input
        type="text"
        placeholder="filter by session / operation id / task / status"
        ...
```

**Scope guard — do NOT change:**
- Any `value={o.id}` on `<option>` elements (trace endpoint depends on
  operation.id)
- The `onChange` handler signature
- Any logic downstream of `selected` (still an operation.id)
- Other views' session/operation handling

---

## Change 2 — `api/db/queries.py::get_operations` populates agent_type

Find the function (currently around line 97):

```python
async def get_operations(
    conn: AsyncConnection,
    limit: int = 50,
    offset: int = 0,
    status_filter: str = "all",
) -> list[dict]:
    q = select(
        operations,
        func.count(tool_calls.c.id).label("tool_call_count")
    ).outerjoin(tool_calls, tool_calls.c.operation_id == operations.c.id)\
     .group_by(operations.c.id)\
     .order_by(desc(operations.c.started_at))\
     .limit(limit).offset(offset)
    if status_filter != "all":
        q = q.where(operations.c.status == status_filter)
    result = await conn.execute(q)
    return _rows(result)
```

The SQLAlchemy approach here (`select(operations)`) is succinct but
adding a COALESCE subquery against a table that isn't in `api/db/models.py`
(agent_llm_traces is managed by a separate module) is awkward. Drop to
raw SQL matching the pattern used by `/api/logs/operations/recent`:

```python
async def get_operations(
    conn: AsyncConnection,
    limit: int = 50,
    offset: int = 0,
    status_filter: str = "all",
) -> list[dict]:
    """List operations with tool-call count + agent_type.

    v2.37.2: agent_type is sourced from the first agent_llm_traces step
    for each operation (same pattern as /api/logs/operations/recent),
    since agent_type is not a column on the operations table. COALESCE
    falls back to 'observe' so no row ever shows `?`.
    """
    where = ""
    params: dict = {"lim": limit, "off": offset}
    if status_filter != "all":
        where = "WHERE o.status = :status"
        params["status"] = status_filter

    sql = f"""
        SELECT
            o.id,
            o.session_id,
            o.label,
            o.started_at,
            o.completed_at,
            o.status,
            o.triggered_by,
            o.model_used,
            o.total_duration_ms,
            o.feedback,
            o.feedback_at,
            o.final_answer,
            o.owner_user,
            COALESCE((
                SELECT t.agent_type
                FROM agent_llm_traces t
                WHERE t.operation_id = o.id::text
                  AND t.agent_type IS NOT NULL
                ORDER BY t.step_index ASC
                LIMIT 1
            ), 'observe')                                AS agent_type,
            (
                SELECT COUNT(*)
                FROM tool_calls tc
                WHERE tc.operation_id = o.id
            )                                            AS tool_call_count
        FROM operations o
        {where}
        ORDER BY o.started_at DESC
        LIMIT :lim OFFSET :off
    """

    result = await conn.execute(text(sql), params)
    rows = []
    for r in result:
        # Mirror _row_to_dict's datetime / json handling inline since
        # we're not using row._mapping pattern here
        rows.append({
            "id": str(r[0]) if r[0] else None,
            "session_id": r[1],
            "label": r[2],
            "task": r[2],  # alias — TraceView / older code may read o.task
            "started_at": r[3].isoformat() if r[3] else None,
            "completed_at": r[4].isoformat() if r[4] else None,
            "status": r[5],
            "triggered_by": r[6],
            "model_used": r[7],
            "total_duration_ms": r[8],
            "feedback": r[9],
            "feedback_at": r[10],
            "final_answer": r[11],
            "owner_user": r[12],
            "agent_type": r[13] or "observe",
            "tool_call_count": int(r[14]) if r[14] is not None else 0,
        })
    return rows
```

**Note on the `task` alias:** TraceView reads `o.task` at line 78 post-
v2.37.2 (`{(o.label || o.task || '').slice(0, 60)}`). Historical frontend
code also references `o.task`. Exposing both `label` (real column) and
`task` (alias) keeps every existing consumer working. Safe extra field,
not a schema change.

**Imports:** `text` is already imported at top of `api/db/queries.py`
(line 10: `from sqlalchemy import select, func, update, text, desc, and_`).
No new imports needed.

**Scope guard — do NOT change:**
- `create_operation`, `complete_operation`, `get_operation`,
  `get_operation_by_session`, `set_operation_feedback`,
  `set_operation_final_answer` — all other functions in this section
  are untouched.
- `/api/logs/operations/recent` endpoint — already populates agent_type
  correctly via the pattern we're borrowing from.
- `operations` schema or any migration files.

---

## Change 3 — Tests

### 3a — `tests/test_operations_list_agent_type.py` (NEW)

```python
"""v2.37.2 — /api/logs/operations populates agent_type from traces."""
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
async def test_operations_list_returns_agent_type_from_trace(postgres_engine, test_client):
    """Seed an operation + a trace step; list endpoint should return the
    trace's agent_type, not the fallback default or '?'."""
    op_id = str(uuid.uuid4())
    async with postgres_engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO operations (id, session_id, label, status, owner_user, started_at) VALUES "
            "(:id, :sid, 'v2.37.2 agent_type test', 'completed', 'testuser', NOW())"
        ), {"id": op_id, "sid": f"sid-{op_id[:8]}"})
        await conn.execute(text(
            "INSERT INTO agent_llm_traces "
            "(operation_id, step_index, agent_type, model, messages_delta, response_raw) "
            "VALUES (:op, 0, 'investigate', 'qwen', '[]', '{}')"
        ), {"op": op_id})

    r = test_client.get("/api/logs/operations?limit=50")
    assert r.status_code == 200
    row = next(o for o in r.json()["operations"] if o["id"] == op_id)
    assert row["agent_type"] == "investigate"
    assert row["session_id"] == f"sid-{op_id[:8]}"


@pg_only
@pytest.mark.asyncio
async def test_operations_list_agent_type_fallback_when_no_traces(postgres_engine, test_client):
    """Operation with no trace rows falls back to 'observe', not null or '?'."""
    op_id = str(uuid.uuid4())
    async with postgres_engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO operations (id, session_id, label, status, owner_user, started_at) VALUES "
            "(:id, 'sid-notrace', 'no-trace operation', 'running', 'testuser', NOW())"
        ), {"id": op_id})

    r = test_client.get("/api/logs/operations?limit=100")
    row = next(o for o in r.json()["operations"] if o["id"] == op_id)
    assert row["agent_type"] == "observe"
    assert row["status"] == "running"


@pg_only
@pytest.mark.asyncio
async def test_operations_list_picks_first_step_agent_type(postgres_engine, test_client):
    """If multiple trace steps exist, agent_type comes from step_index=0
    (matches /recent endpoint behaviour)."""
    op_id = str(uuid.uuid4())
    async with postgres_engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO operations (id, session_id, label, status, owner_user, started_at) VALUES "
            "(:id, 'sid-multistep', 'multi-step op', 'completed', 'testuser', NOW())"
        ), {"id": op_id})
        # Steps 0 and 1 — step 0 is 'execute', step 1 is 'investigate'
        await conn.execute(text(
            "INSERT INTO agent_llm_traces "
            "(operation_id, step_index, agent_type, model, messages_delta, response_raw) "
            "VALUES "
            "(:op, 0, 'execute', 'qwen', '[]', '{}'),"
            "(:op, 1, 'investigate', 'qwen', '[]', '{}')"
        ), {"op": op_id})

    r = test_client.get("/api/logs/operations?limit=100")
    row = next(o for o in r.json()["operations"] if o["id"] == op_id)
    assert row["agent_type"] == "execute"  # step 0 wins


@pg_only
@pytest.mark.asyncio
async def test_operations_list_includes_session_id_field(postgres_engine, test_client):
    """Regression: session_id must be present in the list response
    so TraceView can render it."""
    op_id = str(uuid.uuid4())
    sid = f"sid-{op_id[:8]}"
    async with postgres_engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO operations (id, session_id, label, status, owner_user, started_at) VALUES "
            "(:id, :sid, 'session_id presence test', 'completed', 'testuser', NOW())"
        ), {"id": op_id, "sid": sid})

    r = test_client.get("/api/logs/operations?limit=100")
    row = next(o for o in r.json()["operations"] if o["id"] == op_id)
    assert row.get("session_id") == sid
    # Also: task alias exists for backward compat
    assert row.get("task") == row.get("label") == "session_id presence test"
```

### 3b — `tests/test_trace_picker_display.py` (NEW structural guard)

```python
"""v2.37.2 — TraceView picker must display session_id, not operation.id.

Structural guard so a future refactor can't silently re-break the
correlation between the Trace picker and the rest of the UI.
"""
import pathlib

REPO_ROOT = pathlib.Path(__file__).parent.parent


def test_trace_view_picker_renders_session_id_not_operation_id():
    p = REPO_ROOT / "gui" / "src" / "components" / "TraceView.jsx"
    src = p.read_text(encoding="utf-8")
    # The v2.37.2 fix: picker reads o.session_id for the display label
    assert "o.session_id" in src, (
        "OperationPicker must read o.session_id for display (v2.37.2)"
    )
    # And the legacy display pattern `{(o.id || '').slice(0, 8)} ·`
    # must NOT be the dropdown's primary identifier anymore. This regex
    # looks for a direct op-id-first-8 display before a ` · `, which
    # was the v2.36.x-v2.37.1 shape.
    import re
    assert not re.search(
        r"\(o\.id\s*\|\|\s*''\)\.slice\(0,\s*8\)\s*}\s*·",
        src,
    ), "o.id.slice(0, 8) as primary display was replaced by o.session_id in v2.37.2"


def test_trace_view_filter_matches_both_ids():
    """Filter must accept both session_id and operation.id as input."""
    p = REPO_ROOT / "gui" / "src" / "components" / "TraceView.jsx"
    src = p.read_text(encoding="utf-8")
    # visible filter combines both
    assert "o.session_id" in src
    assert "o.id" in src


def test_trace_view_option_value_is_operation_id():
    """<option value={o.id}> must stay — the trace API endpoint uses
    operation.id, not session_id."""
    p = REPO_ROOT / "gui" / "src" / "components" / "TraceView.jsx"
    src = p.read_text(encoding="utf-8")
    assert "value={o.id}" in src, (
        "<option value=o.id> must remain — trace endpoint is keyed on operation.id"
    )


def test_operations_list_queries_joins_agent_llm_traces():
    """Regression: api/db/queries.py::get_operations must source
    agent_type from agent_llm_traces (matches /recent endpoint)."""
    p = REPO_ROOT / "api" / "db" / "queries.py"
    src = p.read_text(encoding="utf-8")
    # Look for the COALESCE subquery pattern against agent_llm_traces
    assert "FROM agent_llm_traces" in src, (
        "get_operations must join/subquery agent_llm_traces for agent_type"
    )
    assert "ORDER BY t.step_index ASC" in src, (
        "get_operations must pick step 0 (earliest step_index) for agent_type"
    )
```

---

## Change 4 — `VERSION`

```
2.37.2
```

---

## Verify

```bash
# Code state
grep -n "o.session_id" gui/src/components/TraceView.jsx                  # >=2 (filter + display)
grep -cn "FROM agent_llm_traces" api/db/queries.py                       # >=1
grep -n "'agent_type'" api/db/queries.py                                 # >=1

# Tests pass
pytest tests/test_operations_list_agent_type.py -v
pytest tests/test_trace_picker_display.py -v

# v2.37.0/1 tests still pass (no regression)
pytest tests/test_recent_operations_endpoint.py -v
pytest tests/test_recent_tasks_wiring.py -v
pytest tests/test_logs_escalations_endpoint.py -v
pytest tests/test_recent_operations_direct_filter.py -v

# CI guard from v2.36.6
pytest tests/test_options_context_server_keys.py -v
```

---

## Commit

```bash
git add -A
git commit -m "fix(ui): v2.37.2 Trace picker shows session_id + agent_type populated

Two tight post-ship fixes from v2.37.1 verification.

TRACE PICKER ID MISMATCH: TraceView.jsx OperationPicker displayed
{(o.id || '').slice(0, 8)} — the operations table primary-key UUID —
while every other UI surface (task banner, escalation banner, WS event
keys, Session Output deep-links) uses session_id, a distinct UUID also
stored on the operations row. Kent runs a task with session_id=9a23e276,
opens Trace picker, sees the operation as e1b0fd59 · ? · running and
can't correlate. Fix swaps the dropdown label to show session_id first
8 chars. <option value={o.id}> stays because the trace API endpoint at
/api/logs/operations/{op_id}/trace is keyed on operation.id — backend
contract untouched. Filter input now matches both session_id and
operation.id so either UUID form pasted from clipboard finds the row.
Input placeholder updated to make this explicit.

AGENT_TYPE POPULATED IN LIST: every operation row showed '· ? ·' in
the agent-type slot because operations table has no agent_type column
(lives on agent_llm_traces, first step), and /api/logs/operations list
endpoint SELECTed operations.* without the subquery. Fix drops
get_operations() in api/db/queries.py from the SQLAlchemy select shape
to raw SQL matching the exact pattern used by v2.37.0's /recent
endpoint: COALESCE subquery against agent_llm_traces.agent_type
filtered on operation_id and agent_type IS NOT NULL, ORDER BY
step_index ASC LIMIT 1, fallback 'observe'. Also exposes a 'task' alias
for 'label' so historical frontend consumers that read o.task keep
working.

4 endpoint tests in tests/test_operations_list_agent_type.py cover
trace-populates-agent_type, no-trace-falls-back-to-observe, multi-step
picks step 0, and session_id-present-in-response. 4 structural guards
in tests/test_trace_picker_display.py lock in the v2.37.2 display
convention + the backend's agent_llm_traces subquery pattern.

No schema changes, no new Settings keys. Session ID (the operator-
facing identifier) now matches between the Trace picker and every
other UI surface."
git push origin main
```

---

## Deploy + smoke

```bash
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```

Smoke:

1. Hard-refresh the browser. Trigger a task (any observe template
   will do — 'List all Swarm services' is fast).
2. Note the session_id visible in the task banner / running badge
   (8-char prefix, e.g. `9a23e276`).
3. Open Logs → Trace. The dropdown should now show `9a23e276 · observe
   · running · List all Swarm services…` — matching the banner ID.
4. Wait for task to complete. Dropdown row should update to `9a23e276
   · observe · completed · …`. No more `· ? ·` in the agent-type slot.
5. Type `9a23e276` (session prefix) into the filter — should find the
   row. Type the operation.id first 8 chars (still visible in URL
   when a trace is selected) — should also find the row.
6. Select the operation. Trace detail renders normally (no backend
   change, endpoint still keyed on operation.id).

---

## Scope guard — do NOT touch

- Trace API endpoint `/api/logs/operations/{op_id}/trace` — still
  keyed on operation.id (correct).
- `api/logger.py`, `api/routers/agent.py` session/operation
  management — unchanged.
- Other views that correctly display session_id (task banner,
  EscalationBanner, Session Output, WebSocket output) — unchanged.
- `/api/logs/operations/recent` — already does the COALESCE correctly
  (v2.37.0). This prompt borrows its pattern.
- Everything escalation-related from v2.37.1 — unchanged.

---

## Post-deploy followups (not v2.37.2)

- External AI Calls view visibility defect — still deferred to v2.37.3
  pending docker logs sample from Kent
- Orphan `running` operations: if the DB has old operations stuck in
  status=running from interrupted sessions, they'll still show up in
  the list. Out of v2.37.2 scope but a good v2.38 candidate: on app
  startup, mark any operation with status=running + started_at older
  than X hours as status=orphaned or status=failed.
