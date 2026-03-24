# Dashboard Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the HP1 dashboard with four infrastructure sections (Containers agent-01, Swarm, VMs, External Services), inline expandable cards with storage/port/IP info, problem emphasis, and a Tools dropdown in the nav.

**Architecture:** New collectors write to `status_snapshots`; new `dashboard` router reads from them and serves typed card payloads; new `ServiceCards.jsx` component renders the four sections.

**Tech Stack:** Python/FastAPI (backend), React + Vite (frontend), `docker` Python SDK, `httpx` for Proxmox/external probing, Tailwind CSS (existing)

**Spec:** `docs/superpowers/specs/2026-03-23-dashboard-redesign.md`

---

## File Map

**Create:**
- `api/collectors/docker_agent01.py` — polls Docker Engine on agent-01, writes container cards to snapshots
- `api/collectors/proxmox_vms.py` — polls Proxmox API for all VM status
- `api/collectors/external_services.py` — probes LM Studio, Proxmox API, TrueNAS, FortiGate
- `api/routers/dashboard.py` — GET card endpoints + POST action endpoints
- `gui/src/components/ServiceCards.jsx` — four-section card grid with inline expand/collapse

**Modify:**
- `api/main.py` — import and register `dashboard` router
- `gui/src/api.js` — add dashboard fetch and action functions
- `gui/src/App.jsx` — Tools dropdown nav, AlertBar, wire ServiceCards into DashboardView

---

## Task 1: Docker agent-01 collector

**Files:**
- Create: `api/collectors/docker_agent01.py`

Follow the exact `SwarmCollector` pattern: subclass `BaseCollector`, set `component = "docker_agent01"`, implement `poll()` using `docker.DockerClient`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_collectors_docker_agent01.py
import pytest
from unittest.mock import MagicMock, patch

def test_poll_returns_containers_key():
    from api.collectors.docker_agent01 import DockerAgent01Collector
    collector = DockerAgent01Collector()

    mock_container = MagicMock()
    mock_container.id = "abc123def456"
    mock_container.attrs = {
        "Name": "/hp1_agent",
        "Config": {"Image": "hp1-ai-agent:latest"},
        "State": {"Status": "running", "Health": {"Status": "healthy"}},
        "HostConfig": {},
        "Mounts": [],
        "NetworkSettings": {"Ports": {"8000/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8000"}]}},
    }
    mock_container.image.id = "sha256:abc"

    mock_client = MagicMock()
    mock_client.containers.list.return_value = [mock_container]
    mock_client.df.return_value = {"Volumes": []}

    with patch("docker.DockerClient", return_value=mock_client):
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(collector.poll())

    assert "containers" in result
    assert result["health"] in ("healthy", "degraded", "error")
    assert result["containers"][0]["name"] == "hp1_agent"
```

- [ ] **Step 2: Run test to confirm it fails**

```
pytest tests/test_collectors_docker_agent01.py -v
```
Expected: `ModuleNotFoundError` or `ImportError`

- [ ] **Step 3: Implement `api/collectors/docker_agent01.py`**

```python
"""
DockerAgent01Collector — polls Docker containers on agent-01 every 30s.

Writes component="docker_agent01" to status_snapshots.
State shape: { health, containers: [ContainerCard], agent01_ip }
"""
import asyncio
import logging
import os

from api.collectors.base import BaseCollector

log = logging.getLogger(__name__)

# Static VM→IP map (matches Ansible inventory)
VM_IP = "192.168.199.10"


class DockerAgent01Collector(BaseCollector):
    component = "docker_agent01"

    def __init__(self):
        super().__init__()
        self.interval = int(os.environ.get("DOCKER_POLL_INTERVAL", "30"))

    async def poll(self) -> dict:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._collect_sync)

    def _collect_sync(self) -> dict:
        import docker
        from docker.errors import DockerException

        docker_host = os.environ.get("DOCKER_HOST", "unix:///var/run/docker.sock")
        try:
            client = docker.DockerClient(base_url=docker_host, timeout=10)
        except Exception as e:
            return {"health": "error", "error": str(e), "containers": [], "agent01_ip": VM_IP}

        try:
            containers = client.containers.list(all=False)
            volume_usage = _get_volume_usage(client)
            last_digests = _load_last_digests()

            cards = []
            for c in containers:
                attrs = c.attrs
                name = (attrs.get("Name") or "").lstrip("/")
                image = attrs.get("Config", {}).get("Image", "")
                state_str = (attrs.get("State") or {}).get("Status", "unknown")
                health_obj = (attrs.get("State") or {}).get("Health", {})
                health_str = health_obj.get("Status", "none") if health_obj else "none"
                ports = _parse_ports(attrs.get("NetworkSettings", {}).get("Ports", {}))
                mounts = [
                    m for m in (attrs.get("Mounts") or []) if m.get("Type") == "volume"
                ]
                volumes = [
                    {
                        "name": m["Name"],
                        "used_bytes": volume_usage.get(m["Name"], {}).get("used_bytes"),
                        "total_bytes": volume_usage.get(m["Name"], {}).get("total_bytes"),
                    }
                    for m in mounts
                ]

                image_id = c.image.id if c.image else None
                last_pull_at = _check_digest(c.id, image, image_id, last_digests)

                dot, problem = _classify_container(state_str, health_str)
                first_port = ports[0].split("→")[0] if ports else ""
                ip_port = f"{VM_IP}:{first_port}" if first_port else ""

                cards.append({
                    "id": c.short_id,
                    "name": name,
                    "image": image,
                    "state": state_str,
                    "health": health_str,
                    "ip_port": ip_port,
                    "uptime": attrs.get("Status", ""),
                    "ports": ports,
                    "volumes": volumes,
                    "last_pull_at": last_pull_at,
                    "dot": dot,
                    "problem": problem,
                })

            overall = "healthy" if all(c["dot"] == "green" for c in cards) else \
                      "degraded" if any(c["dot"] == "amber" for c in cards) else \
                      "critical"
            return {"health": overall, "containers": cards, "agent01_ip": VM_IP}

        except DockerException as e:
            return {"health": "error", "error": str(e), "containers": [], "agent01_ip": VM_IP}
        finally:
            try:
                client.close()
            except Exception:
                pass


def _parse_ports(ports_dict: dict) -> list[str]:
    result = []
    for container_port, bindings in ports_dict.items():
        if not bindings:
            continue
        for b in bindings:
            host_port = b.get("HostPort", "")
            cp = container_port.split("/")[0]
            if host_port:
                result.append(f"{host_port}→{cp}")
    return result


def _get_volume_usage(client) -> dict:
    """Returns {volume_name: {used_bytes, total_bytes}} from docker df."""
    try:
        df = client.df()
        result = {}
        for v in df.get("Volumes") or []:
            name = v.get("Name", "")
            usage = v.get("UsageData", {})
            result[name] = {
                "used_bytes": usage.get("Size"),
                "total_bytes": None,  # Docker df doesn't give total
            }
        return result
    except Exception:
        return {}


def _load_last_digests() -> dict:
    """Load stored image digests from status_snapshots (sync via direct DB read)."""
    import json
    try:
        from api.db.base import _engine  # use existing engine
        from sqlalchemy import text
        with _engine.connect() as conn:
            rows = conn.execute(
                text("SELECT component, state FROM status_snapshots "
                     "WHERE component LIKE 'image_digest:%' "
                     "ORDER BY timestamp DESC")
            ).fetchall()
        result = {}
        for row in rows:
            comp = row[0]
            state = row[1] if isinstance(row[1], dict) else json.loads(row[1] or "{}")
            if comp not in result:
                result[comp] = state
        return result
    except Exception:
        return {}


def _check_digest(container_id: str, image: str, image_id: str | None, last_digests: dict) -> str | None:
    """
    Compare current image_id to stored. If changed or new, write new snapshot and return now().
    Returns ISO timestamp of last known pull, or None.
    """
    if not image_id:
        return None
    key = f"image_digest:{image}"
    stored = last_digests.get(key, {})
    if stored.get("digest") != image_id:
        # New or changed — write snapshot (fire and forget via sync DB write)
        import json
        from datetime import datetime, timezone
        from api.db.base import _engine
        from sqlalchemy import text
        now = datetime.now(timezone.utc).isoformat()
        try:
            with _engine.begin() as conn:
                conn.execute(
                    text("INSERT INTO status_snapshots (component, state, is_healthy, timestamp) "
                         "VALUES (:comp, :state, true, :ts)"),
                    {"comp": key, "state": json.dumps({"digest": image_id, "image": image}), "ts": now}
                )
        except Exception:
            pass
        return now
    return stored.get("pulled_at")


