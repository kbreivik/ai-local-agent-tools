# CC PROMPT — v2.45.25 — feat(facts): agent_observation write path — drain state.run_facts to known_facts_current

## What this does
Closes the deferred-from-v2.35 stub. The fact-extraction pipeline already
writes to `state.run_facts` after each tool call (in
`api/agents/step_facts.py:process_tool_result`). After the run completes,
`state.run_facts` is currently discarded. This prompt drains that dict into
`known_facts_current` with `source='agent_observation'` and `metadata` that
includes the operation_id so the existing `get_facts_by_operation()` helper
can surface them in the trace digest.

The source weight `factSourceWeight_agent_observation=0.5` and the half-life
`factHalfLifeHours_agent=24` are already registered in settings (v2.35),
so persisted facts will land at moderate confidence and decay quickly — exactly
what the v2.35 spec ("agent_observation source weight 0.5 with adaptive
promotion ladder") prescribes.

Version bump: 2.45.24 → 2.45.25

---

## Context

`StepState.run_facts` is a dict keyed by `fact_key`, each value:

```python
{
    "value":     <any>,
    "step":      int,
    "tool":      str,
    "timestamp": iso8601 str,
    "raw":       <original extractor output>,
}
```

`api/db/known_facts.py` exposes:

```python
def batch_upsert_facts(facts: list[dict], actor='collector') -> dict
# fact dict: {fact_key, source, value, metadata}
```

And `get_facts_by_operation(operation_id)` already filters by
`metadata->>'operation_id'`, so persisted rows must include
`operation_id` in metadata.

---

## Change 1 — NEW FILE — `api/agents/step_persist.py`

Create new file `api/agents/step_persist.py`:

```python
"""step_persist — drain StepState.run_facts to known_facts_current — v2.45.25.

After a successful step, the in-run fact dict is persisted as
agent_observation source. Source weight (0.5) and half-life (24h) come from
the registered settings, so these facts decay quickly and only stay around
when re-observed.

Idempotent: state.run_facts_persisted prevents double-writes on multi-step
runs that call this hook from different code paths.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)


def persist_run_facts(
    state,                    # StepState
    *,
    operation_id: str,
    session_id: str,
    agent_type: str,
    task: str,
) -> dict:
    """Drain state.run_facts → known_facts_current as agent_observation rows.

    Returns the batch_upsert_facts totals dict. No-ops on:
    - empty run_facts
    - state.final_status indicating failure (error, escalated)
    - already drained this run (state.run_facts_persisted)
    """
    if getattr(state, "run_facts_persisted", False):
        return {"skipped": "already_persisted"}
    if not state.run_facts:
        return {"skipped": "no_facts"}
    if str(getattr(state, "final_status", "")).lower() in ("error", "escalated", "failed"):
        return {"skipped": f"final_status={state.final_status}"}

    facts = []
    for fact_key, fact in state.run_facts.items():
        if not fact_key or not isinstance(fact, dict):
            continue
        value = fact.get("value")
        # Skip None values — agent_observation should not poison the store
        # with absences. A missing observation is not the same as "value is None".
        if value is None:
            continue
        facts.append({
            "fact_key": fact_key,
            "source":   "agent_observation",
            "value":    value,
            "metadata": {
                "operation_id": operation_id,
                "session_id":   session_id,
                "agent_type":   agent_type,
                "task_snippet": (task or "")[:200],
                "step":         fact.get("step"),
                "tool":         fact.get("tool"),
                "observed_at":  fact.get("timestamp")
                                or datetime.now(timezone.utc).isoformat(),
            },
        })

    if not facts:
        state.run_facts_persisted = True
        return {"skipped": "no_writable_facts"}

    try:
        from api.db.known_facts import batch_upsert_facts
        totals = batch_upsert_facts(facts, actor="agent_observation")
    except Exception as e:
        log.warning("persist_run_facts: batch upsert failed: %s", e)
        return {"error": str(e)}

    state.run_facts_persisted = True
    log.info(
        "agent_observation: persisted %d facts (insert=%d touch=%d change=%d) "
        "operation=%s",
        len(facts),
        totals.get("insert", 0),
        totals.get("touch", 0),
        totals.get("change", 0),
        operation_id,
    )
    try:
        from api.metrics import AGENT_OBSERVATION_FACTS_WRITTEN
        AGENT_OBSERVATION_FACTS_WRITTEN.labels(
            agent_type=agent_type,
        ).inc(len(facts))
    except Exception:
        pass
    return totals
```

---

## Change 2 — `api/agents/step_state.py` — add idempotency flag

CC: open `api/agents/step_state.py`. The file defines a `StepState` dataclass.
Find the field list and add `run_facts_persisted` as a bool field defaulting
to False, alongside the existing flags (e.g. `empty_completion_synth_done`,
`audit_logged`).

If the field already exists, leave it. The exact line layout depends on the
existing dataclass — match the surrounding style.

Example (adapt to actual structure):

```python
    run_facts_persisted: bool = False  # v2.45.25 — drain to known_facts_current
```

---

## Change 3 — `api/metrics.py` — register counter

CC: open `api/metrics.py`. Find the counter definitions (look for `Counter(` or
`prometheus_client.Counter`). Add:

```python
AGENT_OBSERVATION_FACTS_WRITTEN = Counter(
    "deathstar_agent_observation_facts_written_total",
    "Number of agent_observation facts persisted to known_facts_current",
    labelnames=["agent_type"],
)
```

If the file uses a different registration style (e.g. registry.register), match
the existing pattern. Place near other agent-related counters
(e.g. `AGENT_TOOL_CALLS`).

---

## Change 4 — call persist_run_facts from the run completion path

CC: locate where a run finishes successfully. Two candidate hook points:

(a) End of `_run_single_agent_step` in `api/routers/agent.py` — runs once per
    step. With multi-step runs, each step persists its own facts (touch
    semantics on duplicates make this safe).

(b) End of `_stream_agent` in `api/routers/agent.py` after all steps
    complete, before the `done` broadcast.

Pick (b) if state is aggregated across steps; pick (a) if each step has its
own StepState. Use `grep -n "state.final_status\|run_facts" api/routers/agent.py
api/agents/pipeline.py` to locate the actual completion path.

Wherever the final completion happens (after the loop ends, before the
done/cleanup broadcast), insert:

```python
    # v2.45.25 — drain agent_observation facts to known_facts_current
    try:
        from api.agents.step_persist import persist_run_facts
        persist_run_facts(
            state,
            operation_id=operation_id,
            session_id=session_id,
            agent_type=agent_type,
            task=task,
        )
    except Exception as _ppe:
        log.debug("persist_run_facts failed: %s", _ppe)
```

CC: ensure `state`, `operation_id`, `session_id`, `agent_type`, and `task`
are all in scope at the chosen hook point. If multi-step runs have a single
`StepState` shared across steps, the run-end hook in `_stream_agent` is
preferred. If each step gets a fresh `StepState`, place the hook at the end
of `_run_single_agent_step` (after the step's loop ends, before return).

---

## Verify

```bash
python -m py_compile api/agents/step_persist.py api/agents/step_state.py api/metrics.py
grep -n "persist_run_facts\|run_facts_persisted" api/agents/step_persist.py api/agents/step_state.py api/routers/agent.py
```

After deploy, run any agent task and check:

```sql
SELECT COUNT(*) FROM known_facts_current WHERE source='agent_observation';
-- should be > 0 within minutes of running tasks
```

Or via API:
```bash
curl -s -b "hp1_auth=$T" "http://localhost:8000/api/facts/list?source=agent_observation" | jq '.facts | length'
```

---

## Version bump

Update `VERSION`: `2.45.24` → `2.45.25`

---

## Commit

```
git add -A
git commit -m "feat(facts): v2.45.25 agent_observation write path — drain state.run_facts to known_facts_current"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```

This closes the v2.35 spec deferral noted in
`PHASE_v2.35_SPEC.md` ("`agent_observation` writes deferred to v2.35.2+").
