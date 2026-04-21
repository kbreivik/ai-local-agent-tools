"""v2.38.3 — External AI client must decrypt the API key before use.

Pre-v2.38.3: synthesize_replace read via backend.get_setting() which
is the raw primitive store accessor — returned ciphertext for
sensitive keys. Caused HTTP 401 on every external AI call because the
ciphertext was sent as the x-api-key header value.

Post-v2.38.3: reads via api.settings_manager.get_setting(key,
SETTINGS_KEYS)["value"] which calls decrypt_value() on encrypted
values before returning. Plaintext key reaches the provider. This
test pins the decryption wiring.
"""
from __future__ import annotations

import asyncio
import inspect
from unittest.mock import AsyncMock, patch

import pytest


# ── Integration: synthesize_replace actually decrypts ────────────────────────

def test_synthesize_replace_decrypts_encrypted_api_key(monkeypatch):
    """Store an encrypted externalApiKey. Verify the outbound HTTP call
    receives the plaintext value, not the ciphertext."""
    from api.agents.external_ai_client import synthesize_replace
    from api.crypto import encrypt_value
    from api.settings_manager import SENSITIVE_KEYS

    # Sanity: confirm the key is treated as sensitive
    assert "externalApiKey" in SENSITIVE_KEYS, (
        "externalApiKey must be in SENSITIVE_KEYS for this test to be meaningful"
    )

    plaintext_key = "sk-ant-test-plaintext-key-XYZ123"
    ciphertext = encrypt_value(plaintext_key)
    # Encryption must actually transform the value — if it doesn't, the
    # bug can't exist and this test is tautological
    assert ciphertext != plaintext_key, "encrypt_value did not transform input"

    # Fake Settings backend that returns ciphertext for sensitive keys
    fake_settings = {
        "externalProvider": "claude",
        "externalApiKey":  ciphertext,        # ← encrypted in DB
        "externalModel":   "claude-sonnet-4-6",
    }

    class _FakeBackend:
        def get_setting(self, key):
            return fake_settings.get(key)
        def set_setting(self, key, value):
            fake_settings[key] = value

    fake_backend = _FakeBackend()
    monkeypatch.setattr(
        "mcp_server.tools.skills.storage.get_backend",
        lambda: fake_backend,
    )

    # Capture the Authorization/x-api-key the client would send
    captured: dict = {}

    async def _fake_call(**kwargs):
        # Mirror the signature of call_external_ai
        captured.update(kwargs)
        from api.agents.external_ai_client import ExternalAIResponse
        return ExternalAIResponse(
            text="ok", provider=kwargs["provider"], model=kwargs["model"],
            input_tokens=1, output_tokens=1, est_cost_usd=None, latency_ms=1,
        )

    with patch(
        "api.agents.external_ai_client.call_external_ai",
        new=AsyncMock(side_effect=_fake_call),
    ):
        asyncio.run(synthesize_replace(
            task="ping", agent_type="observe", messages=[],
        ))

    # The regression: ciphertext must not reach the provider
    assert captured["api_key"] == plaintext_key, (
        f"synthesize_replace passed ciphertext to call_external_ai: "
        f"{captured.get('api_key')!r} — expected plaintext {plaintext_key!r}"
    )
    assert captured["provider"] == "claude"
    assert captured["model"] == "claude-sonnet-4-6"


def test_synthesize_replace_raises_auth_error_on_empty_key(monkeypatch):
    """Empty externalApiKey → ExternalAIAuthError BEFORE any HTTP call.
    Locks in the pre-call validation path."""
    from api.agents.external_ai_client import (
        synthesize_replace, ExternalAIAuthError,
    )

    fake_settings = {
        "externalProvider": "claude",
        "externalApiKey":  "",
        "externalModel":   "claude-sonnet-4-6",
    }

    class _FakeBackend:
        def get_setting(self, key):
            return fake_settings.get(key)
        def set_setting(self, key, value):
            fake_settings[key] = value

    monkeypatch.setattr(
        "mcp_server.tools.skills.storage.get_backend",
        lambda: _FakeBackend(),
    )

    with patch(
        "api.agents.external_ai_client.call_external_ai",
        new=AsyncMock(),
    ) as mocked:
        with pytest.raises(ExternalAIAuthError):
            asyncio.run(synthesize_replace(
                task="ping", agent_type="observe", messages=[],
            ))
        assert mocked.call_count == 0, (
            "call_external_ai must NOT be invoked when api_key is empty"
        )


def test_synthesize_replace_raises_auth_error_on_empty_model(monkeypatch):
    """Empty externalModel → ExternalAIAuthError BEFORE any HTTP call."""
    from api.agents.external_ai_client import (
        synthesize_replace, ExternalAIAuthError,
    )

    fake_settings = {
        "externalProvider": "claude",
        "externalApiKey":  "sk-ant-ok",
        "externalModel":   "",
    }

    class _FakeBackend:
        def get_setting(self, key):
            return fake_settings.get(key)
        def set_setting(self, key, value):
            fake_settings[key] = value

    monkeypatch.setattr(
        "mcp_server.tools.skills.storage.get_backend",
        lambda: _FakeBackend(),
    )

    with patch(
        "api.agents.external_ai_client.call_external_ai",
        new=AsyncMock(),
    ) as mocked:
        with pytest.raises(ExternalAIAuthError):
            asyncio.run(synthesize_replace(
                task="ping", agent_type="observe", messages=[],
            ))
        assert mocked.call_count == 0


# ── Structural: source-level guard against regression ──────────────────────

def test_source_reads_externalApiKey_through_decrypting_path():
    """The source file must read externalApiKey through the
    settings_manager.get_setting path, not via the raw backend
    primitive. Structural guard — catches copy-paste of the old
    pattern.
    """
    import pathlib
    src = (
        pathlib.Path(__file__).parent.parent
        / "api" / "agents" / "external_ai_client.py"
    ).read_text(encoding="utf-8")

    # Must import the decrypting helper
    assert "from api.settings_manager import get_setting" in src, (
        "external_ai_client.py must import get_setting from "
        "api.settings_manager — that's the decrypting read path"
    )
    # Must reference SETTINGS_KEYS registry (required for the decrypting call)
    assert "SETTINGS_KEYS" in src, (
        "external_ai_client.py must reference SETTINGS_KEYS — without "
        "the registry, get_setting can't find the key metadata"
    )
    # Must NOT read externalApiKey through the raw backend primitive
    # (accept either 'backend.get_setting("externalApiKey")' or
    # "…'externalApiKey')" forms)
    assert 'backend.get_setting("externalApiKey")' not in src, (
        "external_ai_client.py must not read externalApiKey via the raw "
        "backend — that path returns ciphertext. Use "
        "api.settings_manager.get_setting instead."
    )
    assert "backend.get_setting('externalApiKey')" not in src


def test_synthesize_replace_signature_unchanged():
    """Pin the public signature of synthesize_replace so callers in
    api/routers/agent.py don't break.
    """
    from api.agents.external_ai_client import synthesize_replace
    sig = inspect.signature(synthesize_replace)
    expected = [
        "task", "agent_type", "messages",
        "digest", "context_max_chars", "timeout_s",
    ]
    actual = list(sig.parameters.keys())
    assert actual == expected, (
        f"synthesize_replace signature drift — expected {expected}, "
        f"got {actual}"
    )
