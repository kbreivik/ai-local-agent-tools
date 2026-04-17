"""Tests for v2.34.12 container-introspection tools."""
from unittest.mock import patch

import pytest

from mcp_server.tools import container_introspect as ci


# ── Argument validation ──────────────────────────────────────────────────────

class TestContainerIdValidation:
    def test_accepts_hex_id(self):
        ci._validate_container_id("f3ef70283135")

    def test_accepts_service_name(self):
        ci._validate_container_id("logstash_logstash.1.jjquw46py3ls8go7cuqvjbr0r")

    @pytest.mark.parametrize("bad", [
        "",
        "../etc/passwd",
        "$(whoami)",
        "id; rm -rf /",
        "id`",
        "a" * 100,
    ])
    def test_rejects_dangerous(self, bad):
        with pytest.raises(ValueError):
            ci._validate_container_id(bad)


class TestPathValidation:
    @pytest.mark.parametrize("p", [
        "/etc/hosts",
        "/etc/resolv.conf",
        "/etc/kafka/server.properties",
        "/opt/logstash/config/logstash.yml",
        "/usr/share/logstash/pipeline/main.conf",
        "/var/log/app.log",
    ])
    def test_accepts_safelisted(self, p):
        ci._validate_path(p)

    @pytest.mark.parametrize("p", [
        "/etc/shadow",           # not in suffix allowlist
        "/etc/../etc/passwd",    # traversal
        "relative/path.conf",    # not absolute
        "/root/.ssh/id_rsa",     # outside allowlist
        "/etc/my.sh",            # disallowed suffix
    ])
    def test_rejects_unsafelisted(self, p):
        with pytest.raises(ValueError):
            ci._validate_path(p)


# ── container_config_read ────────────────────────────────────────────────────

class TestContainerConfigRead:
    def test_happy_path(self):
        with patch("mcp_server.tools.container_introspect._ssh_exec") as mock:
            mock.return_value = {"status": "ok", "data": {
                "output": "line1\nline2\nline3"}}
            r = ci.container_config_read(
                host="worker-03",
                container_id="f3ef70283135",
                path="/etc/hosts",
            )
            assert r["status"] == "ok"
            assert r["data"]["lines_returned"] == 3
            assert r["data"]["truncated"] is False
            # Verify the command was properly quoted and no metacharacters injected
            call_cmd = mock.call_args[1]["command"]
            assert "docker exec f3ef70283135 cat /etc/hosts" in call_cmd
            assert "|" in call_cmd and "head -200" in call_cmd

    def test_rejects_unsafelisted_path(self):
        r = ci.container_config_read(
            host="worker-03", container_id="f3ef70283135",
            path="/etc/shadow",
        )
        assert r["status"] == "error"
        assert "not in read-only allowlist" in r["message"]

    def test_max_lines_capped(self):
        with patch("mcp_server.tools.container_introspect._ssh_exec") as mock:
            mock.return_value = {"status": "ok", "data": {"output": ""}}
            ci.container_config_read(
                host="w", container_id="abc",
                path="/etc/hosts", max_lines=99999,
            )
            assert "head -500" in mock.call_args[1]["command"]


# ── container_env ────────────────────────────────────────────────────────────

class TestContainerEnv:
    def test_redacts_secrets(self):
        with patch("mcp_server.tools.container_introspect._ssh_exec") as mock:
            mock.return_value = {"status": "ok", "data": {"output":
                "KAFKA_BOOTSTRAP=broker-1:9092\n"
                "DB_PASSWORD=hunter2\n"
                "API_TOKEN=sk-secret\n"
                "LOG_LEVEL=info"
            }}
            r = ci.container_env(host="w", container_id="abc")
            env = {e["key"]: e["value"] for e in r["data"]["env"]}
            assert env["DB_PASSWORD"] == "<redacted>"
            assert env["API_TOKEN"] == "<redacted>"
            assert env["KAFKA_BOOTSTRAP"] == "broker-1:9092"
            assert env["LOG_LEVEL"] == "info"
            assert r["data"]["redacted_count"] == 2

    def test_grep_pattern_filter(self):
        with patch("mcp_server.tools.container_introspect._ssh_exec") as mock:
            mock.return_value = {"status": "ok", "data": {"output":
                "KAFKA_BOOTSTRAP=x\nELASTICSEARCH_HOSTS=y\nLOG_LEVEL=info"
            }}
            r = ci.container_env(host="w", container_id="abc",
                                 grep_pattern="KAFKA")
            assert r["data"]["count"] == 1
            assert r["data"]["env"][0]["key"] == "KAFKA_BOOTSTRAP"


# ── container_tcp_probe ──────────────────────────────────────────────────────

class TestContainerTcpProbe:
    def test_reachable(self):
        with patch("mcp_server.tools.container_introspect._ssh_exec") as mock:
            mock.return_value = {"status": "ok", "data": {
                "output": "OK\nRTT_NS=3200000"
            }}
            r = ci.container_tcp_probe(
                host="w", container_id="abc",
                target_host="192.168.199.33", target_port=9094,
            )
            assert r["data"]["reachable"] is True
            assert r["data"]["rtt_ms"] == 3

    def test_unreachable(self):
        with patch("mcp_server.tools.container_introspect._ssh_exec") as mock:
            mock.return_value = {"status": "ok", "data": {
                "output": "FAIL\nRTT_NS=5000000000"
            }}
            r = ci.container_tcp_probe(
                host="w", container_id="abc",
                target_host="192.168.199.33", target_port=9094,
            )
            assert r["data"]["reachable"] is False

    def test_rejects_shell_injection(self):
        r = ci.container_tcp_probe(
            host="w", container_id="abc",
            target_host="1.2.3.4; rm -rf /", target_port=80,
        )
        assert r["status"] == "error"
        assert "invalid target_host" in r["message"]

    def test_rejects_bad_port(self):
        r = ci.container_tcp_probe(
            host="w", container_id="abc",
            target_host="1.2.3.4", target_port=99999,
        )
        assert r["status"] == "error"


# ── router allowlist integration ─────────────────────────────────────────────

class TestRouterAllowlists:
    def test_new_tools_in_observe_allowlist(self):
        from api.agents.router import OBSERVE_AGENT_TOOLS
        for name in (
            "container_config_read", "container_env", "container_networks",
            "container_tcp_probe", "container_discover_by_service",
        ):
            assert name in OBSERVE_AGENT_TOOLS, f"{name} missing from observe"

    def test_new_tools_in_investigate_allowlist(self):
        from api.agents.router import INVESTIGATE_AGENT_TOOLS
        for name in (
            "container_config_read", "container_env", "container_networks",
            "container_tcp_probe", "container_discover_by_service",
        ):
            assert name in INVESTIGATE_AGENT_TOOLS, f"{name} missing from investigate"

    def test_new_tools_NOT_in_build_allowlist(self):
        from api.agents.router import BUILD_AGENT_TOOLS
        assert "container_config_read" not in BUILD_AGENT_TOOLS