def _classify_container(state: str, health: str) -> tuple[str, str | None]:
    if state == "running":
        if health in ("healthy", "none"):
            return "green", None
        if health in ("starting",):
            return "amber", "starting"
        if health == "unhealthy":
            return "amber", "health check failing"
    return "red", "exited"
```

- [ ] **Step 4: Run test to confirm it passes**

```
pytest tests/test_collectors_docker_agent01.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/collectors/docker_agent01.py tests/test_collectors_docker_agent01.py
git commit -m "feat(dashboard): add DockerAgent01Collector for container status"
```

---

## Task 2: Proxmox VM collector

**Files:**
- Create: `api/collectors/proxmox_vms.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_collectors_proxmox_vms.py
import pytest
from unittest.mock import patch, MagicMock

def test_poll_returns_vms_key():
    from api.collectors.proxmox_vms import ProxmoxVMsCollector
    collector = ProxmoxVMsCollector()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": [{"vmid": 9200, "name": "agent-01", "status": "running",
                  "cpu": 0.14, "mem": 2200000000, "maxmem": 4294967296,
                  "netin": 0, "netout": 0}]
    }

    with patch("httpx.get", return_value=mock_resp):
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(collector.poll())

    assert "vms" in result
    assert result["health"] in ("healthy", "degraded", "error", "unconfigured")
```

- [ ] **Step 2: Run test to confirm it fails**

```
pytest tests/test_collectors_proxmox_vms.py -v
```

- [ ] **Step 3: Implement `api/collectors/proxmox_vms.py`**

```python
"""
ProxmoxVMsCollector — polls all VMs across all Proxmox nodes every 30s.

Env vars: PROXMOX_HOST, PROXMOX_TOKEN_ID, PROXMOX_TOKEN_SECRET
Writes component="proxmox_vms" to status_snapshots.
State shape: { health, vms: [VMCard] }
"""
import asyncio
import logging
import os

from api.collectors.base import BaseCollector

log = logging.getLogger(__name__)

NODES = ["pve", "pve2", "pve3"]  # Proxmox node names; override via PROXMOX_NODES env

# Static vmid→IP map (matches Ansible inventory)
VM_IP_MAP = {
    9200: "192.168.199.10",
    9211: "192.168.199.21",
    9212: "192.168.199.22",
    9213: "192.168.199.23",
    9221: "192.168.199.31",
    9222: "192.168.199.32",
    9223: "192.168.199.33",
    9230: "192.168.199.40",
}

# Static vmid→friendly node label
VM_NODE_LABEL = {
    9200: "Pmox1", 9230: "Pmox1",
    9211: "Pmox3", 9212: "Pmox3", 9213: "Pmox3",
    9221: "Pmox3", 9222: "Pmox3", 9223: "Pmox3",
}


class ProxmoxVMsCollector(BaseCollector):
    component = "proxmox_vms"

    def __init__(self):
        super().__init__()
        self.interval = int(os.environ.get("PROXMOX_POLL_INTERVAL", "30"))

    async def poll(self) -> dict:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._collect_sync)

    def _collect_sync(self) -> dict:
        host = os.environ.get("PROXMOX_HOST", "")
        token_id = os.environ.get("PROXMOX_TOKEN_ID", "")
        token_secret = os.environ.get("PROXMOX_TOKEN_SECRET", "")

        if not host:
            return {"health": "unconfigured", "vms": [], "message": "PROXMOX_HOST not set"}

        import httpx
        headers = {"Authorization": f"PVEAPIToken={token_id}={token_secret}"}
        base = f"https://{host}:8006/api2/json"
        nodes = os.environ.get("PROXMOX_NODES", ",".join(NODES)).split(",")

        vms = []
        try:
            for node in nodes:
                try:
                    r = httpx.get(f"{base}/nodes/{node}/qemu",
                                  headers=headers, verify=False, timeout=8)
                    if r.status_code != 200:
                        continue
                    for vm in r.json().get("data", []):
                        vmid = vm["vmid"]
                        status = vm.get("status", "unknown")
                        cpu_pct = round(vm.get("cpu", 0) * 100, 1) if status == "running" else None
                        mem_used = vm.get("mem")
                        maxmem = vm.get("maxmem")
                        mem_used_gb = round(mem_used / 1e9, 1) if mem_used else None
                        maxmem_gb = round(maxmem / 1e9, 1) if maxmem else None

                        disks = _get_disk_usage(base, headers, node, vmid) if status == "running" else []
                        dot, problem = _classify_vm(status, disks)

                        vms.append({
                            "vmid": vmid,
                            "name": vm.get("name", f"vm-{vmid}"),
                            "node": VM_NODE_LABEL.get(vmid, node),
                            "status": status,
                            "ip": VM_IP_MAP.get(vmid, ""),
                            "vcpus": vm.get("cpus", 0),
                            "maxmem_gb": maxmem_gb,
                            "cpu_pct": cpu_pct,
                            "mem_used_gb": mem_used_gb,
                            "disks": disks,
                            "dot": dot,
                            "problem": problem,
                        })
                except Exception as e:
                    log.warning("Proxmox node %s error: %s", node, e)

            overall = "healthy" if all(v["dot"] == "green" for v in vms) else \
                      "degraded" if any(v["dot"] in ("amber", "red") for v in vms) else \
                      "healthy"
            return {"health": overall, "vms": vms}

        except Exception as e:
            return {"health": "error", "error": str(e), "vms": []}


def _get_disk_usage(base: str, headers: dict, node: str, vmid: int) -> list:
    import httpx
    try:
        r = httpx.get(f"{base}/nodes/{node}/qemu/{vmid}/agent/get-fsinfo",
                      headers=headers, verify=False, timeout=5)
        if r.status_code != 200:
            return []
        data = r.json().get("data", {})
        result_data = data.get("result", []) if isinstance(data, dict) else []
        disks = []
        for fs in result_data:
            total = fs.get("total-bytes", 0)
            used = fs.get("used-bytes", 0)
            mp = fs.get("mountpoint", "")
            if total and mp:
                disks.append({"mountpoint": mp, "used_bytes": used, "total_bytes": total})
        return disks
    except Exception:
        return []


def _classify_vm(status: str, disks: list) -> tuple[str, str | None]:
    if status == "running":
        for d in disks:
            if d["total_bytes"] and (d["used_bytes"] / d["total_bytes"]) > 0.70:
                pct = round(d["used_bytes"] / d["total_bytes"] * 100)
                return "amber", f"disk {pct}% full"
        return "green", None
    if status == "paused":
        return "amber", "paused"
    if status == "stopped":
        return "red", "stopped"
    return "grey", None
```

- [ ] **Step 4: Run test to confirm it passes**

```
pytest tests/test_collectors_proxmox_vms.py -v
```

- [ ] **Step 5: Commit**

```bash
git add api/collectors/proxmox_vms.py tests/test_collectors_proxmox_vms.py
git commit -m "feat(dashboard): add ProxmoxVMsCollector for VM status"
```

---

## Task 3: External services collector

**Files:**
- Create: `api/collectors/external_services.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_collectors_external_services.py
from unittest.mock import patch, MagicMock
import time

def test_poll_returns_services_key():
    from api.collectors.external_services import ExternalServicesCollector
    collector = ExternalServicesCollector()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.elapsed.total_seconds.return_value = 0.042

    with patch("httpx.get", return_value=mock_resp):
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(collector.poll())

    assert "services" in result
    assert result["health"] in ("healthy", "degraded", "error", "unconfigured")
    for svc in result["services"]:
        assert "slug" in svc
        assert "dot" in svc
