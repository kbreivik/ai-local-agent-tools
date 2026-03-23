"""
GET /api/dashboard/* — Dashboard card data from DB snapshots.

All data comes from the status_snapshots table, written by background collectors.
Never calls Docker/Proxmox/external services directly — that's the collectors' job.
"""
import asyncio
import json
import os

from fastapi import APIRouter, Depends

from api.auth import get_current_user
from api.db.base import get_engine
from api.db import queries as q

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_state(snap: dict | None) -> dict:
    """Parse snapshot state field (may be JSON string or dict)."""
    if not snap:
        return {}
    state = snap.get("state") or {}
    if isinstance(state, str):
        try:
            state = json.loads(state)
        except Exception:
            state = {}
    return state


def _swarm_dot(svc: dict) -> str:
    running = svc.get("running_tasks") or svc.get("running_replicas", 0)
    desired = svc.get("desired_tasks") or svc.get("desired_replicas", 1)
    if running == desired:
        return "green"
    if running > 0:
        return "amber"
    return "red"


def _swarm_problem(svc: dict) -> str | None:
    running = svc.get("running_tasks") or svc.get("running_replicas", 0)
    desired = svc.get("desired_tasks") or svc.get("desired_replicas", 1)
    if running == 0:
        return "no replicas running"
    if running < desired:
        return f"{running}/{desired} replicas"
    return None


# ── GET /containers/agent01 ───────────────────────────────────────────────────

@router.get("/containers/agent01")
async def get_containers_agent01(user: str = Depends(get_current_user)):
    """Docker containers on agent-01 from latest snapshot."""
    async with get_engine().connect() as conn:
        snap = await q.get_latest_snapshot(conn, "docker_agent01")

    state = _parse_state(snap)
    return {
        "containers": state.get("containers", []),
        "agent01_ip": state.get("agent01_ip", ""),
        "health": state.get("health", "unknown"),
        "last_updated": snap.get("timestamp") if snap else None,
    }


# ── GET /containers/swarm ─────────────────────────────────────────────────────

@router.get("/containers/swarm")
async def get_containers_swarm(user: str = Depends(get_current_user)):
    """Swarm services and nodes from latest swarm snapshot, enriched with image pull times."""
    async with get_engine().connect() as conn:
        snap = await q.get_latest_snapshot(conn, "swarm")
        state = _parse_state(snap)

        # Enrich each service with last_pull_at from image_digest snapshots
        # and compute dot/problem dynamically
        services_raw = state.get("services", [])
        services = []
        for svc in services_raw:
            image = svc.get("image", "")
            last_pull_at = None
            if image:
                digest_snap = await q.get_latest_snapshot(conn, f"image_digest:{image}")
                if digest_snap:
                    last_pull_at = digest_snap.get("timestamp")

            enriched = dict(svc)
            enriched["last_pull_at"] = last_pull_at
            enriched["dot"] = _swarm_dot(svc)
            enriched["problem"] = _swarm_problem(svc)
            services.append(enriched)

        # Split nodes into managers and workers
        nodes = state.get("nodes", [])
        swarm_managers = sum(1 for n in nodes if n.get("role") == "manager")
        swarm_workers  = sum(1 for n in nodes if n.get("role") == "worker")

    return {
        "services": services,
        "swarm_managers": swarm_managers,
        "swarm_workers": swarm_workers,
        "health": state.get("health", "unknown"),
        "last_updated": snap.get("timestamp") if snap else None,
    }


# ── GET /vms ──────────────────────────────────────────────────────────────────

@router.get("/vms")
async def get_vms(user: str = Depends(get_current_user)):
    """Proxmox VM list from latest snapshot."""
    async with get_engine().connect() as conn:
        snap = await q.get_latest_snapshot(conn, "proxmox_vms")

    state = _parse_state(snap)
    return {
        "vms": state.get("vms", []),
        "health": state.get("health", "unknown"),
        "last_updated": snap.get("timestamp") if snap else None,
    }


