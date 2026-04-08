"""Tests for webhook dispatch added in v1.25."""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock


# ── _dispatch_webhook ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dispatch_webhook_no_url():
    """No URL configured → returns silently without making any HTTP call."""
    from api.alerts import _dispatch_webhook
    with patch("api.settings_manager.get_setting", return_value={"value": ""}):
        # Should not raise, should not call httpx
        await _dispatch_webhook({"severity": "critical", "message": "test"})


@pytest.mark.asyncio
async def test_dispatch_webhook_sends_post():
    """URL configured → POSTs the alert payload."""
    from api.alerts import _dispatch_webhook
    mock_response = MagicMock()
    mock_response.status_code = 200

    with patch("api.settings_manager.get_setting", return_value={"value": "https://example.com/hook"}):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)
            await _dispatch_webhook({
                "severity": "critical",
                "component": "external_services",
                "message": "TrueNAS: healthy → error",
                "timestamp": "2026-04-08T12:00:00Z",
            })
            mock_client.post.assert_called_once()
            call_kwargs = mock_client.post.call_args
            assert call_kwargs[0][0] == "https://example.com/hook"
            payload = call_kwargs[1]["json"]
            assert payload["severity"] == "critical"
            assert payload["platform"] == "deathstar"


@pytest.mark.asyncio
async def test_dispatch_webhook_tolerates_http_error():
    """Non-2xx response → logs debug, does not raise."""
    from api.alerts import _dispatch_webhook
    mock_response = MagicMock()
    mock_response.status_code = 500

    with patch("api.settings_manager.get_setting", return_value={"value": "https://example.com/hook"}):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)
            await _dispatch_webhook({"severity": "warning", "message": "test"})
            # Should not raise


@pytest.mark.asyncio
async def test_dispatch_webhook_tolerates_connection_error():
    """Connection error → logs debug, does not raise."""
    import httpx
    from api.alerts import _dispatch_webhook

    with patch("api.settings_manager.get_setting", return_value={"value": "https://unreachable.invalid/hook"}):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)
            await _dispatch_webhook({"severity": "critical", "message": "test"})
            # Should not raise


# ── test-webhook endpoint ─────────────────────────────────────────────────────

def test_test_webhook_no_url_configured():
    from fastapi.testclient import TestClient
    from api.main import app
    client = TestClient(app)
    login = client.post("/api/auth/login", json={"username": "admin", "password": "superduperadmin"})
    token = login.json().get("access_token", "")
    headers = {"Authorization": f"Bearer {token}"}

    with patch("api.settings_manager.get_setting", return_value={"value": ""}):
        resp = client.post("/api/alerts/test-webhook", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["ok"] is False
    assert "No webhook URL" in resp.json()["message"]


def test_test_webhook_requires_auth():
    from fastapi.testclient import TestClient
    from api.main import app
    client = TestClient(app)
    resp = client.post("/api/alerts/test-webhook")
    assert resp.status_code == 401


def test_settings_keys_include_notification_keys():
    from api.routers.settings import SETTINGS_KEYS
    assert "notificationWebhookUrl" in SETTINGS_KEYS
    assert "notifyOnRecovery" in SETTINGS_KEYS
    assert SETTINGS_KEYS["notificationWebhookUrl"]["sens"] is False
    assert SETTINGS_KEYS["notifyOnRecovery"]["default"] is False


def test_notification_keys_in_categories():
    from api.settings_manager import CATEGORIES
    assert CATEGORIES.get("notificationWebhookUrl") == "notifications"
    assert CATEGORIES.get("notifyOnRecovery") == "notifications"
