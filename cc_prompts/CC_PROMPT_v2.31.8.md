# CC PROMPT — v2.31.8 — feat(security): agent loop hard caps

## What this does
Adds explicit, enforced limits on how long and how hard an agent task can run.
Today `_MAX_STEPS_BY_TYPE` caps step count at 12-20, but there are no caps on:

- Wall-clock time (a single slow tool call can stall for minutes)
- Total tokens across the run (qwen3-coder + long history = real cost)
- Number of destructive tool calls in one task (no upper bound today)

A runaway agent can burn tokens and — worse — keep attempting destructive
remediation. This prompt adds belt-and-braces caps, all env-configurable,
with clear halt reasons written to the escalation table when breached.

Two changes, both in `api/routers/agent.py`.

---

## Change 1 — api/routers/agent.py — add cap constants + helper

Near the other constants at the top of the file (next to
`_MAX_STEPS_BY_TYPE`), add:

```python
# ─── Hard caps on agent runs (v2.31.8) ───────────────────────────────────────
# All env-configurable so an operator can tighten them without a redeploy.
_AGENT_MAX_WALL_CLOCK_S   = int(os.environ.get("AGENT_MAX_WALL_CLOCK_S",   "600"))   # 10 min
_AGENT_MAX_TOTAL_TOKENS   = int(os.environ.get("AGENT_MAX_TOTAL_TOKENS",   "120000"))
_AGENT_MAX_DESTRUCTIVE    = int(os.environ.get("AGENT_MAX_DESTRUCTIVE",    "3"))
_AGENT_MAX_TOOL_FAILURES  = int(os.environ.get("AGENT_MAX_TOOL_FAILURES",  "8"))


def _cap_exceeded(
    *,
    started_monotonic: float,
    total_tokens: int,
    destructive_calls: int,
    tool_failures: int,
) -> tuple[bool, str]:
    """Return (exceeded, reason). reason is human-readable or empty."""
    import time as _t
    elapsed = _t.monotonic() - started_monotonic
    if elapsed > _AGENT_MAX_WALL_CLOCK_S:
        return True, (f"wall-clock cap exceeded ({int(elapsed)}s > "
                      f"{_AGENT_MAX_WALL_CLOCK_S}s)")
    if total_tokens > _AGENT_MAX_TOTAL_TOKENS:
        return True, (f"token cap exceeded ({total_tokens} > "
                      f"{_AGENT_MAX_TOTAL_TOKENS})")
    if destructive_calls > _AGENT_MAX_DESTRUCTIVE:
        return True, (f"destructive-call cap exceeded ({destructive_calls} > "
                      f"{_AGENT_MAX_DESTRUCTIVE})")
    if tool_failures > _AGENT_MAX_TOOL_FAILURES:
        return True, (f"tool-failure cap exceeded ({tool_failures} > "
                      f"{_AGENT_MAX_TOOL_FAILURES})")
    return False, ""
```

---

## Change 2 — api/routers/agent.py — enforce caps in _run_single_agent_step

Inside `_run_single_agent_step`, find the start of the main `try: ... while
step < max_steps:` block. Add local counters just before the `while`:

```python
        import time as _time
        _run_started = _time.monotonic()
        _destructive_calls = 0
        _tool_failures = 0
```

Then at the top of the while-body (right after `step += 1`), add the check:

```python
            exceeded, reason = _cap_exceeded(
                started_monotonic=_run_started,
                total_tokens=total_prompt_tokens + total_completion_tokens,
                destructive_calls=_destructive_calls,
                tool_failures=_tool_failures,
            )
            if exceeded:
                await manager.send_line(
                    "halt", f"CAP: {reason}",
                    status="escalated", session_id=session_id,
                )
                # Persist to escalation table so it shows in the banner
                try:
                    from api.routers.escalations import record_escalation
                    record_escalation(
                        session_id=session_id,
                        reason=f"Agent halted by cap: {reason}",
                        operation_id=operation_id,
                        severity="warning",
                    )
                except Exception:
                    pass
                last_reasoning = (
                    f"Task stopped — {reason}. Partial findings above may be "
                    f"useful; re-run with a narrower task if needed."
                )
                await manager.send_line("reasoning", last_reasoning, session_id=session_id)
                if is_final_step:
                    await manager.broadcast({
                        "type": "done", "session_id": session_id, "agent_type": agent_type,
                        "content": last_reasoning, "status": "ok", "choices": [],
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                final_status = "capped"
                break
```

Then two accounting hooks need adding further down in the same function:

**2a.** Increment `_destructive_calls` whenever a DESTRUCTIVE_TOOL executes
successfully. Find the block where `invoke_tool` is actually called (the
`else:` branch of the plan_action / clarifying_question / propose_subtask /
escalate chain — the line `result = await asyncio.get_event_loop().run_in_executor(...)`).
Immediately after that `result =` assignment, add:
```python
                        if fn_name in DESTRUCTIVE_TOOLS:
                            _destructive_calls += 1
```

**2b.** Increment `_tool_failures` whenever a tool returns error/degraded
(hard failure path). Find the existing block starting with
`_is_hard_failure = result_status in ("failed", "escalated") ...`. Right
after that assignment and the `_is_degraded` / `_is_investigate` lines,
before the `if _is_degraded and _is_investigate:` branch, add:
```python
                if _is_hard_failure or result_status == "error":
                    _tool_failures += 1
```

---

## Commit
```
git add -A
git commit -m "feat(security): v2.31.8 agent loop hard caps (wall-clock, tokens, destructive, failures)"
git push origin main
```

---

## How to test

1. **Defaults visible** at startup — add a log line temporarily if needed, or
   `docker exec hp1_agent python -c "from api.routers.agent import _AGENT_MAX_WALL_CLOCK_S, _AGENT_MAX_TOTAL_TOKENS, _AGENT_MAX_DESTRUCTIVE, _AGENT_MAX_TOOL_FAILURES; print(_AGENT_MAX_WALL_CLOCK_S, _AGENT_MAX_TOTAL_TOKENS, _AGENT_MAX_DESTRUCTIVE, _AGENT_MAX_TOOL_FAILURES)"`.
   Expect `600 120000 3 8`.

2. **Wall-clock cap (safest to test)** — temporarily set a tiny cap in `.env`:
   ```
   AGENT_MAX_WALL_CLOCK_S=15
   ```
   Restart the agent, run any observe task that usually takes longer than 15s
   (the storage-overview task). The Output should show `HALT: CAP: wall-clock
   cap exceeded`. Check Logs → Actions (v2.31.6): rows exist up to the cap
   point, then stop. Revert the env var.

3. **Token cap** — set `AGENT_MAX_TOTAL_TOKENS=500`, restart, run any task.
   The first step's tokens will exceed 500 and the cap should fire on step 2.

4. **Destructive cap** — set `AGENT_MAX_DESTRUCTIVE=0`, run a task that
   triggers a destructive tool. First destructive call bumps counter to 1,
   next loop iteration trips the cap. Confirm an escalation row is recorded
   and the banner shows it.

5. **Failure cap** — set `AGENT_MAX_TOOL_FAILURES=1`, trigger any task that
   uses `truenas_pool_status` (known to error without API key). Second
   failure should halt.

6. **Revert all env overrides** and confirm normal operation resumes.
