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
