# CC PROMPT — v2.36.1 — External AI Router: rule engine

## What this does

Adds `should_escalate_to_external_ai(state)` — a pure function the agent loop
can call to decide whether to route to an external AI. Five independent rule
types from the v2.36.0 Settings keys:

1. `consecutive_failures` — N tool calls in a row returned `status=error`
2. `budget_exhaustion` — hit the tool-call budget cap with no `DIAGNOSIS:` marker
3. `gate_failure` — `hallucination_guard_exhausted` OR `fabrication_detected_count >= 2`
4. `prior_attempts` — same entity has ≥N failed attempts in last 7d
5. `complexity_prefilter` — classifier is `investigate` AND task matches keyword list AND ≥M prior attempts (fires pre-run at step 0)

No wiring into the agent loop yet. v2.36.1 ships the function + full test
suite; v2.36.2/3 wires it behind the `externalRoutingMode` flag.

Version bump: 2.36.0 → 2.36.1.

---

## Why

The router is the brain of the v2.36.x subsystem. Ship it standalone and fully
tested so v2.36.2/3 can plug it in with confidence. Design locked in the
Kent/Claude spar: 5 rules, boolean/int settings, rules ORed, first-match wins
with a stable priority order.

---

## Change 1 — `api/agents/external_router.py` — new module

Create new file:

```python
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
```

---

## Change 2 — `tests/test_external_router.py` — new test file

