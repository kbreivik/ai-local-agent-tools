"""v2.35.21 — POST /api/settings/test-external-ai round-trip + error paths."""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock


def _mk_response(status_code: int, json_body: dict):
    r = MagicMock()
    r.status_code = status_code
    r.json = MagicMock(return_value=json_body)
    return r


@pytest.mark.asyncio
async def test_unknown_provider_returns_error():
    from api.routers.settings import test_external_ai
    out = await test_external_ai(
        body={"provider": "bogus", "api_key": "x", "model": "y"},
        _="test_user",
    )
    assert out["ok"] is False
    assert out["stage"] == "auth"
    assert "bogus" in out["error"]


@pytest.mark.asyncio
async def test_missing_key_and_no_db_key_returns_error():
    from api.routers.settings import test_external_ai
    with patch("api.settings_manager.get_setting",
               return_value={"value": "", "source": "default", "encrypted": False}):
        out = await test_external_ai(
            body={"provider": "claude", "api_key": "", "model": "claude-sonnet-4-6"},
            _="test_user",
        )
    assert out["ok"] is False
    assert out["stage"] == "auth"
    assert "No API key" in out["error"]


@pytest.mark.asyncio
async def test_masked_key_falls_back_to_db():
    """Key with *** should trigger DB lookup."""
    from api.routers.settings import test_external_ai

    with patch("api.settings_manager.get_setting",
               return_value={"value": "sk-real", "source": "db", "encrypted": True}), \
         patch("httpx.AsyncClient") as MockClient:
        mock_ctx = AsyncMock()
        mock_ctx.post = AsyncMock(return_value=_mk_response(200, {
            "model": "claude-sonnet-4-6",
            "usage": {"input_tokens": 3, "output_tokens": 1},
        }))
        MockClient.return_value.__aenter__.return_value = mock_ctx

        out = await test_external_ai(
            body={"provider": "claude", "api_key": "sk-r***",
                  "model": "claude-sonnet-4-6"},
            _="test_user",
        )
        # Verify the DB key was used, not the masked value
        call_headers = mock_ctx.post.call_args.kwargs["headers"]
        assert call_headers["x-api-key"] == "sk-real"

    assert out["ok"] is True
    assert out["input_tokens"]  == 3
    assert out["output_tokens"] == 1


@pytest.mark.asyncio
async def test_401_marked_as_auth_stage():
    from api.routers.settings import test_external_ai
    with patch("httpx.AsyncClient") as MockClient:
        mock_ctx = AsyncMock()
        mock_ctx.post = AsyncMock(return_value=_mk_response(401, {
            "error": {"message": "invalid x-api-key"},
        }))
        MockClient.return_value.__aenter__.return_value = mock_ctx

        out = await test_external_ai(
            body={"provider": "claude", "api_key": "sk-bad",
                  "model": "claude-sonnet-4-6"},
            _="test_user",
        )
    assert out["ok"] is False
    assert out["stage"] == "auth"
    assert out["status"] == 401
    assert "invalid" in out["error"].lower()


@pytest.mark.asyncio
async def test_404_model_marked_as_request_stage():
    """Model-not-found is a request-stage problem, not auth."""
    from api.routers.settings import test_external_ai
    with patch("httpx.AsyncClient") as MockClient:
        mock_ctx = AsyncMock()
        mock_ctx.post = AsyncMock(return_value=_mk_response(404, {
            "error": {"message": "model not found: claude-sonnet-99"},
        }))
        MockClient.return_value.__aenter__.return_value = mock_ctx

        out = await test_external_ai(
            body={"provider": "claude", "api_key": "sk-ok",
                  "model": "claude-sonnet-99"},
            _="test_user",
        )
    assert out["ok"] is False
    assert out["stage"] == "request"
    assert "model" in out["error"].lower()


@pytest.mark.asyncio
async def test_openai_uses_bearer_header():
    from api.routers.settings import test_external_ai
    with patch("httpx.AsyncClient") as MockClient:
        mock_ctx = AsyncMock()
        mock_ctx.post = AsyncMock(return_value=_mk_response(200, {
            "model": "gpt-4o",
            "usage": {"prompt_tokens": 2, "completion_tokens": 1},
        }))
        MockClient.return_value.__aenter__.return_value = mock_ctx

        out = await test_external_ai(
            body={"provider": "openai", "api_key": "sk-openai",
                  "model": "gpt-4o"},
            _="test_user",
        )
        call = mock_ctx.post.call_args
        assert call.args[0] == "https://api.openai.com/v1/chat/completions"
        assert call.kwargs["headers"]["Authorization"] == "Bearer sk-openai"
    assert out["ok"] is True
    # OpenAI schema → translated to input_tokens/output_tokens in response
    assert out["input_tokens"]  == 2
    assert out["output_tokens"] == 1


@pytest.mark.asyncio
async def test_grok_hits_xai_base():
    from api.routers.settings import test_external_ai
    with patch("httpx.AsyncClient") as MockClient:
        mock_ctx = AsyncMock()
        mock_ctx.post = AsyncMock(return_value=_mk_response(200, {"model": "grok-2-latest"}))
        MockClient.return_value.__aenter__.return_value = mock_ctx

        out = await test_external_ai(
            body={"provider": "grok", "api_key": "xai-key", "model": "grok-2-latest"},
            _="test_user",
        )
        assert mock_ctx.post.call_args.args[0] == "https://api.x.ai/v1/chat/completions"
    assert out["ok"] is True


@pytest.mark.asyncio
async def test_timeout_marked_as_request_stage():
    import httpx
    from api.routers.settings import test_external_ai
    with patch("httpx.AsyncClient") as MockClient:
        mock_ctx = AsyncMock()
        mock_ctx.post = AsyncMock(side_effect=httpx.TimeoutException("slow"))
        MockClient.return_value.__aenter__.return_value = mock_ctx

        out = await test_external_ai(
            body={"provider": "claude", "api_key": "sk-x", "model": "claude-sonnet-4-6"},
            _="test_user",
        )
    assert out["ok"] is False
    assert out["stage"] == "request"
    assert "Timed out" in out["error"]
