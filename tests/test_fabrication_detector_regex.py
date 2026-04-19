"""v2.35.11 regression — fabrication detector must not flag prose.

Three common false-positive patterns observed on v2.35.10 synthesis
outputs (op e442810b): 'word (parenthetical)' mentions that were
extracted by _PROSE_CITE_RE because it allowed whitespace before `(`.
"""
from __future__ import annotations

import pytest


def test_parenthetical_prose_not_cited():
    from api.agents.fabrication_detector import extract_cited_tools
    text = (
        "EVIDENCE:\n"
        "- list_connections(platform='pihole') are unavailable "
        "(tool not registered)\n"
        "- hp1-ai-agent-lab (agent-01, 192.168.199.10) confirmed reachable\n"
    )
    cites = extract_cited_tools(text)
    # list_connections IS a tool call (no whitespace before `(`).
    assert "list_connections" in cites
    # These are prose words followed by space + `(` — NOT tool citations.
    assert "unavailable" not in cites
    assert "lab" not in cites
    assert "registered" not in cites


def test_real_tool_call_still_cited():
    from api.agents.fabrication_detector import extract_cited_tools
    text = "- swarm_node_status() returned 6 nodes"
    cites = extract_cited_tools(text)
    assert "swarm_node_status" in cites


def test_prose_citations_also_require_immediate_paren():
    from api.agents.fabrication_detector import extract_cited_tools
    text = (
        "The agent called vm_exec(host='worker-01') and got a result. "
        "This analysis (running now) does not cite other tools."
    )
    cites = extract_cited_tools(text)
    assert "vm_exec" in cites
    assert "analysis" not in cites
    assert "running" not in cites


def test_is_fabrication_no_longer_fires_on_dns_synthesis():
    """The exact synthesis from op e442810b should not be flagged."""
    from api.agents.fabrication_detector import is_fabrication
    text = (
        "EVIDENCE:\n"
        "- list_connections(platform='pihole') and list_connections"
        "(platform='technitium') are unavailable (tool not registered)\n"
        "- /etc/resolv.conf check blocked despite allowlist pattern '^cat\\b'\n"
        "- hp1-ai-agent-lab (agent-01, 192.168.199.10) confirmed reachable "
        "via vm_host\n"
        "\nROOT CAUSE: DNS resolver chain health cannot be assessed.\n"
        "\nNEXT STEPS:\n"
        "- Manually run `cat /etc/resolv.conf` on hp1-ai-agent-lab\n"
    )
    actual_tools = [
        "list_connections", "vm_exec", "vm_exec_allowlist_request",
        "vm_exec_allowlist_add", "infra_lookup",
    ]
    fired, detail = is_fabrication(text, actual_tool_names=actual_tools)
    assert not fired, (
        f"False positive on valid failure-report synthesis. Cited: "
        f"{detail['cited']!r}, fabricated: {detail['fabricated']!r}"
    )


def test_fabrication_detector_still_catches_real_fabrication():
    """The canonical bf3a71ea-style fabrication must still fire."""
    from api.agents.fabrication_detector import is_fabrication
    # Agent calls zero tools but cites three fake ones
    text = (
        "EVIDENCE:\n"
        "- container_inspect(id='x7k9a') returned IP 10.0.4.17\n"
        "- dns_lookup(host='elastic-ingress.internal') resolved to 10.0.4.17\n"
        "- port_scan(host='10.0.4.17', port=9092) confirmed open\n"
    )
    fired, detail = is_fabrication(text, actual_tool_names=[])
    assert fired
    assert len(detail["fabricated"]) >= 3
