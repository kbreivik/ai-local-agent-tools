"""v2.35.7 regression — PREFLIGHT FACTS must carry a disambiguation note
preventing the agent from using fact entity_ids as vm_exec host= targets."""
from __future__ import annotations

import pytest


class _FakeResult:
    """Minimal shim matching the attributes that
    format_preflight_facts_section() reads off a PreflightResult."""
    preflight_facts = [
        {
            "fact_key": "prod.proxmox.vm.hp1-prod-worker-03.memory_gb",
            "fact_value": 4.3,
            "source": "proxmox_collector",
            "last_verified": None,
            "confidence": 1.00,
        }
    ]
    trace = ["task: disk usage", "tier1: 1 regex match"]


def test_preflight_block_contains_disambiguation_note():
    """format_preflight_facts_section() must warn the agent that entity_ids
    in the block are not guaranteed to be SSH-reachable."""
    from api.agents.preflight import format_preflight_facts_section

    # Pass explicit settings so the function doesn't try to read from DB.
    settings = {
        "preflightPanelMode": "always_visible",
        "factInjectionThreshold": 0.7,
        "factInjectionMaxRows": 40,
    }
    rendered = format_preflight_facts_section(_FakeResult(), settings=settings)
    assert rendered, "non-empty facts should produce non-empty block"
    # Disambiguation note must be present
    assert "may NOT be valid as `host=`" in rendered or \
           "may not be valid as" in rendered.lower(), \
        (f"PREFLIGHT FACTS block missing disambiguation clause.\n"
         f"Got:\n{rendered[-500:]}")
    assert "vm_exec" in rendered.lower(), \
        "disambiguation clause must mention vm_exec explicitly"
    assert "AVAILABLE VM HOSTS" in rendered, \
        "disambiguation clause must point the agent to the AVAILABLE VM HOSTS section"


def test_available_vm_hosts_hint_claims_authority():
    """The vm_host capability hint in _stream_agent must claim sole authority
    over vm_exec host= parameters, so the agent doesn't pull names from
    PREFLIGHT FACTS / memory."""
    import api.routers.agent as agent_mod
    src = open(agent_mod.__file__, encoding='utf-8').read()
    # Find the AVAILABLE VM HOSTS hint literal
    assert "AVAILABLE VM HOSTS" in src
    # Must contain the authority claim
    assert ("AUTHORITATIVE" in src) or ("ONLY these names" in src), \
        ("_stream_agent vm_host capability hint does not claim sole authority. "
         "Without this the agent will pull hostnames from PREFLIGHT FACTS / "
         "memory and fail vm_exec calls — see op a7e146a1.")
    # Must explicitly warn about PREFLIGHT FACTS
    assert "PREFLIGHT FACTS" in src or "preflight" in src.lower(), \
        "vm_host capability hint does not warn about PREFLIGHT entity_ids"
