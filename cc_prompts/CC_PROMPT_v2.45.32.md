# CC PROMPT — v2.45.32 — fix(tests): deterministic clarification/plan handling + per-test trace + memory restore

## What this does
Fixes a cluster of test-runner bugs the operator just hit:

1. **Clarification questions popped up in the operator's browser** instead of being answered by the test. The runner connects to WS and POSTs `/run` in sequence, but `_collect()` can miss the first broadcast if the agent is fast — racing the WS client startup against the agent's first emit.

2. **Tests "just passed" without showing what was asked.** The `had_clarification`/`had_plan` flags are recorded, but the *question text*, *plan summary*, and *answer used* are not — there's no audit trail.

3. **`memoryEnabled` is left mutated** after a test run because `_run_tests_bg` calls `set_setting()` globally without restoring it. A user clicks Run after a memory-off baseline and silently has memory disabled.

4. **`clarification_answer` POST has no retry** — if the auth race or a 502 swallows the request, the agent waits 300s then auto-resolves with "timeout" → wrong answer → silent test fail.

5. **Test results are not linked back to `operations.id`** — clicking through to Trace from the Results panel requires hand-correlating timestamps.

6. **JWT TTL=90min vs 47-min A/B baselines** — late tests can fail their `/clarify` and `/confirm` POSTs when the token expires mid-run.

Version bump: 2.45.31 → 2.45.32

---

## Change 1 — `api/clarification.py` — pre-arm future before the question is asked

The race fix has to happen on the server side. `wait_for_clarification` currently
*creates* the future when called. If the test runner POSTs `/clarify` before the
agent has actually called `clarifying_question()` (because the test runner is
trying to be defensive), the POST returns "no pending future".

Add a `prearm_clarification(session_id)` helper that creates the future
proactively. The agent loop's `wait_for_clarification` then reuses an existing
pre-armed future if present.

Find the existing module body. Replace the `_pending` dict line and below with:

```python
import asyncio
import logging
from typing import Dict

log = logging.getLogger(__name__)

# Map session_id → Future. Agents await it; resolve_clarification sets it.
_pending: Dict[str, asyncio.Future] = {}

# v2.45.32 — pre-armed answers: set by /clarify when no future yet exists,
# then consumed by the next prearm_clarification / wait_for_clarification
# call for the same session. Lets test runners send the answer before the
# agent has actually called clarifying_question() without race conditions.
_prearmed_answers: Dict[str, str] = {}


def prearm_clarification(session_id: str) -> asyncio.Future:
    """Create + register a future for `session_id` if not already present.

    Returns the future. If a pre-armed answer was deposited via
    `resolve_clarification` before any waiter existed, the future is returned
    already-resolved. Idempotent.
    """
    loop = asyncio.get_event_loop()
    fut = _pending.get(session_id)
    if fut is None or fut.done():
        fut = loop.create_future()
        _pending[session_id] = fut
    if session_id in _prearmed_answers and not fut.done():
        fut.set_result(_prearmed_answers.pop(session_id))
    return fut


async def wait_for_clarification(session_id: str, timeout: float = 300.0) -> str:
    """Suspend caller until resolve_clarification() is called or timeout fires.

    v2.45.32: reuses any future created by prearm_clarification(); also
    consumes a pre-armed answer if one was deposited before the agent reached
    this call.
    """
    future = prearm_clarification(session_id)
    try:
        return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
    except asyncio.TimeoutError:
        log.warning("[clarification] timeout waiting for session %s", session_id)
        return "timeout — proceed with best guess"
    finally:
        _pending.pop(session_id, None)


def resolve_clarification(session_id: str, answer: str) -> bool:
    """Called by POST /api/agent/clarify to unblock the waiting agent loop.

    v2.45.32: if no future exists yet (test runner is faster than agent),
    deposit the answer in _prearmed_answers; the next prearm/wait call
    consumes it. Returns True in both cases so the API endpoint's
    'no pending future' message stops appearing on success.
    """
    future = _pending.get(session_id)
    if future is not None and not future.done():
        future.set_result(answer)
        log.info("[clarification] resolved session %s: %r", session_id, answer)
        return True
    # No waiter yet — deposit for the next caller to consume.
    _prearmed_answers[session_id] = answer
    log.info("[clarification] pre-armed session %s: %r", session_id, answer)
    return True
```

Apply the same pattern to `api/confirmation.py`. Open it, replace the body
(after the docstring) with:

