# CC PROMPT — v2.47.11 — fix(tests): auto-cancel un-pre-armed gates during test runs

## What this does
Closes the last popup-during-tests gap. v2.47.9 blocked external AI but
plan_pending and clarification_needed modals can still appear when the
agent triggers a gate the test runner didn't pre-arm.

**The real problem**: v2.45.32's pre-arm in `tests/integration/test_agent.py`
is conditional:

```python
if tc.triggers_clarification or tc.clarification_answer not in ("", "cancel"):
    await http.post(f"{API_BASE}/api/agent/clarify", ...)
if tc.triggers_plan:
    await http.post(f"{API_BASE}/api/agent/confirm", ...)
```

It only pre-arms gates the test case explicitly *expects* to trigger.
But the agent can trigger gates *unexpectedly*:

- v2.45.18's clarify→plan_action injection: if a test's pre-armed
  clarification answer is "cancel", the harness may auto-inject
  plan_action afterward. No pre-arm for that → modal pops → blocks 300s.
- The agent may decide to call clarifying_question for a task the test
  didn't anticipate. No pre-arm → modal pops → blocks 300s.

User confirmation: "full-mem-on-baseline still pops up with approval
needed, but get's cancelled by timeout or me, so run will fail on that
every time, unless we solve the pre filled answers for the approvals
when ran as tests".

**The fix**: in the wait primitives themselves, when `test_run_active`
is true AND no pre-arm has been deposited, auto-resolve with a safe
default instead of broadcasting and waiting. This guarantees no test
ever blocks on a gate the runner didn't anticipate.

Behavior matrix after this lands:

| Pre-arm? | test_run_active? | Result |
|----------|------------------|--------|
| Yes | any | Use pre-armed answer (existing v2.45.32 behavior) |
| No | True | Auto-resolve with safe default (NEW) |
| No | False | Wait normally (real user run, existing behavior) |

