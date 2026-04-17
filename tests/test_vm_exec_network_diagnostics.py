"""v2.34.10 — network diagnostics allowlist + safe-pipe passthrough.

Exercises _validate_command in mcp_server.tools.vm across the new
read-only network primitives and the pipe/redirect safelist.
"""
from mcp_server.tools.vm import _validate_command


# ── Base primitives allowed ──────────────────────────────────────────────────

def test_nc_port_probe_allowed():
    ok, _ = _validate_command("nc -zv 192.168.199.33 9094")
    assert ok is True


def test_docker_exec_nc_allowed():
    ok, _ = _validate_command("docker exec abc123 nc -zv 192.168.199.33 9094")
    assert ok is True


def test_ping_with_count_allowed():
    ok, _ = _validate_command("ping -c 3 192.168.199.33")
    assert ok is True


def test_netstat_listeners_allowed():
    ok, _ = _validate_command("netstat -tuln")
    assert ok is True


def test_ss_listeners_allowed():
    ok, _ = _validate_command("ss -tuln")
    assert ok is True


# ── Safe pipes ──────────────────────────────────────────────────────────────

def test_pipe_head_allowed():
    ok, _ = _validate_command("nc -zv 192.168.199.33 9094 2>&1 | head -5")
    assert ok is True


def test_pipe_grep_allowed():
    ok, _ = _validate_command("netstat -tuln | grep 9094")
    assert ok is True


def test_pipe_tail_allowed():
    ok, _ = _validate_command("journalctl -n 200 | tail -20")
    assert ok is True


def test_double_pipe_allowed():
    ok, _ = _validate_command("ps aux | sort -k3 -rn | head -10")
    assert ok is True


def test_redirect_dev_null_allowed():
    ok, _ = _validate_command("curl -I http://example.com 2> /dev/null")
    assert ok is True


# ── Blocks ──────────────────────────────────────────────────────────────────

def test_dangerous_chars_still_blocked():
    ok, reason = _validate_command("nc -zv host 9094; rm -rf /")
    assert ok is False
    assert isinstance(reason, str)
    assert ";" in reason or "metacharacter" in reason.lower()


def test_grep_with_file_arg_blocked():
    """grep -f FILE could read arbitrary files."""
    ok, reason = _validate_command("netstat -tuln | grep -f /etc/passwd")
    assert ok is False
    assert isinstance(reason, str)
    assert "-f" in reason


def test_command_substitution_blocked():
    ok, _ = _validate_command("nc -zv $(cat /etc/hostname) 9094")
    assert ok is False


def test_backtick_substitution_blocked():
    ok, _ = _validate_command("nc -zv `hostname` 9094")
    assert ok is False


def test_pipe_to_unknown_command_blocked():
    ok, reason = _validate_command("nc -zv host 9094 | tee /tmp/out")
    assert ok is False
    assert isinstance(reason, str)
    assert "tee" in reason


def test_arbitrary_redirect_blocked():
    """A plain `> /tmp/foo` is not in REDIRECT_SAFELIST — must be blocked."""
    ok, _ = _validate_command("df -h > /tmp/out")
    assert ok is False


def test_and_operator_blocked():
    ok, _ = _validate_command("df -h && rm -rf /")
    assert ok is False
