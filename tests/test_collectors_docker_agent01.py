# tests/test_collectors_docker_agent01.py
import asyncio
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

    with patch("docker.DockerClient", return_value=mock_client), \
         patch("api.collectors.docker_agent01._load_last_digests", return_value={}), \
         patch("api.collectors.docker_agent01._check_digest", return_value="2026-01-01T00:00:00+00:00"):
        import asyncio
        result = asyncio.run(collector.poll())

    assert "containers" in result
    assert result["health"] == "healthy"
    assert result["containers"][0]["name"] == "hp1_agent"
    assert result["containers"][0]["last_pull_at"] is not None


def test_exited_container_returns_red_dot():
    from api.collectors.docker_agent01 import DockerAgent01Collector
    collector = DockerAgent01Collector()

    mock_container = MagicMock()
    mock_container.id = "dead1234"
    mock_container.short_id = "dead12"
    mock_container.attrs = {
        "Name": "/crashed_service",
        "Config": {"Image": "some-image:latest"},
        "State": {"Status": "exited", "Health": {}},
        "HostConfig": {},
        "Mounts": [],
        "NetworkSettings": {"Ports": {}},
        "Status": "Exited (1) 5 minutes ago",
    }
    mock_container.image.id = "sha256:def"

    mock_client = MagicMock()
    mock_client.containers.list.return_value = [mock_container]
    mock_client.df.return_value = {"Volumes": []}

    with patch("docker.DockerClient", return_value=mock_client), \
         patch("api.collectors.docker_agent01._load_last_digests", return_value={}), \
         patch("api.collectors.docker_agent01._check_digest", return_value=None):
        result = asyncio.run(collector.poll())

    assert result["containers"][0]["dot"] == "red"
    assert result["containers"][0]["problem"] == "exited"
    assert result["health"] == "critical"