```python
"""v2.36.1 — External AI Router rule-engine tests.

Each rule gets positive (fires) + negative (doesn't fire) coverage plus the
mode-gate and cap-gate checks. Uses a monkeypatched _get_setting so tests are
fast and don't touch the DB.
"""
import pytest
from unittest.mock import patch

from api.agents.external_router import (
    RouterState, RouterDecision,
    should_escalate_to_external_ai,
)


def _settings(**overrides):
    """Build a closure matching _get_setting(key, default) → value."""
    defaults = {
        "externalRoutingMode": "auto",
        "routeOnBudgetExhaustion": True,
        "routeOnGateFailure": True,
        "routeOnConsecutiveFailures": 0,
        "routeOnPriorAttemptsGte": 0,
        "routeOnComplexityKeywords": "",
        "routeOnComplexityMinPriorAttempts": 2,
    }
    defaults.update(overrides)

    def fake_get_setting(key, default):
        return defaults.get(key, default)
    return fake_get_setting


# ── Mode gate ─────────────────────────────────────────────────────────────────

def test_mode_off_never_fires():
    with patch("api.agents.external_router._get_setting",
               side_effect=_settings(externalRoutingMode="off")):
        d = should_escalate_to_external_ai(RouterState(
            halluc_guard_exhausted=True,   # would fire in auto mode
        ))
    assert d.escalate is False
    assert d.rule_fired == "none"
    assert "disabled" in d.reason
    assert d.mode == "off"


def test_mode_manual_never_auto_fires():
    """Manual mode is UI-button only — router must not auto-fire."""
    with patch("api.agents.external_router._get_setting",
               side_effect=_settings(externalRoutingMode="manual")):
        d = should_escalate_to_external_ai(RouterState(
            halluc_guard_exhausted=True,
        ))
    assert d.escalate is False
    assert "manual" in d.reason


# ── Per-op cap ────────────────────────────────────────────────────────────────

def test_per_op_cap_blocks_even_when_rule_fires():
    with patch("api.agents.external_router._get_setting",
               side_effect=_settings()):
        d = should_escalate_to_external_ai(RouterState(
            halluc_guard_exhausted=True,
            external_calls_this_op=3, external_calls_cap=3,
        ))
    assert d.escalate is False
    assert "cap reached" in d.reason


# ── gate_failure rule ─────────────────────────────────────────────────────────

def test_gate_failure_fires_on_hallucination_guard():
    with patch("api.agents.external_router._get_setting",
               side_effect=_settings()):
        d = should_escalate_to_external_ai(RouterState(
            halluc_guard_exhausted=True,
        ))
    assert d.escalate is True
    assert d.rule_fired == "gate_failure"


def test_gate_failure_fires_on_fabrication_ge_2():
    with patch("api.agents.external_router._get_setting",
               side_effect=_settings()):
        d = should_escalate_to_external_ai(RouterState(
            fabrication_detected_count=2,
        ))
    assert d.escalate is True
    assert d.rule_fired == "gate_failure"


def test_gate_failure_quiet_on_one_fabrication():
    with patch("api.agents.external_router._get_setting",
               side_effect=_settings()):
        d = should_escalate_to_external_ai(RouterState(
            fabrication_detected_count=1,
        ))
    assert d.escalate is False


def test_gate_failure_off_when_setting_disabled():
    with patch("api.agents.external_router._get_setting",
               side_effect=_settings(routeOnGateFailure=False)):
        d = should_escalate_to_external_ai(RouterState(
            halluc_guard_exhausted=True,
        ))
    assert d.escalate is False


# ── consecutive_failures rule ─────────────────────────────────────────────────

def test_consecutive_failures_fires_when_over_threshold():
    with patch("api.agents.external_router._get_setting",
               side_effect=_settings(routeOnConsecutiveFailures=3)):
        d = should_escalate_to_external_ai(RouterState(
            consecutive_tool_failures=3,
        ))
    assert d.escalate is True
    assert d.rule_fired == "consecutive_failures"


def test_consecutive_failures_quiet_under_threshold():
    with patch("api.agents.external_router._get_setting",
               side_effect=_settings(routeOnConsecutiveFailures=3)):
        d = should_escalate_to_external_ai(RouterState(
            consecutive_tool_failures=2,
        ))
    assert d.escalate is False


def test_consecutive_failures_disabled_by_zero():
    """Default 0 means rule is disabled — never fires regardless of count."""
    with patch("api.agents.external_router._get_setting",
               side_effect=_settings(routeOnConsecutiveFailures=0)):
        d = should_escalate_to_external_ai(RouterState(
            consecutive_tool_failures=99,
        ))
    assert d.escalate is False


# ── budget_exhaustion rule ────────────────────────────────────────────────────

def test_budget_exhaustion_fires_without_diagnosis():
    with patch("api.agents.external_router._get_setting",
               side_effect=_settings()):
        d = should_escalate_to_external_ai(RouterState(
            tool_calls_made=16, tool_budget=16,
            diagnosis_emitted=False,
        ))
    assert d.escalate is True
    assert d.rule_fired == "budget_exhaustion"


def test_budget_exhaustion_quiet_when_diagnosis_emitted():
    """Agent hit the cap BUT produced a DIAGNOSIS: — no escalation needed."""
    with patch("api.agents.external_router._get_setting",
               side_effect=_settings()):
        d = should_escalate_to_external_ai(RouterState(
            tool_calls_made=16, tool_budget=16,
            diagnosis_emitted=True,
        ))
    assert d.escalate is False


def test_budget_exhaustion_off_when_setting_disabled():
    with patch("api.agents.external_router._get_setting",
               side_effect=_settings(routeOnBudgetExhaustion=False)):
        d = should_escalate_to_external_ai(RouterState(
            tool_calls_made=16, tool_budget=16, diagnosis_emitted=False,
        ))
    assert d.escalate is False


# ── prior_attempts rule ───────────────────────────────────────────────────────

def test_prior_attempts_fires_when_over_threshold():
    with patch("api.agents.external_router._get_setting",
               side_effect=_settings(routeOnPriorAttemptsGte=3)):
        d = should_escalate_to_external_ai(RouterState(
            prior_failed_attempts_7d=3,
        ))
    assert d.escalate is True
    assert d.rule_fired == "prior_attempts"


def test_prior_attempts_disabled_by_zero():
    with patch("api.agents.external_router._get_setting",
               side_effect=_settings(routeOnPriorAttemptsGte=0)):
        d = should_escalate_to_external_ai(RouterState(
            prior_failed_attempts_7d=99,
        ))
    assert d.escalate is False


# ── complexity_prefilter rule (is_prerun=True) ────────────────────────────────

def test_complexity_prefilter_fires_with_keyword_and_prior():
    with patch("api.agents.external_router._get_setting",
               side_effect=_settings(
                   routeOnComplexityKeywords="correlate,root cause,why",
                   routeOnComplexityMinPriorAttempts=2,
               )):
        d = should_escalate_to_external_ai(
            RouterState(
                agent_type="investigate",
                task_text="Investigate why Kafka broker-3 fell out of the cluster",
                prior_failed_attempts_7d=2,
            ),
            is_prerun=True,
        )
    assert d.escalate is True
    assert d.rule_fired == "complexity_prefilter"


def test_complexity_prefilter_quiet_without_prior_attempts():
    with patch("api.agents.external_router._get_setting",
               side_effect=_settings(
                   routeOnComplexityKeywords="why",
                   routeOnComplexityMinPriorAttempts=2,
               )):
        d = should_escalate_to_external_ai(
            RouterState(
                agent_type="investigate",
                task_text="Investigate why broker-3 is offline",
                prior_failed_attempts_7d=1,
            ),
            is_prerun=True,
        )
    assert d.escalate is False


def test_complexity_prefilter_only_fires_prerun():
    """During normal run (is_prerun=False), complexity_prefilter is skipped."""
    with patch("api.agents.external_router._get_setting",
               side_effect=_settings(
                   routeOnComplexityKeywords="why",
                   routeOnComplexityMinPriorAttempts=1,
               )):
        d = should_escalate_to_external_ai(
            RouterState(
                agent_type="investigate",
                task_text="why broker-3",
                prior_failed_attempts_7d=5,
            ),
            is_prerun=False,
        )
    assert d.rule_fired != "complexity_prefilter"


def test_complexity_prefilter_off_when_keywords_empty():
    with patch("api.agents.external_router._get_setting",
               side_effect=_settings(
                   routeOnComplexityKeywords="",
                   routeOnComplexityMinPriorAttempts=1,
               )):
        d = should_escalate_to_external_ai(
            RouterState(
                agent_type="investigate",
                task_text="why broker-3 is failing",
                prior_failed_attempts_7d=5,
            ),
            is_prerun=True,
        )
    assert d.escalate is False


# ── Priority order ────────────────────────────────────────────────────────────

def test_priority_gate_failure_beats_budget():
    """Both rules fire → gate_failure wins (higher priority)."""
    with patch("api.agents.external_router._get_setting",
               side_effect=_settings()):
        d = should_escalate_to_external_ai(RouterState(
            halluc_guard_exhausted=True,
            tool_calls_made=16, tool_budget=16, diagnosis_emitted=False,
        ))
    assert d.rule_fired == "gate_failure"


# ── Keyword parsing ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("correlate,root cause,why", ["correlate", "root cause", "why"]),
    ('["correlate","root cause","why"]', ["correlate", "root cause", "why"]),
    ("", []),
    ("  ", []),
    ("single", ["single"]),
    (["a", "b"], ["a", "b"]),
    (None, []),
])
def test_keyword_list_parsing(raw, expected):
    from api.agents.external_router import _parse_keyword_list
    assert _parse_keyword_list(raw) == expected
```

