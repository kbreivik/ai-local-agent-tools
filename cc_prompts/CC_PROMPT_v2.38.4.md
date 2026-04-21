# CC PROMPT — v2.38.4 — External AI failure visibility

## What this does

Closes a UX gap surfaced while diagnosing v2.38.3's ciphertext bug. When
`_maybe_route_to_external_ai` raises `ExternalAIError` (auth, network,
timeout), the DB-side bookkeeping already works (`write_external_ai_call`
+ `record_escalation` both fire, `operations.status` is set to
`escalation_failed`), but the WebSocket broadcast at three different
call sites in `api/routers/agent.py` still emits `type="done"` with
`status="ok"` and the stale local `last_reasoning` text from the
forced-synthesis fallback that preceded the external call. Operator
sees a successful-looking done event and the local fallback text; no
error indication; Logs → Escalations row IS there but the UI surface
the operator is looking at says the opposite.

Kent's report (post-v2.38.2 deploy): "hit budget on tool call, and
moved externally, I approved but then it dropped dead, and no log in
escalations". The "dropped dead" was the UI showing "done" with the
stale pre-escalation text; "no log in escalations" was the
pre-v2.37.1 split-brain view OR the UI simply not indicating that an
escalation had been recorded for this run.

### Three call sites

All three are in `api/routers/agent.py`, inside `_run_single_agent_step`:

1. **Budget-exhaustion path** — around line 1553 — the one Kent hit.
   Caller was the `_tool_budget` exhaustion branch. Catches as generic
   Exception.
2. **Hallucination-guard-exhausted path** — around line 1876. Catches
   as generic Exception, sets `final_status="escalation_failed"`.
3. **Fabrication-guard-exhausted path** — around line 2011. Same shape.

Each catches with `except Exception as _re:` — logs a warning with
`log.warning("external AI routing failed: %s", _re)` which goes to
docker logs but not to the operator's browser — then falls through
to the broadcast block which emits `type="done"` + `status="ok"`.

### Fix

Three surgical edits to the three except blocks:

1. **Louder logging.** Upgrade `log.warning(...)` to a structured
   multi-line warning that includes `session_id`, `operation_id`,
   error class name, and error message. Still goes to docker only,
   but `grep -i 'EXTERNAL_AI_ROUTE_FAIL'` will find it instantly.
   One grep pattern, three call sites, same format.
2. **Surface the failure to the UI.** Set a local
   `_external_ai_route_error` string in the except block. At the
   broadcast block below, when this variable is truthy, emit
   `type="done"` with `status="failed"` (not `"ok"`), `reason="escalation_failed"`,
   and prepend a short `[EXTERNAL AI FAILED: <reason>]` line to the
   `content` so the operator sees BOTH the last local output AND the
   fact that the external escalation failed. Without this the UI has
   no indication whatsoever that anything went wrong.
3. **Harness trace line.** Emit a `manager.send_line("halt", ...)`
   message inside the except block so the failure also appears in
   the live-output stream, not just the final done event. The
   `halt` prefix already has amber styling in AgentFeed.

No schema changes. No new Settings. No new deps. Three near-identical
edits in one file.

Version bump: 2.38.3 → 2.38.4 (`.x.4` — UX visibility patch, same
subsystem as v2.38.3).

---

## Change 1 — `api/routers/agent.py`, budget-exhaustion block

Find the block around line 1532:

```python
                # v2.36.3 — budget_exhaustion rule check
                try:
                    _router_synth = await _maybe_route_to_external_ai(
                        session_id=session_id,
                        operation_id=operation_id,
                        task=task,
                        agent_type=agent_type,
                        messages=messages,
                        tool_calls_made=len(tools_used_names),
                        tool_budget=_tool_budget,
                        diagnosis_emitted="DIAGNOSIS:" in (last_reasoning or ""),
                        consecutive_tool_failures=_tool_failures,
                        halluc_guard_exhausted=(_halluc_guard_attempts >= _halluc_guard_max),
                        fabrication_detected_count=(1 if _fabrication_detected_once else 0),
                        external_calls_this_op=0,
                        scope_entity=parent_session_id or "",
                        is_prerun=False,
                        prior_failed_attempts_7d=0,
                    )
                    if _router_synth:
                        last_reasoning = _router_synth
                except Exception as _re:
                    # Halt-on-failure: mark status and fall through
                    log.warning("external AI routing failed: %s", _re)
                    final_status = "escalation_failed"

                if is_final_step:
                    choices = _extract_choices(last_reasoning) if last_reasoning else None
                    await manager.broadcast({
                        "type": "done", "session_id": session_id, "agent_type": agent_type,
                        "content": last_reasoning or f"Agent reached tool budget ({_tool_budget}).",
                        "status": "ok", "choices": choices or [],
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                break
```

Replace with:

```python
                # v2.36.3 — budget_exhaustion rule check
                _external_ai_route_error = ""  # v2.38.4 — surface escalation failures to UI
                try:
                    _router_synth = await _maybe_route_to_external_ai(
                        session_id=session_id,
                        operation_id=operation_id,
                        task=task,
                        agent_type=agent_type,
                        messages=messages,
                        tool_calls_made=len(tools_used_names),
                        tool_budget=_tool_budget,
                        diagnosis_emitted="DIAGNOSIS:" in (last_reasoning or ""),
                        consecutive_tool_failures=_tool_failures,
                        halluc_guard_exhausted=(_halluc_guard_attempts >= _halluc_guard_max),
                        fabrication_detected_count=(1 if _fabrication_detected_once else 0),
                        external_calls_this_op=0,
                        scope_entity=parent_session_id or "",
                        is_prerun=False,
                        prior_failed_attempts_7d=0,
                    )
                    if _router_synth:
                        last_reasoning = _router_synth
                except Exception as _re:
                    # v2.38.4 — louder logging + UI surface. Previous code
                    # logged a single-line warning and fell through silently
                    # to a done/ok broadcast, which masked real failures
                    # (esp. auth 401s from the pre-v2.38.3 ciphertext bug).
                    log.warning(
                        "EXTERNAL_AI_ROUTE_FAIL rule=budget_exhaustion "
                        "session=%s operation=%s err_class=%s err=%s",
                        session_id, operation_id, type(_re).__name__, _re,
                    )
                    _external_ai_route_error = (
                        f"{type(_re).__name__}: {str(_re)[:240]}"
                    )
                    final_status = "escalation_failed"
                    try:
                        await manager.send_line(
                            "halt",
                            f"[external-ai] route failed — {_external_ai_route_error}",
                            status="failed", session_id=session_id,
                        )
                    except Exception:
                        pass

                if is_final_step:
                    choices = _extract_choices(last_reasoning) if last_reasoning else None
                    if _external_ai_route_error:
                        _done_status = "failed"
                        _done_content = (
                            f"[EXTERNAL AI ESCALATION FAILED: {_external_ai_route_error}]\n\n"
                            f"{last_reasoning or f'Agent reached tool budget ({_tool_budget}).'}"
                        )
                        _done_reason = "escalation_failed"
                    else:
                        _done_status = "ok"
                        _done_content = last_reasoning or f"Agent reached tool budget ({_tool_budget})."
                        _done_reason = None
                    _payload = {
                        "type": "done", "session_id": session_id, "agent_type": agent_type,
                        "content": _done_content,
                        "status": _done_status, "choices": choices or [],
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    if _done_reason:
                        _payload["reason"] = _done_reason
                    await manager.broadcast(_payload)
                break
```

---

## Change 2 — `api/routers/agent.py`, hallucination-guard-exhausted block

Find the similar block around line 1840, currently ending with
`final_status = "escalation_failed"` followed by an `if is_final_step:`
broadcast with `"status": "failed"` (this branch actually uses
`status=failed` already, but hard-codes `reason="hallucination_guard_exhausted"`
and does not surface the external-AI sub-reason when routing also
failed).

Current shape (around line 1846-1900):