```

- [ ] **Step 2: Run test to confirm it fails**

```
pytest tests/test_collectors_external_services.py -v
```

- [ ] **Step 3: Implement `api/collectors/external_services.py`**

```python
"""
ExternalServicesCollector — probes external service endpoints every 30s.

Services: LM Studio, Proxmox API, TrueNAS, FortiGate
Writes component="external_services" to status_snapshots.
State shape: { health, services: [ExternalServiceCard] }
"""
import asyncio
import logging
import os
import time

from api.collectors.base import BaseCollector

log = logging.getLogger(__name__)

SERVICES_CONFIG = [
    {
        "name": "LM Studio",
        "slug": "lm_studio",
        "service_type": "OpenAI-compat API",
        "host_env": "LM_STUDIO_URL",
        "path": "/v1/models",
        "open_ui_url": None,
    },
    {
        "name": "Proxmox API",
        "slug": "proxmox",
        "service_type": "Proxmox cluster API",
        "host_env": "PROXMOX_HOST",
        "path": "/api2/json/version",
        "port": 8006,
        "scheme": "https",
        "open_ui_url_template": "https://{host}:8006",
    },
    {
        "name": "TrueNAS",
        "slug": "truenas",
        "service_type": "TrueNAS REST API",
        "host_env": "TRUENAS_HOST",
        "path": "/api/v2.0/system/info",
        "scheme": "https",
        "auth_env": "TRUENAS_API_KEY",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
        "open_ui_url_template": "https://{host}",
    },
    {
        "name": "FortiGate",
        "slug": "fortigate",
        "service_type": "FortiGate REST API",
        "host_env": "FORTIGATE_HOST",
        "path": "/api/v2/monitor/system/status",
        "scheme": "https",
        "auth_env": "FORTIGATE_API_KEY",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
        "open_ui_url_template": "https://{host}",
    },
]


class ExternalServicesCollector(BaseCollector):
    component = "external_services"

    def __init__(self):
        super().__init__()
        self.interval = int(os.environ.get("EXTERNAL_POLL_INTERVAL", "30"))

    async def poll(self) -> dict:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._collect_sync)

    def _collect_sync(self) -> dict:
        import httpx

        cards = []
        for cfg in SERVICES_CONFIG:
            host_raw = os.environ.get(cfg["host_env"], "")
            # LM_STUDIO_URL may be a full URL like http://x.x.x.x:1234
            if host_raw.startswith("http"):
                base_url = host_raw.rstrip("/")
            else:
                scheme = cfg.get("scheme", "http")
                port = cfg.get("port", "")
                base_url = f"{scheme}://{host_raw}" + (f":{port}" if port else "")

            host_display = host_raw or "not configured"
            open_ui = None
            if "open_ui_url_template" in cfg and host_raw:
                open_ui = cfg["open_ui_url_template"].format(host=host_raw)

            if not host_raw:
                cards.append({
                    "name": cfg["name"], "slug": cfg["slug"],
                    "service_type": cfg["service_type"],
                    "host_port": host_display, "summary": "not configured",
                    "latency_ms": None, "reachable": False,
                    "open_ui_url": open_ui, "storage": None,
                    "dot": "grey", "problem": "not configured",
                })
                continue

            headers = {}
            auth_key = os.environ.get(cfg.get("auth_env", ""), "")
            if auth_key and "auth_header" in cfg:
                headers[cfg["auth_header"]] = cfg.get("auth_prefix", "") + auth_key

            url = base_url + cfg["path"]
            try:
                t0 = time.monotonic()
                r = httpx.get(url, headers=headers, verify=False, timeout=8, follow_redirects=True)
                latency_ms = round((time.monotonic() - t0) * 1000)
                reachable = r.status_code < 500
            except Exception:
                latency_ms = None
                reachable = False

            summary = _build_summary(cfg["slug"], r if reachable else None)
            storage = _build_storage(cfg["slug"], r if reachable else None)
            dot, problem = _classify_external(reachable, latency_ms)

            cards.append({
                "name": cfg["name"], "slug": cfg["slug"],
                "service_type": cfg["service_type"],
                "host_port": host_display,
                "summary": summary,
                "latency_ms": latency_ms,
                "reachable": reachable,
                "open_ui_url": open_ui,
                "storage": storage,
                "dot": dot,
                "problem": problem,
            })

        reachable_count = sum(1 for s in cards if s["reachable"])
        has_error = any(s["dot"] == "red" for s in cards)
        has_warn = any(s["dot"] == "amber" for s in cards)
        health = "healthy" if not has_error and not has_warn else \
                 "degraded" if has_warn else "critical"
        return {"health": health, "services": cards}


def _build_summary(slug: str, resp) -> str:
    if resp is None:
        return "unreachable"
    try:
        if slug == "lm_studio":
            data = resp.json()
            models = data.get("data", [])
            return models[0].get("id", "no model") if models else "no model loaded"
        if slug == "proxmox":
            data = resp.json().get("data", {})
            return f"version {data.get('version', '?')}"
        if slug == "truenas":
            data = resp.json()
            return f"TrueNAS {data.get('version', '?')}"
        if slug == "fortigate":
            return "authenticated"
    except Exception:
        pass
    return "ok"


def _build_storage(slug: str, resp) -> dict | None:
    """TrueNAS only — pool usage from /api/v2.0/pool endpoint."""
    if slug != "truenas" or resp is None:
        return None
    # Pool data requires a separate call — return None here; dashboard router can enrich on demand
    return None


def _classify_external(reachable: bool, latency_ms: int | None) -> tuple[str, str | None]:
    if not reachable:
        return "red", "unreachable"
    if latency_ms and latency_ms > 500:
        return "red", f"high latency ({latency_ms} ms)"
    if latency_ms and latency_ms > 100:
        return "amber", f"high latency ({latency_ms} ms)"
    return "green", None
```

- [ ] **Step 4: Run test to confirm it passes**

```
pytest tests/test_collectors_external_services.py -v
```

- [ ] **Step 5: Commit**

```bash
git add api/collectors/external_services.py tests/test_collectors_external_services.py
git commit -m "feat(dashboard): add ExternalServicesCollector for external service probing"
```

---

## Task 4: Dashboard router — GET endpoints

**Files:**
- Create: `api/routers/dashboard.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_routers_dashboard.py
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock
import json

@pytest.fixture
def client():
    from api.main import app
    with patch("api.auth.get_current_user", return_value="testuser"):
        with TestClient(app) as c:
            yield c

def _mock_snapshot(state: dict):
    return {"state": json.dumps(state), "timestamp": "2026-01-01T00:00:00Z"}

def test_get_containers_agent01(client):
    state = {"health": "healthy", "containers": [
        {"id": "abc", "name": "hp1_agent", "image": "hp1-ai-agent:latest",
         "state": "running", "health": "healthy", "ip_port": "192.168.199.10:8000",
         "uptime": "Up 2 hours", "ports": ["8000→8000"], "volumes": [],
         "last_pull_at": None, "dot": "green", "problem": None}
    ], "agent01_ip": "192.168.199.10"}

    with patch("api.db.queries.get_latest_snapshot", new_callable=AsyncMock,
               return_value=_mock_snapshot(state)):
        r = client.get("/api/dashboard/containers/agent01")
    assert r.status_code == 200
    data = r.json()
    assert "containers" in data
    assert data["containers"][0]["name"] == "hp1_agent"

def test_get_vms(client):
    state = {"health": "healthy", "vms": [
        {"vmid": 9200, "name": "agent-01", "node": "Pmox1", "status": "running",
         "ip": "192.168.199.10", "vcpus": 2, "maxmem_gb": 4.0,
         "cpu_pct": 14.0, "mem_used_gb": 2.1, "disks": [],
         "dot": "green", "problem": None}
    ]}

    with patch("api.db.queries.get_latest_snapshot", new_callable=AsyncMock,
               return_value=_mock_snapshot(state)):
        r = client.get("/api/dashboard/vms")
    assert r.status_code == 200
    assert "vms" in r.json()

def test_get_external(client):
    state = {"health": "healthy", "services": [
        {"name": "LM Studio", "slug": "lm_studio", "service_type": "OpenAI-compat API",
         "host_port": "192.168.1.100:1234", "summary": "llama-3.1-8b",
         "latency_ms": 42, "reachable": True, "open_ui_url": None,
         "storage": None, "dot": "green", "problem": None}
    ]}

    with patch("api.db.queries.get_latest_snapshot", new_callable=AsyncMock,
               return_value=_mock_snapshot(state)):
        r = client.get("/api/dashboard/external")
    assert r.status_code == 200
    assert "services" in r.json()
