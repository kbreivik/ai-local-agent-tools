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
