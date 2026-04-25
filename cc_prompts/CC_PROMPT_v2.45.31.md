# CC PROMPT — v2.45.31 — fix(orch): suppress auto-prepended observe step when task explicitly names plan_action

## What this does
Closes the `action-kafka-restart-01` (without-memory) failure from the
v2.45.17 audit ("0 steps · pre_kafka_check blocks entry").

Root cause: `api/agents/orchestrator.py:build_step_plan()` reads the
`_CHECK_PREFIXES` set ({"verify", "check", "ensure", "confirm", "validate",
"first", **"before"**, "after checking", "make sure"}) and, when any of
these words appear anywhere in the task, auto-prepends an "observe"
pre-check step before the action step.

For `action-kafka-restart-01`:
> "perform a rolling restart of kafka brokers — use plan_action to propose
> the restart plan **before** executing kafka_rolling_restart_safe"

The word "before" matches `_CHECK_PREFIXES`. The orchestrator inserts a
pre-check observe step. That observe step calls `pre_kafka_check`, which
returns DEGRADED (worker-03 is down), then `verdict_from_text` sees the
word "degraded" → HALT verdict → action step never runs → `plan_action` is
never called → test fails.

The user is using "before" as a temporal preposition describing the action
sequence ("plan before executing"), not as an instruction for the harness
to insert a separate pre-check. The task already explicitly mentions
`plan_action` — that's a strong signal the user has specified the flow they
want.

Fix: when the task mentions `plan_action` (or `plan first`) explicitly,
skip the auto-prepended observe step. The user has named the gating tool;
the agent will call it as the first action-step tool, which is the correct
flow.

Version bump: 2.45.30 → 2.45.31

---

## Context

`api/agents/orchestrator.py:build_step_plan` currently:

```python
words = set(re.findall(r'\b\w+\b', task.lower()))
is_cleanup = bool(words & _CLEANUP_WORDS)
has_precheck = bool(words & _CHECK_PREFIXES)

if intent in ("execute", "action"):
    steps = []
    if has_precheck or is_cleanup:
        steps.append({...observe step...})
    steps.append({...action step...})
    if is_cleanup:
        steps.append({...verify step...})
```

`pre_kafka_check` returns a degraded result naturally during partial outage,
which is correct. The issue is the auto-prepended step running it as part of
an UPGRADE intent — the agent never gets the chance to plan around the
known-degraded state.

---

## Change 1 — `api/agents/orchestrator.py` — explicit-flow override

Find the `build_step_plan` function. Right after the existing word-set
computation:

```python
    words = set(re.findall(r'\b\w+\b', task.lower()))
    is_cleanup = bool(words & _CLEANUP_WORDS)
    has_precheck = bool(words & _CHECK_PREFIXES)
```

Insert a follow-up rule:

```python
    # v2.45.31 — Skip auto-prepended observe step when the user has named
    # the gating tool explicitly. Tasks like "use plan_action to propose
    # the restart before executing kafka_rolling_restart_safe" use "before"
    # as a temporal preposition about the action sequence, not as a request
    # to insert a separate pre-check. plan_action is itself the gating
    # mechanism; the agent will call it on step 1 of the action.
    #
    # This also covers free-form tasks where the user has already specified
    # an investigation+execute sequence in prose and we should not
    # double-decompose. Cleanup operations still get pre+post observe
    # steps because the verify-after-cleanup signal genuinely needs both.
    _explicit_plan = (
        "plan_action" in (task or "").lower()
        or "plan first" in (task or "").lower()
    )
    if _explicit_plan and not is_cleanup:
        has_precheck = False
```

CC: place the override block immediately AFTER the original
`is_cleanup` / `has_precheck` assignments and BEFORE the
`if intent in ("execute", "action"):` branch. Do not modify the existing
two assignments — the override is a separate, narrowly-scoped step.

---

## Change 2 — sanity-check: log the decision

Find the line at the end of `build_step_plan` that returns `steps`:

```python
    # Number steps
    for i, s in enumerate(steps):
        s["step"] = i + 1

    return steps
```

Right BEFORE the `return steps`, insert:

```python
    # v2.45.31 — Diagnostic log when explicit-plan override fires, so the
    # decision is visible in container logs. Cheap (one info per run).
    if _explicit_plan and not is_cleanup and intent in ("execute", "action"):
        import logging as _log_orch
        _log_orch.getLogger(__name__).info(
            "orchestrator: explicit plan_action mention in task — "
            "skipped auto-prepended observe step (intent=%s)", intent,
        )
```

CC: `_explicit_plan` and `is_cleanup` are in scope here from Change 1.
`intent` is the local variable already in scope.

---

## Change 3 — test-coverage update (optional but recommended)

Add a regression test for this behaviour. CC: locate the test directory
that contains orchestrator tests. Likely `tests/test_orchestrator.py` or
`tests/agents/test_orchestrator.py`. Search:

```bash
grep -rn "build_step_plan\|orchestrator" tests/ 2>/dev/null | head -20
```

If a test file exists for orchestrator, append:

```python
def test_v245_31_explicit_plan_skips_auto_precheck():
    """v2.45.31 — task mentioning plan_action explicitly should not get an
    auto-prepended observe step from the 'before' keyword."""
    from api.agents.orchestrator import build_step_plan
    task = (
        "perform a rolling restart of kafka brokers — use plan_action to "
        "propose the restart plan before executing kafka_rolling_restart_safe"
    )
    steps = build_step_plan(task)
    intents = [s["intent"] for s in steps]
    assert "observe" not in intents, (
        f"Expected no observe pre-step (explicit plan_action in task), "
        f"got {intents}"
    )
    assert intents[0] in ("execute", "action"), (
        f"Expected first step to be execute/action, got {intents}"
    )


def test_v245_31_check_keyword_still_triggers_precheck_when_no_plan():
    """v2.45.31 — the pre-check heuristic still fires when plan_action is
    NOT explicitly mentioned. Don't regress the original behaviour."""
    from api.agents.orchestrator import build_step_plan
    task = "verify kafka health then upgrade kafka-stack_kafka1"
    steps = build_step_plan(task)
    intents = [s["intent"] for s in steps]
    assert "observe" in intents, (
        f"Expected observe pre-step from 'verify' keyword, got {intents}"
    )
```

If no orchestrator test file exists, skip Change 3 — the regression-coverage
gap is a separate concern. Don't create a new test file just for this.

---

## Verify

```bash
python -m py_compile api/agents/orchestrator.py

python -c "
from api.agents.orchestrator import build_step_plan
task = 'perform a rolling restart of kafka brokers — use plan_action to propose the restart plan before executing kafka_rolling_restart_safe'
steps = build_step_plan(task)
print('intents:', [s['intent'] for s in steps])
assert 'observe' not in [s['intent'] for s in steps], 'FAIL — auto pre-check still fires'
print('PASS — explicit plan_action override works')

# Negative control: 'verify' word still triggers
task2 = 'verify kafka health then upgrade kafka-stack_kafka1'
steps2 = build_step_plan(task2)
print('intents2:', [s['intent'] for s in steps2])
assert 'observe' in [s['intent'] for s in steps2], 'FAIL — verify keyword no longer triggers pre-check'
print('PASS — verify keyword still triggers pre-check')
"
```

After deploy, re-run the without-memory variant of the smoke suite:

```bash
# From the dashboard Tests panel: run smoke-mem-off-fast
# Or via API:
curl -X POST http://localhost:8000/api/tests/run \
  -H 'Content-Type: application/json' -b "hp1_auth=$T" \
  -d '{"test_ids": ["action-kafka-restart-01"], "memory_enabled": false}'
```

Expected: `step_count > 0`, `plan_action` appears in `tools_called`,
test passes (or stops cleanly on the user-rejected plan, which is the
expected behaviour given `auto_confirm=False`).

---

## Version bump

Update `VERSION`: `2.45.30` → `2.45.31`

---

## Commit

```
git add -A
git commit -m "fix(orch): v2.45.31 skip auto-prepended observe step when task names plan_action explicitly"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```

After deploy, `action-kafka-restart-01` (without-memory) should reach the
action step, call `plan_action`, and receive the user rejection within the
50s stop window. The test result row will show `step_count >= 1` and
`tools_called` containing `plan_action`.
