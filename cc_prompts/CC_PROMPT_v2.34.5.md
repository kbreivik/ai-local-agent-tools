# CC PROMPT — v2.34.5 — fix(agents): propose_subtask math is unreachable — earlier nudge + dynamic reserve

## Evidence

Live trace 2026-04-17 15:17–15:19 (investigate Logstash→ES writes). Budget=16.
Nudge fired at 12/16 (v2.33.3 @ 70%). Agent called `propose_subtask` at step 8
(tool call #13), `remaining=3`, `reserve=2` → max sub-budget=1, min=2 → refused.
Tried again at step 9, `remaining=1` → refused. Budget exhausted, forced summary.

**Root cause: the nudge fires too late for the spawn math to succeed.** Guaranteed
refuse every time. The v2.33.3 threshold and the v2.34.0 reserve+minimum don't
agree. Either the nudge has to fire earlier, or the reserve has to relax when
the parent has nothing useful left to do.

## Fix — two coupled changes

1. **Drop the `budgetNudgeThreshold` floor** from 0.70 to the point where a
   spawn is still mathematically viable. For an investigate agent (budget=16,
   reserve=2, min_sub_budget=2), a viable spawn needs `remaining >= min + reserve + 1`
   (the +1 is the propose_subtask call itself), so `used <= budget - 5 = 11`,
   i.e. fire at `used/budget = 0.69`. Rounding and leaving headroom:
   **nudge at 60%** (9.6 → fire at used=10). At that point remaining=6, after
   propose_subtask call remaining=5, reserve=2, max sub=3 — viable.

2. **Relax reserve when parent has no DIAGNOSIS.** The whole point of reserve
   is "leave parent budget to synthesise *after* the sub-agent returns."
   If parent hasn't diagnosed anything yet AND is near exhaustion, reserving
   2 is backwards — parent has nothing to do with those slots anyway. Dynamic
   rule in `_handle_propose_subtask`:
   - `diagnosis_seen = True and remaining > reserve` → reserve = 2 (default)
   - `diagnosis_seen = False and budget_used / budget >= 0.60` → reserve = 0
   - otherwise → reserve = min(2, remaining // 3)

Together these ensure: nudge fires early enough that spawn is reachable, and
even if it fires late, the reserve collapses so the spawn still succeeds.

Version bump: 2.34.4 → 2.34.5

---

## Change 1 — api/routers/agent.py — nudge threshold

Locate the v2.33.3 budget-nudge emission (look for `70% threshold reached`
in the log message or `budget_nudge` WS event). Replace the hard-coded 0.70
with a setting:

```python
NUDGE_THRESHOLD = float(settings.get("subagentNudgeThreshold", 0.60))
...
if tools_used >= int(budget * NUDGE_THRESHOLD) and not diagnosis_seen:
    # emit [budget] XX% threshold reached (N/M) without DIAGNOSIS — nudging...
    ...
```

Register the new setting key with default 0.60 in the settings module used by
v2.33.3. Clamp to [0.40, 0.90] at read time to prevent misuse.

Update the log message to interpolate the current threshold:

```python
log = f"[budget] {int(NUDGE_THRESHOLD*100)}% threshold reached ({tools_used}/{budget}) without DIAGNOSIS — nudging agent toward propose_subtask"
```

## Change 2 — _handle_propose_subtask — dynamic reserve

In `_handle_propose_subtask` (v2.34.0, `api/routers/agent.py` or
`api/agents/orchestrator.py`), replace the static reserve lookup:

```python
reserve = int(settings.get("subagentMinParentReserve", 2))
```

with a dynamic computation:

```python
def _dynamic_reserve(parent_task, settings) -> int:
    default_reserve = int(settings.get("subagentMinParentReserve", 2))
    # Relax reserve when parent has nothing to synthesise from
    if not parent_task.last_diagnosis:
        usage_frac = parent_task.tools_used / max(1, parent_task.budget_tools)
        if usage_frac >= 0.60:
            # Parent is late-game and has no diagnosis — no reason to reserve
            return 0
        # Late enough to matter but not quite exhausted — partial reserve
        return min(default_reserve, (parent_task.budget_tools - parent_task.tools_used) // 3)
    return default_reserve

reserve = _dynamic_reserve(parent_task, settings)
```

Emit the reserve value in the refuse message so operators can see what math ran:

```python
return {
    "ok": False,
    "error": (
        f"sub-agent insufficient budget: parent remaining={parent_remaining}, "
        f"reserve={reserve} ({'relaxed' if reserve < default_reserve else 'default'}), "
        f"max_sub={max_sub_budget}, min={2}. Complete this task yourself — do not delegate."
    ),
}
```

## Change 3 — emit nudge counter metric

Add to `api/metrics.py`:

```python
BUDGET_NUDGE_COUNTER = Counter(
    "deathstar_agent_budget_nudges_total",
    "Budget nudges fired by outcome",
    ["outcome"],  # proposed_and_spawned | proposed_and_refused | not_proposed | diagnosis_present
)
```

Increment in the nudge path and in `_handle_propose_subtask`. Lets us measure
how often the nudge actually results in a useful spawn vs. a refuse.

## Change 4 — tests

`tests/test_subagent_budget_math.py`:

```python
@pytest.mark.asyncio
async def test_spawn_viable_when_nudge_fires_at_60_percent(fake_llm, db):
    """At budget=16, nudge at 60% fires at used=10.
    propose_subtask call is #11 → remaining=5 → reserve=2 → max_sub=3 → spawn OK.
    """
    fake_llm.set_script_to_trigger_nudge_and_propose(budget=16, tools_used_before_nudge=10)
    await run_task("test", agent_type="investigate")
    rows = await db.fetch_all("SELECT * FROM subagent_runs")
    assert len(rows) == 1
    assert rows[0]["terminal_status"] == "done"


@pytest.mark.asyncio
async def test_reserve_relaxes_when_no_diagnosis(fake_llm, db):
    """Parent at 70% with no diagnosis → reserve drops to 0 → spawn viable."""
    fake_llm.set_script_late_stage_no_diagnosis(budget=16, tools_used_before_propose=13)
    await run_task("test", agent_type="investigate")
    rows = await db.fetch_all("SELECT * FROM subagent_runs")
    assert len(rows) == 1, "Late-stage spawn without diagnosis must succeed with reserve=0"


@pytest.mark.asyncio
async def test_reserve_holds_when_diagnosis_present(fake_llm, db):
    """Parent emitted DIAGNOSIS section → reserve stays at 2 → tight spawn refused."""
    fake_llm.set_script_with_diagnosis_and_late_propose(budget=16, tools_used_before_propose=14)
    result = await run_task("test", agent_type="investigate")
    rows = await db.fetch_all("SELECT * FROM subagent_runs")
    # Depending on test params, should refuse — parent has diagnosis, no point delegating late
    assert len(rows) == 0
    assert "reserve=2" in result["last_refuse_message"]


def test_nudge_threshold_clamped():
    from api.agents.orchestrator import _resolve_nudge_threshold
    assert _resolve_nudge_threshold({"subagentNudgeThreshold": "0.1"}) == 0.40
    assert _resolve_nudge_threshold({"subagentNudgeThreshold": "0.99"}) == 0.90
    assert _resolve_nudge_threshold({}) == 0.60
```

## Change 5 — backfill the trace

Run a smoke test identical to the 15:17 trace after deploy. Confirm:
- Nudge fires at step 7 (used=10), not step 8 (used=12)
- Sub-agent actually spawns (subagent_runs row written)
- `deathstar_subagent_spawns_total{outcome="spawned"}` increments
- Parent receives sub-agent output and resumes

## Version bump
Update `VERSION`: 2.34.4 → 2.34.5

## Commit
```
git add -A
git commit -m "fix(agents): v2.34.5 propose_subtask math now reachable — nudge at 60% + dynamic reserve"
git push origin main
```