# ── GET /external ─────────────────────────────────────────────────────────────

@router.get("/external")
async def get_external(user: str = Depends(get_current_user)):
    """External service statuses from latest snapshot."""
    async with get_engine().connect() as conn:
        snap = await q.get_latest_snapshot(conn, "external_services")

    state = _parse_state(snap)
    return {
        "services": state.get("services", []),
        "health": state.get("health", "unknown"),
        "last_updated": snap.get("timestamp") if snap else None,
    }


# ── Action endpoints ────────────────────────────────────────────────────────────

from pydantic import BaseModel


class ScaleRequest(BaseModel):
    replicas: int


def _docker_client():
    import docker
    host = os.environ.get("DOCKER_HOST", "unix:///var/run/docker.sock")
    return docker.DockerClient(base_url=host, timeout=15)


@router.post("/containers/{container_id}/pull")
async def pull_container(container_id: str, user: str = Depends(get_current_user)):
    return await asyncio.to_thread(_do_pull, container_id)


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
    return await asyncio.to_thread(_do_restart, container_id)


def _do_restart(container_id: str) -> dict:
    try:
        client = _docker_client()
        client.containers.get(container_id).restart()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/containers/{container_id}/stop")
async def stop_container(container_id: str, user: str = Depends(get_current_user)):
    return await asyncio.to_thread(_do_stop, container_id)


def _do_stop(container_id: str) -> dict:
    try:
        client = _docker_client()
        client.containers.get(container_id).stop()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/services/{service_name}/pull")
async def pull_service(service_name: str, user: str = Depends(get_current_user)):
    return await asyncio.to_thread(_do_service_pull, service_name)


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
    return await asyncio.to_thread(_do_scale, service_name, body.replicas)


def _do_scale(service_name: str, replicas: int) -> dict:
    try:
        client = _docker_client()
        client.services.get(service_name).scale(replicas)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/vms/{node}/{vmid}/start")
async def start_vm(node: str, vmid: int, user: str = Depends(get_current_user)):
    return await asyncio.to_thread(_do_vm_action, node, vmid, "start")


@router.post("/vms/{node}/{vmid}/reboot")
async def reboot_vm(node: str, vmid: int, user: str = Depends(get_current_user)):
    return await asyncio.to_thread(_do_vm_action, node, vmid, "reboot")


def _do_vm_action(node: str, vmid: int, action: str) -> dict:
    import httpx
    ALLOWED_NODES = {"Pmox1", "Pmox2", "Pmox3"}
    if node not in ALLOWED_NODES:
        return {"ok": False, "error": "unknown node"}
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
    return await asyncio.to_thread(_do_probe, slug)


def _do_probe(slug: str) -> dict:
    import httpx, time
    from api.collectors.external_services import SERVICES_CONFIG
    cfg = next((c for c in SERVICES_CONFIG if c["slug"] == slug), None)
    if not cfg:
        return {"reachable": False, "latency_ms": None}

    host_raw = os.environ.get(cfg["host_env"], "")
    if not host_raw:
        return {"reachable": False, "latency_ms": None}

    if host_raw.startswith("http"):
        base_url = host_raw.rstrip("/")
        strip = cfg.get("strip_suffix", "")
        if strip and base_url.endswith(strip):
            base_url = base_url[: -len(strip)]
    else:
        scheme = cfg.get("scheme", "http")
        port = cfg.get("port", "")
        base_url = f"{scheme}://{host_raw}" + (f":{port}" if port else "")

    headers = {}
    if cfg.get("auth_type") == "pve_token":
        token_id = os.environ.get(cfg.get("auth_token_id_env", ""), "")
        token_secret = os.environ.get(cfg.get("auth_token_secret_env", ""), "")
        if token_id and token_secret:
            headers["Authorization"] = f"PVEAPIToken={token_id}={token_secret}"
    else:
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
