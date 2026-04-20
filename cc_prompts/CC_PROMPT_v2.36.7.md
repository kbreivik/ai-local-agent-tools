# CC PROMPT — v2.36.7 — Operations view: populate model column

## What this does

The Operations view in Logs has been showing an empty "Model" column for
every agent-started run. Confirmed today with two back-to-back ops (v2.36.5
verification runs) — both `operations.model_used` values persisted as empty
strings despite LM Studio returning `qwen/qwen3.6-35b-a3b` in the live feed.

Two layers to fix:

1. **Insert-time seed.** `api/routers/agent.py::run_agent` and
   `run_subtask` currently call the 3-arg legacy alias
   `logger_mod.log_operation(session_id, task, owner_user=user)`, which
   hardcodes `model_used=""` via `log_operation_start`. We wire them to
   pass `_lm_model()` as a seed so every newly-created operation has a
   reasonable value from insert onwards.

2. **Complete-time backfill from trace.** v2.36.0's `_extract_response_model`
   gets the REAL model string from the API response into the
   `agent_llm_traces.model` column for every LLM step (local model name for
   local steps, `claude-sonnet-4-6` / `gpt-4o` / etc. for v2.36.3 external
   AI escalations via the `step_index=99999` tag row). We extend
   `log_operation_complete` to backfill `operations.model_used` from the
   highest-step_index trace row on terminal write. If the run escalated to
   external AI, this picks up the external model; for local-only runs it
   picks up the LM Studio-reported name (which may differ from `_lm_model()`
   if the env-var label is stale).

Version bump: 2.36.6 → 2.36.7 (`.x.N` — fix).

---

## Why

Evidence from 2026-04-20:

1. Kent's screenshot of Logs → Operations shows two consecutive rows:
   - 20:55:35 — "Check UniFi network device status" → `completed`, Model column **blank**
   - 20:58:21 — "Check UniFi list all clients …" → `capped`, Model column **"—"**

   Two different UI renderings of an empty/null field — likely `""` vs
   `None`, confirming the field is empty at the DB level.

2. Live WebSocket feed for both ops shows `Model: qwen/qwen3.6-35b-a3b` in
   the step broadcasts — the model info IS in flight, just not landing in
   `operations.model_used`.

3. `api/routers/agent.py` bottom — both the `run_agent` endpoint
   (`/api/agent/run`) and `run_subtask` (`/api/agent/subtask`) use the
   legacy 3-arg alias:

   ```python
   operation_id = await logger_mod.log_operation(session_id, req.task, owner_user=user)
   ```

   The alias in `api/logger.py`:

   ```python
   async def log_operation(session_id: str, label: str, owner_user: str = "admin") -> str:
       return await log_operation_start(session_id, label, owner_user=owner_user)
   ```

   silently drops the `model_used` arg — it never gets to
   `log_operation_start(..., model_used="")` which passes `""` into
   `q.create_operation`. `operations.model_used` is written as `""` at
   insert and never updated.

4. `log_operation_complete` (called in the `_stream_agent` finally block)
   only updates `status` + `total_duration_ms` — never touches
   `model_used`.

5. v2.36.0's provenance fix landed `_extract_response_model` at all four
   `log_llm_step` call sites → `agent_llm_traces.model` gets the real
   API-reported model for every step (local + external). The Operations
   view's data source is `operations.model_used` though, not a joined
   query against `agent_llm_traces`. v2.36.0 didn't wire the bridge
   between the two.

Fixing the insert seed alone gives the Operations view a reasonable
default for every run. Adding the complete-time backfill from
`agent_llm_traces` closes the v2.36.0 loop — external-AI runs will show
`claude-sonnet-4-6` or similar, not the local model name seed.

---

## Change 1 — `api/logger.py`

### 1a — extend `log_operation` alias to forward `model_used`

Find:

```python
# Legacy alias used by existing callers
async def log_operation(session_id: str, label: str, owner_user: str = "admin") -> str:
    return await log_operation_start(session_id, label, owner_user=owner_user)
```

Replace with:

```python
# Legacy alias used by existing callers. Accepts model_used kwarg so the
# Operations view gets a reasonable default from insert onwards — v2.36.7
# previously dropped it silently, leaving operations.model_used='' for
# every agent-started run.
async def log_operation(
    session_id: str,
    label: str,
    owner_user: str = "admin",
    model_used: str = "",
) -> str:
    return await log_operation_start(
        session_id, label, owner_user=owner_user, model_used=model_used,
    )
```

Backward compatible — every existing call site that doesn't pass
`model_used` keeps working with the old `""` default.

### 1b — backfill `operations.model_used` from `agent_llm_traces` on completion

Find `log_operation_complete`:

```python
async def log_operation_complete(
    operation_id: str,
    status: str,
    duration_ms: int = 0,
) -> None:
    """Write directly to DB — bypasses queue to guarantee the write completes."""
    if not operation_id:
        return
    try:
        async with get_engine().begin() as conn:
            await q.complete_operation(
                conn,
                operation_id=operation_id,
                status=status,
                total_duration_ms=duration_ms,
            )
    except Exception as e:
        log.error("log_operation_complete failed for %s: %s", operation_id, e)
```

Replace with:

```python
async def log_operation_complete(
    operation_id: str,
    status: str,
    duration_ms: int = 0,
) -> None:
    """Write directly to DB — bypasses queue to guarantee the write completes.

    v2.36.7: also backfills `operations.model_used` from the highest-
    step_index row in `agent_llm_traces` for this op. Covers external-AI
    escalations (v2.36.3 writes a step_index=99999 trace row with the
    external provider's model string) and LM-Studio runs where the
    API-reported model differs from the env-var label. Only overwrites
    when the trace row has a non-empty model string; otherwise the
    insert-time seed value (from run_agent / run_subtask) is preserved.
    """
    if not operation_id:
        return
    try:
        async with get_engine().begin() as conn:
            await q.complete_operation(
                conn,
                operation_id=operation_id,
                status=status,
                total_duration_ms=duration_ms,
            )
            # v2.36.7 backfill — best-effort, never blocks the caller.
            try:
                from sqlalchemy import text as _t
                await conn.execute(
                    _t(
                        "UPDATE operations "
                        "SET model_used = COALESCE( "
                        "    (SELECT model FROM agent_llm_traces "
                        "     WHERE operation_id = :op "
                        "       AND model IS NOT NULL "
                        "       AND model <> '' "
                        "     ORDER BY step_index DESC "
                        "     LIMIT 1), "
                        "    model_used "
                        ") "
                        "WHERE id = :op"
                    ),
                    {"op": operation_id},
                )
            except Exception as _be:
                log.debug(
                    "model_used backfill for %s skipped: %s",
                    operation_id, _be,
                )
    except Exception as e:
        log.error("log_operation_complete failed for %s: %s", operation_id, e)
```

Note the SQL:

- `ORDER BY step_index DESC LIMIT 1` picks the LAST trace row — which is
  step_index=99999 for external-AI escalations (v2.36.3's sentinel value)
  and the final local step for everything else. Both cases give us the
  correct model.
- `model IS NOT NULL AND model <> ''` filters out empty rows (e.g.
  pre-v2.36.0 traces) so they don't nuke the insert-time seed.
- `COALESCE(subquery, model_used)` preserves the existing column value if
  the subquery returns NULL (no trace exists, or all trace rows have
  empty model).
- Runs inside the same transaction as `complete_operation` — atomic.
- Wrapped in try/except at debug level — if the schema migration for
  `agent_llm_traces.model` hasn't run yet, or the DB backend differs, the
  caller's terminal-status write still succeeds.

---

## Change 2 — `api/routers/agent.py`

Two call sites at the bottom of the file. Both pass `_lm_model()` as the
seed value.

### 2a — `run_agent`

Find:

```python
@router.post("/run", response_model=RunResponse)
async def run_agent(req: RunRequest, background_tasks: BackgroundTasks,
                    user: str = Depends(get_current_user)):
    """Start an agent task. Streams output to ws://host:8000/ws/output."""
    session_id = req.session_id or str(uuid.uuid4())
    operation_id = await logger_mod.log_operation(session_id, req.task, owner_user=user)
```

Replace the operation creation line with:

```python
    operation_id = await logger_mod.log_operation(
        session_id, req.task, owner_user=user, model_used=_lm_model(),
    )
```

### 2b — `run_subtask`

Find:

```python
@router.post("/subtask", response_model=RunResponse)
async def run_subtask(req: SubtaskRequest, background_tasks: BackgroundTasks,
                      user: str = Depends(get_current_user)):
    """Start an execute sub-agent from a proposal, injecting parent investigation context."""
    session_id   = str(uuid.uuid4())
    operation_id = await logger_mod.log_operation(session_id, req.task, owner_user=user)
```

Replace the operation creation line with:

```python
    operation_id = await logger_mod.log_operation(
        session_id, req.task, owner_user=user, model_used=_lm_model(),
    )
```

Sub-agents inherit the parent's model by default at insert; the complete-
time backfill from `agent_llm_traces` then upgrades the value to the
actual API-reported model (which for a v2.34.0 sub-agent is always the
same LM Studio model as the parent — sub-agents don't independently
escalate to external AI).

### 2c — grep for other callers (verify-only)

```bash
grep -n "logger_mod.log_operation(" api/routers/agent.py
```

Expect exactly 2 matches after the edits above, both with
`model_used=_lm_model()`. If more appear (future sub-agent spawn paths,
etc.), they need the same treatment — add to this prompt before shipping.

```bash
grep -rn "logger_mod\.log_operation\b\|logger\.log_operation\b" api/ | grep -v _complete | grep -v _start
```

Expect only the 2 lines above. Any other match means a caller we missed.

---

## Change 3 — `tests/test_operations_model_column.py` (NEW)

Two tests. Python-only, uses the existing DB fixture pattern from
`tests/conftest.py` or `tests/test_external_ai_calls_endpoint.py` —
whichever the project uses.

```python
"""v2.36.7 — operations.model_used is populated at insert and backfilled
from agent_llm_traces on completion.

Two failure modes this test locks in:

1. Regression: the `log_operation` legacy alias used to silently drop
   `model_used`. If someone re-introduces the 3-arg signature without
   kwarg forwarding, `test_log_operation_alias_forwards_model_used`
   fails.

2. Regression: the complete-time backfill from `agent_llm_traces` was
   the v2.36.0 -> v2.36.7 missing link between provenance and the
   Operations view. If anyone removes the COALESCE subquery from
   `log_operation_complete`, `test_completion_backfills_model_from_trace`
   fails.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import text

from api.db.base import get_engine
from api import logger as logger_mod


# ── Helper: run async test in sync pytest ─────────────────────────────────────

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── Helper: insert a fake agent_llm_traces row ────────────────────────────────

async def _insert_trace_row(operation_id: str, step_index: int, model: str) -> None:
    """Insert a minimal agent_llm_traces row for backfill testing.

    Uses raw SQL to avoid pulling in the full llm_traces schema — we only
    need step_index + model for the backfill subquery to find the row.
    """
    async with get_engine().begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO agent_llm_traces "
                "(id, operation_id, step_index, model, messages_delta, "
                " response_raw, created_at) "
                "VALUES (:id, :op, :step, :model, '[]'::jsonb, '{}'::jsonb, NOW())"
            ),
            {
                "id":    str(uuid.uuid4()),
                "op":    operation_id,
                "step":  step_index,
                "model": model,
            },
        )


async def _read_model_used(operation_id: str) -> str | None:
    async with get_engine().connect() as conn:
        result = await conn.execute(
            text("SELECT model_used FROM operations WHERE id = :id"),
            {"id": operation_id},
        )
        row = result.fetchone()
    return row[0] if row else None


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.postgres
def test_log_operation_alias_forwards_model_used():
    """The 3-arg `log_operation` alias must forward `model_used` kwarg."""
    session_id = str(uuid.uuid4())
    op_id = _run(logger_mod.log_operation(
        session_id=session_id,
        label="test v2.36.7 insert-seed",
        owner_user="test",
        model_used="test-model-v2.36.7",
    ))

    assert op_id

    model = _run(_read_model_used(op_id))
    assert model == "test-model-v2.36.7", (
        f"insert-time seed not persisted; got {model!r}. "
        "Check log_operation alias forwards model_used kwarg."
    )


@pytest.mark.postgres
def test_completion_backfills_model_from_trace():
    """log_operation_complete backfills model_used from latest trace row.

    Scenario: op inserts with seed='local-model'. Two trace rows written
    — step_index=0 with 'local-model', step_index=99999 with 'external-
    claude'. Completion must pick the higher step_index (external).
    """
    session_id = str(uuid.uuid4())
    op_id = _run(logger_mod.log_operation(
        session_id=session_id,
        label="test v2.36.7 complete-backfill",
        owner_user="test",
        model_used="local-model",
    ))

    # Simulate a v2.36.3 external-AI escalation: two trace rows, the
    # higher step_index carrying the external model name.
    _run(_insert_trace_row(op_id, step_index=0,     model="local-model"))
    _run(_insert_trace_row(op_id, step_index=99999, model="external-claude"))

    _run(logger_mod.log_operation_complete(op_id, status="completed"))

    model = _run(_read_model_used(op_id))
    assert model == "external-claude", (
        f"completion backfill should pick the highest step_index row "
        f"(external-claude), got {model!r}"
    )


@pytest.mark.postgres
def test_completion_preserves_seed_when_no_trace():
    """Empty `agent_llm_traces` → COALESCE preserves insert-time seed."""
    session_id = str(uuid.uuid4())
    op_id = _run(logger_mod.log_operation(
        session_id=session_id,
        label="test v2.36.7 complete-no-trace",
        owner_user="test",
        model_used="seed-only",
    ))

    _run(logger_mod.log_operation_complete(op_id, status="completed"))

    model = _run(_read_model_used(op_id))
    assert model == "seed-only", (
        f"no trace rows — COALESCE must preserve the insert-time seed; "
        f"got {model!r}"
    )


@pytest.mark.postgres
def test_completion_ignores_empty_trace_model():
    """Trace row with empty model → COALESCE skips it and preserves seed."""
    session_id = str(uuid.uuid4())
    op_id = _run(logger_mod.log_operation(
        session_id=session_id,
        label="test v2.36.7 complete-empty-trace-model",
        owner_user="test",
        model_used="seed-value",
    ))

    # Pre-v2.36.0 trace row — model column empty (it existed before the
    # provenance fix). Backfill SQL filters on `model <> ''` so this
    # row is ignored and the seed value is preserved.
    _run(_insert_trace_row(op_id, step_index=5, model=""))

    _run(logger_mod.log_operation_complete(op_id, status="completed"))

    model = _run(_read_model_used(op_id))
    assert model == "seed-value", (
        f"empty trace.model should be filtered by the WHERE clause; "
        f"got {model!r}"
    )
```

Scoping note: if the project already uses `@pytest.mark.postgres` as the
marker for DB-touching tests, use it verbatim. If the convention is
different (e.g. an `async_postgres` marker or a fixture), adapt.
Preserve the four test names — they read as documentation of the
invariants.

---

## Change 4 — `VERSION`

```
2.36.7
```

---

## Verify

```bash
# Structural greps
grep -n "logger_mod.log_operation(" api/routers/agent.py
# Expect exactly 2 lines — both with model_used=_lm_model()

grep -rn "logger_mod\.log_operation\b\|logger\.log_operation\b" api/ \
  | grep -v "_complete\|_start"
# Expect only the 2 lines above.

grep -n "COALESCE" api/logger.py
# Expect 1 match inside log_operation_complete.

# Regression tests
pytest tests/test_operations_model_column.py -v
# All 4 must pass.

# Existing test suite must still pass
pytest tests/test_tool_budget_settings.py tests/test_options_context_server_keys.py -v
```

---

## Commit

```bash
git add -A
git commit -m "fix(logs): v2.36.7 populate operations.model_used — insert seed + trace backfill

The Operations view in Logs has been showing an empty Model column for
every agent-started run. Two layers:

1. Insert seed: api/routers/agent.py::run_agent and run_subtask used the
   3-arg legacy log_operation alias that silently dropped model_used,
   so operations.model_used was written as '' at insert and never set.
   Both call sites now pass model_used=_lm_model(). The alias itself
   gains a model_used kwarg that forwards to log_operation_start —
   backward compatible with every other caller.

2. Complete-time backfill: v2.36.0 added _extract_response_model and
   populated agent_llm_traces.model with the REAL API-reported model
   for every LLM step (including step_index=99999 for v2.36.3 external-
   AI escalations). log_operation_complete now backfills
   operations.model_used from the highest-step_index trace row via a
   COALESCE subquery — external escalations show claude-sonnet-4-6 /
   gpt-4o / etc., local runs show the LM-Studio-reported model name
   (which may differ from the _lm_model() env-var label).

Backfill is best-effort — wrapped in try/except at debug level so a
schema mismatch can't block the terminal-status write.

4 new regression tests in tests/test_operations_model_column.py cover
the alias kwarg forwarding, the external-AI step_index=99999 pickup,
the no-trace seed-preservation path, and the empty-model-filter path."
git push origin main
```

---

## Deploy + smoke

```bash
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```

1. Run any observe task (e.g. "Check UniFi list all clients").
2. Open Logs → Operations. The new row's Model column should show the
   LM-Studio model name (e.g. `qwen/qwen3.6-35b-a3b`), not blank.
3. SQL spot-check:
   ```bash
   docker compose exec hp1_agent python -c "
   import asyncio
   from api.db.base import get_engine
   from sqlalchemy import text
   async def main():
       async with get_engine().connect() as c:
           r = await c.execute(text(
               'SELECT id, model_used FROM operations '
               'ORDER BY started_at DESC LIMIT 3'
           ))
           for row in r.fetchall():
               print(row)
   asyncio.run(main())
   "
   ```
   Expect non-empty `model_used` for the three most recent ops.

4. External-AI smoke (optional — needs v2.36.3 enabled): set
   `externalRoutingMode=auto`, trigger an escalation via a complex task,
   approve in the confirm modal. After completion the Operations view
   should show the external model name (`claude-sonnet-4-6` etc.) for
   that row, not the local LM-Studio model.

---

## Scope guard — do NOT touch

- Tool-call rows (`tool_calls.model_used`) — already correctly populated
  by `log_tool_call`. Unchanged.
- `agent_llm_traces` schema — v2.36.0's provenance fix is the only source
  of truth for model strings. This prompt only READS from it.
- `operations` schema — no migration. `model_used` column already exists.
- `q.complete_operation` — keep its existing 3-arg signature. Backfill
  lives in the caller (`log_operation_complete`), not the query layer.
- External AI calls table — untouched.
- Agent loop logic — untouched.