```python
import asyncio
import logging
from typing import Dict

log = logging.getLogger(__name__)

_pending: Dict[str, asyncio.Future] = {}
_prearmed_decisions: Dict[str, bool] = {}


def prearm_confirmation(session_id: str) -> asyncio.Future:
    """v2.45.32 — pre-arm a future for `session_id`; consume any pre-armed
    decision. Idempotent."""
    loop = asyncio.get_event_loop()
    fut = _pending.get(session_id)
    if fut is None or fut.done():
        fut = loop.create_future()
        _pending[session_id] = fut
    if session_id in _prearmed_decisions and not fut.done():
        fut.set_result(_prearmed_decisions.pop(session_id))
    return fut


async def wait_for_confirmation(session_id: str, timeout: float = 300.0) -> bool:
    future = prearm_confirmation(session_id)
    try:
        return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
    except asyncio.TimeoutError:
        log.warning("[confirmation] timeout waiting for session %s — auto-cancelling", session_id)
        return False
    finally:
        _pending.pop(session_id, None)


def resolve_confirmation(session_id: str, approved: bool) -> bool:
    future = _pending.get(session_id)
    if future is not None and not future.done():
        future.set_result(approved)
        log.info("[confirmation] session %s: approved=%s", session_id, approved)
        return True
    _prearmed_decisions[session_id] = approved
    log.info("[confirmation] pre-armed session %s: approved=%s", session_id, approved)
    return True
```

---

## Change 2 — `tests/integration/test_agent.py` — pre-arm answers + retry POSTs + capture all prompts

Open `tests/integration/test_agent.py`. Apply these changes:

### 2a. Extend `TestResult` dataclass

Find:
```python
@dataclass
class TestResult:
    id: str
    ...
    timed_out: bool
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
```

Replace the field list (preserve existing fields) by adding new fields BEFORE `timestamp`:

```python
    # v2.45.32 — capture full clarification/plan content for audit trail
    clarification_question: str = ""
    clarification_answer_used: str = ""
    plan_summary: str = ""
    plan_steps_count: int = 0
    plan_approved: bool = False
    operation_id: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
```

### 2b. Pre-arm answers BEFORE running the agent

Find the `run_test` function. After the `session_id = str(uuid4())` line and the
`messages: list[dict] = []` line, BEFORE the WS connection block, add:

```python
    # v2.45.32 — pre-arm the clarification/plan answers via the API so they
    # are deposited at the server BEFORE the agent loop reaches the
    # clarifying_question() / plan_action() call. Eliminates the WS-race that
    # would otherwise route the modal to whichever browser is connected.
    if tc.triggers_clarification or tc.clarification_answer not in ("", "cancel"):
        try:
            await http.post(
                f"{API_BASE}/api/agent/clarify",
                json={"session_id": session_id, "answer": tc.clarification_answer},
                timeout=5,
            )
        except Exception:
            pass  # Best-effort — agent will still emit and re-prompt
    if tc.triggers_plan:
        try:
            await http.post(
                f"{API_BASE}/api/agent/confirm",
                json={"session_id": session_id, "approved": tc.auto_confirm},
                timeout=5,
            )
        except Exception:
            pass
```

### 2c. Retry the in-loop responses if the prearm somehow missed

In the `_collect()` async function, find the existing `mtyp == "plan_pending"`
block. Replace it with:

```python
                    # v2.45.32 — re-send the response in case the prearm got
                    # delivered before /run dispatched the operation_id. Server
                    # idempotently accepts duplicates (last writer wins on the future).
                    if mtyp == "plan_pending" and sid == session_id:
                        try:
                            r_plan = msg.get("plan", {}) or {}
                            captured["plan_summary"] = (r_plan.get("summary") or "")[:300]
                            captured["plan_steps_count"] = len(r_plan.get("steps", []) or [])
                            captured["plan_approved"] = bool(tc.auto_confirm)
                        except Exception:
                            pass
                        # Up to 3 retries — server has a 300s timeout, but we want
                        # to surface real failures fast.
                        for _attempt in range(3):
                            try:
                                _r = await http.post(
                                    f"{API_BASE}/api/agent/confirm",
                                    json={"session_id": session_id,
                                          "approved": tc.auto_confirm},
                                    timeout=5,
                                )
                                if _r.status_code == 200:
                                    break
                            except Exception:
                                pass
                            await asyncio.sleep(0.5)
```

Replace the existing `mtyp == "clarification_needed"` block with:

