import asyncio
import os
from unittest.mock import patch, MagicMock


def test_poll_returns_services_key():
    from api.collectors.external_services import ExternalServicesCollector
    collector = ExternalServicesCollector()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.elapsed.total_seconds.return_value = 0.042
    mock_resp.json.return_value = {"data": [{"id": "llama-3.1-8b"}]}

    env = {
        "LM_STUDIO_URL": "http://192.168.1.100:1234",
        "PROXMOX_HOST": "192.168.1.5",
        "TRUENAS_HOST": "192.168.1.10",
        "FORTIGATE_HOST": "192.168.1.1",
    }
    with patch.dict(os.environ, env, clear=False), \
         patch("api.collectors.external_services.httpx.get", return_value=mock_resp):
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

    env = {"LM_STUDIO_URL": "", "PROXMOX_HOST": "", "TRUENAS_HOST": "", "FORTIGATE_HOST": ""}
    with patch.dict(os.environ, env, clear=False):
        result = asyncio.run(collector.poll())

    assert "services" in result
    # All unconfigured → grey dots
    for svc in result["services"]:
        assert svc["dot"] == "grey"


def test_unreachable_service_returns_red_dot():
    from api.collectors.external_services import ExternalServicesCollector
    collector = ExternalServicesCollector()

    env = {"LM_STUDIO_URL": "http://192.168.1.100:1234"}
    with patch.dict(os.environ, env, clear=False), \
         patch("api.collectors.external_services.httpx.get", side_effect=Exception("connection refused")):
        result = asyncio.run(collector.poll())

    lm = next(s for s in result["services"] if s["slug"] == "lm_studio")
    assert lm["dot"] == "red"
    assert lm["reachable"] is False