```

- [ ] **Step 2: Run test to confirm it fails**

```
pytest tests/test_routers_dashboard.py::test_get_containers_agent01 -v
```
Expected: 404 (route not yet registered)

- [ ] **Step 3: Implement `api/routers/dashboard.py` GET endpoints**

```python
"""
Dashboard router — serves pre-computed card payloads from status_snapshots.

GET  /api/dashboard/containers/agent01  — ContainerCards
GET  /api/dashboard/containers/swarm    — SwarmServiceCards (existing swarm snapshot)
GET  /api/dashboard/vms                 — VMCards
GET  /api/dashboard/external            — ExternalServiceCards

POST endpoints for actions are in a separate section below.
"""
import json
import logging
import os

from fastapi import APIRouter, Depends, HTTPException

from api.auth import get_current_user
from api.db.base import get_engine
from api.db import queries as q

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])
log = logging.getLogger(__name__)


def _parse_state(snap: dict | None) -> dict:
    if not snap:
        return {}
    state = snap.get("state") or {}
    if isinstance(state, str):
        try:
            state = json.loads(state)
        except Exception:
            state = {}
    return state


@router.get("/containers/agent01")
async def get_agent01_containers(user: str = Depends(get_current_user)):
    async with get_engine().connect() as conn:
        snap = await q.get_latest_snapshot(conn, "docker_agent01")
    state = _parse_state(snap)
    return {
        "containers": state.get("containers", []),
        "agent01_ip": state.get("agent01_ip", "192.168.199.10"),
        "health": state.get("health", "unknown"),
    }


@router.get("/containers/swarm")
async def get_swarm_services(user: str = Depends(get_current_user)):
    async with get_engine().connect() as conn:
        snap = await q.get_latest_snapshot(conn, "swarm")
    state = _parse_state(snap)
    services = state.get("services", [])

    # Enrich swarm services with last_pull_at from image_digest snapshots
    async with get_engine().connect() as conn:
        for svc in services:
            image = svc.get("image", "")
            if image:
                digest_snap = await q.get_latest_snapshot(conn, f"image_digest:{image}")
                digest_state = _parse_state(digest_snap)
                svc["last_pull_at"] = digest_snap.get("timestamp") if digest_snap else None
                svc["dot"] = _swarm_dot(svc)
                svc["problem"] = _swarm_problem(svc)
            else:
                svc["last_pull_at"] = None

    return {
        "services": services,
        "swarm_managers": state.get("manager_count", 0),
        "swarm_workers": len([n for n in state.get("nodes", []) if n.get("role") == "worker"]),
        "health": state.get("health", "unknown"),
    }


@router.get("/vms")
async def get_vms(user: str = Depends(get_current_user)):
    async with get_engine().connect() as conn:
        snap = await q.get_latest_snapshot(conn, "proxmox_vms")
    state = _parse_state(snap)
    return {
        "vms": state.get("vms", []),
        "health": state.get("health", "unknown"),
    }


@router.get("/external")
async def get_external_services(user: str = Depends(get_current_user)):
    async with get_engine().connect() as conn:
        snap = await q.get_latest_snapshot(conn, "external_services")
    state = _parse_state(snap)
    return {
        "services": state.get("services", []),
        "health": state.get("health", "unknown"),
    }


def _swarm_dot(svc: dict) -> str:
    running = svc.get("running_tasks") or svc.get("replicas_running", 0)
    desired = svc.get("desired_tasks") or svc.get("replicas_desired", 1)
    if running == desired:
        return "green"
    if running > 0:
        return "amber"
    return "red"


def _swarm_problem(svc: dict) -> str | None:
    running = svc.get("running_tasks") or svc.get("replicas_running", 0)
    desired = svc.get("desired_tasks") or svc.get("replicas_desired", 1)
    if running == 0:
        return "no replicas running"
    if running < desired:
        return f"{running}/{desired} replicas"
    return None
```

- [ ] **Step 4: Register router in `api/main.py`**

Add to the import line and include it:
```python
# In imports, add:
from api.routers.dashboard import router as dashboard_router
# In router registrations, add:
app.include_router(dashboard_router)
```

- [ ] **Step 5: Run tests to confirm they pass**

```
pytest tests/test_routers_dashboard.py -v
```

- [ ] **Step 6: Commit**

```bash
git add api/routers/dashboard.py api/main.py tests/test_routers_dashboard.py
git commit -m "feat(dashboard): add dashboard router with GET card endpoints"
```

---

## Task 5: Dashboard router — POST action endpoints

**Files:**
- Modify: `api/routers/dashboard.py`

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_routers_dashboard.py

def test_restart_container(client):
    with patch("docker.DockerClient") as mock_dc:
        mock_container = MagicMock()
        mock_dc.return_value.containers.get.return_value = mock_container
        r = client.post("/api/dashboard/containers/abc123/restart")
    assert r.status_code == 200
    assert r.json()["ok"] is True

def test_probe_external(client):
    import httpx
    with patch("httpx.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.elapsed.total_seconds.return_value = 0.042
        mock_get.return_value = mock_resp
        r = client.post("/api/dashboard/external/lm_studio/probe")
    assert r.status_code == 200
    data = r.json()
    assert "reachable" in data
    assert "latency_ms" in data
```

- [ ] **Step 2: Run tests to confirm they fail**

```
pytest tests/test_routers_dashboard.py::test_restart_container -v
```

- [ ] **Step 3: Add POST endpoints to `api/routers/dashboard.py`**

Append to `dashboard.py`:

```python
# ── Action endpoints ───────────────────────────────────────────────────────────

from pydantic import BaseModel


class ScaleRequest(BaseModel):
    replicas: int


def _docker_client():
    import docker
    host = os.environ.get("DOCKER_HOST", "unix:///var/run/docker.sock")
    return docker.DockerClient(base_url=host, timeout=15)


@router.post("/containers/{container_id}/pull")
async def pull_container(container_id: str, user: str = Depends(get_current_user)):
    """Pull the image for container_id and recreate it."""
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _do_pull, container_id)


def _do_pull(container_id: str) -> dict:
    try:
        client = _docker_client()
        container = client.containers.get(container_id)
        image_name = container.attrs["Config"]["Image"]
        client.images.pull(image_name)
        container.restart()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/containers/{container_id}/restart")
async def restart_container(container_id: str, user: str = Depends(get_current_user)):
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _do_restart, container_id)


def _do_restart(container_id: str) -> dict:
    try:
        client = _docker_client()
        client.containers.get(container_id).restart()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/containers/{container_id}/stop")
async def stop_container(container_id: str, user: str = Depends(get_current_user)):
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _do_stop, container_id)


def _do_stop(container_id: str) -> dict:
    try:
        client = _docker_client()
        client.containers.get(container_id).stop()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/services/{service_name}/pull")
async def pull_service(service_name: str, user: str = Depends(get_current_user)):
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _do_service_pull, service_name)


def _do_service_pull(service_name: str) -> dict:
    try:
        client = _docker_client()
        service = client.services.get(service_name)
        image = service.attrs["Spec"]["TaskTemplate"]["ContainerSpec"]["Image"]
        client.images.pull(image)
        service.force_update()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/services/{service_name}/scale")
async def scale_service(service_name: str, body: ScaleRequest, user: str = Depends(get_current_user)):
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _do_scale, service_name, body.replicas)


def _do_scale(service_name: str, replicas: int) -> dict:
    try:
        client = _docker_client()
        service = client.services.get(service_name)
        service.scale(replicas)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/vms/{node}/{vmid}/start")
async def start_vm(node: str, vmid: int, user: str = Depends(get_current_user)):
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _do_vm_action, node, vmid, "start")


@router.post("/vms/{node}/{vmid}/reboot")
async def reboot_vm(node: str, vmid: int, user: str = Depends(get_current_user)):
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _do_vm_action, node, vmid, "reboot")


def _do_vm_action(node: str, vmid: int, action: str) -> dict:
    import httpx
    host = os.environ.get("PROXMOX_HOST", "")
    token_id = os.environ.get("PROXMOX_TOKEN_ID", "")
    token_secret = os.environ.get("PROXMOX_TOKEN_SECRET", "")
    if not host:
        return {"ok": False, "error": "PROXMOX_HOST not configured"}
    try:
        headers = {"Authorization": f"PVEAPIToken={token_id}={token_secret}"}
        url = f"https://{host}:8006/api2/json/nodes/{node}/qemu/{vmid}/status/{action}"
        r = httpx.post(url, headers=headers, verify=False, timeout=10)
        if r.status_code in (200, 202):
            return {"ok": True}
        return {"ok": False, "error": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/external/{slug}/probe")
async def probe_external(slug: str, user: str = Depends(get_current_user)):
    """Fire a single probe and return fresh latency/reachable."""
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _do_probe, slug)


def _do_probe(slug: str) -> dict:
    import httpx, time
    from api.collectors.external_services import SERVICES_CONFIG
    cfg = next((c for c in SERVICES_CONFIG if c["slug"] == slug), None)
    if not cfg:
        return {"ok": False, "error": f"Unknown service: {slug}"}

    host_raw = os.environ.get(cfg["host_env"], "")
    if not host_raw:
        return {"reachable": False, "latency_ms": None}

    if host_raw.startswith("http"):
        base_url = host_raw.rstrip("/")
    else:
        scheme = cfg.get("scheme", "http")
        port = cfg.get("port", "")
        base_url = f"{scheme}://{host_raw}" + (f":{port}" if port else "")

    headers = {}
    auth_key = os.environ.get(cfg.get("auth_env", ""), "")
    if auth_key and "auth_header" in cfg:
        headers[cfg["auth_header"]] = cfg.get("auth_prefix", "") + auth_key

    try:
        t0 = time.monotonic()
        r = httpx.get(base_url + cfg["path"], headers=headers, verify=False,
                      timeout=8, follow_redirects=True)
        latency_ms = round((time.monotonic() - t0) * 1000)
        return {"reachable": r.status_code < 500, "latency_ms": latency_ms}
    except Exception:
        return {"reachable": False, "latency_ms": None}
```

