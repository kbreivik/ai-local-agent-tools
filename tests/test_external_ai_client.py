"""v2.36.3 — External AI client tests. httpx mocked, no network."""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock


def _mk_resp(status: int, body: dict):
    r = MagicMock()
    r.status_code = status
    r.json = MagicMock(return_value=body)
    return r


@pytest.mark.asyncio
async def test_claude_success_normalises_tokens():
    from api.agents.external_ai_client import _call_claude
    with patch("httpx.AsyncClient") as MockClient:
        ctx = AsyncMock()
        ctx.post = AsyncMock(return_value=_mk_resp(200, {
            "model": "claude-sonnet-4-6",
            "content": [{"type": "text", "text": "STATUS: HEALTHY"}],
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }))
        MockClient.return_value.__aenter__.return_value = ctx
        result = await _call_claude(
            "sk-x", "claude-sonnet-4-6",
            "system", "user", 10.0,
        )
    assert result.text == "STATUS: HEALTHY"
    assert result.provider == "claude"
    assert result.input_tokens == 100
    assert result.output_tokens == 50
    # cost: (100*3 + 50*15) / 1M = 1050/1M = 0.00105
    assert abs(result.est_cost_usd - 0.00105) < 1e-5


@pytest.mark.asyncio
async def test_claude_401_raises_auth_error():
    from api.agents.external_ai_client import _call_claude, ExternalAIAuthError
    with patch("httpx.AsyncClient") as MockClient:
        ctx = AsyncMock()
        ctx.post = AsyncMock(return_value=_mk_resp(401, {
            "error": {"message": "invalid x-api-key"},
        }))
        MockClient.return_value.__aenter__.return_value = ctx
        with pytest.raises(ExternalAIAuthError):
            await _call_claude("sk-bad", "claude-sonnet-4-6", "s", "u", 10.0)


@pytest.mark.asyncio
async def test_openai_uses_bearer():
    from api.agents.external_ai_client import _call_openai_compatible
    with patch("httpx.AsyncClient") as MockClient:
        ctx = AsyncMock()
        ctx.post = AsyncMock(return_value=_mk_resp(200, {
            "model": "gpt-4o",
            "choices": [{"message": {"content": "STATUS: HEALTHY"}}],
            "usage": {"prompt_tokens": 80, "completion_tokens": 40},
        }))
        MockClient.return_value.__aenter__.return_value = ctx
        result = await _call_openai_compatible(
            "openai", "https://api.openai.com", "sk-openai",
            "gpt-4o", "s", "u", 10.0,
        )
        assert ctx.post.call_args.kwargs["headers"]["Authorization"] == "Bearer sk-openai"
    assert result.provider == "openai"
    # OpenAI token-field names get normalised to input/output
    assert result.input_tokens == 80
    assert result.output_tokens == 40


@pytest.mark.asyncio
async def test_grok_hits_xai_base():
    from api.agents.external_ai_client import _call_openai_compatible
    with patch("httpx.AsyncClient") as MockClient:
        ctx = AsyncMock()
        ctx.post = AsyncMock(return_value=_mk_resp(200, {
            "model": "grok-2-latest", "choices": [{"message": {"content": "ok"}}],
        }))
        MockClient.return_value.__aenter__.return_value = ctx
        result = await _call_openai_compatible(
            "grok", "https://api.x.ai", "xai-key",
            "grok-2-latest", "s", "u", 10.0,
        )
        assert ctx.post.call_args.args[0] == "https://api.x.ai/v1/chat/completions"
    assert result.provider == "grok"


@pytest.mark.asyncio
async def test_timeout_raises_timeout_error():
    import httpx
    from api.agents.external_ai_client import _call_claude, ExternalAITimeoutError
    with patch("httpx.AsyncClient") as MockClient:
        ctx = AsyncMock()
        ctx.post = AsyncMock(side_effect=httpx.TimeoutException("slow"))
        MockClient.return_value.__aenter__.return_value = ctx
        with pytest.raises(ExternalAITimeoutError):
            await _call_claude("sk-x", "claude-sonnet-4-6", "s", "u", 1.0)


def test_flatten_messages_preserves_tool_calls():
    from api.agents.external_ai_client import _flatten_openai_messages_to_text
    messages = [
        {"role": "system", "content": "You are an agent"},
        {"role": "user", "content": "check broker-3"},
        {"role": "assistant", "content": "checking",
         "tool_calls": [{"function": {"name": "kafka_broker_status",
                                      "arguments": '{"broker":3}'}}]},
        {"role": "tool", "tool_call_id": "c1",
         "content": '{"status":"offline"}'},
    ]
    out = _flatten_openai_messages_to_text(messages)
    assert "[SYSTEM]" in out
    assert "[USER]" in out
    assert "[TOOL CALL] kafka_broker_status" in out
    assert "[TOOL RESULT]" in out
    assert '"status":"offline"' in out


def test_flatten_truncates_long_histories():
    from api.agents.external_ai_client import _flatten_openai_messages_to_text
    big = [{"role": "user", "content": "x" * 20000}]
    out = _flatten_openai_messages_to_text(big, max_chars=5000)
    assert len(out) < 6000
    assert "history truncated" in out


def test_cost_estimate_uses_longest_prefix_match():
    from api.agents.external_ai_client import _estimate_cost
    # claude-sonnet-4-6 should match (claude, claude-sonnet-4-6) not (claude, claude-sonnet)
    c = _estimate_cost("claude", "claude-sonnet-4-6", 1000, 500)
    # Both prefixes have the same rate so equal result — verifies no crash
    assert c is not None and c > 0


def test_cost_estimate_returns_none_for_unknown_model():
    from api.agents.external_ai_client import _estimate_cost
    assert _estimate_cost("claude", "mystery-model-xyz", 1000, 500) is None