```python
                    if mtyp == "clarification_needed" and sid == session_id:
                        captured["clarification_question"] = (
                            msg.get("question") or "")[:500]
                        captured["clarification_answer_used"] = tc.clarification_answer
                        for _attempt in range(3):
                            try:
                                _r = await http.post(
                                    f"{API_BASE}/api/agent/clarify",
                                    json={"session_id": session_id,
                                          "answer": tc.clarification_answer},
                                    timeout=5,
                                )
                                if _r.status_code == 200:
                                    break
                            except Exception:
                                pass
                            await asyncio.sleep(0.5)
```

Right above the `async def _collect():` line, add:

```python
            captured: dict = {
                "clarification_question": "",
                "clarification_answer_used": "",
                "plan_summary": "",
                "plan_steps_count": 0,
                "plan_approved": False,
                "operation_id": "",
            }
```

In the `_collect()` body, find the existing `if not msg or msg.get("type") == "pong":` block. Right after it,
add:

```python
                    # v2.45.32 — capture operation_id from the first agent_start
                    # broadcast so the result row links back to the trace.
                    if msg.get("type") == "agent_start" and not captured.get("operation_id"):
                        # operation_id may be on the agent_start broadcast itself
                        # or fetched via /api/agent/operations/{session_id}
                        # Prefer the broadcast field; fall back later if absent.
                        if msg.get("operation_id"):
                            captured["operation_id"] = msg.get("operation_id", "")
```

If `operation_id` isn't on `agent_start`, fall back: AFTER `await asyncio.wait_for(_collect(), timeout=tc.timeout_s)`,
add:

```python
            # v2.45.32 — fall back to fetching operation_id by session
            if not captured.get("operation_id"):
                try:
                    _opr = await http.get(
                        f"{API_BASE}/api/operations/by-session/{session_id}",
                        timeout=5,
                    )
                    if _opr.status_code == 200:
                        _opd = _opr.json()
                        captured["operation_id"] = _opd.get("id", "") or _opd.get("operation_id", "")
                except Exception:
                    pass
```

(CC: if `/api/operations/by-session/{sid}` does not exist, comment out this fallback
block and replace with a TODO — the field stays empty in the result row but the
test still works.)

### 2d. Pass `captured` into `_evaluate`

Find the line that calls `_evaluate(tc, our_msgs, duration, timed_out)`. Change to:

```python
    return _evaluate(tc, our_msgs, duration, timed_out, captured=captured)
```

### 2e. Update `_evaluate` to populate the new fields

Find the `_evaluate` signature:

```python
def _evaluate(tc: TestCase, messages: list[dict], duration: float,
              timed_out: bool) -> TestResult:
```

Change to:

```python
def _evaluate(tc: TestCase, messages: list[dict], duration: float,
              timed_out: bool, *, captured: dict | None = None) -> TestResult:
    captured = captured or {}
```

At the bottom, find the `return TestResult(...)` block. Add the new fields BEFORE the
existing `timed_out=timed_out,` line:

```python
        clarification_question=captured.get("clarification_question", ""),
        clarification_answer_used=captured.get("clarification_answer_used", ""),
        plan_summary=captured.get("plan_summary", ""),
        plan_steps_count=captured.get("plan_steps_count", 0),
        plan_approved=captured.get("plan_approved", False),
        operation_id=captured.get("operation_id", ""),
```

### 2f. Persist new fields in `save_results`

Find `save_results()`. In the dict comprehension that builds each result row,
add the new fields before `"timed_out": r.timed_out,`:

```python
                "clarification_question":    r.clarification_question,
                "clarification_answer_used": r.clarification_answer_used,
                "plan_summary":              r.plan_summary,
                "plan_steps_count":          r.plan_steps_count,
                "plan_approved":             r.plan_approved,
                "operation_id":              r.operation_id,
```

---

## Change 3 — `api/db/test_runs.py` + DB schema — store new fields

`api/db/test_runs.py:insert_result` writes a fixed column list. Add a column to
`test_run_results` and pass through the new fields.

### 3a. Find `insert_result` and replace with:

```python
def insert_result(run_id: str, r: dict) -> None:
    if not _is_pg():
        return
    try:
        conn = _conn(); cur = conn.cursor()
        cur.execute("""
            INSERT INTO test_run_results
                (run_id, test_id, category, task, passed, soft, critical,
                 failures, warnings, agent_type, tools_called, step_count,
                 duration_s, timed_out,
                 clarification_question, clarification_answer_used,
                 plan_summary, plan_steps_count, plan_approved, operation_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    %s,%s,%s,%s,%s,%s)
        """, (run_id, r['id'], r.get('category', ''), r.get('task', ''),
              r.get('passed', False), r.get('soft', False), r.get('critical', False),
              json.dumps(r.get('failures', [])), json.dumps(r.get('warnings', [])),
              r.get('agent_type', ''), json.dumps(r.get('tools_called', [])),
              r.get('step_count', 0), r.get('duration_s', 0),
              r.get('timed_out', False),
              r.get('clarification_question', ''),
              r.get('clarification_answer_used', ''),
              r.get('plan_summary', ''),
              r.get('plan_steps_count', 0),
              r.get('plan_approved', False),
              r.get('operation_id', '')))
        conn.commit(); cur.close(); conn.close()
    except Exception as e:
        log.debug("insert_result: %s", e)
```

### 3b. Add a startup migration

CC: locate the migrations module. Likely `api/db/migrations.py` or
`api/db/__init__.py`. Search:

```bash
grep -rn "test_run_results\|CREATE TABLE.*test_run" api/db/ 2>&1 | head -20
```

Find where `test_run_results` is created. Right after that block, add an
`ALTER TABLE` migration that's idempotent:

```python
def _ensure_v2_45_32_columns(conn) -> None:
    """v2.45.32 — add audit columns to test_run_results."""
    cur = conn.cursor()
    cur.execute("""
        ALTER TABLE test_run_results
            ADD COLUMN IF NOT EXISTS clarification_question TEXT DEFAULT '',
            ADD COLUMN IF NOT EXISTS clarification_answer_used TEXT DEFAULT '',
            ADD COLUMN IF NOT EXISTS plan_summary TEXT DEFAULT '',
            ADD COLUMN IF NOT EXISTS plan_steps_count INTEGER DEFAULT 0,
            ADD COLUMN IF NOT EXISTS plan_approved BOOLEAN DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS operation_id TEXT DEFAULT ''
    """)
    conn.commit()
    cur.close()
```

Wire `_ensure_v2_45_32_columns` into the existing migration runner. CC: if the
existing setup runs migrations sequentially in a list, append it; otherwise
call it from the same place `test_run_results` is created.

If the existing pattern doesn't use `IF NOT EXISTS` (older PG), wrap each
`ALTER` in its own try/except so re-running is safe.

Update `get_run` and `list_runs` SELECT lists to include the new columns. CC:
find both functions and append the new column names to the SELECT lists.

---

## Change 4 — `api/routers/tests_api.py` — restore `memoryEnabled` after run

Find `_run_tests_bg`. Before the `if memory_enabled is not None:` block, add:

```python
        # v2.45.32 — capture pre-run settings so we can restore them after.
        _restore_memory_enabled = None
        _restore_memory_backend = None
        try:
            from api.settings_manager import get_setting as _gs
            _restore_memory_enabled = (_gs("memoryEnabled") or {}).get("value")
            _restore_memory_backend = (_gs("memoryBackend") or {}).get("value")
        except Exception:
            pass
```

After `save_results(results)` and before `_t_end = ...`, add:

```python
        # v2.45.32 — restore the pre-run setting state so a manual user run
        # immediately after a memory-off baseline is not silently degraded.
        try:
            from api.settings_manager import set_setting as _ss
            if _restore_memory_enabled is not None and memory_enabled is not None:
                _ss("memoryEnabled", _restore_memory_enabled)
            if _restore_memory_backend is not None and memory_backend is not None:
                _ss("memoryBackend", _restore_memory_backend)
        except Exception as _re:
            import logging as _rl
            _rl.getLogger(__name__).warning(
                "v2.45.32 settings restore failed: %s", _re,
            )
```

CC: ensure the restore block is in a `finally` clause so it runs even if the
test run crashes. The simplest move: change the `try:` at the top of
`_run_tests_bg` to wrap everything, with the restore in `finally:`. If that's
too invasive, leave as a `try/finally` around just the run-test block.

---

## Change 5 — `api/routers/tests_api.py` — extend JWT TTL for long runs

Find:

```python
        from api.auth import create_internal_token
        _fresh_token = create_internal_token(expires_minutes=90)
```

Change `expires_minutes=90` to `expires_minutes=180`. The full A/B baselines
(47 min × 2 = 94 min wall-clock) currently sit *just* over the 90-min TTL.
180 minutes is ample headroom and still bounded.

---

## Change 6 — Frontend: render new fields in TestsPanel Results

