"""
API contract tests for GET /api/entities and GET /api/entities/health.
Mocks _build_entities to avoid DB dependency.
"""
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from api.collectors.base import Entity


def _sample_entities():
    return [
        Entity(id="proxmox_vms:pve1:vm:100", label="vm-100", component="proxmox_vms",
               platform="proxmox", section="COMPUTE", status="healthy", latency_ms=30),
        Entity(id="external_services:truenas", label="TrueNAS", component="external_services",
               platform="truenas", section="STORAGE", status="error", last_error="unreachable"),
        Entity(id="external_services:fortigate", label="FortiGate", component="external_services",
               platform="fortigate", section="NETWORK", status="healthy", latency_ms=18),
    ]


@pytest.fixture
def client():
    from api.main import app
    return TestClient(app)


@pytest.fixture
def mock_entities():
    return [e.to_dict() for e in _sample_entities()]


def _auth_header(client):
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "superduperadmin"})
    token = resp.json().get("access_token", "")
    return {"Authorization": f"Bearer {token}"}


def test_entities_health_no_auth_required(client, mock_entities):
    with patch("api.routers.entities._build_entities", new_callable=AsyncMock, return_value=mock_entities):
        resp = client.get("/api/entities/health")
    assert resp.status_code == 200


def test_entities_health_rollup_worst_status(client, mock_entities):
    with patch("api.routers.entities._build_entities", new_callable=AsyncMock, return_value=mock_entities):
        resp = client.get("/api/entities/health")
    data = resp.json()
    assert data["status"] == "error"
    assert data["entity_count"] == 3
    assert data["error_count"] == 1


def test_entities_health_section_summary(client, mock_entities):
    with patch("api.routers.entities._build_entities", new_callable=AsyncMock, return_value=mock_entities):
        resp = client.get("/api/entities/health")
    summary = resp.json()["section_summary"]
    assert "COMPUTE" in summary and "STORAGE" in summary and "NETWORK" in summary
    assert summary["STORAGE"]["error"] == 1
    assert summary["COMPUTE"]["healthy"] == 1


def test_entities_health_all_healthy(client):
    healthy = [Entity(id=f"x:{i}", label=f"x{i}", component="c", platform="proxmox",
                      section="COMPUTE", status="healthy").to_dict() for i in range(3)]
    with patch("api.routers.entities._build_entities", new_callable=AsyncMock, return_value=healthy):
        resp = client.get("/api/entities/health")
    assert resp.json()["status"] == "healthy"


def test_entities_health_maintenance_excluded(client):
    entities = [
        Entity(id="a:1", label="A", component="c", platform="proxmox",
               section="COMPUTE", status="maintenance").to_dict(),
        Entity(id="a:2", label="B", component="c", platform="truenas",
               section="STORAGE", status="healthy").to_dict(),
    ]
    with patch("api.routers.entities._build_entities", new_callable=AsyncMock, return_value=entities):
        resp = client.get("/api/entities/health")
    assert resp.json()["status"] == "healthy"


def test_entities_list_requires_auth(client):
    resp = client.get("/api/entities")
    assert resp.status_code == 401


def test_entities_list_returns_all(client, mock_entities):
    with patch("api.routers.entities._build_entities", new_callable=AsyncMock, return_value=mock_entities):
        resp = client.get("/api/entities", headers=_auth_header(client))
    assert resp.status_code == 200
    ids = [e["id"] for e in resp.json()]
    assert "proxmox_vms:pve1:vm:100" in ids


def test_entities_shape(client, mock_entities):
    with patch("api.routers.entities._build_entities", new_callable=AsyncMock, return_value=mock_entities):
        resp = client.get("/api/entities", headers=_auth_header(client))
    for e in resp.json():
        for field in ("id", "label", "component", "platform", "section", "status"):
            assert field in e
        assert e["status"] in ("healthy", "degraded", "error", "maintenance", "unknown")


def test_entities_section_filter(client, mock_entities):
    with patch("api.routers.entities._build_entities", new_callable=AsyncMock, return_value=mock_entities):
        resp = client.get("/api/entities/section/COMPUTE", headers=_auth_header(client))
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["section"] == "COMPUTE"


def test_entities_section_case_insensitive(client, mock_entities):
    with patch("api.routers.entities._build_entities", new_callable=AsyncMock, return_value=mock_entities):
        resp = client.get("/api/entities/section/storage", headers=_auth_header(client))
    assert all(e["section"] == "STORAGE" for e in resp.json())
