import asyncio
import os
from unittest.mock import patch, MagicMock


def test_poll_returns_services_key():
    from api.collectors.external_services import ExternalServicesCollector
    collector = ExternalServicesCollector()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": [{"id": "llama-3.1-8b"}]}

    env = {"LM_STUDIO_BASE_URL": "http://192.168.1.100:1234/v1"}
    with patch.dict(os.environ, env, clear=False), \
         patch("api.collectors.external_services.httpx.get", return_value=mock_resp), \
         patch("api.connections.get_connection_for_platform", return_value=None):
        result = asyncio.run(collector.poll())

    assert "services" in result
    assert result["health"] in ("healthy", "degraded", "critical", "error")
    for svc in result["services"]:
        assert "slug" in svc
        assert "dot" in svc
        assert svc["dot"] in ("green", "amber", "red", "grey")


def test_unconfigured_service_shows_grey():
    from api.collectors.external_services import ExternalServicesCollector
    collector = ExternalServicesCollector()

    env = {"LM_STUDIO_BASE_URL": ""}
    with patch.dict(os.environ, env, clear=False), \
         patch("api.connections.get_connection_for_platform", return_value=None):
        result = asyncio.run(collector.poll())

    assert "services" in result
    # LM Studio unconfigured → grey dot
    lm = [s for s in result["services"] if s["slug"] == "lm_studio"]
    assert len(lm) == 1
    assert lm[0]["dot"] == "grey"


def test_unreachable_service_returns_red_dot():
    from api.collectors.external_services import ExternalServicesCollector
    collector = ExternalServicesCollector()

    env = {"LM_STUDIO_BASE_URL": "http://192.168.1.100:1234/v1"}
    with patch.dict(os.environ, env, clear=False), \
         patch("api.collectors.external_services.httpx.get", side_effect=Exception("refused")), \
         patch("api.connections.get_connection_for_platform", return_value=None):
        result = asyncio.run(collector.poll())

    lm = [s for s in result["services"] if s["slug"] == "lm_studio"]
    assert len(lm) == 1
    assert lm[0]["dot"] == "red"
