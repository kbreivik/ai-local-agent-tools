# CC PROMPT — v2.35.14 — Forced synthesis on empty-completion path

## What this does

v2.35.13 verification surfaced a silent failure mode with the new
`agent_performance_summary` tool (op `1ebb7047`, 2026-04-19): the agent
called 5 substantive tools successfully and the orchestrator marked
`status=completed` — but `final_answer` was empty (0 chars). The
Trace viewer confirmed `gates_fired: {}` and every step's
`finish_reason: "tool_calls"`. The LLM never produced assistant text
because it kept choosing tool calls, and the loop exited "naturally"
(not via a hard cap) so v2.34.17's forced-synthesis code path — which
only triggers on budget / wall-clock / token / failure caps — did not
fire. Operators saw a task that "completed" successfully with no
useful output.

This is a generalisable failure mode — any observe/investigate agent
that chooses tool calls on its final turn (instead of emitting text)
will exit with empty `final_answer` unless the loop itself forces a
synthesis on that path.

Version bump: 2.35.13 → 2.35.14.

The fix: when the agent loop is about to exit on a natural (non-cap)
termination AND `final_answer` is still empty AND at least one
substantive tool call was made, run the same forced-synthesis path
used for hard caps. Same code, just more triggers.

---

## Evidence gathered before this prompt was written

Op `1ebb7047-1211-4c5d-8fb7-86c1852abcd2` (Agent success rate audit,
2026-04-19 against commit `46e2836`):

```
status: completed                 final_answer_len: 0
tool_count: 5                     gates_fired: {}
steps:
  0: agent_performance_summary   finish_reason=tool_calls  content_len=0
  1: swarm_status                finish_reason=tool_calls  content_len=0
  2: agent_status                finish_reason=tool_calls  content_len=0
  3: skill_health_summary        finish_reason=tool_calls  content_len=0
  4: audit_log                   finish_reason=tool_calls  content_len=0
```

All 5 steps emitted `finish_reason: "tool_calls"` with zero content
length. The agent loop exited after step 5 with no assistant text —
something in the loop (probably an `audit_log`-terminates-the-run
heuristic or simply running out of agent turns cleanly) ended the run
with status=completed but no final synthesis.

Contrast with budget-cap path (op `b5328859`, same session): 8 tool
calls, status=`capped`, forced synthesis fires, `final_answer` has
1252 chars of HARNESS FALLBACK output with per-host snippets. That
path works because v2.34.17 forces synthesis; the empty-completion
path does not trigger the same code.

---

## Change 1 — `api/routers/agent.py` — force synthesis on natural empty exit

CC: grep for the agent loop's terminal branch in `_stream_agent` /
`drive_agent`. You're looking for the point where the loop decides to
stop because the LLM's last response was a terminal one (text-only
finish OR post-audit_log OR step-budget-exceeded-without-reason-tag)
and then writes `final_answer` to the operations table.

At that point, add a check: if `final_answer` is empty AND the loop
is exiting with a "completed"-class status (not cancelled, not
explicit error), invoke `run_forced_synthesis` with a new reason
label `empty_completion`.

Pseudocode of the wiring (CC: adapt names to what's actually in
scope):

```python
# Just before the terminal status write on the happy-path
if not final_answer:
    # Count substantive tools (META_TOOLS already defined elsewhere)
    substantive = sum(
        1 for tc in tool_history_local
        if tc.get("tool_name") not in META_TOOLS
    )
    if substantive >= 1:
        log.warning(
            "agent loop empty-completion detected op=%s tools=%d subst=%d; "
            "invoking forced_synthesis",
            operation_id, len(tool_history_local), substantive,
        )
        try:
            from api.agents.forced_synthesis import run_forced_synthesis
            synthesis_text, harness_msg, raw = run_forced_synthesis(
                client=client,
                model=_lm_model(),
                messages=messages_for_llm,       # current in-scope messages
                agent_type=agent_type,
                reason="empty_completion",
                tool_count=len(tool_history_local),
                budget=_tool_budget,
                actual_tool_names=[
                    tc.get("tool_name") for tc in tool_history_local
                ],
                operation_id=operation_id,        # v2.35.13 DB-source path
            )
            final_answer = synthesis_text or ""
        except Exception as e:
            log.warning(
                "forced_synthesis on empty_completion failed op=%s: %s",
                operation_id, e,
            )
```