```python
                        # v2.36.3 — gate_failure router rule
                        try:
                            _router_synth = await _maybe_route_to_external_ai(
                                session_id=session_id,
                                operation_id=operation_id,
                                task=task,
                                agent_type=agent_type,
                                messages=messages,
                                tool_calls_made=len(tools_used_names),
                                tool_budget=_tool_budget,
                                diagnosis_emitted=False,
                                consecutive_tool_failures=_tool_failures,
                                halluc_guard_exhausted=True,
                                fabrication_detected_count=(2 if _fabrication_detected_once else 0),
                                external_calls_this_op=0,
                                scope_entity=parent_session_id or "",
                                is_prerun=False,
                            )
                            if _router_synth:
                                last_reasoning = _router_synth
                                final_status = "completed"
                                if is_final_step:
                                    await manager.broadcast({
                                        "type":       "done",
                                        ...
```

The existing code does surface `status="failed"` on the outer branch
(hallucination guard exhaustion is always a failure). What we need
to add is the `EXTERNAL_AI_ROUTE_FAIL` log + `halt` line-send so
operators can tell that the external-AI rescue ALSO failed, not just
that the local guard exhausted.

Locate the `except Exception as _re:` block currently containing:

```python
                        except Exception as _re:
                            log.warning("external AI routing on gate failure: %s", _re)
                            final_status = "escalation_failed"
```

Replace with:

```python
                        except Exception as _re:
                            # v2.38.4 — louder logging + UI surface
                            log.warning(
                                "EXTERNAL_AI_ROUTE_FAIL rule=gate_failure "
                                "agent=%s session=%s operation=%s err_class=%s err=%s",
                                "halluc_guard", session_id, operation_id,
                                type(_re).__name__, _re,
                            )
                            try:
                                await manager.send_line(
                                    "halt",
                                    f"[external-ai] rescue route failed — "
                                    f"{type(_re).__name__}: {str(_re)[:200]}",
                                    status="failed", session_id=session_id,
                                )
                            except Exception:
                                pass
                            final_status = "escalation_failed"
```

Do the same in the fabrication-guard-exhausted branch's identical
`except Exception as _re:` (around line 2011). Use
`rule=gate_failure agent=fabrication_guard` in the log message so the
two sub-rules are distinguishable in grep.

---

## Change 3 — `VERSION`

```
2.38.4
```

---

## Change 4 — Tests

### NEW `tests/test_external_ai_route_failure_ux.py`

Structural guards — no runtime. Pure file parsing.