- [ ] **Step 4: Run tests to confirm they pass**

```
pytest tests/test_routers_dashboard.py -v
```

- [ ] **Step 5: Commit**

```bash
git add api/routers/dashboard.py tests/test_routers_dashboard.py
git commit -m "feat(dashboard): add POST action endpoints (pull, restart, stop, scale, VM start/reboot, probe)"
```

---

## Task 6: Frontend — dashboard API functions

**Files:**
- Modify: `gui/src/api.js`

- [ ] **Step 1: Add functions to `api.js`**

Append to `gui/src/api.js`:

```js
// ── Dashboard ─────────────────────────────────────────────────────────────────

export async function fetchDashboardContainers() {
  const r = await fetch(`${BASE}/api/dashboard/containers/agent01`, { headers: authHeaders() })
  return r.json()
}

export async function fetchDashboardSwarm() {
  const r = await fetch(`${BASE}/api/dashboard/containers/swarm`, { headers: authHeaders() })
  return r.json()
}

export async function fetchDashboardVMs() {
  const r = await fetch(`${BASE}/api/dashboard/vms`, { headers: authHeaders() })
  return r.json()
}

export async function fetchDashboardExternal() {
  const r = await fetch(`${BASE}/api/dashboard/external`, { headers: authHeaders() })
  return r.json()
}

export async function dashboardAction(path, body = null) {
  const r = await fetch(`${BASE}/api/dashboard/${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: body ? JSON.stringify(body) : undefined,
  })
  return r.json()
}
```

- [ ] **Step 2: Verify by checking the file was updated correctly**

```bash
grep -n "fetchDashboardContainers\|dashboardAction" gui/src/api.js
```

- [ ] **Step 3: Commit**

```bash
git add gui/src/api.js
git commit -m "feat(dashboard): add dashboard API fetch + action helpers"
```

---

## Task 7: Frontend — ServiceCards component

**Files:**
- Create: `gui/src/components/ServiceCards.jsx`

This is the main visual component. Implement all four sections with inline card expansion.

- [ ] **Step 1: Create `gui/src/components/ServiceCards.jsx`**

```jsx
/**
 * ServiceCards — four-section infrastructure dashboard.
 * Sections: Containers·agent-01, Containers·Swarm, VMs·Proxmox, External Services
 * Cards expand inline on click; one open at a time globally.
 */
import { useState, useEffect, useCallback, useRef } from 'react'
import {
  fetchDashboardContainers, fetchDashboardSwarm,
  fetchDashboardVMs, fetchDashboardExternal,
  dashboardAction
} from '../api'

const POLL_MS = 30_000

// ── Visual helpers ─────────────────────────────────────────────────────────────

const DOT_CLS = {
  green: 'bg-green-500 ring-1 ring-green-400/40',
  amber: 'bg-amber-500 ring-1 ring-amber-400/40',
  red:   'bg-red-500 ring-1 ring-red-400/60 animate-pulse',
  grey:  'bg-gray-600',
}

const CARD_STATE = {
  healthy: { bg: 'bg-[#131325]', border: 'border-[#1e1e3a]', nameCls: 'text-gray-100' },
  warn:    { bg: 'bg-[#161008]', border: 'border-[#3a2a0a]', nameCls: 'text-amber-200' },
  error:   { bg: 'bg-[#130808]', border: 'border-[#3a0e0e]', nameCls: 'text-red-300' },
  unknown: { bg: 'bg-[#131325]', border: 'border-[#222]',    nameCls: 'text-gray-400' },
}

function cardState(dot) {
  if (dot === 'red')   return CARD_STATE.error
  if (dot === 'amber') return CARD_STATE.warn
  if (dot === 'grey')  return CARD_STATE.unknown
  return CARD_STATE.healthy
}

function Dot({ color }) {
  return <span className={`inline-block w-[6px] h-[6px] rounded-full flex-shrink-0 ${DOT_CLS[color] || DOT_CLS.grey}`} />
}

function PullBadge({ lastPullAt }) {
  if (!lastPullAt) return <span className="text-[9px] px-1.5 py-px rounded bg-[#2a1010] text-red-400 border border-[#3a1818]">↓ unknown</span>
  const age = Date.now() - new Date(lastPullAt).getTime()
  const hours = age / 3600000
  if (hours < 24) {
    const mins = Math.round(age / 60000)
    const label = mins < 60 ? `${mins} min ago` : `${Math.round(hours)}h ago`
    return <span className="text-[9px] px-1.5 py-px rounded bg-[#0d2a0d] text-green-400 border border-[#1a3a1a]">↓ {label}</span>
  }
  const days = Math.round(hours / 24)
  const cls = days <= 7
    ? 'bg-[#2a200a] text-amber-400 border-[#3a2e12]'
    : 'bg-[#2a1010] text-red-400 border-[#3a1818]'
  return <span className={`text-[9px] px-1.5 py-px rounded border ${cls}`}>↓ {days}d ago</span>
}