The safe defaults match the test runner's existing convention:
- `wait_for_clarification` → `"cancel"` (matches `tc.clarification_answer = "cancel"` default for tests that don't expect clarification)
- `wait_for_confirmation` → `False` (matches `tc.auto_confirm = False`, also the only legal test value per the assertion in test_agent.py line ~885)

Version bump: 2.47.10 → 2.47.11

NOTE: v2.47.10 (the gen_reference.py CI fix) MUST be done first since
it's already queued PENDING. This v2.47.11 builds on a clean main.

---

## Change 1 — `api/clarification.py` — auto-cancel during test runs

CC: open `api/clarification.py`. Find `wait_for_clarification`. Current:

```python
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
```

Replace with:

```python
async def wait_for_clarification(session_id: str, timeout: float = 300.0) -> str:
    """Suspend caller until resolve_clarification() is called or timeout fires.

    v2.45.32: reuses any future created by prearm_clarification(); also
    consumes a pre-armed answer if one was deposited before the agent reached
    this call.
    v2.47.11: when test_run_active is True and no pre-arm exists, auto-cancel
    instead of blocking on a modal that no operator will click.
    """
    future = prearm_clarification(session_id)

    # If pre-armed, future is already done — return immediately
    if future.done():
        try:
            return future.result()
        finally:
            _pending.pop(session_id, None)

    # v2.47.11 — auto-cancel during test runs to prevent zombie modals.
    # The test runner pre-arms gates it expects (triggers_clarification=True);
    # gates triggered unexpectedly (e.g. v2.45.18 clarify→plan injection on
    # observe tasks, agent deciding to clarify when test didn't anticipate)
    # would otherwise pop a modal and block for the full timeout.
    try:
        from api.routers.tests_api import test_run_active
        if test_run_active:
            log.info("[clarification] auto-cancel session %s (test run, no pre-arm)",
                     session_id)
            _pending.pop(session_id, None)
            return "cancel"
    except Exception:
        pass

    try:
        return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
    except asyncio.TimeoutError:
        log.warning("[clarification] timeout waiting for session %s", session_id)
        return "timeout — proceed with best guess"
    finally:
        _pending.pop(session_id, None)
```

CC: the entire function body is being replaced. Match indentation. Keep
the existing imports — no new imports needed at the top (the
`from api.routers.tests_api import test_run_active` is intentionally
inside the try-block to avoid circular import issues on module load).

---

## Change 2 — `api/confirmation.py` — auto-cancel during test runs

CC: open `api/confirmation.py`. Find `wait_for_confirmation`. Current:

```python
async def wait_for_confirmation(session_id: str, timeout: float = 300.0) -> bool:
    future = prearm_confirmation(session_id)
    try:
        return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
    except asyncio.TimeoutError:
        log.warning("[confirmation] timeout waiting for session %s — auto-cancelling", session_id)
        return False
    finally:
        _pending.pop(session_id, None)
```

Replace with:

```python
async def wait_for_confirmation(session_id: str, timeout: float = 300.0) -> bool:
    future = prearm_confirmation(session_id)

    # If pre-armed, future is already done — return immediately
    if future.done():
        try:
            return future.result()
        finally:
            _pending.pop(session_id, None)

    # v2.47.11 — auto-reject during test runs to prevent zombie modals.
    # See companion change in api/clarification.py for rationale. Tests
    # that explicitly trigger plan_action pre-arm via tc.triggers_plan;
    # gates triggered unexpectedly (e.g. v2.45.18 clarify→plan injection)
    # would otherwise block for the full 300s timeout.
    # Defaults to False (rejected) — matches the assertion in
    # tests/integration/test_agent.py:main that no test may have
    # auto_confirm=True.
    try:
        from api.routers.tests_api import test_run_active
        if test_run_active:
            log.info("[confirmation] auto-reject session %s (test run, no pre-arm)",
                     session_id)
            _pending.pop(session_id, None)
            return False
    except Exception:
        pass

    try:
        return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
    except asyncio.TimeoutError:
        log.warning("[confirmation] timeout waiting for session %s — auto-cancelling", session_id)
        return False
    finally:
        _pending.pop(session_id, None)
```

CC: same pattern as Change 1.

---

## Change 3 — leave preflight disambiguation alone (for now)

The preflight wait primitive lives in a different code path that doesn't
have a `wait_for_*` function in the same shape. Touching it would
require finding the polling loop or asyncio.Event that backs
`/api/agent/preflight/clarify` and adding the same short-circuit there.

If after this prompt deploys you still see popups during testing, the
trace will identify the gate (`preflight_needed` would be the next
suspect). Defer preflight to v2.47.12 if needed — keep this prompt
minimal.

---

## Verify

```bash
python -m py_compile api/clarification.py api/confirmation.py

grep -n "test_run_active" api/clarification.py api/confirmation.py
# Expected: 1 match in each file
```

After deploy, run a fresh full-mem-on-baseline. Watch the GUI:
- No popups should appear during the run, OR
- If a popup appears, it should auto-dismiss within 1-2 seconds (because
  the agent moved past the gate)

Verify in container logs:
```bash
docker logs hp1_agent --since 5m 2>&1 | grep -E "auto-cancel|auto-reject" | head
# Expected: lines like "[clarification] auto-cancel session ..." or
#           "[confirmation] auto-reject session ..." for tests that
#           triggered gates without pre-arm
```

If those lines appear, the fix is working. If popups still block the
run after this, the gate is preflight disambiguation and we'll need
v2.47.12.

---

## Why NOT just fix the test runner instead

Alternative: make `tests/integration/test_agent.py` pre-arm BOTH gates
for every test (whether or not `triggers_clarification`/`triggers_plan`
is set). That works but:

1. Requires the test runner to know all possible gates (currently 4)
2. Pre-arm POSTs add latency to test startup (4 POSTs per test × 38 tests = 152 extra requests)
3. Doesn't help if a NEW gate is added later and the runner forgets to pre-arm it

Server-side auto-cancel is cleaner: any future gate added to the agent
loop just needs a `test_run_active` short-circuit at its wait primitive,
and tests immediately benefit. No test runner changes needed.

---

## Version bump

Update `VERSION`: `2.47.10` → `2.47.11`

---

## Commit

```
git add -A
git commit -m "fix(tests): v2.47.11 auto-cancel un-pre-armed gates during test runs"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```

After deploy + fresh full-mem-on-baseline:
- No blocking popups (key user requirement)
- Score numbers reflect actual agent behaviour, not modal-dismissal latency
- `[confirmation] auto-reject` / `[clarification] auto-cancel` log lines
  identify which tests had unexpected gate fires (useful for deciding
  if the test case definition should be updated)
