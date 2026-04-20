"""External AI Router — decides whether to escalate an agent run to Claude/OpenAI/Grok.

v2.36.1 rule engine. Pure function `should_escalate_to_external_ai(state)` →
{escalate: bool, rule_fired: str, reason: str}. No side effects, no DB writes.
Read-only Settings lookup via skills storage backend.

Wired into agent loop by v2.36.2/3. v2.36.1 ships standalone + tested.

5 rules, evaluated in priority order. First match wins. All rules OR'd with
the master mode switch (externalRoutingMode='auto' required for any rule to
fire; 'manual' means UI button only; 'off' means router always returns no-op).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class RouterState:
    """Snapshot of agent-run state the router reads.

    Populated by the caller (agent loop). Kept flat + serialisable so tests
    can build instances without standing up an agent loop.
    """
    # Task classification
    agent_type: str = ""                          # observe|investigate|execute|build
    task_text: str = ""
    scope_entity: str = ""                        # e.g. 'kafka_broker-3'

    # Live progress
    tool_calls_made: int = 0
    tool_budget: int = 16
    diagnosis_emitted: bool = False               # look for 'DIAGNOSIS:' marker
    consecutive_tool_failures: int = 0

    # Gate firings (cumulative across the run)
    halluc_guard_exhausted: bool = False
    fabrication_detected_count: int = 0

    # External calls made so far in this run
    external_calls_this_op: int = 0
    external_calls_cap: int = 3

    # Per-entity prior attempts (from agent_attempts table)
    prior_failed_attempts_7d: int = 0


@dataclass
class RouterDecision:
    """Result of should_escalate_to_external_ai.

    escalate=True means the caller should route to external AI (subject to the
    requireConfirmation gate, handled in v2.36.2).
    """
    escalate: bool = False
    rule_fired: str = "none"
    reason: str = ""
    mode: str = "off"  # observed externalRoutingMode when decision was made


# Stable priority order — first match wins. Kept explicit for operator clarity.
_RULE_ORDER = (
    "complexity_prefilter",   # step 0 only — runs before any tool calls
    "gate_failure",           # hallucination/fabrication — urgent
    "consecutive_failures",   # tool loop stuck in errors
    "budget_exhaustion",      # hit the cap with no diagnosis
    "prior_attempts",         # this entity is cursed — skip local attempt
)


def _get_setting(key: str, default: Any) -> Any:
    """Thin wrapper around the skills backend with safe fallback."""
    try:
        from mcp_server.tools.skills.storage import get_backend
        v = get_backend().get_setting(key)
        return v if v is not None else default
    except Exception:
        return default


def _as_bool(v: Any, default: bool = False) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return default


def _as_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _parse_keyword_list(raw: Any) -> list[str]:
    """Settings value may be CSV, JSON array, or empty. Normalise to list[str]."""
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(x).strip().lower() for x in raw if str(x).strip()]
    s = str(raw).strip()
    if not s:
        return []
    # Try JSON array
    if s.startswith("["):
        try:
            import json
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return [str(x).strip().lower() for x in parsed if str(x).strip()]
        except Exception:
            pass
    # CSV fallback
    return [p.strip().lower() for p in s.split(",") if p.strip()]


def should_escalate_to_external_ai(
    state: RouterState,
    *,
    is_prerun: bool = False,
) -> RouterDecision:
    """Decide whether this agent run should route to external AI.

    `is_prerun=True` means we're checking at step 0 before any tool calls —
    only the `complexity_prefilter` rule fires in that phase. All other rules
    require live run state and fire during/after tool calls.

    Reads Settings on every call (no caching) so operator flips take effect
    on the next run without a restart.
    """
    mode = str(_get_setting("externalRoutingMode", "off")).strip().lower()
    if mode not in ("manual", "auto"):
        return RouterDecision(
            escalate=False, rule_fired="none",
            reason=f"routing disabled (mode={mode!r})", mode=mode,
        )
    if mode == "manual":
        # Only the UI button can fire in manual mode. Router says no.
        return RouterDecision(
            escalate=False, rule_fired="none",
            reason="manual mode — router does not auto-fire", mode=mode,
        )

    # Hard cap: refuse if this op has already used its external-call budget.
    if state.external_calls_this_op >= state.external_calls_cap:
        return RouterDecision(
            escalate=False, rule_fired="none",
            reason=(
                f"per-op cap reached ({state.external_calls_this_op}"
                f"/{state.external_calls_cap})"
            ),
            mode=mode,
        )

    # ── Rule evaluation ────────────────────────────────────────────────────
    # Gathered as (rule_name, fired, reason) tuples; first fired wins per
    # _RULE_ORDER. Evaluation is cheap — OK to do all and pick.
    outcomes: dict[str, tuple[bool, str]] = {}

    # complexity_prefilter — pre-run only
    if is_prerun:
        keywords = _parse_keyword_list(_get_setting("routeOnComplexityKeywords", ""))
        min_prior = _as_int(_get_setting("routeOnComplexityMinPriorAttempts", 2), 2)
        task_low = (state.task_text or "").lower()
        matched_kw = next((kw for kw in keywords if kw in task_low), None)
        if (keywords
                and state.agent_type in ("investigate", "research")
                and matched_kw
                and state.prior_failed_attempts_7d >= min_prior):
            outcomes["complexity_prefilter"] = (True, (
                f"complexity keyword {matched_kw!r} matched; "
                f"prior_failed_attempts_7d={state.prior_failed_attempts_7d} "
                f">= {min_prior}"
            ))
        else:
            outcomes["complexity_prefilter"] = (False, "")

    # gate_failure
    gate_on = _as_bool(_get_setting("routeOnGateFailure", True), True)
    if gate_on and (state.halluc_guard_exhausted
                    or state.fabrication_detected_count >= 2):
        outcomes["gate_failure"] = (True, (
            f"hallucination_guard_exhausted={state.halluc_guard_exhausted}, "
            f"fabrication_detected_count={state.fabrication_detected_count}"
        ))
    else:
        outcomes["gate_failure"] = (False, "")

    # consecutive_failures
    cf_threshold = _as_int(_get_setting("routeOnConsecutiveFailures", 0), 0)
    if cf_threshold > 0 and state.consecutive_tool_failures >= cf_threshold:
        outcomes["consecutive_failures"] = (True, (
            f"consecutive_tool_failures={state.consecutive_tool_failures} "
            f">= threshold {cf_threshold}"
        ))
    else:
        outcomes["consecutive_failures"] = (False, "")

    # budget_exhaustion
    be_on = _as_bool(_get_setting("routeOnBudgetExhaustion", True), True)
    if (be_on
            and state.tool_budget > 0
            and state.tool_calls_made >= state.tool_budget
            and not state.diagnosis_emitted):
        outcomes["budget_exhaustion"] = (True, (
            f"tool_calls_made={state.tool_calls_made}"
            f"/{state.tool_budget}, no DIAGNOSIS: emitted"
        ))
    else:
        outcomes["budget_exhaustion"] = (False, "")

    # prior_attempts
    pa_threshold = _as_int(_get_setting("routeOnPriorAttemptsGte", 0), 0)
    if pa_threshold > 0 and state.prior_failed_attempts_7d >= pa_threshold:
        outcomes["prior_attempts"] = (True, (
            f"prior_failed_attempts_7d={state.prior_failed_attempts_7d} "
            f">= threshold {pa_threshold}"
        ))
    else:
        outcomes["prior_attempts"] = (False, "")

    # Pick first rule in priority order that fired.
    for rule in _RULE_ORDER:
        fired, reason = outcomes.get(rule, (False, ""))
        if fired:
            return RouterDecision(
                escalate=True, rule_fired=rule,
                reason=reason, mode=mode,
            )

    return RouterDecision(
        escalate=False, rule_fired="none",
        reason="no rule fired", mode=mode,
    )


def record_decision(decision: RouterDecision) -> None:
    """Emit the Prometheus counter for this decision. Never raises."""
    try:
        from api.metrics import EXTERNAL_ROUTING_DECISIONS
        if decision.escalate:
            EXTERNAL_ROUTING_DECISIONS.labels(
                decision="escalated", rule=decision.rule_fired,
            ).inc()
        elif decision.mode == "off":
            EXTERNAL_ROUTING_DECISIONS.labels(
                decision="skipped_mode_off", rule="none",
            ).inc()
        elif "cap reached" in (decision.reason or ""):
            EXTERNAL_ROUTING_DECISIONS.labels(
                decision="skipped_cap_exhausted", rule="none",
            ).inc()
        else:
            EXTERNAL_ROUTING_DECISIONS.labels(
                decision="skipped_rule_quiet", rule="none",
            ).inc()
    except Exception as e:
        log.debug("record_decision metric failed: %s", e)
