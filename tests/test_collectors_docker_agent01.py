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


def test_ghcr_container_exposes_running_version_and_built_at():
    """GHCR image with OCI labels → running_version and built_at in card."""
    from api.collectors.docker_agent01 import DockerAgent01Collector
    collector = DockerAgent01Collector()

    mock_container = MagicMock()
    mock_container.id = "abc123def456"
    mock_container.short_id = "abc123"
    mock_container.attrs = {
        "Name": "/hp1_agent",
        "Config": {"Image": "ghcr.io/kbreivik/hp1-ai-agent:latest"},
        "State": {"Status": "running", "Health": None},
        "HostConfig": {},
        "Mounts": [],
        "NetworkSettings": {"Ports": {}},
        "Status": "Up 1 hour",
    }
    mock_container.image.id = "sha256:abc"
    mock_container.image.labels = {
        "org.opencontainers.image.version": "v1.10.0",
        "org.opencontainers.image.created": "2026-03-20T12:00:00Z",
    }

    mock_client = MagicMock()
    mock_client.containers.list.return_value = [mock_container]
    mock_client.df.return_value = {"Volumes": []}

    with patch("docker.DockerClient", return_value=mock_client), \
         patch("api.collectors.docker_agent01._load_last_digests", return_value={}), \
         patch("api.collectors.docker_agent01._check_digest", return_value=None):
        result = asyncio.run(collector.poll())

    card = result["containers"][0]
    assert card["running_version"] == "1.10.0"        # leading v stripped
    assert card["built_at"] == "2026-03-20T12:00:00Z"


def test_non_ghcr_container_has_null_version_fields():
    """Non-GHCR image → running_version and built_at are None regardless of labels."""
    from api.collectors.docker_agent01 import DockerAgent01Collector
    collector = DockerAgent01Collector()

    mock_container = MagicMock()
    mock_container.id = "def456abc123"
    mock_container.short_id = "def456"
    mock_container.attrs = {
        "Name": "/muninndb",
        "Config": {"Image": "postgres:16"},
        "State": {"Status": "running", "Health": None},
        "HostConfig": {},
        "Mounts": [],
        "NetworkSettings": {"Ports": {}},
        "Status": "Up 2 days",
    }
    mock_container.image.id = "sha256:def"
    mock_container.image.labels = {
        "org.opencontainers.image.version": "16.0",
    }

    mock_client = MagicMock()
    mock_client.containers.list.return_value = [mock_container]
    mock_client.df.return_value = {"Volumes": []}

    with patch("docker.DockerClient", return_value=mock_client), \
         patch("api.collectors.docker_agent01._load_last_digests", return_value={}), \
         patch("api.collectors.docker_agent01._check_digest", return_value=None):
        result = asyncio.run(collector.poll())

    card = result["containers"][0]
    assert card["running_version"] is None
    assert card["built_at"] is None


def test_ghcr_container_missing_labels_has_null_version():
    """GHCR image with no OCI labels → running_version is None, no crash."""
    from api.collectors.docker_agent01 import DockerAgent01Collector
    collector = DockerAgent01Collector()

    mock_container = MagicMock()
    mock_container.id = "aaa111bbb222"
    mock_container.short_id = "aaa111"
    mock_container.attrs = {
        "Name": "/hp1_agent",
        "Config": {"Image": "ghcr.io/kbreivik/hp1-ai-agent:latest"},
        "State": {"Status": "running", "Health": None},
        "HostConfig": {},
        "Mounts": [],
        "NetworkSettings": {"Ports": {}},
        "Status": "Up 5 minutes",
    }
    mock_container.image.id = "sha256:aaa"
    mock_container.image.labels = {}    # no labels

    mock_client = MagicMock()
    mock_client.containers.list.return_value = [mock_container]
    mock_client.df.return_value = {"Volumes": []}

    with patch("docker.DockerClient", return_value=mock_client), \
         patch("api.collectors.docker_agent01._load_last_digests", return_value={}), \
         patch("api.collectors.docker_agent01._check_digest", return_value=None):
        result = asyncio.run(collector.poll())

    card = result["containers"][0]
    assert card["running_version"] is None
    assert card["built_at"] is None
