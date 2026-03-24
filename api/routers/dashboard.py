"""
GET /api/dashboard/* — Dashboard card data from DB snapshots.

All data comes from the status_snapshots table, written by background collectors.
Never calls Docker/Proxmox/external services directly — that's the collectors' job.
"""
import asyncio
import json
import logging
import os
import re
import time as _time

from fastapi import APIRouter, Depends, HTTPException

from api.auth import get_current_user
from api.db.base import get_engine
from api.db import queries as q

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

log = logging.getLogger(__name__)

_GHCR_TAG_CACHE: dict = {}   # { image_bare: (tags, fetched_at) }
_GHCR_TAG_TTL = 600          # 10 minutes


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
    """Proxmox VM and LXC list from latest snapshot."""
    async with get_engine().connect() as conn:
        snap = await q.get_latest_snapshot(conn, "proxmox_vms")

    state = _parse_state(snap)
    return {
        "vms": state.get("vms", []),
        "lxc": state.get("lxc", []),
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


# ── GET /containers/{id}/tags ─────────────────────────────────────────────────

def _fetch_ghcr_tags(image_bare: str) -> list[str]:
    """Fetch semver tags from GHCR for a bare image name (e.g. ghcr.io/user/repo).
    Returns sorted-descending list of strict semver tags, up to 20.
    Raises RuntimeError on auth failure, IOError on network failure.
    Results cached for _GHCR_TAG_TTL seconds.
    """
    import httpx

    cached = _GHCR_TAG_CACHE.get(image_bare)
    if cached and (_time.monotonic() - cached[1]) < _GHCR_TAG_TTL:
        return cached[0]

    token = os.environ.get("GHCR_TOKEN", "")
    if not token:
        raise RuntimeError("GHCR_TOKEN not configured")

    repo = image_bare[len("ghcr.io/"):]   # kbreivik/hp1-ai-agent
    headers = {"Authorization": f"Bearer {token}"}
    semver_re = re.compile(r"^\d+\.\d+\.\d+$")
    all_tags: list[str] = []
    url = f"https://ghcr.io/v2/{repo}/tags/list?n=100"

    for _ in range(3):
        try:
            r = httpx.get(url, headers=headers, timeout=10, follow_redirects=True)
        except Exception as exc:
            raise IOError(f"GHCR unreachable: {exc}") from exc

        if r.status_code in (401, 403):
            raise RuntimeError(f"GHCR auth failed: HTTP {r.status_code}")
        if not r.ok:
            raise IOError(f"GHCR error: HTTP {r.status_code}")

        all_tags.extend(r.json().get("tags") or [])

        if len([t for t in all_tags if semver_re.match(t)]) >= 20:
            break

        # Follow Link header pagination
        next_url = None
        for part in r.headers.get("link", "").split(","):
            part = part.strip()
            if 'rel="next"' in part:
                next_url = part.split(";")[0].strip().strip("<>")
                break
        if not next_url:
            break
        url = next_url

    semver_tags = [t for t in all_tags if semver_re.match(t)]
    semver_tags.sort(key=lambda v: tuple(int(x) for x in v.split(".")), reverse=True)
    result = semver_tags[:20]
    _GHCR_TAG_CACHE[image_bare] = (result, _time.monotonic())
    return result


@router.get("/containers/{container_id}/tags")
async def get_container_tags(container_id: str, user: str = Depends(get_current_user)):
    """Available GHCR semver tags for a GHCR-hosted container image.

    Returns { tags: [...] } sorted descending. Cached 10 min on the backend.
    Returns empty tags list for non-GHCR images (not an error).
    """
    async with get_engine().connect() as conn:
        snap = await q.get_latest_snapshot(conn, "docker_agent01")

    state = _parse_state(snap)
    containers = state.get("containers", [])
    container = next((c for c in containers if c["id"] == container_id), None)

    if container is None:
        raise HTTPException(status_code=404, detail="container not found")

    image = container.get("image", "")
    if not image.startswith("ghcr.io/"):
        return {"tags": [], "error": "not a ghcr image"}

    bare = image.split("@")[0].split(":")[0]   # ghcr.io/kbreivik/hp1-ai-agent

    try:
        tags = await asyncio.to_thread(_fetch_ghcr_tags, bare)
        return {"tags": tags}
    except RuntimeError as exc:
        log.warning("GHCR auth error for %s: %s", bare, exc)
        raise HTTPException(status_code=503, detail=str(exc))
    except IOError as exc:
        log.warning("GHCR network error for %s: %s", bare, exc)
        raise HTTPException(status_code=502, detail=str(exc))


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
    return await asyncio.to_thread(_do_proxmox_action, "qemu", node, vmid, "start")


@router.post("/vms/{node}/{vmid}/reboot")
async def reboot_vm(node: str, vmid: int, user: str = Depends(get_current_user)):
    return await asyncio.to_thread(_do_proxmox_action, "qemu", node, vmid, "reboot")


@router.post("/lxc/{node}/{vmid}/start")
async def start_lxc(node: str, vmid: int, user: str = Depends(get_current_user)):
    return await asyncio.to_thread(_do_proxmox_action, "lxc", node, vmid, "start")


@router.post("/lxc/{node}/{vmid}/stop")
async def stop_lxc(node: str, vmid: int, user: str = Depends(get_current_user)):
    return await asyncio.to_thread(_do_proxmox_action, "lxc", node, vmid, "stop")


@router.post("/lxc/{node}/{vmid}/reboot")
async def reboot_lxc(node: str, vmid: int, user: str = Depends(get_current_user)):
    return await asyncio.to_thread(_do_proxmox_action, "lxc", node, vmid, "reboot")


def _do_proxmox_action(pve_type: str, node: str, vmid: int, action: str) -> dict:
    """pve_type: 'qemu' for VMs, 'lxc' for containers."""
    import httpx
    from api.collectors.proxmox_vms import NODES
    if node not in NODES:
        return {"ok": False, "error": f"unknown node '{node}' — must be one of {NODES}"}
    host = os.environ.get("PROXMOX_HOST", "")
    token_id = os.environ.get("PROXMOX_TOKEN_ID", "")
    token_secret = os.environ.get("PROXMOX_TOKEN_SECRET", "")
    if not host:
        return {"ok": False, "error": "PROXMOX_HOST not configured"}
    try:
        headers = {"Authorization": f"PVEAPIToken={token_id}={token_secret}"}
        url = f"https://{host}:8006/api2/json/nodes/{node}/{pve_type}/{vmid}/status/{action}"
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


# ── Self-update ────────────────────────────────────────────────────────────────

@router.post("/self-update")
async def self_update(user: str = Depends(get_current_user)):
    """Pull latest image from GHCR and restart via docker compose.

    Returns 202 immediately. The compose up runs in a background thread after a
    short delay so this response has time to reach the client before the
    container restarts.
    """
    image = os.environ.get("HP1_IMAGE", "ghcr.io/kbreivik/hp1-ai-agent:latest")
    compose_file = _find_compose_file()
    if not compose_file:
        return {"ok": False, "error": "docker-compose.yml not found — cannot restart"}

    asyncio.get_event_loop().run_in_executor(None, _do_self_update, image, compose_file)
    return {"ok": True, "image": image, "message": "Update triggered — agent will restart in ~5s"}


def _find_compose_file() -> str | None:
    import pathlib
    candidates = [
        pathlib.Path("/app/docker/docker-compose.yml"),
        pathlib.Path("/opt/hp1-agent/docker/docker-compose.yml"),
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return None


def _do_self_update(image: str, compose_file: str) -> None:
    import subprocess, time
    log.info("self-update: pulling %s", image)
    try:
        subprocess.run(["docker", "pull", image], check=True, timeout=120)
        log.info("self-update: pull complete, restarting via compose in 3s")
        time.sleep(3)
        subprocess.run(
            ["docker", "compose", "-f", compose_file, "up", "-d",
             "--remove-orphans", "--pull", "never"],
            check=True, timeout=60,
        )
    except Exception as e:
        log.error("self-update failed: %s", e)
