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
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)


# v2.47.2 — exclude agent_observation facts written by the SAME task slug
# within the last 60 minutes. Prevents self-loop poisoning where a fact
# written by a wrong run 5 minutes ago is injected as authoritative on the
# next test run for the same task.
#
# TODO(v2.47.x): wire this into the read side. Today the fact-injection path
# is `api/agents/preflight.py::resolve_against_inventory` →
# `get_confident_facts_for_entity` → `api/db/known_facts.get_confident_facts`.
# That path resolves by entity_id, not task_snippet, so applying the filter
# requires plumbing the current task slug down through `preflight_resolve`
# and `resolve_against_inventory`. Until that lands, this helper is exposed
# for callers that already have both the fact dict and the current task
# slug (e.g. future targeted injection paths). Changes 1 + 2 close most of
# the regression on their own.
def _is_self_loop_fact(fact: dict, current_task_slug: str) -> bool:
    if fact.get("source") != "agent_observation":
        return False
    md = fact.get("metadata") or {}
    if not isinstance(md, dict):
        return False
    fact_task = (md.get("task_snippet") or "").lower()
    if not fact_task:
        return False
    # Crude slug match: same first 30 chars
    if fact_task[:30] != (current_task_slug or "")[:30]:
        return False
    # Time check — only filter recent ones (< 60 min old)
    last_verified = fact.get("last_verified")
    if not last_verified:
        return True  # no timestamp → assume recent and filter
    try:
        if isinstance(last_verified, str):
            ts = datetime.fromisoformat(last_verified.replace("Z", "+00:00"))
        else:
            ts = last_verified
        age = datetime.now(timezone.utc) - ts
        return age < timedelta(minutes=60)
    except Exception:
        return False


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