function VolBar({ vol }) {
  if (!vol.used_bytes || !vol.total_bytes) {
    return <div className="text-[10px] text-gray-600 mb-1">{vol.name || vol.mountpoint}</div>
  }
  const pct = Math.round((vol.used_bytes / vol.total_bytes) * 100)
  const fillCls = pct > 80 ? 'bg-red-500' : pct > 60 ? 'bg-amber-500' : 'bg-violet-500'
  const usedGb = (vol.used_bytes / 1e9).toFixed(1)
  const totalGb = (vol.total_bytes / 1e9).toFixed(1)
  return (
    <div className="mb-[5px]">
      <div className="flex justify-between text-[10px] text-gray-600 mb-[2px]">
        <span>{vol.name || vol.mountpoint}</span>
        <span className="text-gray-700">{usedGb} / {totalGb} GB</span>
      </div>
      <div className="h-[4px] rounded bg-[#0a0a18] overflow-hidden">
        <div className={`h-full rounded ${fillCls}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

function ActionBtn({ label, onClick, variant = 'default', loading, disabled }) {
  const base = 'text-[10px] px-2 py-1 rounded border w-full text-left disabled:opacity-40 transition-colors'
  const variants = {
    primary: 'bg-violet-600/20 text-violet-300 border-violet-500/30 hover:bg-violet-600/30',
    urgent:  'bg-red-900/30 text-red-400 border-red-700/40 hover:bg-red-900/50',
    default: 'bg-[#0d0d1a] text-gray-500 border-[#222] hover:text-gray-300',
    danger:  'bg-transparent text-red-500/40 border-red-900/20 hover:text-red-500/70',
  }
  return (
    <button
      className={`${base} ${variants[variant]}`}
      onClick={onClick}
      disabled={disabled || loading}
    >
      {loading ? '…' : label}
    </button>
  )
}

// ── Confirm dialog ─────────────────────────────────────────────────────────────

function useConfirm() {
  const [pending, setPending] = useState(null)
  const confirm = (msg, onConfirm) => setPending({ msg, onConfirm })
  const Dialog = pending ? (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-[#1a1a2e] border border-[#333] rounded-lg p-5 max-w-sm w-full mx-4">
        <p className="text-sm text-gray-300 mb-4">{pending.msg}</p>
        <div className="flex gap-2 justify-end">
          <button onClick={() => setPending(null)} className="text-xs px-3 py-1.5 rounded border border-[#333] text-gray-500 hover:text-gray-300">Cancel</button>
          <button onClick={() => { pending.onConfirm(); setPending(null) }} className="text-xs px-3 py-1.5 rounded bg-red-800/60 text-red-300 border border-red-700/40 hover:bg-red-800/80">Confirm</button>
        </div>
      </div>
    </div>
  ) : null
  return { confirm, Dialog }
}

// ── Generic card ───────────────────────────────────────────────────────────────

function InfraCard({ cardKey, openKey, setOpenKey, dot, name, sub, net, collapsed, expanded }) {
  const isOpen = openKey === cardKey
  const cs = cardState(dot)
  return (
    <div
      className={`${cs.bg} border ${isOpen ? 'border-violet-500 shadow-[0_0_0_1px_rgba(124,106,247,0.15)]' : cs.border} rounded-lg px-2.5 py-2.5 cursor-pointer transition-colors`}
      onClick={() => setOpenKey(isOpen ? null : cardKey)}
    >
      <div className="flex items-center gap-1.5 mb-0.5">
        <Dot color={dot} />
        <span className={`text-[12px] font-semibold truncate ${cs.nameCls}`}>{name}</span>
      </div>
      {sub && <div className="text-[10px] text-[#3a3a5a] font-mono truncate mb-0.5">{sub}</div>}
      {net && <div className="text-[10px] text-[#4a5a7a] font-mono mb-1">{net}</div>}
      {isOpen ? (
        <div onClick={e => e.stopPropagation()}>
          {expanded}
          <button className="mt-1.5 w-full text-[9px] text-gray-700 hover:text-gray-500" onClick={() => setOpenKey(null)}>✕ close</button>
        </div>
      ) : collapsed}
    </div>
  )
}

// ── Section wrapper ────────────────────────────────────────────────────────────

function Section({ label, meta, errorCount, cols = 5, children }) {
  return (
    <div>
      <div className="flex items-baseline gap-2 mb-2">
        <span className="text-[11px] text-gray-600 uppercase tracking-wider">{label}</span>
        {meta && <span className="text-[10px] text-gray-800">{meta}</span>}
        {errorCount > 0 && <span className="text-[10px] text-red-500/60">{errorCount} issue{errorCount !== 1 ? 's' : ''}</span>}
      </div>
      <div className={`grid gap-2`} style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}>
        {children}
      </div>
    </div>
  )
}

// ── Stat row in expanded ───────────────────────────────────────────────────────

function StatRow({ stats }) {
  return (
    <div className="flex gap-2 mb-2">
      {stats.map(({ v, l, color }) => (
        <div key={l} className="flex-1 bg-[#0d0d1a] rounded p-1.5">
          <div className={`text-[12px] font-semibold ${color || 'text-gray-300'}`}>{v ?? '—'}</div>
          <div className="text-[9px] text-gray-700 mt-px">{l}</div>
        </div>
      ))}
    </div>
  )
}

function Divider() {
  return <div className="h-px bg-[#1a1a30] my-2" />
}

function Actions({ buttons }) {
  return (
    <div className="flex flex-col gap-1.5 mt-1.5">
      {buttons}
    </div>
  )
}

// ── Container card (agent-01 & Swarm) ─────────────────────────────────────────

function ContainerCardExpanded({ c, isSwarm, onAction, confirm }) {
  const [loading, setLoading] = useState({})

  const act = async (key, path, body, msg) => {
    const run = async () => {
      setLoading(l => ({ ...l, [key]: true }))
      const r = await dashboardAction(path, body)
      setLoading(l => ({ ...l, [key]: false }))
      if (!r.ok) alert(r.error)
      else onAction()
    }
    msg ? confirm(msg, run) : run()
  }

  const pullPath = isSwarm ? `services/${c.name}/pull` : `containers/${c.id}/pull`
  const pullColor = c.last_pull_at && (Date.now() - new Date(c.last_pull_at).getTime()) > 7 * 86400000 ? 'urgent' : 'primary'

  return (
    <>
      <StatRow stats={[
        { v: c.uptime || (c.replicas_running != null ? `${c.replicas_running}/${c.replicas_desired}` : '—'), l: isSwarm ? 'Replicas' : 'Uptime' },
        { v: c.last_pull_at ? _relativeTime(c.last_pull_at) : 'unknown', l: 'Last Pull', color: !c.last_pull_at ? 'text-red-400' : 'text-gray-300' },
      ]} />
      {c.ports?.length > 0 && (
        <div className="text-[10px] text-[#4a6a9a] font-mono mb-1.5">
          <span className="text-[9px] text-gray-700">ports </span>{c.ports.join(' · ')}
        </div>
      )}
      <Divider />
      {(c.volumes || []).map(v => <VolBar key={v.name || v.mountpoint} vol={v} />)}
      {c.volumes?.length > 0 && <Divider />}
      <Actions buttons={[
        <ActionBtn key="pull" label="↓ Pull Latest" variant={pullColor} loading={loading.pull} onClick={() => act('pull', pullPath, null, null)} />,
        <ActionBtn key="logs" label="View Logs" loading={loading.logs} onClick={() => window.location.hash = '#logs'} />,
        !isSwarm && <ActionBtn key="restart" label="Restart" loading={loading.restart} onClick={() => act('restart', `containers/${c.id}/restart`, null, `Restart ${c.name}?`)} />,
        !isSwarm && <ActionBtn key="stop" label="Stop" variant="danger" loading={loading.stop} onClick={() => act('stop', `containers/${c.id}/stop`, null, `Stop ${c.name}? This will terminate the container.`)} />,
        isSwarm  && <ActionBtn key="scale" label="Scale" loading={loading.scale} onClick={() => { const n = parseInt(prompt('Replicas:', c.replicas_desired)); if (n > 0) act('scale', `services/${c.name}/scale`, { replicas: n }, null) }} />,
      ].filter(Boolean)} />
    </>
  )
}

function ContainerCardCollapsed({ c }) {
  return (
    <>
      <div className="text-[10px] text-[#383850] mb-1">{c.uptime || (c.replicas_running != null ? `${c.replicas_running}/${c.replicas_desired} replicas` : '')}</div>
      {c.problem
        ? <div className="text-[10px] px-1.5 py-px rounded inline-flex items-center gap-1 bg-red-950/50 text-red-400 border border-red-900/40 mb-1">⚠ {c.problem}</div>
        : <PullBadge lastPullAt={c.last_pull_at} />}
    </>
  )
}

// ── VM card ───────────────────────────────────────────────────────────────────

function VMCardExpanded({ vm, onAction, confirm }) {
  const [loading, setLoading] = useState({})

  const act = async (key, action, msg) => {
    const run = async () => {
      setLoading(l => ({ ...l, [key]: true }))
      const r = await dashboardAction(`vms/${vm.node.toLowerCase().replace('pmox', 'pve')}/${vm.vmid}/${action}`)
      setLoading(l => ({ ...l, [key]: false }))
      if (!r.ok) alert(r.error)
      else onAction()
    }
    msg ? confirm(msg, run) : run()
  }

  return (
    <>
      <StatRow stats={[
        { v: vm.cpu_pct != null ? `${vm.cpu_pct}%` : '—', l: 'CPU' },
        { v: vm.mem_used_gb != null ? `${vm.mem_used_gb} / ${vm.maxmem_gb} GB` : '—', l: 'RAM' },
      ]} />
      <Divider />
      {(vm.disks || []).map(d => <VolBar key={d.mountpoint} vol={{ name: d.mountpoint, used_bytes: d.used_bytes, total_bytes: d.total_bytes }} />)}
      {vm.disks?.length > 0 && <Divider />}
      <Actions buttons={
        vm.status === 'stopped'
          ? [
            <ActionBtn key="start" label="Start VM" variant="urgent" loading={loading.start} onClick={() => act('start', 'start', null)} />,
            <ActionBtn key="proxmox" label="View in Proxmox" onClick={() => window.open(`https://${location.hostname}:8006`, '_blank')} />,
          ]
          : [
            <ActionBtn key="console" label="Open Console" onClick={() => window.open(`https://${location.hostname}:8006/?console=kvm&vmid=${vm.vmid}&node=${vm.node.toLowerCase().replace('pmox', 'pve')}&novnc=1`, '_blank')} />,
            <ActionBtn key="proxmox" label="View in Proxmox" onClick={() => window.open(`https://${location.hostname}:8006`, '_blank')} />,
            <ActionBtn key="reboot" label="Reboot" variant="danger" loading={loading.reboot} onClick={() => act('reboot', 'reboot', `Reboot ${vm.name}? The VM will be temporarily unreachable.`)} />,
          ]
      } />
    </>
  )
}

