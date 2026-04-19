"""v2.35.9 regression tests.

1. _resolve_connection must be unambiguous or return None.
2. _validate_command must allow && / || when every segment is allowed.
3. _validate_command must still reject single & (background) and lone $/`.
"""
from __future__ import annotations

import pytest


# ── Unique partial match ──────────────────────────────────────────────────

def test_resolve_connection_unique_suffix_match():
    from mcp_server.tools.vm import _resolve_connection
    conns = [
        {"id": 1, "label": "ds-docker-manager-01", "host": "192.168.199.21"},
        {"id": 2, "label": "ds-docker-manager-02", "host": "192.168.199.22"},
        {"id": 3, "label": "hp1-ai-agent-lab",     "host": "192.168.199.10"},
    ]
    # Exact label
    assert _resolve_connection("ds-docker-manager-01", conns)["id"] == 1
    # Unique suffix
    assert _resolve_connection("manager-01", conns)["id"] == 1
    assert _resolve_connection("agent-lab", conns)["id"] == 3


def test_resolve_connection_ambiguous_returns_none():
    from mcp_server.tools.vm import _resolve_connection
    conns = [
        {"id": 1, "label": "ds-docker-manager-01", "host": "192.168.199.21"},
        {"id": 2, "label": "hp1-prod-manager-01",  "host": "192.168.199.221"},
    ]
    # 'manager-01' ends both labels — must NOT silently pick one
    assert _resolve_connection("manager-01", conns) is None


def test_resolve_connection_ip_still_works():
    from mcp_server.tools.vm import _resolve_connection
    conns = [{"id": 1, "label": "foo", "host": "192.168.199.10"}]
    assert _resolve_connection("192.168.199.10", conns)["id"] == 1


# ── Boolean chain validation ──────────────────────────────────────────────

def test_validate_command_allows_and_chain():
    from mcp_server.tools.vm import _validate_command
    ok, result = _validate_command("free -m && uptime", session_id="")
    assert ok, f"expected && chain of read-only cmds allowed, got: {result!r}"


def test_validate_command_allows_or_chain():
    from mcp_server.tools.vm import _validate_command
    ok, result = _validate_command("df -h / || uptime", session_id="")
    assert ok, f"expected || chain of read-only cmds allowed, got: {result!r}"


def test_validate_command_rejects_chain_with_blocked_segment():
    from mcp_server.tools.vm import _validate_command
    # `rm` is not in the allowlist — chain with && must fail as a whole
    ok, result = _validate_command("df -h && rm -rf /", session_id="")
    assert not ok
    # Error should name the bad segment
    err_text = result if isinstance(result, str) else result.get("message", "")
    assert "rm" in err_text


def test_validate_command_still_rejects_single_ampersand_background():
    """Single & (background process) must stay blocked.
    This test ensures our chain-split doesn't accidentally allow it.
    """
    from mcp_server.tools.vm import _validate_command
    ok, result = _validate_command("sleep 100 &", session_id="")
    assert not ok
    # Error mentions metachar or disallowed character
    err_text = result if isinstance(result, str) else result.get("message", "")
    assert "&" in err_text or "metachar" in err_text.lower()


def test_validate_command_still_rejects_command_substitution():
    """$() and backticks must stay blocked regardless of chaining."""
    from mcp_server.tools.vm import _validate_command
    ok, _ = _validate_command("df $(echo /)", session_id="")
    assert not ok
    ok, _ = _validate_command("df `echo /`", session_id="")
    assert not ok


def test_validate_command_chain_depth_cap():
    """v2.35.18: cap raised 3→5 segments (max 4 boolean operators).
    4-segment chains are now accepted; 6-segment chains still rejected."""
    from mcp_server.tools.vm import _validate_command
    # 4 segments (3 operators) — now allowed, every segment validates
    ok, _ = _validate_command(
        "df -h && uptime && free -m && uname -a", session_id=""
    )
    assert ok, "4-segment chain should be accepted after v2.35.18"
    # 6 segments (5 operators) — still over the cap
    ok, result = _validate_command(
        "df -h && uptime && free -m && uname -a && whoami && hostname",
        session_id="",
    )
    assert not ok
    err_text = result if isinstance(result, str) else result.get("message", "")
    assert "chain" in err_text.lower() or "boolean" in err_text.lower()


def test_validate_command_four_chain_segments_the_vm_health_pattern():
    """Regression pin for the exact command shape that was breaking the
    multi-host VM-health task. Agents emit this verbatim; it must now pass
    validation so the status agent doesn't burn its 8-call budget on
    per-host splits. See docs/AGENT_FAILURE_ANALYSIS_v2.35.md Sample 2."""
    from mcp_server.tools.vm import _validate_command
    ok, _ = _validate_command(
        "df -h && free -m && uptime && whoami", session_id=""
    )
    assert ok


# ── Template text regression ──────────────────────────────────────────────

def test_dns_resolver_template_no_agent01_literal():
    """The DNS resolver consistency template must not reference a
    non-existent host label 'agent-01'."""
    import pathlib
    p = (pathlib.Path(__file__).parent.parent
         / "gui" / "src" / "components" / "TaskTemplates.jsx")
    src = p.read_text(encoding="utf-8")
    # Locate the DNS template block
    idx = src.find("DNS resolver consistency")
    assert idx > 0, "template not found"
    # Take a generous window after the label
    block = src[idx:idx + 2000]
    assert "agent-01" not in block, (
        "DNS resolver consistency template references non-existent host label "
        "'agent-01'. Use 'hp1-ai-agent-lab' or point the agent at "
        "list_connections(platform='vm_host')."
    )