```python
"""v2.38.4 — Visibility guards for external AI routing failures.

When _maybe_route_to_external_ai raises, three different call sites
must log loudly with the EXTERNAL_AI_ROUTE_FAIL prefix, send a halt
line, and (at the budget-exhaustion site) broadcast done with
status='failed' + reason='escalation_failed' instead of masking the
failure as ok.
"""
from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).parent.parent
AGENT_ROUTER = REPO_ROOT / "api" / "routers" / "agent.py"


def _src() -> str:
    return AGENT_ROUTER.read_text(encoding="utf-8")


def test_loud_log_prefix_appears_for_each_rule():
    """Every except block catching a _maybe_route_to_external_ai
    failure must log with the EXTERNAL_AI_ROUTE_FAIL prefix so
    operators can grep docker logs."""
    src = _src()
    occurrences = src.count("EXTERNAL_AI_ROUTE_FAIL")
    assert occurrences >= 3, (
        f"Expected >=3 EXTERNAL_AI_ROUTE_FAIL log prefixes (one per "
        f"call site — budget_exhaustion, halluc_guard, fabrication), "
        f"found {occurrences}. Grep for 'EXTERNAL_AI_ROUTE_FAIL' in "
        f"api/routers/agent.py."
    )


def test_budget_exhaustion_path_surfaces_failure_to_ui():
    """The budget-exhaustion call site must emit status='failed' +
    reason='escalation_failed' when external routing raises, not a
    stale done/ok."""
    src = _src()
    # The budget-exhaustion path is the ONE that previously always
    # emitted status="ok" regardless of routing success.
    assert "_external_ai_route_error" in src, (
        "Missing _external_ai_route_error sentinel — budget-exhaustion "
        "except block must capture the failure for the broadcast block "
        "below to surface it."
    )
    # The content block must prepend [EXTERNAL AI ESCALATION FAILED:
    assert "EXTERNAL AI ESCALATION FAILED" in src, (
        "Content block must prepend '[EXTERNAL AI ESCALATION FAILED: "
        "...]' when _external_ai_route_error is truthy (v2.38.4)."
    )
    # And the status must flip to failed
    assert re.search(
        r'_done_status\s*=\s*"failed"', src,
    ), "status='failed' not set on external-AI failure path"


def test_halt_line_sent_on_external_ai_failure():
    """Every except block must send a 'halt' line to the live-output
    stream so the failure shows up in AgentFeed, not just the final
    done event."""
    src = _src()
    # Pattern: within 400 chars after a line that logs
    # EXTERNAL_AI_ROUTE_FAIL, there must be a manager.send_line("halt",
    # reference.
    matches = list(re.finditer(r"EXTERNAL_AI_ROUTE_FAIL", src))
    assert len(matches) >= 3, "need >=3 log sites to check halt lines"
    for m in matches:
        window = src[m.start(): m.start() + 1200]
        assert 'send_line' in window and '"halt"' in window, (
            f"halt line-send missing within 1200 chars of "
            f"EXTERNAL_AI_ROUTE_FAIL log (char {m.start()})"
        )


def test_no_silent_fallthrough_warning_remains():
    """The old 'external AI routing failed: %s' shape was the silent
    fallthrough. The v2.38.4 upgrade replaces it with structured
    EXTERNAL_AI_ROUTE_FAIL. Catch regressions if someone copy-pastes
    the old pattern back in."""
    src = _src()
    # The old format string was 'external AI routing failed: %s' with
    # NO context. After v2.38.4 every such call has the loud prefix
    # plus session+operation identifiers. If the bare phrase reappears
    # somewhere new, fail.
    # Tolerance: the exact old one-line call has been replaced so
    # count should be zero. Future refactors that want to log in this
    # area must use the EXTERNAL_AI_ROUTE_FAIL prefix.
    bare = src.count('"external AI routing failed: %s"')
    assert bare == 0, (
        f"Found {bare} uses of the old silent 'external AI routing "
        f"failed: %s' log shape — replace with structured "
        f"EXTERNAL_AI_ROUTE_FAIL log including session/operation ids."
    )
```

---

## Verify

```bash
# Fix applied at all three sites
grep -c 'EXTERNAL_AI_ROUTE_FAIL' api/routers/agent.py   # >=3

# Old silent-warning shape gone
grep -c '"external AI routing failed: %s"' api/routers/agent.py   # 0

# New sentinel + content prefix
grep -n '_external_ai_route_error' api/routers/agent.py   # >=3
grep -n 'EXTERNAL AI ESCALATION FAILED' api/routers/agent.py   # >=1

# Tests pass
pytest tests/test_external_ai_route_failure_ux.py -v

# v2.38.3 tests still pass (should — independent files)
pytest tests/test_external_ai_client_decrypts_key.py -v
pytest tests/test_no_raw_backend_read_of_sensitive_keys.py -v
```

---

## Commit