function VMCardCollapsed({ vm }) {
  return (
    <>
      <div className="text-[10px] text-[#383850] mb-1">{vm.vcpus} vCPU · {vm.maxmem_gb} GB RAM</div>
      {vm.problem
        ? <div className="text-[10px] px-1.5 py-px rounded inline-flex items-center gap-1 bg-amber-950/40 text-amber-400 border border-amber-900/30 mb-1">⚠ {vm.problem}</div>
        : <span className="text-[9px] px-1.5 py-px rounded bg-[#0d1a2a] text-blue-400 border border-[#1a2a3a]">● {vm.status}</span>}
    </>
  )
}

// ── External service card ─────────────────────────────────────────────────────

function ExternalCardExpanded({ svc, onAction }) {
  const [probeLoading, setProbeLoading] = useState(false)
  const [liveLatency, setLiveLatency] = useState(null)

  const probe = async () => {
    setProbeLoading(true)
    const r = await dashboardAction(`external/${svc.slug}/probe`)
    setProbeLoading(false)
    if (r.latency_ms != null) setLiveLatency(r.latency_ms)
  }

  const latency = liveLatency ?? svc.latency_ms
  return (
    <>
      <StatRow stats={[
        { v: latency != null ? `${latency} ms` : '—', l: 'Latency', color: !svc.reachable ? 'text-red-400' : latency > 100 ? 'text-amber-400' : 'text-green-400' },
        { v: svc.reachable ? 'online' : 'offline', l: 'Status', color: svc.reachable ? 'text-gray-300' : 'text-red-400' },
      ]} />
      {svc.storage && <><VolBar vol={{ name: svc.storage.name, used_bytes: svc.storage.used_bytes, total_bytes: svc.storage.total_bytes }} /><Divider /></>}
      <Actions buttons={[
        <ActionBtn key="probe" label="Test Connection" loading={probeLoading} onClick={probe} />,
        svc.open_ui_url && <ActionBtn key="ui" label="Open UI" onClick={() => window.open(svc.open_ui_url, '_blank')} />,
      ].filter(Boolean)} />
    </>
  )
}

function ExternalCardCollapsed({ svc }) {
  const latencyColor = !svc.reachable ? 'text-red-400' : svc.latency_ms > 100 ? 'text-amber-400' : 'text-green-400'
  return (
    <>
      <div className="text-[10px] text-[#383850] mb-1 truncate">{svc.summary}</div>
      {svc.problem
        ? <div className="text-[10px] px-1.5 py-px rounded inline-flex gap-1 bg-red-950/50 text-red-400 border border-red-900/40">⚠ {svc.problem}</div>
        : <span className={`text-[10px] font-mono ${latencyColor}`}>● {svc.latency_ms != null ? `${svc.latency_ms} ms` : '—'}</span>}
    </>
  )
}

// ── Utility ───────────────────────────────────────────────────────────────────

function _relativeTime(iso) {
  if (!iso) return 'unknown'
  const age = Date.now() - new Date(iso).getTime()
  const mins = Math.round(age / 60000)
  if (mins < 60) return `${mins} min ago`
  const hours = Math.round(age / 3600000)
  if (hours < 24) return `${hours}h ago`
  return `${Math.round(hours / 24)}d ago`
}

// ── Main export ───────────────────────────────────────────────────────────────

export default function ServiceCards() {
  const [containers, setContainers] = useState(null)
  const [swarm, setSwarm]           = useState(null)
  const [vms, setVMs]               = useState(null)
  const [external, setExternal]     = useState(null)
  const [openKey, setOpenKey]       = useState(null)
  const { confirm, Dialog }         = useConfirm()

  const load = useCallback(async () => {
    const [c, s, v, e] = await Promise.allSettled([
      fetchDashboardContainers(),
      fetchDashboardSwarm(),
      fetchDashboardVMs(),
      fetchDashboardExternal(),
    ])
    if (c.status === 'fulfilled') setContainers(c.value)
    if (s.status === 'fulfilled') setSwarm(s.value)
    if (v.status === 'fulfilled') setVMs(v.value)
    if (e.status === 'fulfilled') setExternal(e.value)
  }, [])

  useEffect(() => {
    load()
    const id = setInterval(load, POLL_MS)
    return () => clearInterval(id)
  }, [load])

  const errorCount = (items) => (items || []).filter(i => i.dot === 'red' || i.dot === 'amber').length

  return (
    <div className="flex flex-col gap-6">
      {Dialog}

      {/* Containers · agent-01 */}
      <Section label="Containers · agent-01" meta={`${containers?.agent01_ip || ''} · ${containers?.containers?.length ?? '…'} running`} errorCount={errorCount(containers?.containers)}>
        {(containers?.containers || []).map(c => (
          <InfraCard
            key={c.id} cardKey={`c-${c.id}`} openKey={openKey} setOpenKey={setOpenKey}
            dot={c.dot} name={c.name} sub={c.image} net={c.ip_port}
            collapsed={<ContainerCardCollapsed c={c} />}
            expanded={<ContainerCardExpanded c={c} isSwarm={false} onAction={load} confirm={confirm} />}
          />
        ))}
      </Section>

      {/* Containers · Swarm */}
      <Section
        label="Containers · Swarm"
        meta={`${swarm?.swarm_managers ?? '…'} managers · ${swarm?.swarm_workers ?? '…'} workers · ${swarm?.services?.length ?? '…'} services`}
        errorCount={errorCount(swarm?.services)}
        cols={4}
      >
        {(swarm?.services || []).map(s => (
          <InfraCard
            key={s.id || s.name} cardKey={`s-${s.id || s.name}`} openKey={openKey} setOpenKey={setOpenKey}
            dot={s.dot || 'green'} name={s.name} sub={s.image} net={s.ports?.[0] ? `:${s.ports[0].split('→')[0]}` : ''}
            collapsed={<ContainerCardCollapsed c={{ ...s, uptime: `${s.replicas_running}/${s.replicas_desired} replicas`, last_pull_at: s.last_pull_at }} />}
            expanded={<ContainerCardExpanded c={{ ...s, replicas_desired: s.replicas_desired, replicas_running: s.replicas_running }} isSwarm={true} onAction={load} confirm={confirm} />}
          />
        ))}
      </Section>

      {/* VMs · Proxmox */}
      <Section label="VMs · Proxmox Cluster" meta="Pmox1 · Pmox2 · Pmox3" errorCount={errorCount(vms?.vms)} cols={4}>
        {(vms?.vms || []).map(vm => (
          <InfraCard
            key={vm.vmid} cardKey={`v-${vm.vmid}`} openKey={openKey} setOpenKey={setOpenKey}
            dot={vm.dot} name={vm.name} sub={`VM ${vm.vmid} · ${vm.node}`} net={vm.ip}
            collapsed={<VMCardCollapsed vm={vm} />}
            expanded={<VMCardExpanded vm={vm} onAction={load} confirm={confirm} />}
          />
        ))}
      </Section>

      {/* External Services */}
      <Section label="External Services" meta={`${external?.services?.filter(s => s.reachable).length ?? '…'} / ${external?.services?.length ?? '…'} reachable`} errorCount={errorCount(external?.services)} cols={4}>
        {(external?.services || []).map(svc => (
          <InfraCard
            key={svc.slug} cardKey={`e-${svc.slug}`} openKey={openKey} setOpenKey={setOpenKey}
            dot={svc.dot} name={svc.name} sub={svc.service_type} net={svc.host_port}
            collapsed={<ExternalCardCollapsed svc={svc} />}
            expanded={<ExternalCardExpanded svc={svc} onAction={load} />}
          />
        ))}
      </Section>
    </div>
  )
}
```

- [ ] **Step 2: Verify the file exists and exports correctly**

```bash
grep -n "export default ServiceCards" gui/src/components/ServiceCards.jsx
```

- [ ] **Step 3: Commit**

```bash
git add gui/src/components/ServiceCards.jsx
git commit -m "feat(dashboard): add ServiceCards component with four infrastructure sections"
```

---

## Task 8: Frontend — Tools dropdown + AlertBar + wire DashboardView

**Files:**
- Modify: `gui/src/App.jsx`

- [ ] **Step 1: Read the current `App.jsx` Header and DashboardView sections**

```bash
grep -n "MAIN_TABS\|DashboardView\|function Header" gui/src/App.jsx
```

- [ ] **Step 2: Update `MAIN_TABS` — remove Ingest and Tests**

Change:
```js
const MAIN_TABS = ['Dashboard', 'Cluster', 'Commands', 'Skills', 'Logs', 'Memory', 'Ingest', 'Output', 'Tests']
```
To:
```js
const MAIN_TABS = ['Dashboard', 'Cluster', 'Commands', 'Skills', 'Logs', 'Memory', 'Output']
const TOOLS_TABS = ['Ingest', 'Tests']
```

- [ ] **Step 3: Add Tools dropdown to the Header tab row**

In the Header JSX where tabs are rendered (where `MAIN_TABS.map(...)` is), add the Tools dropdown after the last tab. Use local `useState` for open/close:

```jsx
// Add near top of Header function:
const [toolsOpen, setToolsOpen] = useState(false)

