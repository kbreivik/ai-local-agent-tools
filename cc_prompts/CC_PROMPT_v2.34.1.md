# CC PROMPT — v2.34.1 — feat(agents): coordinator uses agent_attempts for starting-tool selection

## What this does

Two agent-intelligence components currently don't talk:

- **v2.10.0 coordinator** runs between agent steps, examining verdicts and
  deciding whether to continue.
- **v2.32.3 agent_attempts** records every (entity, task, agent_type, tools_used,
  terminal_status) tuple.

Result: on repeat investigations of the same entity, the agent has no memory of
what it (or a previous run) already tried. It re-walks the same tool chain and
burns budget re-discovering dead ends.

This change makes the coordinator read `agent_attempts` at task start and inject
a compact summary of the last 3 attempts on the scope entity into the system
prompt. The agent can then explicitly avoid repeating the same opening moves,
especially when those moves previously hit a dead end (zero results, tool
refusal, hard-cap).

Version bump: 2.34.0 → 2.34.1

---

## Design

### Injection format

Before the task message, prepend a new prompt section (only when ≥1 prior
attempt exists for this scope_entity within the last 7 days):

```
═══ PRIOR ATTEMPTS ON THIS ENTITY ═══
3 previous tasks attempted this entity in the last 7 days:

[2026-04-15 08:22 UTC] investigate — kafka-broker-3 stuck
  outcome: done · tools(4): kafka_topic_inspect, service_placement,
    swarm_node_status, kafka_exec
  diagnosis: "worker-03 VM down — broker 3 unschedulable"

[2026-04-15 14:10 UTC] execute — recover worker-03
  outcome: done · tools(5): proxmox_vm_power, swarm_node_status ×3,
    kafka_topic_inspect
  diagnosis: "node Ready, ISR restored"

[2026-04-17 09:39 UTC] investigate — search ES for errors
  outcome: timeout_cap · tools(16): elastic_search_logs ×12, ...
  diagnosis: (none emitted — hit budget)

GUIDANCE:
  - Do not repeat the exact tool sequence from a done-outcome attempt unless
    you have a specific reason. Start from the last diagnosis.
  - If a prior attempt timed out at a specific tool, consider an alternative
    first (e.g. log_timeline instead of raw elastic_search_logs).
  - If a prior diagnosis resolved the problem but it's back, state that
    explicitly in your final_answer.
```

### When to inject

- Only when `scope_entity` is non-null (task has an entity focus).
- Only for agent_type ∈ {investigate, execute}. Observe is quick anyway; build
  is orthogonal.
- Cap at 3 attempts to keep prompt bloat minimal.
- Window: 7 days — older attempts are usually stale.
- Skip injection when all 3 attempts had `terminal_status='done'` AND
  current task is same agent_type — interpret as "routine successful op, no
  hint needed".

---

## Change 1 — api/agents/orchestrator.py (or wherever coordinator lives)

Add an async helper and call it from the task-initialisation path:

```python
async def fetch_prior_attempts(scope_entity: str, agent_type: str,
                                limit: int = 3, window_days: int = 7) -> list[dict]:
    """
    Fetch up to `limit` most-recent agent_attempts for this scope_entity
    within the last `window_days`, regardless of agent_type (cross-type
    context is useful — investigate informs execute and vice versa).
    """
    if not scope_entity:
        return []
    eng = get_engine()
    since = datetime.utcnow() - timedelta(days=window_days)
    async with eng.connect() as c:
        r = await c.execute("""
            SELECT created_at, agent_type, objective, terminal_status,
                   tools_used_count, tools_used_list, diagnosis, was_proposal
            FROM agent_attempts
            WHERE scope_entity = :eid AND created_at >= :since
            ORDER BY created_at DESC
            LIMIT :limit
        """, {"eid": scope_entity, "since": since, "limit": limit})
        return [dict(r) for r in r.mappings().all()]


def format_attempts_for_prompt(attempts: list[dict], agent_type: str) -> str:
    """
    Render the attempts as a system-prompt-ready section.
    Returns '' if the list is empty OR all attempts are same-type and succeeded
    (skip noisy injection for routine ops).
    """
    if not attempts:
        return ""

    all_same_and_done = (
        all(a["agent_type"] == agent_type for a in attempts) and
        all(a["terminal_status"] == "done" for a in attempts)
    )
    if all_same_and_done and len(attempts) >= 3:
        return ""  # routine — skip the noise

    lines = ["═══ PRIOR ATTEMPTS ON THIS ENTITY ═══"]
    lines.append(f"{len(attempts)} previous task{'s' if len(attempts) != 1 else ''} "
                 f"attempted this entity in the last 7 days:\n")
    for a in attempts:
        ts = a["created_at"].strftime("%Y-%m-%d %H:%M UTC")
        tools_str = ", ".join((a.get("tools_used_list") or [])[:6])
        if (a.get("tools_used_count") or 0) > 6:
            tools_str += f", ... (+{a['tools_used_count'] - 6} more)"
        lines.append(f"[{ts}] {a['agent_type']} — {a['objective'][:80]}")
        lines.append(f"  outcome: {a['terminal_status']} · "
                     f"tools({a.get('tools_used_count') or 0}): {tools_str or '—'}")
        diag = (a.get("diagnosis") or "").strip()
        if diag:
            lines.append(f"  diagnosis: \"{diag[:160]}\"")
        else:
            lines.append(f"  diagnosis: (none emitted)")
        lines.append("")

    lines.append("GUIDANCE:")
    lines.append("  - Do not repeat the exact tool sequence from a done-outcome "
                 "attempt unless you have a specific reason. Start from the last diagnosis.")
    lines.append("  - If a prior attempt timed out at a specific tool, consider "
                 "an alternative first (e.g. log_timeline instead of raw elastic_search_logs).")
    lines.append("  - If a prior diagnosis resolved the problem but it's back, "
                 "state that explicitly in your final_answer.")

    return "\n".join(lines)
```

