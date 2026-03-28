"""Unit tests for prompt_builder.py."""
from mcp_server.tools.skills import prompt_builder


def test_build_generation_prompt_contains_description():
    prompt = prompt_builder.build_generation_prompt(
        description="FortiGate system status",
        category="networking",
        api_base="",
        auth_type="none",
        context_docs=[],
        existing_skills=[],
        spec=None,
    )
    assert "FortiGate system status" in prompt


def test_build_generation_prompt_contains_hard_constraints():
    prompt = prompt_builder.build_generation_prompt(
        description="test skill",
        category="general",
        api_base="",
        auth_type="none",
        context_docs=[],
        existing_skills=[],
        spec=None,
    )
    # Hard constraints block dangerous imports
    lower = prompt.lower()
    assert "subprocess" in lower or "dangerous" in lower or "banned" in lower or "import" in lower


def test_build_generation_prompt_includes_context_docs():
    docs = ["## Reference\n\nSome API documentation here."]
    prompt = prompt_builder.build_generation_prompt(
        description="test skill",
        category="general",
        api_base="",
        auth_type="none",
        context_docs=docs,
        existing_skills=[],
        spec=None,
    )
    assert "Some API documentation here" in prompt


def test_build_generation_prompt_empty_docs_no_crash():
    prompt = prompt_builder.build_generation_prompt(
        description="test skill",
        category="general",
        api_base="",
        auth_type="none",
        context_docs=[],
        existing_skills=[],
        spec=None,
    )
    assert isinstance(prompt, str)
    assert len(prompt) > 100


def test_build_generation_prompt_existing_skills_mentioned():
    prompt = prompt_builder.build_generation_prompt(
        description="another proxmox skill",
        category="compute",
        api_base="",
        auth_type="none",
        context_docs=[],
        existing_skills=["proxmox_vm_status", "proxmox_node_health"],
        spec=None,
    )
    assert "proxmox_vm_status" in prompt or "proxmox_node_health" in prompt


def test_build_generation_prompt_none_context_docs_no_crash():
    """Passing None for context_docs (the default) should not crash."""
    prompt = prompt_builder.build_generation_prompt(
        description="test skill",
        category="general",
        api_base="",
        auth_type="none",
        context_docs=None,
        existing_skills=None,
        spec=None,
    )
    assert isinstance(prompt, str)
    assert len(prompt) > 50


def test_build_generation_prompt_contains_category():
    prompt = prompt_builder.build_generation_prompt(
        description="test skill",
        category="networking",
        api_base="",
        auth_type="none",
        context_docs=[],
        existing_skills=[],
        spec=None,
    )
    assert "networking" in prompt


def test_build_generation_prompt_api_base_included_when_provided():
    prompt = prompt_builder.build_generation_prompt(
        description="test skill",
        category="general",
        api_base="https://example.local/api",
        auth_type="none",
        context_docs=[],
        existing_skills=[],
        spec=None,
    )
    assert "https://example.local/api" in prompt


def test_build_generation_prompt_spec_included_when_provided():
    spec = {"name": "test_skill", "endpoint": "/api/v1/status", "method": "GET"}
    prompt = prompt_builder.build_generation_prompt(
        description="test skill",
        category="general",
        api_base="",
        auth_type="none",
        context_docs=[],
        existing_skills=[],
        spec=spec,
    )
    assert "/api/v1/status" in prompt


def test_build_generation_prompt_proxmox_auth_pattern_injected():
    """Proxmox skills get the token split pattern injected."""
    prompt = prompt_builder.build_generation_prompt(
        description="proxmox node health check",
        category="compute",
        api_base="",
        auth_type="api_token",
        context_docs=[],
        existing_skills=[],
        spec=None,
    )
    assert "PROXMOX_TOKEN_ID" in prompt or "proxmox" in prompt.lower()