CC: open `gui/src/components/TestsPanel.jsx`. Find the function that renders a
single result row (likely `ResultRow` or inline JSX with `r.test_id`,
`r.failures`, `r.warnings`). Below the existing `r.failures` / `r.warnings`
display, add a third compact section that shows the new fields when populated:

```jsx
{r.clarification_question && (
  <div style={{ fontSize: 9, color: 'var(--text-3)', marginTop: 2 }}>
    <span style={{ color: 'var(--cyan)' }}>Q:</span> {r.clarification_question}
    {r.clarification_answer_used && (
      <span> — <span style={{ color: 'var(--accent)' }}>A:</span> {r.clarification_answer_used}</span>
    )}
  </div>
)}
{r.plan_summary && (
  <div style={{ fontSize: 9, color: 'var(--text-3)', marginTop: 2 }}>
    <span style={{ color: 'var(--amber)' }}>Plan:</span> {r.plan_summary}
    {r.plan_steps_count > 0 && (
      <span> ({r.plan_steps_count} steps, {r.plan_approved ? 'approved' : 'cancelled'})</span>
    )}
  </div>
)}
{r.operation_id && (
  <div style={{ fontSize: 8, color: 'var(--text-3)', marginTop: 1 }}>
    op: <a
      href={`/logs?operation=${r.operation_id}`}
      style={{ color: 'var(--cyan)', textDecoration: 'none' }}
    >{r.operation_id.slice(0, 8)}</a>
  </div>
)}
```

The link target depends on the Logs view URL pattern. CC: check the existing
Logs router handler in `App.jsx` or wherever the Logs view is mounted; pick
the existing pattern (e.g. `/logs/op/{id}` or `?operation=` query). Match it.

---

## Change 7 — `api/routers/agent.py` — emit `operation_id` on `agent_start`

Find the `agent_start` broadcast inside `_stream_agent`:

```python
    await manager.broadcast({
        "type":       "agent_start",
        "agent_type": first_intent,
        "session_id": session_id,
        "timestamp":  datetime.now(timezone.utc).isoformat(),
    })
```

Add `"operation_id": operation_id,` before the `timestamp` line:

```python
    await manager.broadcast({
        "type":         "agent_start",
        "agent_type":   first_intent,
        "session_id":   session_id,
        "operation_id": operation_id,
        "timestamp":    datetime.now(timezone.utc).isoformat(),
    })
```

Test runner already captures `operation_id` from `agent_start` per Change 2c.

---

## Verify

```bash
python -m py_compile \
  api/clarification.py api/confirmation.py \
  api/routers/tests_api.py api/routers/agent.py \
  api/db/test_runs.py tests/integration/test_agent.py

# Pre-arm contract regression test (no LLM needed):
python -c "
import asyncio
from api.clarification import resolve_clarification, wait_for_clarification

async def t():
    # Pre-arm an answer before any waiter exists
    ok = resolve_clarification('test-sid', 'kafka-stack_kafka1')
    assert ok, 'pre-arm should succeed'
    # Now the agent waits — it should get the pre-armed value immediately
    answer = await wait_for_clarification('test-sid', timeout=2)
    assert answer == 'kafka-stack_kafka1', f'got {answer!r}'
    print('PASS — pre-arm before wait works')

asyncio.run(t())
"
```

After deploy, run the smoke suite from the Tests panel. Watch container logs:

```bash
docker logs hp1_agent --since 5m -f 2>&1 | grep -E "clarification|confirmation"
```

You should see for clarification tests:
```
[clarification] pre-armed session abc-123: 'kafka-stack_kafka1'
... agent reaches clarifying_question() ...
[clarification] resolved session abc-123: 'kafka-stack_kafka1'  (or, if pre-armed: nothing more)
```

The browser should NOT show the modal (it gets the broadcast but the agent
already has its answer). After the run finishes, open the Results tab — each
clarification/plan test row should show the question + answer + op-id link.

---

## Version bump

Update `VERSION`: `2.45.31` → `2.45.32`

---

## Commit

```
git add -A
git commit -m "fix(tests): v2.45.32 deterministic clarification/plan handling + per-test trace + memory restore"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```

After deploy:
- Test clarifications/plans answer themselves deterministically; the operator's
  browser stops getting popped on test runs.
- Each test row in the Results tab shows what was asked and how it was answered.
- A click on `op:abc1234e` jumps to the Trace for that test.
- `memoryEnabled` returns to its pre-run state so manual runs aren't silently
  degraded.
- Long A/B baselines no longer fail their late `/clarify` POSTs from JWT TTL.