```bash
git add -A
git commit -m "fix(ui): v2.38.4 surface external AI routing failures instead of masking as done/ok

Kent hit budget cap, routed to Claude, approved the confirmation, then
the UI showed what looked like a successful done event with the local
forced_synthesis text and no error indication. Under the hood:
v2.36.3's ExternalAIAuthError (pre-v2.38.3 ciphertext bug) fired,
record_escalation + write_external_ai_call both wrote correctly, and
operations.status went to escalation_failed in the DB. But the three
call sites of _maybe_route_to_external_ai in api/routers/agent.py all
caught the exception with 'except Exception as _re: log.warning(...);
final_status = escalation_failed' and fell through to a broadcast
that hard-coded type='done' + status='ok'. Failure was invisible to
the operator. 'No log in escalations' was in part this — the row was
there, but the UI masked the fact that an escalation had been
recorded for this run.

Fix: three edits to the three except blocks.

1. Replace the bare log.warning with a structured
   'EXTERNAL_AI_ROUTE_FAIL rule=... session=... operation=... err_class=...
   err=...' log prefix so operators can grep docker logs with a single
   token.

2. At the budget-exhaustion site (the one Kent hit), capture the
   error into _external_ai_route_error and prepend '[EXTERNAL AI
   ESCALATION FAILED: ...]' to the done content; flip the broadcast
   status from 'ok' to 'failed' and add reason='escalation_failed'
   so the UI can render it distinctly from a normal completion.

3. At all three sites, send a 'halt' line to the live-output stream
   via manager.send_line so the failure also shows in AgentFeed, not
   just the final done event. The existing amber styling on halt-
   prefixed messages then flags the failure in-stream.

No schema changes, no new Settings keys, no new deps. All changes
in api/routers/agent.py. 4 structural tests in
tests/test_external_ai_route_failure_ux.py lock in the loud-log
prefix count (>=3), the sentinel variable + content prefix + status
flip at the budget-exhaustion site, the halt line-send near each log
call, and absence of the legacy silent-warning shape.

Pairs with v2.38.3 (the ciphertext fix that eliminates the
ExternalAIAuthError in the first place). v2.38.3 makes the external
call succeed; v2.38.4 makes any residual failure visible instead of
silent."
git push origin main
```

---

## Deploy + smoke

```bash
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```

Smoke plan depends on v2.38.3 being shipped first. Two variants:

1. **v2.38.3 shipped, external AI now succeeds.** Trigger a budget
   cap, approve the confirmation, verify the external call completes
   and `[EXTERNAL: claude/...]` prefix appears on the final_answer.
   v2.38.4 changes are dormant (no failure path exercised) but still
   visible in the source.

2. **Simulate a v2.38.4 failure path without rolling back v2.38.3.**
   Temporarily blank out `externalApiKey` via Settings (or set it to
   garbage that will 401). Trigger a budget cap, approve the
   confirmation, verify:
   - Live output stream shows `[external-ai] route failed — ExternalAIAuthError: ...`
   - Final done event shows up in Output with red/failed styling
     (not green/ok) and the content starts with `[EXTERNAL AI
     ESCALATION FAILED: ...]`
   - `docker logs hp1_agent --since 10m 2>&1 | grep EXTERNAL_AI_ROUTE_FAIL`
     returns one line with session + operation IDs
   - Logs → Escalations shows a new critical row
   - Logs → External AI Calls shows an auth_error row
   Then restore the valid API key.

---

## Scope guard — DO NOT TOUCH

- `api/agents/external_ai_client.py` — v2.38.3's domain.
- `api/agents/external_router.py`, `external_ai_confirmation.py` —
  unchanged.
- `record_escalation`, `write_external_ai_call` — already correct,
  not in scope.
- The hallucination-guard and fabrication-detector exhaustion logic
  itself — only the tiny except block around the router call touches.
- Frontend — WebSocket `status`/`reason` fields already handled
  by AgentFeed; no frontend change needed. (If `reason` rendering
  is ugly, that's v2.38.5 polish, not v2.38.4.)

---

## Followups (not v2.38.4)

- v2.38.5 could add a counter `deathstar_external_ai_route_failures_total{rule,err_class}`
  so auth drifts, timeouts, and network errors become alertable.
- Consider making the external AI failure banner persistent in the
  UI until dismissed, similar to EscalationBanner — not just a
  transient done event.
- Audit the prerun (complexity_prefilter) external-AI call site
  at ~line 4212 — it catches exceptions too but via a different
  pattern (`log.debug("prerun external route check failed")` — debug,
  not warning, and no UI surface). If this path fires in production,
  upgrade similarly.