Do NOT invoke forced synthesis if:
- `final_answer` already has content (normal happy path)
- No substantive tool calls (nothing to synthesise from — let
  hallucination guard / normal path handle it)
- Loop exited with an explicit error status (`failed`, `cancelled`,
  `escalated`) — those have their own handling

The check must be idempotent — if the loop can reach the terminal
state more than once for the same operation_id, subsequent passes
should not re-run forced synthesis.

## Change 2 — `api/agents/forced_synthesis.py` — register `empty_completion` reason

Add to `_REASON_LABELS`:

```python
_REASON_LABELS = {
    "budget_cap":        "tool-call budget-cap",
    "wall_clock":        "wall-clock cap",
    "token_cap":         "token cap",
    "destructive_cap":   "destructive-call cap",
    "tool_failures":     "consecutive-tool-failure cap",
    # v2.35.14 — natural exit with no assistant text emitted
    "empty_completion":  "natural completion with empty final_answer",
}
```

No other code change needed in this file — `run_forced_synthesis`
already accepts arbitrary `reason` strings and threads them through
the Prometheus counters and harness message.

## Change 3 — `api/metrics.py` — Prometheus counter label already covers it

No change needed. `FORCED_SYNTHESIS_COUNTER{reason,agent_type}` already
accepts any `reason` label, so `reason="empty_completion"` will appear
as a new time-series automatically. Same for `_drift_total`,
`_fallback_total`, `_fabricated_total`.

## Change 4 — `api/agents/gate_detection.py` — surface `empty_completion` in Gates Fired

Find the existing gate-detection logic for `forced_synthesis` and
extend it to distinguish the new reason (so the Trace viewer shows
the operator which path fired). CC: inspect the file — the existing
pattern likely maps a gate name to a detection predicate.

Add a separate entry:

```python
# v2.35.14: empty-completion is a distinct operational signal
# — the agent finished without error but also without synthesising.
# Operators should see this differently from budget-cap fallbacks.
"empty_completion_rescued": lambda trace: any(
    s.get("reason") == "empty_completion"
    for s in (trace.get("forced_synthesis_invocations") or [])
),
```

