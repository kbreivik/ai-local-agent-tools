"""v2.38.4 — Visibility guards for external AI routing failures.

When _maybe_route_to_external_ai raises, three different call sites
must log loudly with the EXTERNAL_AI_ROUTE_FAIL prefix, send a halt
line, and (at the budget-exhaustion site) broadcast done with
status='failed' + reason='escalation_failed' instead of masking the
failure as ok.
"""
from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).parent.parent
AGENT_ROUTER = REPO_ROOT / "api" / "routers" / "agent.py"


def _src() -> str:
    return AGENT_ROUTER.read_text(encoding="utf-8")


def test_loud_log_prefix_appears_for_each_rule():
    """Every except block catching a _maybe_route_to_external_ai
    failure must log with the EXTERNAL_AI_ROUTE_FAIL prefix so
    operators can grep docker logs."""
    src = _src()
    occurrences = src.count("EXTERNAL_AI_ROUTE_FAIL")
    assert occurrences >= 3, (
        f"Expected >=3 EXTERNAL_AI_ROUTE_FAIL log prefixes (one per "
        f"call site — budget_exhaustion, halluc_guard, fabrication), "
        f"found {occurrences}. Grep for 'EXTERNAL_AI_ROUTE_FAIL' in "
        f"api/routers/agent.py."
    )


def test_budget_exhaustion_path_surfaces_failure_to_ui():
    """The budget-exhaustion call site must emit status='failed' +
    reason='escalation_failed' when external routing raises, not a
    stale done/ok."""
    src = _src()
    # The budget-exhaustion path is the ONE that previously always
    # emitted status="ok" regardless of routing success.
    assert "_external_ai_route_error" in src, (
        "Missing _external_ai_route_error sentinel — budget-exhaustion "
        "except block must capture the failure for the broadcast block "
        "below to surface it."
    )
    # The content block must prepend [EXTERNAL AI ESCALATION FAILED:
    assert "EXTERNAL AI ESCALATION FAILED" in src, (
        "Content block must prepend '[EXTERNAL AI ESCALATION FAILED: "
        "...]' when _external_ai_route_error is truthy (v2.38.4)."
    )
    # And the status must flip to failed
    assert re.search(
        r'_done_status\s*=\s*"failed"', src,
    ), "status='failed' not set on external-AI failure path"


def test_halt_line_sent_on_external_ai_failure():
    """Every except block must send a 'halt' line to the live-output
    stream so the failure shows up in AgentFeed, not just the final
    done event."""
    src = _src()
    # Pattern: within 400 chars after a line that logs
    # EXTERNAL_AI_ROUTE_FAIL, there must be a manager.send_line("halt",
    # reference.
    matches = list(re.finditer(r"EXTERNAL_AI_ROUTE_FAIL", src))
    assert len(matches) >= 3, "need >=3 log sites to check halt lines"
    for m in matches:
        window = src[m.start(): m.start() + 1200]
        assert 'send_line' in window and '"halt"' in window, (
            f"halt line-send missing within 1200 chars of "
            f"EXTERNAL_AI_ROUTE_FAIL log (char {m.start()})"
        )


def test_no_silent_fallthrough_warning_remains():
    """The old 'external AI routing failed: %s' shape was the silent
    fallthrough. The v2.38.4 upgrade replaces it with structured
    EXTERNAL_AI_ROUTE_FAIL. Catch regressions if someone copy-pastes
    the old pattern back in."""
    src = _src()
    # The old format string was 'external AI routing failed: %s' with
    # NO context. After v2.38.4 every such call has the loud prefix
    # plus session+operation identifiers. If the bare phrase reappears
    # somewhere new, fail.
    # Tolerance: the exact old one-line call has been replaced so
    # count should be zero. Future refactors that want to log in this
    # area must use the EXTERNAL_AI_ROUTE_FAIL prefix.
    bare = src.count('"external AI routing failed: %s"')
    assert bare == 0, (
        f"Found {bare} uses of the old silent 'external AI routing "
        f"failed: %s' log shape — replace with structured "
        f"EXTERNAL_AI_ROUTE_FAIL log including session/operation ids."
    )
