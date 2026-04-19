"""v2.35.19 — uptime allowlist allows -p / -s flag args."""
import pytest
from mcp_server.tools.vm import _validate_command


@pytest.mark.parametrize("cmd", [
    "uptime",
    "uptime -p",
    "uptime -s",
    "uptime --pretty",
    "uptime --since",
])
def test_uptime_variants_pass(cmd):
    ok, _ = _validate_command(cmd)
    assert ok, f"Expected {cmd!r} to pass allowlist"


def test_uptime_in_chain():
    """Canonical pattern from Sample 2 of v2.35.18 analysis."""
    ok, _ = _validate_command("df -h && free -m && uptime -p && whoami")
    assert ok


def test_uptime_does_not_allow_injection():
    """-p is fine but arbitrary args still rejected by metachar guard."""
    ok, err = _validate_command("uptime -p; rm /tmp/x")
    assert not ok
    err_str = err if isinstance(err, str) else err.get("message", "")
    assert "metacharacters" in err_str.lower() or ";" in err_str