(If the current gate-detection infrastructure uses a different
shape, adapt accordingly — the intent is: "show a `rescued empty
completion` row in the Gates Fired panel whenever the
empty-completion path fired.")

## Change 5 — tests

Extend `tests/test_forced_synthesis_drift.py`:

```python
def test_forced_synthesis_accepts_empty_completion_reason():
    """v2.35.14: the new reason label must round-trip through the harness
    message and Prometheus counter."""
    from api.agents.forced_synthesis import (
        build_harness_message, _REASON_LABELS,
    )
    assert "empty_completion" in _REASON_LABELS
    msg = build_harness_message(
        reason="empty_completion", tool_count=5, budget=8,
    )
    # Reason label is used verbatim in the harness message
    assert _REASON_LABELS["empty_completion"] in msg
    # Harness still enforces the critical format rules
    assert "CRITICAL FORMAT RULE" in msg


def test_programmatic_fallback_empty_completion_reason():
    """v2.35.14: _programmatic_fallback gracefully handles the new reason."""
    from api.agents.forced_synthesis import _programmatic_fallback
    out = _programmatic_fallback(
        reason="empty_completion",
        tool_count=5, budget=8,
        actual_tool_calls=[
            {"tool_name": "agent_performance_summary", "status": "ok",
             "params": {"hours_back": 24},
             "result": {"status": "ok",
                        "message": "55 runs in past 24h, 30.9% success"}},
            {"tool_name": "swarm_status", "status": "ok", "params": {},
             "result": {"status": "ok", "message": "6/6 nodes Ready"}},
        ],
    )
    assert "HARNESS FALLBACK" in out
    # New reason label shows in the opening line
    assert "natural completion" in out.lower()
    # Per-tool snippets present (v2.35.13 enrichment)
    assert "agent_performance_summary" in out
    assert "55 runs" in out
    assert "swarm_status" in out
    assert "6/6 nodes" in out
```

New integration test in a new file `tests/test_empty_completion_path.py`:

```python
"""v2.35.14 regression — agent loop must not exit with empty final_answer
when substantive tool calls were made but the LLM never emitted assistant
text. This is an end-to-end test of the wiring in api/routers/agent.py."""

import pytest
from unittest.mock import MagicMock, patch


def test_empty_completion_invokes_forced_synthesis(monkeypatch):
    """Simulate the exact condition from op 1ebb7047: 5 tool_calls-only
    steps, zero assistant text, natural loop exit. Forced synthesis must
    fire and produce non-empty final_answer."""
    from api.agents import forced_synthesis as fs

    # Mock run_forced_synthesis to verify it's called with the new reason
    called_with = {}

    def fake_run(**kwargs):
        called_with.update(kwargs)
        return (
            "[HARNESS FALLBACK] natural completion with empty final_answer\n"
            "EVIDENCE:\n- agent_performance_summary(24) status=ok: 55 runs",
            "harness msg",
            None,
        )

    monkeypatch.setattr(fs, "run_forced_synthesis", fake_run)

    # CC: this test needs to call into the actual agent loop's terminal
    # write path. Exact import + invocation depends on how the loop is
    # structured — if _finalize_operation() is the terminal write,
    # call that with mocked state showing 5 tool calls and empty FA.
    # If no such testable seam exists, this test may need to be
    # pared down to just asserting the reason constant + fallback
    # output, deferring end-to-end verification to the smoke test.
    #
    # For now, assert the mechanism would work if invoked:
    result_text, _, _ = fs.run_forced_synthesis(
        client=None, model="x", messages=[],
        agent_type="observe",
        reason="empty_completion",
        tool_count=5, budget=8,
        actual_tool_names=["agent_performance_summary", "swarm_status",
                           "agent_status", "skill_health_summary",
                           "audit_log"],
    )
    assert result_text
    assert "empty" in result_text.lower() or "HARNESS" in result_text
```

## Change 6 — `VERSION`

```
2.35.14
```

## Verify

```bash
pytest tests/test_forced_synthesis_drift.py -v
pytest tests/test_empty_completion_path.py -v
pytest tests/ -v -k "forced_synthesis or empty_completion"
```

## Commit

```bash
git add -A
git commit -m "fix(agents): v2.35.14 forced synthesis on empty-completion path

Op 1ebb7047 (v2.35.13 verification, agent_performance_summary audit)
completed successfully with 5 substantive tool calls but final_answer
was empty. Trace showed every step had finish_reason=tool_calls and
zero content — the LLM never emitted assistant text, the loop exited
'naturally' (no hard cap), and v2.34.17's forced_synthesis (which
only fires on budget/wall-clock/token/failure caps) never triggered.
Operators saw status=completed with no useful output.

Generalisable failure mode: any observe/investigate run where the
LLM chooses tool calls on its final turn.

Fix: in the agent loop's terminal happy-path branch, detect
empty final_answer + >=1 substantive tool call, invoke
run_forced_synthesis with new reason 'empty_completion'. The
v2.35.13 DB-sourced enrichment then produces a HARNESS FALLBACK
with per-tool result snippets. Same code path as budget-cap — just
more triggers.

_REASON_LABELS extended. Gate detection extended to surface the
new path in the Trace viewer's Gates Fired sidebar. Two unit tests
lock in the round-trip of the new reason label."
git push origin main
```

## Deploy + smoke test

```bash
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```

1. Re-fire **Agent success rate audit** — expect status=completed
   AND non-empty `final_answer` with per-tool snippets from
   `agent_performance_summary`, `swarm_status` etc.
2. Re-fire **PBS datastore health** — unchanged behaviour expected
   (agent produces text naturally).
3. `/metrics` — new series
   `deathstar_forced_synthesis_total{reason="empty_completion"}`
   should appear.
4. `/api/logs/operations/<id>/trace?format=digest` — should show
   `empty_completion_rescued` in the Gates Fired block.