---

## Change 3 — `VERSION`

```
2.36.1
```

---

## Verify

```bash
pytest tests/test_external_router.py -v
```

Should be 21 tests, all passing, <1s runtime.

---

## Commit

```bash
git add -A
git commit -m "feat(agents): v2.36.1 External AI Router rule engine

Adds should_escalate_to_external_ai(state) — pure function deciding whether an
agent run should route to Claude/OpenAI/Grok. Reads Settings on every call
(no caching) so operator flips take effect on the next run.

5 rules, evaluated in stable priority order. First match wins:
  1. complexity_prefilter — keyword match + prior-attempts threshold (step 0)
  2. gate_failure         — hallucination_guard_exhausted or fabrication >= 2
  3. consecutive_failures — N tool calls in a row returned status=error
  4. budget_exhaustion    — hit tool-call cap with no DIAGNOSIS: emitted
  5. prior_attempts       — same entity has >= N failed attempts in last 7d

Master switch externalRoutingMode gates everything:
  off    — returns no-op immediately
  manual — UI button only (router always returns no-op)
  auto   — rules fire

Per-op hard cap (routeMaxExternalCallsPerOp=3 default) refuses regardless of
rule match once the budget is exhausted — mode/rule cannot override it.

21 regression tests cover all 5 rules (positive + negative + disabled),
mode gating, per-op cap, priority order, keyword parsing (CSV, JSON, empty,
list). Pure-function design means tests run in <1s with no DB.

No wiring into the agent loop — v2.36.2/3 plugs this in behind the flag.
v2.36.1 ships the function standalone + tested."
git push origin main
```

---

## Deploy + smoke

Nothing to verify at runtime — this module is not called by anything yet.
Confirm the import path works:

```bash
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent

docker exec -i $(docker ps -q -f name=hp1_agent) python -c \
  'from api.agents.external_router import should_escalate_to_external_ai, RouterState; print(should_escalate_to_external_ai(RouterState()))'
```

Should print: `RouterDecision(escalate=False, rule_fired='none', reason="routing disabled (mode='off')", mode='off')`.

---

## Scope guard — do NOT touch

- Agent loop — not wired yet. v2.36.2/3 does that.
- UI — v2.36.4.
- Actual external-provider calls — v2.36.3.
- `should_escalate_to_external_ai` must remain PURE (no DB writes, no LLM calls,
  no side effects beyond the metric counter in `record_decision`). This is a
  testability contract.