// In the tab row, after MAIN_TABS.map(...):
<div className="relative">
  <button
    onClick={() => setToolsOpen(o => !o)}
    className={`text-[13px] px-3 h-11 flex items-center border-b-2 transition-colors
      ${TOOLS_TABS.includes(activeTab)
        ? 'text-white border-amber-500'
        : 'text-amber-500/70 border-transparent hover:text-amber-400'}`}
  >
    Tools ▾
  </button>
  {toolsOpen && (
    <div
      className="absolute top-full left-0 bg-[#1a1a2e] border border-[#333] rounded shadow-lg z-50 py-1 min-w-[120px]"
      onMouseLeave={() => setToolsOpen(false)}
    >
      {TOOLS_TABS.map(tab => (
        <button
          key={tab}
          onClick={() => { onTab(tab); setToolsOpen(false) }}
          className={`w-full text-left px-4 py-2 text-[13px] hover:bg-[#222] transition-colors
            ${activeTab === tab ? 'text-white' : 'text-gray-400'}`}
        >
          {tab}
        </button>
      ))}
    </div>
  )}
</div>
```

- [ ] **Step 4: Add AlertBar component (inline in App.jsx)**

Add before `AppShell`:

```jsx
function AlertBar({ containers, swarm, vms, external }) {
  const issues = []
  for (const c of containers?.containers || []) if (c.problem) issues.push({ sev: c.dot, text: `${c.name} ${c.problem}` })
  for (const s of swarm?.services || []) if (s.problem) issues.push({ sev: s.dot, text: `${s.name} ${s.problem}` })
  for (const v of vms?.vms || []) if (v.problem) issues.push({ sev: v.dot, text: `${v.name} ${v.problem}` })
  for (const e of external?.services || []) if (e.problem) issues.push({ sev: e.dot, text: `${e.name} ${e.problem}` })
  if (!issues.length) return null
  issues.sort((a, b) => (a.sev === 'red' ? -1 : b.sev === 'red' ? 1 : 0))
  const shown = issues.slice(0, 3)
  const extra = issues.length - 3
  return (
    <div className="bg-[#1a0a0a] border-b border-[#3a1010] px-5 py-2 flex items-center gap-2 text-[11px]">
      <span className="text-red-400 text-[13px]">⚠</span>
      <span className="text-red-400/80 flex-1">{shown.map(i => i.text).join(' · ')}{extra > 0 ? ` · +${extra} more` : ''}</span>
      <span className="bg-red-500 text-white text-[10px] px-2 py-px rounded-full">{issues.length}</span>
    </div>
  )
}
```

- [ ] **Step 5: Import ServiceCards and wire into DashboardView**

Add import at top of App.jsx:
```js
import ServiceCards from './components/ServiceCards'
```

Update `DashboardView` to include ServiceCards below the existing cards:
```jsx
function DashboardView() {
  return (
    <div className="flex flex-col gap-6">
      <DashboardCards />
      <ServiceCards />
    </div>
  )
}
```

- [ ] **Step 6: For AlertBar data — lift state or use a simple context**

The simplest approach: move the `ServiceCards` data fetching up into `DashboardView` and pass the data down to both `ServiceCards` and `AlertBar`. Update `DashboardView`:

```jsx
function DashboardView() {
  // ServiceCards manages its own data internally for polling.
  // AlertBar gets data from a shared ref via a callback.
  // Simplest: render AlertBar inside ServiceCards using a prop.
  return (
    <div className="flex flex-col gap-6">
      <DashboardCards />
      <ServiceCards showAlertBar />
    </div>
  )
}
```

In `ServiceCards.jsx`, accept `showAlertBar` prop and render `<AlertBar ... />` at the top when truthy. Import AlertBar from App or inline it in ServiceCards (copy the JSX).

- [ ] **Step 7: Manual smoke test**

```
# Start dev server
cd gui && npm run dev
# Open http://localhost:5173
# Verify:
# - Nav shows Tools ▾ dropdown with Tests + Ingest
# - Dashboard shows ServiceCards sections
# - Cards expand on click
# - Alert bar appears if any service has a problem
```

- [ ] **Step 8: Commit**

```bash
git add gui/src/App.jsx gui/src/components/ServiceCards.jsx
git commit -m "feat(dashboard): add Tools dropdown, AlertBar, wire ServiceCards into DashboardView"
```

---

## Task 9: Integration smoke test + final commit

- [ ] **Step 1: Run all new tests**

```bash
pytest tests/test_collectors_docker_agent01.py tests/test_collectors_proxmox_vms.py tests/test_collectors_external_services.py tests/test_routers_dashboard.py -v
```
Expected: all pass

- [ ] **Step 2: Syntax-check all new Python files**

```bash
python -m py_compile api/collectors/docker_agent01.py api/collectors/proxmox_vms.py api/collectors/external_services.py api/routers/dashboard.py
echo "Syntax OK"
```

- [ ] **Step 3: Start API and check new endpoints are registered**

```bash
python -m uvicorn api.main:app --port 8001 &
sleep 3
curl -s http://localhost:8001/openapi.json | python -m json.tool | grep "/api/dashboard"
kill %1
```
Expected: shows all 8 `/api/dashboard/*` routes

- [ ] **Step 4: Build frontend**

```bash
cd gui && npm run build
```
Expected: builds without errors

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "feat(dashboard): dashboard redesign complete — service cards, Tools nav, alert bar"
git push
```
