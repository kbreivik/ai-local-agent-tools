"""Tests for GET /api/dashboard/* endpoints.

All tests mock `api.db.queries.get_latest_snapshot` to avoid a real DB,
and use a real JWT obtained via the login endpoint.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from api.main import app
from api.auth import get_current_user

_tc = TestClient(app)


# ── Auth-bypassing fixture for POST action tests ────────────────────────────────

@pytest.fixture
def client():
    """TestClient with get_current_user overridden to bypass auth."""
    app.dependency_overrides[get_current_user] = lambda: "admin"
    c = TestClient(app)
    yield c
    app.dependency_overrides.pop(get_current_user, None)


# ── Auth helper ────────────────────────────────────────────────────────────────

def auth_headers():
    """Obtain a valid JWT for test requests."""
    r = _tc.post("/api/auth/login", json={"username": "admin", "password": "superduperadmin"})
    if r.status_code != 200:
        pytest.skip("Auth not available in test env")
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ── Snapshot fixtures ──────────────────────────────────────────────────────────

def _agent01_snap():
    return {
        "component": "docker_agent01",
        "timestamp": "2026-01-01T00:00:00+00:00",
        "is_healthy": True,
        "state": json.dumps({
            "health": "healthy",
            "agent01_ip": "192.168.199.10",
            "containers": [
                {
                    "id": "abc123",
                    "name": "hp1_agent",
                    "image": "hp1-ai-agent:latest",
                    "state": "running",
                    "health": "healthy",
                    "ip_port": "192.168.199.10:8000",
                    "uptime": "Up 3 hours",
                    "ports": ["8000→8000"],
                    "volumes": [],
                    "last_pull_at": "2026-01-01T00:00:00+00:00",
                    "dot": "green",
                    "problem": None,
                }
            ],
        }),
    }


def _swarm_snap():
    return {
        "component": "swarm",
        "timestamp": "2026-01-01T00:00:00+00:00",
        "is_healthy": True,
        "state": json.dumps({
            "health": "healthy",
            "message": "3 nodes, 2 services — all healthy",
            "nodes": [
                {"id": "node1", "hostname": "manager-01", "role": "manager",
                 "state": "ready", "availability": "active", "leader": True},
                {"id": "node2", "hostname": "manager-02", "role": "manager",
                 "state": "ready", "availability": "active", "leader": False},
                {"id": "node3", "hostname": "worker-01", "role": "worker",
                 "state": "ready", "availability": "active", "leader": False},
            ],
            "services": [
                {
                    "id": "svc1",
                    "name": "hp1_stack_api",
                    "image": "hp1-ai-agent:latest",
                    "desired_replicas": 1,
                    "running_replicas": 1,
                    "mode": "replicated",
                    "update_state": "",
                },
                {
                    "id": "svc2",
                    "name": "hp1_stack_worker",
                    "image": "hp1-ai-agent:latest",
                    "desired_replicas": 2,
                    "running_replicas": 1,
                    "mode": "replicated",
                    "update_state": "",
                },
            ],
            "node_count": 3,
            "service_count": 2,
            "manager_count": 2,
        }),
    }


def _proxmox_snap():
    return {
        "component": "proxmox_vms",
        "timestamp": "2026-01-01T00:00:00+00:00",
        "is_healthy": True,
        "state": json.dumps({
            "health": "healthy",
            "vms": [
                {
                    "vmid": 9200,
                    "name": "hp1-prod-agent-01",
                    "node": "Pmox1",
                    "status": "running",
                    "ip": "192.168.199.10",
                    "vcpus": 4,
                    "maxmem_gb": 8.0,
                    "cpu_pct": 5.0,
                    "mem_used_gb": 3.2,
                    "disks": [],
                    "dot": "green",
                    "problem": None,
                }
            ],
        }),
    }


def _external_snap():
    return {
        "component": "external_services",
        "timestamp": "2026-01-01T00:00:00+00:00",
        "is_healthy": True,
        "state": json.dumps({
            "health": "healthy",
            "services": [
                {
                    "name": "LM Studio",
                    "slug": "lm_studio",
                    "service_type": "OpenAI-compat API",
                    "host_port": "192.168.1.100:1234",
                    "summary": "qwen2.5-7b",
                    "latency_ms": 42,
                    "reachable": True,
                    "open_ui_url": None,
                    "storage": None,
                    "dot": "green",
                    "problem": None,
                }
            ],
        }),
    }


def _image_digest_snap():
    return {
        "component": "image_digest:hp1-ai-agent:latest",
        "timestamp": "2026-01-01T12:00:00+00:00",
        "is_healthy": True,
        "state": {"digest": "sha256:abc", "image": "hp1-ai-agent:latest"},
    }


# ── /containers/agent01 ────────────────────────────────────────────────────────

def test_containers_agent01_requires_auth():
    """GET /api/dashboard/containers/agent01 without token returns 401."""
    r = _tc.get("/api/dashboard/containers/agent01")
    assert r.status_code == 401


def test_containers_agent01_returns_containers_and_health():
    """Returns containers list, agent01_ip, and health from snapshot."""
    h = auth_headers()

    async def fake_snapshot(conn, component):
        if component == "docker_agent01":
            return _agent01_snap()
        return {}

    with patch("api.routers.dashboard.q.get_latest_snapshot", side_effect=fake_snapshot):
        r = _tc.get("/api/dashboard/containers/agent01", headers=h)

    assert r.status_code == 200, r.text
    body = r.json()
    assert "containers" in body
    assert "agent01_ip" in body
    assert "health" in body
    assert body["health"] == "healthy"
    assert body["agent01_ip"] == "192.168.199.10"
    assert len(body["containers"]) == 1
    assert body["containers"][0]["name"] == "hp1_agent"


def test_containers_agent01_no_snapshot_returns_unknown():
    """When no snapshot exists, health is unknown and containers is empty."""
    h = auth_headers()

    async def fake_snapshot(conn, component):
        return {}

    with patch("api.routers.dashboard.q.get_latest_snapshot", side_effect=fake_snapshot):
        r = _tc.get("/api/dashboard/containers/agent01", headers=h)

    assert r.status_code == 200
    body = r.json()
    assert body["health"] == "unknown"
    assert body["containers"] == []


# ── /containers/swarm ──────────────────────────────────────────────────────────

def test_containers_swarm_requires_auth():
    """GET /api/dashboard/containers/swarm without token returns 401."""
    r = _tc.get("/api/dashboard/containers/swarm")
    assert r.status_code == 401


def test_containers_swarm_returns_services_and_nodes():
    """Returns services with dot/problem, swarm_managers, swarm_workers, health."""
    h = auth_headers()

    async def fake_snapshot(conn, component):
        if component == "swarm":
            return _swarm_snap()
        if "image_digest:" in component:
            return _image_digest_snap()
        return {}

    with patch("api.routers.dashboard.q.get_latest_snapshot", side_effect=fake_snapshot):
        r = _tc.get("/api/dashboard/containers/swarm", headers=h)

    assert r.status_code == 200, r.text
    body = r.json()
    assert "services" in body
    assert "swarm_managers" in body
    assert "swarm_workers" in body
    assert "health" in body
    assert body["health"] == "healthy"
    assert isinstance(body["services"], list)
    assert isinstance(body["swarm_managers"], int)
    assert isinstance(body["swarm_workers"], int)


def test_containers_swarm_services_have_dot_and_problem():
    """Each swarm service has dot and problem fields computed dynamically."""
    h = auth_headers()

    async def fake_snapshot(conn, component):
        if component == "swarm":
            return _swarm_snap()
        return {}

    with patch("api.routers.dashboard.q.get_latest_snapshot", side_effect=fake_snapshot):
        r = _tc.get("/api/dashboard/containers/swarm", headers=h)

    assert r.status_code == 200
    services = r.json()["services"]
    assert len(services) == 2
    # First service: 1/1 replicas → green
    svc_api = next(s for s in services if s["name"] == "hp1_stack_api")
    assert svc_api["dot"] == "green"
    assert svc_api["problem"] is None
    # Second service: 1/2 replicas → amber
    svc_worker = next(s for s in services if s["name"] == "hp1_stack_worker")
    assert svc_worker["dot"] == "amber"
    assert svc_worker["problem"] is not None


def test_containers_swarm_managers_and_workers_split_correctly():
    """Managers and workers are split from nodes by role."""
    h = auth_headers()

    async def fake_snapshot(conn, component):
        if component == "swarm":
            return _swarm_snap()
        return {}

    with patch("api.routers.dashboard.q.get_latest_snapshot", side_effect=fake_snapshot):
        r = _tc.get("/api/dashboard/containers/swarm", headers=h)

    assert r.status_code == 200
    body = r.json()
    assert body["swarm_managers"] == 2
    assert body["swarm_workers"] == 1


def test_containers_swarm_no_snapshot_returns_unknown():
    """When no snapshot exists, returns empty lists and unknown health."""
    h = auth_headers()

    async def fake_snapshot(conn, component):
        return {}

    with patch("api.routers.dashboard.q.get_latest_snapshot", side_effect=fake_snapshot):
        r = _tc.get("/api/dashboard/containers/swarm", headers=h)

    assert r.status_code == 200
    body = r.json()
    assert body["health"] == "unknown"
    assert body["services"] == []
    assert body["swarm_managers"] == 0
    assert body["swarm_workers"] == 0


# ── /vms ──────────────────────────────────────────────────────────────────────

def test_vms_requires_auth():
    """GET /api/dashboard/vms without token returns 401."""
    r = _tc.get("/api/dashboard/vms")
    assert r.status_code == 401


def test_vms_returns_vms_and_health():
    """Returns vms list and health from proxmox_vms snapshot."""
    h = auth_headers()

    async def fake_snapshot(conn, component):
        if component == "proxmox_vms":
            return _proxmox_snap()
        return {}

    with patch("api.routers.dashboard.q.get_latest_snapshot", side_effect=fake_snapshot):
        r = _tc.get("/api/dashboard/vms", headers=h)

    assert r.status_code == 200, r.text
    body = r.json()
    assert "vms" in body
    assert "health" in body
    assert body["health"] == "healthy"
    assert len(body["vms"]) == 1
    assert body["vms"][0]["name"] == "hp1-prod-agent-01"


def test_vms_no_snapshot_returns_unknown():
    """When no snapshot exists, health is unknown and vms is empty."""
    h = auth_headers()

    async def fake_snapshot(conn, component):
        return {}

    with patch("api.routers.dashboard.q.get_latest_snapshot", side_effect=fake_snapshot):
        r = _tc.get("/api/dashboard/vms", headers=h)

    assert r.status_code == 200
    body = r.json()
    assert body["health"] == "unknown"
    assert body["vms"] == []


# ── /external ─────────────────────────────────────────────────────────────────

def test_external_requires_auth():
    """GET /api/dashboard/external without token returns 401."""
    r = _tc.get("/api/dashboard/external")
    assert r.status_code == 401


def test_external_returns_services_and_health():
    """Returns services list and health from external_services snapshot."""
    h = auth_headers()

    async def fake_snapshot(conn, component):
        if component == "external_services":
            return _external_snap()
        return {}

    with patch("api.routers.dashboard.q.get_latest_snapshot", side_effect=fake_snapshot):
        r = _tc.get("/api/dashboard/external", headers=h)

    assert r.status_code == 200, r.text
    body = r.json()
    assert "services" in body
    assert "health" in body
    assert body["health"] == "healthy"
    assert len(body["services"]) == 1
    assert body["services"][0]["name"] == "LM Studio"


def test_external_no_snapshot_returns_unknown():
    """When no snapshot exists, health is unknown and services is empty."""
    h = auth_headers()

    async def fake_snapshot(conn, component):
        return {}

    with patch("api.routers.dashboard.q.get_latest_snapshot", side_effect=fake_snapshot):
        r = _tc.get("/api/dashboard/external", headers=h)

    assert r.status_code == 200
    body = r.json()
    assert body["health"] == "unknown"
    assert body["services"] == []


# ── _swarm_dot / _swarm_problem helpers ───────────────────────────────────────

def test_swarm_dot_all_running():
    from api.routers.dashboard import _swarm_dot
    svc = {"running_replicas": 3, "desired_replicas": 3}
    assert _swarm_dot(svc) == "green"


def test_swarm_dot_partial():
    from api.routers.dashboard import _swarm_dot
    svc = {"running_replicas": 1, "desired_replicas": 3}
    assert _swarm_dot(svc) == "amber"


def test_swarm_dot_none_running():
    from api.routers.dashboard import _swarm_dot
    svc = {"running_replicas": 0, "desired_replicas": 3}
    assert _swarm_dot(svc) == "red"


def test_swarm_problem_none_when_healthy():
    from api.routers.dashboard import _swarm_problem
    svc = {"running_replicas": 2, "desired_replicas": 2}
    assert _swarm_problem(svc) is None


def test_swarm_problem_message_when_partial():
    from api.routers.dashboard import _swarm_problem
    svc = {"running_replicas": 1, "desired_replicas": 3}
    msg = _swarm_problem(svc)
    assert msg is not None
    assert "1/3" in msg


def test_swarm_problem_message_when_zero():
    from api.routers.dashboard import _swarm_problem
    svc = {"running_replicas": 0, "desired_replicas": 2}
    assert _swarm_problem(svc) == "no replicas running"


# ── POST action tests ──────────────────────────────────────────────────────────

def test_restart_container(client):
    with patch("docker.DockerClient") as mock_dc:
        mock_container = MagicMock()
        mock_dc.return_value.containers.get.return_value = mock_container
        r = client.post("/api/dashboard/containers/abc123/restart")
    assert r.status_code == 200
    assert r.json()["ok"] is True

def test_stop_container(client):
    with patch("docker.DockerClient") as mock_dc:
        mock_container = MagicMock()
        mock_dc.return_value.containers.get.return_value = mock_container
        r = client.post("/api/dashboard/containers/abc123/stop")
    assert r.status_code == 200
    assert r.json()["ok"] is True

def test_scale_service(client):
    with patch("docker.DockerClient") as mock_dc:
        mock_service = MagicMock()
        mock_dc.return_value.services.get.return_value = mock_service
        r = client.post("/api/dashboard/services/myservice/scale", json={"replicas": 3})
    assert r.status_code == 200
    assert r.json()["ok"] is True

def test_probe_external_lm_studio(client):
    import os
    with patch.dict(os.environ, {"LM_STUDIO_URL": "http://192.168.1.100:1234"}):
        with patch("httpx.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_get.return_value = mock_resp
            r = client.post("/api/dashboard/external/lm_studio/probe")
    assert r.status_code == 200
    data = r.json()
    assert "reachable" in data
    assert "latency_ms" in data

def test_probe_external_unknown_slug(client):
    r = client.post("/api/dashboard/external/nonexistent_slug/probe")
    assert r.status_code == 200
    data = r.json()
    assert data["reachable"] is False
    assert data["latency_ms"] is None
