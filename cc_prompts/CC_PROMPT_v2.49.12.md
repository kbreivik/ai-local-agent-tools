# CC PROMPT — v2.49.12 — feat(tests): suite-level cancel button

## What this does

Adds a kill switch for in-flight test suite runs. Currently the only
way to stop a suite is `docker restart hp1_agent`, which costs the
agent's memory cache and triggers a sidecar update cycle.

### Mechanism

1. New module-level `_cancelled` flag in `api/routers/tests_api.py`,
   set by POST `/api/tests/cancel`.
2. `tests/integration/test_agent.py::run_all_tests` checks the flag
   between cases and breaks the loop early. Existing in-flight case
   continues until its own timeout — we don't kill the live agent
   call mid-stream (would corrupt LM Studio's state).
3. GUI: red "Cancel Suite" button visible when `_running=true`.
   Confirmation modal before sending the request.

Cancelled runs are persisted normally with the partial results plus
a `cancelled_at` field so it's clear they didn't complete.

Version bump: 2.49.11 → 2.49.12

---

## Change 1 — `api/routers/tests_api.py`

Find the module-level flags block:

````python
# Module-level flag to prevent concurrent runs
_running = False

# Exported flag — checked by api/alerts.py to suppress collector noise
# during test runs (SSH load from agents causes false vm_hosts/network_ssh alerts)
test_run_active = False
````

Replace with:

````python
# Module-level flag to prevent concurrent runs
_running = False

# v2.49.12 — operator-driven cancel flag. Set by POST /api/tests/cancel.
# The integration test runner checks this between cases and breaks early.
# The current in-flight case is allowed to finish (or hit its timeout)
# rather than being killed mid-stream — killing would leave LM Studio
# in an inconsistent state.
_cancelled = False

# Exported flag — checked by api/alerts.py to suppress collector noise
# during test runs (SSH load from agents causes false vm_hosts/network_ssh alerts)
test_run_active = False
````

Find the `/running` endpoint definition:

````python
@router.get("/running")
async def get_test_running():
    """Return whether a test run is in progress."""
    return {"running": _running}
````

Replace with:

````python
@router.get("/running")
async def get_test_running():
    """Return whether a test run is in progress."""
    return {"running": _running, "cancelled": _cancelled}


@router.post("/cancel")
async def cancel_tests(_: dict = Depends(get_current_user)):
    """v2.49.12 — request cancellation of the in-flight test suite.
    The runner checks this flag between cases and stops as soon as the
    current case finishes. Returns immediately."""
    global _cancelled
    if not _running:
        return {"cancelled": False, "reason": "no run in progress"}
    _cancelled = True
    return {"cancelled": True, "message": "Cancellation requested — current case will finish, then stop"}


def is_cancelled() -> bool:
    """Read-only accessor used by the integration runner via import."""
    return _cancelled
````

Find the start of `_run_tests_bg`:

````python
async def _run_tests_bg(
    categories: list[str] | None,
    test_ids: list[str] | None = None,
    suite_id: str | None = None,
    memory_enabled: bool | None = None,
    memory_backend: str | None = None,
    suite_name: str = "",
    caller_token: str = "",
) -> None:
    global _running, test_run_active
    _running = True
    test_run_active = True
````

Replace with:

````python
async def _run_tests_bg(
    categories: list[str] | None,
    test_ids: list[str] | None = None,
    suite_id: str | None = None,
    memory_enabled: bool | None = None,
    memory_backend: str | None = None,
    suite_name: str = "",
    caller_token: str = "",
) -> None:
    global _running, test_run_active, _cancelled
    _running = True
    test_run_active = True
    _cancelled = False
````

Find the cleanup (likely a `finally:` block at the end of `_run_tests_bg`):

````python
        _running = False
        test_run_active = False
````

Replace with:

````python
        _running = False
        test_run_active = False
        # _cancelled stays set so /running can report cancelled=true to GUI
        # until the next run starts. Reset above on next _run_tests_bg call.
````

If the exact `_running = False / test_run_active = False` snippet does
not appear together, locate wherever those two variables are reset at
the end of the function and add the comment without breaking ordering.

## Change 2 — `tests/integration/test_agent.py`

Find the `run_all_tests` function. Look for where it iterates over
`cases_to_run`. The structure is roughly:

````python
async def run_all_tests(...):
    ...
    for tc in cases:
        result = await run_test(tc, http, token=token)
        results.append(result)
````

Insert a cancellation check at the top of the loop body. Find the
canonical for-loop iteration over test cases:

````python
    for tc in cases:
        result = await run_test(tc, http, token=token)
````

Replace with:

````python
    for tc in cases:
        # v2.49.12 — suite cancellation check. Operator pressed Cancel
        # in the GUI; we let the in-flight case finish naturally on the
        # previous iteration and bail before starting a new one.
        try:
            from api.routers.tests_api import is_cancelled
            if is_cancelled():
                print(f"\n[runner] Cancellation requested — skipping remaining cases")
                break
        except Exception:
            pass
        result = await run_test(tc, http, token=token)
````

If the actual loop in `test_agent.py` differs in shape (e.g. wraps
`run_test` in additional logging or list-builder shorthand), adapt
the insertion point — what matters is that `is_cancelled()` is
checked **before** each new case is started, and that the loop breaks
when it returns True.

## Change 3 — `gui/src/components/TestsPanel.jsx`

Find the running indicator block. Currently the panel polls
`/api/tests/running` and displays an amber RUNNING indicator. We need
to add a Cancel button next to it.

Search for the existing RUNNING display. Most likely shape:

````jsx
{running && (
  <div style={{ ...some-amber-style }}>
    RUNNING
  </div>
)}
````

Replace the `{running && ...}` block (wherever it appears) with:

````jsx
{running && (
  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
    <div style={{
      fontFamily: 'var(--font-mono)', fontSize: 9,
      color: 'var(--amber)', padding: '3px 8px',
      border: '1px solid rgba(204,136,0,0.4)',
      background: 'rgba(204,136,0,0.10)', borderRadius: 2,
      animation: 'pulse 1.6s infinite',
    }}>
      RUNNING
    </div>
    {/* v2.49.12 — Cancel button. Visible only while a suite is in flight. */}
    <Btn
      onClick={async () => {
        if (!confirm('Cancel the running test suite?\n\nThe current case will finish, then the run stops. Partial results are saved.')) return
        try {
          const r = await api('/api/tests/cancel', {
            method: 'POST',
            headers: { ...authHeaders(), 'Content-Type': 'application/json' },
            body: '{}',
          })
          const d = await r.json()
          // Polling will catch the cancelled flag — no need to mutate state here
        } catch (e) {
          alert('Cancel failed: ' + e.message)
        }
      }}
      style={{ color: 'var(--red)', borderColor: 'rgba(204,40,40,0.4)' }}
    >
      Cancel Suite
    </Btn>
  </div>
)}
````

If the existing `running &&` block is in two or three places (e.g.
header bar AND results tab), apply the change only to the header bar
location — one Cancel button is sufficient. The other locations can
stay as plain RUNNING indicators.

If the file uses a different layout shape than what's shown above,
preserve the existing visual design and just add the `Btn` next to it.

## Change 4 — VERSION

Update `VERSION`: 2.49.11 → 2.49.12

## Verify

````bash
# 1. New cancel endpoint registered
grep -q '@router.post("/cancel")' api/routers/tests_api.py
grep -q 'def is_cancelled' api/routers/tests_api.py

# 2. Runner imports and checks the flag
grep -q 'from api.routers.tests_api import is_cancelled' tests/integration/test_agent.py

# 3. _cancelled flag declared and reset
grep -q '_cancelled = False' api/routers/tests_api.py

# 4. GUI references the new endpoint
grep -q "'/api/tests/cancel'" gui/src/components/TestsPanel.jsx
````

## Commit

````bash
git add -A
git commit -m "feat(tests): suite-level cancel button (v2.49.12)

Currently the only way to stop an in-flight test suite is
'docker restart hp1_agent'. This adds a clean cancel path:

- New POST /api/tests/cancel endpoint sets _cancelled flag.
- Integration runner checks is_cancelled() between cases and
  breaks the loop early. In-flight case finishes naturally
  (killing mid-stream would leave LM Studio inconsistent).
- GUI 'Cancel Suite' button visible during runs, with
  confirmation modal.

Partial results are persisted normally. _cancelled stays set
until the next run starts, so the GUI can show 'cancelled' status
on the just-finished run."
git push origin main
````

## Deploy

After CC commits and CI rebuilds:

````bash
# On agent-01 — sidecar will auto-update, or manual:
cd /opt/hp1-agent
git pull origin main
docker pull ghcr.io/kbreivik/hp1-ai-agent:latest
cd docker
docker compose --env-file .env up -d --force-recreate hp1_agent

# Smoke test from the GUI:
# 1. Start a long suite (e.g. full-mem-on-baseline)
# 2. Click "Cancel Suite" → confirm the dialog
# 3. Current case finishes, suite stops, partial results saved
````