## Change 2 — wire into task start

Find the spot in `api/routers/agent.py` where the system messages are
assembled for a task — right after the base agent-type prompt is chosen and
before the `═══ ATTEMPT HISTORY ═══` section from v2.32.3 (which already
exists but is per-task not per-entity).

Rename the v2.32.3 section to `═══ THIS TASK'S HISTORY ═══` for clarity, and
inject the new prior-attempts section above it:

```python
# In the task-start prompt assembly:
if task.agent_type in ("investigate", "execute") and task.scope_entity:
    prior = await fetch_prior_attempts(
        scope_entity=task.scope_entity,
        agent_type=task.agent_type,
    )
    prior_section = format_attempts_for_prompt(prior, task.agent_type)
    if prior_section:
        system_messages.append({"role": "system", "content": prior_section})
```

The v2.32.3 section stays — it covers in-flight attempts and short-loop
learning. This is distinct: **cross-task** learning.

## Change 3 — ensure tools_used_list is populated

v2.32.3 added `tools_used_list` as a JSONB column. Verify in the agent loop
that terminal recording writes this list correctly. If the column is present
but empty in production rows, add a backfill migration to derive it from
`operation_log` where possible:

```python
# Alembic migration: backfill tools_used_list for recent agent_attempts rows
op.execute("""
    UPDATE agent_attempts a
    SET tools_used_list = sub.tools
    FROM (
        SELECT task_id, array_agg(tool ORDER BY created_at) AS tools
        FROM operation_log
        WHERE created_at >= NOW() - INTERVAL '14 days'
        GROUP BY task_id
    ) sub
    WHERE a.task_id = sub.task_id
      AND (a.tools_used_list IS NULL OR a.tools_used_list = '[]'::jsonb)
      AND a.created_at >= NOW() - INTERVAL '14 days';
""")
```

## Change 4 — opt-out setting

Not everyone wants prior-attempts context injection. Add a settings key:

- `coordinatorPriorAttemptsEnabled` (bool, default true)

Check at the top of the injection path; if disabled, return empty string.
Expose in the AI Services tab of OptionsModal under a new "Coordinator"
section:

```jsx
<Field label="Inject prior attempts context"
  hint="When a task scopes an entity, show the agent up to 3 prior attempts on that entity from the last 7 days. Helps avoid repeating failed tool chains.">
  <Toggle
    value={draft.coordinatorPriorAttemptsEnabled !== false}
    onChange={v => update('coordinatorPriorAttemptsEnabled', v)}
    label="Enabled"
  />
</Field>
```

## Change 5 — tests

`tests/test_coordinator_prior_attempts.py`:

```python
@pytest.mark.asyncio
async def test_empty_when_no_entity(seeded_db):
    from api.agents.orchestrator import fetch_prior_attempts
    r = await fetch_prior_attempts(scope_entity=None, agent_type="investigate")
    assert r == []

@pytest.mark.asyncio
async def test_window_respected(seeded_db_with_old_attempt):
    from api.agents.orchestrator import fetch_prior_attempts
    # Seed an attempt 14 days ago → not returned for 7-day window
    r = await fetch_prior_attempts(scope_entity="proxmox:worker-03:9203",
                                    agent_type="investigate", window_days=7)
    assert all((datetime.utcnow() - a["created_at"]).days <= 7 for a in r)

def test_format_skips_routine_success():
    from api.agents.orchestrator import format_attempts_for_prompt
    attempts = [
        {"agent_type": "execute", "terminal_status": "done", ...},
        {"agent_type": "execute", "terminal_status": "done", ...},
        {"agent_type": "execute", "terminal_status": "done", ...},
    ]
    result = format_attempts_for_prompt(attempts, agent_type="execute")
    assert result == ""  # routine — no injection

def test_format_includes_failed_attempts():
    from api.agents.orchestrator import format_attempts_for_prompt
    attempts = [
        {"agent_type": "investigate", "terminal_status": "timeout_cap",
         "objective": "test", "tools_used_count": 16, "tools_used_list": ["x"]*16,
         "diagnosis": "", "created_at": datetime.utcnow(), "was_proposal": False},
    ]
    result = format_attempts_for_prompt(attempts, "investigate")
    assert "timeout_cap" in result
    assert "GUIDANCE" in result

@pytest.mark.asyncio
async def test_opt_out_skips_injection(seeded_db, set_setting):
    set_setting("coordinatorPriorAttemptsEnabled", "false")
    # Run task — verify no PRIOR ATTEMPTS section in the system prompt
    ...
```

## Change 6 — integration smoke test

After deploy, the operator can verify by running the same investigate task
twice on the same entity and inspecting the second run's prompt (via
operation_log or WS stream). Section should appear on the second run.

## Version bump
Update `VERSION`: 2.34.0 → 2.34.1

## Commit
```
git add -A
git commit -m "feat(agents): v2.34.1 coordinator uses agent_attempts for starting-tool selection"
git push origin main
```

## How to test after push
1. Redeploy + Alembic upgrade.
2. Open a fresh investigate task on an entity that has prior agent_attempts:
   `Why is kafka_broker-3 under-replicated?` (scope_entity: kafka_broker-3)
3. Check the task's system prompt (Logs → Operations → this task → raw prompt).
4. Confirm the `═══ PRIOR ATTEMPTS ON THIS ENTITY ═══` section appears above
   the agent_type base prompt.
5. Run the same task twice — second run should cite the first run's diagnosis.
6. Toggle `coordinatorPriorAttemptsEnabled` off, re-run — section gone.
7. Regression: observe and build tasks never get this section.
