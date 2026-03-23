# tests/test_collectors_docker_agent01.py
import pytest
from unittest.mock import MagicMock, patch

def test_poll_returns_containers_key():
    from api.collectors.docker_agent01 import DockerAgent01Collector
    collector = DockerAgent01Collector()

    mock_container = MagicMock()
    mock_container.id = "abc123def456"
    mock_container.short_id = "abc123"
    mock_container.attrs = {
        "Name": "/hp1_agent",
        "Config": {"Image": "hp1-ai-agent:latest"},
        "State": {"Status": "running", "Health": {"Status": "healthy"}},
        "HostConfig": {},
        "Mounts": [],
        "NetworkSettings": {"Ports": {"8000/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8000"}]}},
        "Status": "Up 3 hours",
    }
    mock_container.image.id = "sha256:abc"

    mock_client = MagicMock()
    mock_client.containers.list.return_value = [mock_container]
    mock_client.df.return_value = {"Volumes": []}

    with patch("docker.DockerClient", return_value=mock_client):
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(collector.poll())

    assert "containers" in result
    assert result["health"] in ("healthy", "degraded", "error", "critical")
    assert result["containers"][0]["name"] == "hp1_agent"
