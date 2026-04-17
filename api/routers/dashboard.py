"""
GET /api/dashboard/* — Dashboard card data from DB snapshots.

All data comes from the status_snapshots table, written by background collectors.
Never calls Docker/Proxmox/external services directly — that's the collectors' job.
"""
import asyncio
import datetime
import json
import logging
import os
import re
import queue as _queue
import threading
import time as _time

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse

from api.auth import get_current_user
from api.db.base import get_engine
from api.db import queries as q
from api.websocket import manager as _ws_manager
from api.db.vm_action_log import record_action, complete_action

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

log = logging.getLogger(__name__)

_GHCR_TAG_CACHE: dict = {}   # { image_bare: (tags, fetched_at) }
_GHCR_TAG_TTL_DEFAULT = 600  # 10 minutes (fallback when setting missing / invalid)


def _get_ghcr_tag_ttl() -> int:
    """Read GHCR tag cache TTL from settings DB, fall back to default."""
    try:
        from mcp_server.tools.skills.storage import get_backend
        raw = get_backend().get_setting("ghcrTagCacheTTL")
        if raw is None or raw == "":
            return _GHCR_TAG_TTL_DEFAULT
        ttl = int(raw)
        return ttl if ttl > 0 else _GHCR_TAG_TTL_DEFAULT
    except Exception:
        return _GHCR_TAG_TTL_DEFAULT

# ── Auto-update state ────────────────────────────────────────────────────────

_AUTO_UPDATE_INTERVAL_DEFAULT = 300   # 5 minutes (fallback when setting missing / invalid)


def _get_auto_update_interval() -> int:
    """Read auto-update interval (seconds) from settings DB, fall back to default."""
    try:
        from mcp_server.tools.skills.storage import get_backend
        raw = get_backend().get_setting("autoUpdateInterval")
        if raw is None or raw == "":
            return _AUTO_UPDATE_INTERVAL_DEFAULT
        val = int(raw)
        return val if val > 0 else _AUTO_UPDATE_INTERVAL_DEFAULT
    except Exception:
        return _AUTO_UPDATE_INTERVAL_DEFAULT
_auto_update_timer: "threading.Timer | None" = None
# Versions before 1.12.2 have broken self-update (no sidecar recreate)
MIN_SAFE_VERSION = (1, 12, 2)
_update_status: dict = {
    "auto_update": False,
    "current_version": "",
    "current_digest": "",
    "latest_digest": "",
    "latest_version": "",
    "update_available": False,
    "last_checked": "",
}


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


# ── PBS backup enrichment ────────────────────────────────────────────────────
# In-process cache to avoid hammering pbs_last_backup on every dashboard call.
_PBS_BACKUP_CACHE: dict = {}   # vmid -> (age_hours | None, cached_at_epoch)
_PBS_BACKUP_CACHE_TTL = 300    # 5 minutes


def _get_pbs_backup_age_hours(vmid) -> float | None:
    """Look up most recent PBS backup age for a VMID. Cached 5 min, never raises."""
    if vmid is None or vmid == "":
        return None
    key = str(vmid)
    now = _time.time()
    cached = _PBS_BACKUP_CACHE.get(key)
    if cached and (now - cached[1]) < _PBS_BACKUP_CACHE_TTL:
        return cached[0]
    try:
        from mcp_server.tools.pbs import pbs_last_backup
        r = pbs_last_backup(key)
        age = r.get("age_hours") if isinstance(r, dict) and r.get("status") != "UNKNOWN" else None
    except Exception:
        age = None
    _PBS_BACKUP_CACHE[key] = (age, now)
    return age


def _enrich_vms_with_pbs_backup(vms: list) -> list:
    """Annotate each VM/LXC dict with pbs_backup_age_hours. Safe on any shape."""
    if not vms:
        return vms
    for vm in vms:
        if not isinstance(vm, dict):
            continue
        vmid = vm.get("vmid") or vm.get("id")
        age = _get_pbs_backup_age_hours(vmid)
        meta = vm.get("metadata")
        if not isinstance(meta, dict):
            meta = {}
            vm["metadata"] = meta
        meta["pbs_backup_age_hours"] = age
        # Also expose at top level for cards that don't unpack metadata
        vm["pbs_backup_age_hours"] = age
    return vms


# ── GET /summary ─────────────────────────────────────────────────────────────

@router.get("/summary")
async def get_dashboard_summary(user: str = Depends(get_current_user)):
    """Single call returning all dashboard data needed for the main dashboard view.

    Assembles from DB snapshots (all fast PG reads — no SSH/API calls).
    Replaces 5–6 individual dashboard endpoint calls on the frontend.
    Response shape is stable — additive changes only.
    """
    from api.collectors import manager as coll_mgr

    async with get_engine().connect() as conn:
        # All fetched in parallel via gather
        import asyncio as _asyncio
        (
            containers_snap,
            swarm_snap,
            vms_snap,
            external_snap,
            vm_hosts_snap,
            windows_snap,
        ) = await _asyncio.gather(
            q.get_latest_snapshot(conn, "docker_agent01"),
            q.get_latest_snapshot(conn, "swarm"),
            q.get_latest_snapshot(conn, "proxmox_vms"),
            q.get_latest_snapshot(conn, "external_services"),
            q.get_latest_snapshot(conn, "vm_hosts"),
            q.get_latest_snapshot(conn, "windows"),
        )

    containers_state = _parse_state(containers_snap)
    swarm_state      = _parse_state(swarm_snap)
    vms_state        = _parse_state(vms_snap)
    external_state   = _parse_state(external_snap)
    vm_hosts_state   = _parse_state(vm_hosts_snap)
    windows_state    = _parse_state(windows_snap)

    # Enrich swarm services with dot/problem
    services = []
    for svc in swarm_state.get("services", []):
        enriched = dict(svc)
        enriched["dot"]     = _swarm_dot(svc)
        enriched["problem"] = _swarm_problem(svc)
        enriched["replicas_running"] = enriched.get("running_replicas")
        enriched["replicas_desired"] = enriched.get("desired_replicas")
        services.append(enriched)

    collectors = coll_mgr.status()

    return {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "containers": {
            "containers":        containers_state.get("containers", []),
            "agent01_ip":        containers_state.get("agent01_ip", ""),
            "health":            containers_state.get("health", "unknown"),
            "connection_label":  containers_state.get("connection_label", "agent-01"),
            "last_updated":      containers_snap.get("timestamp") if containers_snap else None,
        },
        "swarm": {
            "services":       services,
            "nodes":          swarm_state.get("nodes", []),
            "swarm_managers": sum(1 for n in swarm_state.get("nodes", []) if n.get("role") == "manager"),
            "swarm_workers":  sum(1 for n in swarm_state.get("nodes", []) if n.get("role") == "worker"),
            "health":         swarm_state.get("health", "unknown"),
            "last_updated":   swarm_snap.get("timestamp") if swarm_snap else None,
        },
        "vms": {
            "clusters":          [
                {**c,
                 "vms": _enrich_vms_with_pbs_backup(list(c.get("vms", []))),
                 "lxc": _enrich_vms_with_pbs_backup(list(c.get("lxc", [])))}
                for c in vms_state.get("clusters", [])
            ],
            "vms":               _enrich_vms_with_pbs_backup(list(vms_state.get("vms", []))),
            "lxc":               _enrich_vms_with_pbs_backup(list(vms_state.get("lxc", []))),
            "health":            vms_state.get("health", "unknown"),
            "connection_label":  vms_state.get("connection_label", ""),
            "connection_host":   vms_state.get("connection_host", ""),
            "last_updated":      vms_snap.get("timestamp") if vms_snap else None,
        },
        "external": {
            "services":    external_state.get("services", []),
            "health":      external_state.get("health", "unknown"),
            "last_updated": external_snap.get("timestamp") if external_snap else None,
        },
        "vm_hosts": {
            "vms":        vm_hosts_state.get("vms", []),
            "health":     vm_hosts_state.get("health", "unknown"),
            "last_updated": vm_hosts_snap.get("timestamp") if vm_hosts_snap else None,
        },
        "windows": {
            "hosts":        windows_state.get("hosts", []),
            "health":       windows_state.get("health", "unknown"),
            "last_updated": windows_snap.get("timestamp") if windows_snap else None,
        },
        "collectors": collectors,
    }


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
        "connection_id": state.get("connection_id", ""),
        "connection_label": state.get("connection_label", "agent-01"),
        "connection_host": state.get("connection_host", ""),
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
            # Alias both naming conventions so frontend works regardless
            enriched["replicas_running"] = enriched.get("running_replicas")
            enriched["replicas_desired"] = enriched.get("desired_replicas")
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
    """Proxmox VM and LXC list from latest snapshot. Supports multiple clusters."""
    async with get_engine().connect() as conn:
        snap = await q.get_latest_snapshot(conn, "proxmox_vms")

    state = _parse_state(snap)
    clusters = state.get("clusters", [])

    # If snapshot predates multi-cluster support (no clusters key),
    # synthesise a single-cluster response from the flat fields for compat.
    if not clusters and (state.get("vms") or state.get("lxc")):
        conn_label = state.get("connection_label", "Proxmox Cluster")
        conn_host = ""
        try:
            from api.connections import get_connection_for_platform
            pconn = get_connection_for_platform("proxmox")
            if pconn:
                conn_label = pconn.get("label", conn_label)
                conn_host = f"{pconn.get('host', '')}:{pconn.get('port', 8006)}"
        except Exception:
            pass
        clusters = [{
            "health": state.get("health", "unknown"),
            "connection_label": conn_label,
            "connection_id": state.get("connection_id", ""),
            "connection_host": conn_host,
            "vms": state.get("vms", []),
            "lxc": state.get("lxc", []),
        }]

    # Enrich VMs with PBS backup freshness (cached 5 min, safe no-op if unavailable)
    clusters = [
        {**c,
         "vms": _enrich_vms_with_pbs_backup(list(c.get("vms", []))),
         "lxc": _enrich_vms_with_pbs_backup(list(c.get("lxc", [])))}
        for c in clusters
    ]

    return {
        "clusters": clusters,
        # Keep flat lists for any code still using vms/lxc directly
        "vms": _enrich_vms_with_pbs_backup(list(state.get("vms", []))),
        "lxc": _enrich_vms_with_pbs_backup(list(state.get("lxc", []))),
        "health": state.get("health", "unknown"),
        # Legacy single-cluster fields — first cluster's values
        "connection_label": clusters[0].get("connection_label", "") if clusters else "",
        "connection_host": clusters[0].get("connection_host", "") if clusters else "",
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


@router.get("/pbs")
async def get_pbs(user: str = Depends(get_current_user)):
    """PBS datastore and task status from latest snapshot."""
    async with get_engine().connect() as conn:
        snap = await q.get_latest_snapshot(conn, "pbs")

    state = _parse_state(snap)
    return {
        "health": state.get("health", "unknown"),
        "datastores": state.get("datastores", []),
        "tasks": state.get("tasks", {}),
        "latency_ms": state.get("latency_ms"),
        "connection_label": state.get("connection_label", ""),
        "last_updated": snap.get("timestamp") if snap else None,
    }


@router.get("/truenas")
async def get_truenas(user: str = Depends(get_current_user)):
    """TrueNAS pool health and capacity from latest snapshot."""
    async with get_engine().connect() as conn:
        snap = await q.get_latest_snapshot(conn, "truenas")

    state = _parse_state(snap)
    return {
        "health": state.get("health", "unknown"),
        "pools": state.get("pools", []),
        "pool_count": state.get("pool_count", 0),
        "latency_ms": state.get("latency_ms"),
        "connection_label": state.get("connection_label", ""),
        "last_updated": snap.get("timestamp") if snap else None,
    }


@router.get("/fortigate")
async def get_fortigate(user: str = Depends(get_current_user)):
    """FortiGate interface health and system info from latest snapshot."""
    async with get_engine().connect() as conn:
        snap = await q.get_latest_snapshot(conn, "fortigate")

    state = _parse_state(snap)
    return {
        "health": state.get("health", "unknown"),
        "hostname": state.get("hostname", ""),
        "version": state.get("version", ""),
        "uptime": state.get("uptime"),
        "ha_mode": state.get("ha_mode", ""),
        "interfaces": state.get("interfaces", []),
        "latency_ms": state.get("latency_ms"),
        "connection_label": state.get("connection_label", ""),
        "last_updated": snap.get("timestamp") if snap else None,
    }


@router.get("/unifi")
async def get_unifi(user: str = Depends(get_current_user)):
    """UniFi device status and client count from latest snapshot."""
    async with get_engine().connect() as conn:
        snap = await q.get_latest_snapshot(conn, "unifi")
    state = _parse_state(snap)
    return {
        "health": state.get("health", "unknown"),
        "auth_mode": state.get("auth_mode", "unknown"),
        "site": state.get("site", "default"),
        "devices": state.get("devices", []),
        "device_count": state.get("device_count", 0),
        "devices_up": state.get("devices_up", 0),
        "devices_down": state.get("devices_down", 0),
        "client_count": state.get("client_count", 0),
        "wired_clients": state.get("wired_clients", 0),
        "wireless_clients": state.get("wireless_clients", 0),
        "latency_ms": state.get("latency_ms"),
        "connection_label": state.get("connection_label", ""),
        "last_updated": snap.get("timestamp") if snap else None,
    }


# ── GET /containers/{id}/tags ─────────────────────────────────────────────────

def _fetch_ghcr_tags(image_bare: str) -> list[str]:
    """Fetch semver tags from GHCR for a bare image name (e.g. ghcr.io/user/repo).
    Returns sorted-descending list of strict semver tags, up to 20.
    Raises RuntimeError on auth failure, IOError on network failure.
    Results cached for _get_ghcr_tag_ttl() seconds.
    """
    import httpx

    cached = _GHCR_TAG_CACHE.get(image_bare)
    if cached and (_time.monotonic() - cached[1]) < _get_ghcr_tag_ttl():
        return cached[0]

    token = os.environ.get("GHCR_TOKEN", "")
    token_source = "env" if token else "none"
    if not token:
        # Fallback: read from settings DB in case sync_env_from_db() missed it
        try:
            from mcp_server.tools.skills.storage import get_backend
            token = get_backend().get_setting("ghcrToken") or ""
            if token:
                os.environ["GHCR_TOKEN"] = token  # backfill for subsequent calls
                token_source = "db"
        except Exception as db_err:
            log.debug("GHCR token DB fallback failed: %s", db_err)
    if not token:
        log.warning("GHCR tag fetch skipped: no token (checked env GHCR_TOKEN and DB ghcrToken)")
        raise RuntimeError("GHCR_TOKEN not configured")
    log.debug("GHCR token found via %s (length=%d)", token_source, len(token))

    repo = image_bare[len("ghcr.io/"):]   # kbreivik/hp1-ai-agent

    # trust_env=False: prevents httpx from picking up http_proxy/https_proxy env vars
    # which can be set to bare hostnames (no scheme) and cause "missing protocol" errors.
    client = httpx.Client(trust_env=False, timeout=10, follow_redirects=True)

    # GHCR v2 API requires OAuth token exchange — PAT cannot be used directly as Bearer.
    tok_url = f"https://ghcr.io/token?scope=repository:{repo}:pull&service=ghcr.io"
    try:
        tok_resp = client.get(tok_url, auth=("token", token))
    except Exception as exc:
        log.error("GHCR token exchange failed (network): %s", exc)
        raise IOError(f"GHCR unreachable: {exc}") from exc
    log.debug("GHCR token exchange: HTTP %d", tok_resp.status_code)
    if tok_resp.status_code in (401, 403):
        log.warning("GHCR auth failed: HTTP %d — token may be expired or lack read:packages scope", tok_resp.status_code)
        raise RuntimeError(f"GHCR auth failed: HTTP {tok_resp.status_code}")
    if not tok_resp.is_success:
        log.warning("GHCR token exchange error: HTTP %d", tok_resp.status_code)
        raise IOError(f"GHCR token error: HTTP {tok_resp.status_code}")
    bearer = tok_resp.json().get("token", "")

    headers = {"Authorization": f"Bearer {bearer}"}
    semver_re = re.compile(r"^\d+\.\d+\.\d+$")
    all_tags: list[str] = []
    url = f"https://ghcr.io/v2/{repo}/tags/list?n=500"

    for _ in range(10):
        try:
            r = client.get(url, headers=headers)
        except Exception as exc:
            raise IOError(f"GHCR unreachable: {exc}") from exc

        if r.status_code in (401, 403):
            raise RuntimeError(f"GHCR auth failed: HTTP {r.status_code}")
        if not r.is_success:
            raise IOError(f"GHCR error: HTTP {r.status_code}")

        all_tags.extend(r.json().get("tags") or [])

        # Follow Link header pagination — do NOT stop early.
        # GHCR returns tags alphabetically, so old tags appear before new ones.
        # We must page through ALL tags to find the newest semver versions.
        next_url = None
        for part in r.headers.get("link", "").split(","):
            part = part.strip()
            if 'rel="next"' in part:
                next_url = part.split(";")[0].strip().strip("<>")
                break
        if not next_url:
            break
        # GHCR Link headers may return relative paths — ensure absolute URL
        if next_url.startswith("/"):
            next_url = f"https://ghcr.io{next_url}"
        url = next_url

    client.close()
    log.debug("GHCR tags fetched: %d total, filtering semver", len(all_tags))
    semver_tags = [t for t in all_tags if semver_re.match(t)]
    # Filter out versions before MIN_SAFE_VERSION (broken self-update, no sidecar recreate)
    semver_tags = [
        t for t in semver_tags
        if tuple(int(x) for x in t.split(".")) >= MIN_SAFE_VERSION
    ]
    semver_tags.sort(key=lambda v: tuple(int(x) for x in v.split(".")), reverse=True)
    result = semver_tags[:20]
    _GHCR_TAG_CACHE[image_bare] = (result, _time.monotonic())
    return result


@router.get("/containers/{container_id}/tags")
async def get_container_tags(container_id: str, force: bool = False, user: str = Depends(get_current_user)):
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
        return JSONResponse(status_code=404, content={"error": "container not found"})

    image = container.get("image", "")
    if not image.startswith("ghcr.io/"):
        return {"tags": [], "error": "not a ghcr image"}

    bare = image.split("@")[0].split(":")[0]   # ghcr.io/kbreivik/hp1-ai-agent

    if force:
        _GHCR_TAG_CACHE.pop(bare, None)

    try:
        tags = await asyncio.to_thread(_fetch_ghcr_tags, bare)
        return {"tags": tags}
    except RuntimeError as exc:
        log.warning("GHCR auth error for %s: %s", bare, exc)
        return JSONResponse(status_code=503, content={"error": "ghcr auth failed"})
    except IOError as exc:
        log.warning("GHCR network error for %s: %s", bare, exc)
        return JSONResponse(status_code=502, content={"error": "ghcr unreachable"})


# ── Action endpoints ────────────────────────────────────────────────────────────

from pydantic import BaseModel


class ScaleRequest(BaseModel):
    replicas: int


# ── Container log stream ───────────────────────────────────────────────────────

async def _log_generator(container_id: str, tail: int):
    """Async generator that streams Docker log lines as SSE data events.

    Uses a background thread to run the blocking Docker SDK iterator and
    bridges output to the async generator via a queue.

    Note: token auth via query param is a necessary compromise. EventSource
    cannot send custom headers. Tokens appear in access logs; acceptable here
    because this is a single-admin homelab with no multi-user exposure.
    """
    import docker
    q = _queue.Queue(maxsize=200)
    _DONE = object()
    stop = threading.Event()

    def _reader():
        try:
            _, container = _resolve_container(container_id)
        except docker.errors.NotFound:
            q.put(f"data: [container '{container_id}' not found]\n\n")
            q.put(_DONE)
            return
        except Exception as e:
            q.put(f"data: [connection error: {e}]\n\n")
            q.put(_DONE)
            return
        try:
            remainder = ""
            for chunk in container.logs(stream=True, follow=True, tail=tail):
                if stop.is_set():
                    return
                text = remainder + chunk.decode("utf-8", errors="replace")
                lns = text.splitlines(keepends=True)
                remainder = lns.pop() if lns and not lns[-1].endswith("\n") else ""
                for line in lns:
                    line = line.strip()
                    if not line:
                        continue
                    # SSE spec: embedded newlines must be split into separate data: lines
                    sse_line = line.replace("\n", "\ndata: ")
                    try:
                        q.put(f"data: {sse_line}\n\n", timeout=1)
                    except _queue.Full:
                        if stop.is_set():
                            return
            if remainder.strip():
                sse_line = remainder.strip().replace("\n", "\ndata: ")
                try:
                    q.put(f"data: {sse_line}\n\n", timeout=1)
                except _queue.Full:
                    pass
        except Exception as e:
            if not stop.is_set():
                try:
                    q.put(f"data: [stream ended: {e}]\n\n", timeout=1)
                except _queue.Full:
                    pass
        finally:
            q.put(_DONE)

    threading.Thread(target=_reader, daemon=True).start()

    try:
        while True:
            try:
                item = await asyncio.to_thread(q.get, timeout=30)
            except _queue.Empty:
                # Safety net: if _DONE was somehow never put, terminate cleanly
                break
            if item is _DONE:
                break
            yield item
    except GeneratorExit:
        stop.set()
        raise



@router.get("/containers/{container_id}/logs/stream")
async def stream_container_logs(
    container_id: str,
    tail: int = 200,
    token: str = "",
    request: Request = None,
):
    """Stream container stdout/stderr as SSE. Auth via cookie (preferred) or ?token= fallback."""
    from api.auth import decode_token
    _token = token or (request.cookies.get("hp1_auth") if request else "")
    try:
        decode_token(_token)
    except HTTPException:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)

    return StreamingResponse(
        _log_generator(container_id, tail),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

# ── Unified log stream ─────────────────────────────────────────────────────────

_LEVEL_PAT = re.compile(r'\b(DEBUG|INFO|WARN(?:ING)?|ERROR|CRITICAL|FATAL)\b', re.IGNORECASE)


def _detect_level(line: str) -> str:
    """Scan a raw log line for a level keyword; default to 'info'."""
    m = _LEVEL_PAT.search(line)
    if not m:
        return 'info'
    w = m.group(1).upper()
    if w in ('WARN', 'WARNING'):
        return 'warn'
    if w == 'FATAL':
        return 'error'
    return w.lower()


async def _unified_log_generator(tail: int):
    """Async generator that fans out to all local Docker containers + Elasticsearch.

    Each SSE event is a JSON object:
        {"ts": "<ISO8601>", "source": "docker|es|status", "container": "<name>",
         "level": "debug|info|warn|error|critical", "msg": "<text>"}

    Docker: one background thread per container using AGENT01_DOCKER_HOST.
    ES: one background polling thread using ELASTIC_URL via httpx.Client (sync).
    All threads share one queue. Generator exits when all sources finish or
    the client disconnects (GeneratorExit -> stop event set).
    """
    import docker as _docker

    shared_q: _queue.Queue = _queue.Queue(maxsize=500)
    stop = threading.Event()
    _DONE = object()
    _lock = threading.Lock()
    _active = [0]  # mutable counter of live source threads

    def _emit(obj: dict) -> None:
        line = json.dumps(obj)
        try:
            shared_q.put(f"data: {line}\n\n", timeout=1)
        except _queue.Full:
            pass

    def _source_done() -> None:
        with _lock:
            _active[0] -= 1
            if _active[0] <= 0:
                try:
                    shared_q.put(_DONE, timeout=2)
                except _queue.Full:
                    pass

    # ── Discover local containers (AGENT01_DOCKER_HOST) ───────────────────────
    local_host = os.environ.get("AGENT01_DOCKER_HOST", "unix:///var/run/docker.sock")
    containers: list = []
    try:
        dc = _docker.DockerClient(base_url=local_host, timeout=15)
        try:
            containers = dc.containers.list()
        finally:
            dc.close()
    except Exception as exc:
        _emit({"source": "status", "msg": f"Docker unavailable: {exc}"})

    # ── Discover Swarm services (DOCKER_HOST → manager) ────────────────────────
    # Swarm services run on workers; use service.logs() via the manager API.
    swarm_host = os.environ.get("DOCKER_HOST", "")
    swarm_services: list = []
    if swarm_host and swarm_host != local_host:
        try:
            dc_swarm = _docker.DockerClient(base_url=swarm_host, timeout=15)
            try:
                swarm_services = dc_swarm.services.list()
            finally:
                dc_swarm.close()
        except Exception as exc:
            _emit({"source": "status", "msg": f"Swarm unavailable: {exc}"})

    # ── Docker reader (one per local container) ────────────────────────────────
    def _docker_reader(container) -> None:
        try:
            remainder = ""
            for chunk in container.logs(stream=True, follow=True, tail=tail):
                if stop.is_set():
                    return
                text = remainder + chunk.decode("utf-8", errors="replace")
                lns = text.splitlines(keepends=True)
                remainder = lns.pop() if lns and not lns[-1].endswith("\n") else ""
                for raw in lns:
                    raw = raw.strip()
                    if not raw:
                        continue
                    _emit({
                        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        "source": "docker",
                        "container": container.name,
                        "level": _detect_level(raw),
                        "msg": raw,
                    })
            if remainder.strip():
                _emit({
                    "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "source": "docker",
                    "container": container.name,
                    "level": _detect_level(remainder.strip()),
                    "msg": remainder.strip(),
                })
        except Exception as exc:
            if not stop.is_set():
                _emit({"source": "status", "msg": f"[{container.name} ended: {exc}]"})
        finally:
            _source_done()

    # ── Swarm service reader (one per service, logs via manager) ──────────────
    def _service_reader(service) -> None:
        svc_name = service.name
        try:
            remainder = ""
            for chunk in service.logs(follow=True, stdout=True, stderr=True, tail=tail):
                if stop.is_set():
                    return
                text = remainder + chunk.decode("utf-8", errors="replace")
                lns = text.splitlines(keepends=True)
                remainder = lns.pop() if lns and not lns[-1].endswith("\n") else ""
                for raw in lns:
                    raw = raw.strip()
                    if not raw:
                        continue
                    # Strip task prefix: "kafka_broker-1.1.abc@worker-01    | msg"
                    if " | " in raw:
                        raw = raw.split(" | ", 1)[1].strip()
                    if not raw:
                        continue
                    _emit({
                        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        "source": "docker",
                        "container": svc_name,
                        "level": _detect_level(raw),
                        "msg": raw,
                    })
        except Exception as exc:
            if not stop.is_set():
                _emit({"source": "status", "msg": f"[{svc_name} ended: {exc}]"})
        finally:
            _source_done()

    # ── Elasticsearch polling reader ───────────────────────────────────────────
    def _es_reader() -> None:
        import httpx
        elastic_url = os.environ.get("ELASTIC_URL", "").rstrip("/")
        index = os.environ.get("ELASTIC_INDEX_PATTERN", "hp1-logs-*")
        if not elastic_url:
            _emit({"source": "status", "msg": "ES offline"})
            _source_done()
            return
        # Connectivity check
        try:
            with httpx.Client(timeout=5) as c:
                c.get(f"{elastic_url}/_cluster/health")
        except Exception:
            _emit({"source": "status", "msg": "ES offline"})
            _source_done()
            return

        seen_ids: set = set()
        last_ts = (
            datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=1)
        ).strftime("%Y-%m-%dT%H:%M:%S.000Z")

        with httpx.Client(timeout=10) as client:
            while not stop.is_set():
                try:
                    r = client.post(
                        f"{elastic_url}/{index}/_search",
                        json={
                            "query": {"range": {"@timestamp": {"gte": last_ts}}},
                            "sort": [{"@timestamp": "asc"}],
                            "size": 50,
                        },
                    )
                    if r.is_success:
                        for hit in r.json().get("hits", {}).get("hits", []):
                            if hit["_id"] in seen_ids:
                                continue
                            seen_ids.add(hit["_id"])
                            src = hit.get("_source", {})
                            ts = src.get("@timestamp", datetime.datetime.now(datetime.timezone.utc).isoformat())
                            if ts > last_ts:
                                last_ts = ts
                            container_name = ""
                            host_name = ""
                            if isinstance(src.get("container"), dict):
                                container_name = src["container"].get("name", "")
                            if isinstance(src.get("host"), dict):
                                host_name = src["host"].get("name", "")
                            # Use container name if available, fall back to host name
                            display_name = container_name or host_name
                            level_raw = "info"
                            if isinstance(src.get("log"), dict):
                                level_raw = src["log"].get("level") or "info"
                            _emit({
                                "ts": ts,
                                "source": "es",
                                "container": display_name,
                                "host": host_name,
                                "level": level_raw.lower(),
                                "msg": src.get("message", ""),
                            })
                except Exception as exc:
                    if not stop.is_set():
                        _emit({"source": "status", "msg": f"ES connection lost: {exc}"})
                    _source_done()
                    return
                # 2-second poll interval in 100ms chunks for responsive stop
                for _ in range(20):
                    if stop.is_set():
                        break
                    _time.sleep(0.1)
        _source_done()

    # ── Start all threads ──────────────────────────────────────────────────────
    source_count = len(containers) + len(swarm_services) + 1  # local + swarm + ES
    _active[0] = source_count  # set before threads start — no lock needed yet

    for c in containers:
        threading.Thread(target=_docker_reader, args=(c,), daemon=True).start()
    for s in swarm_services:
        threading.Thread(target=_service_reader, args=(s,), daemon=True).start()
    threading.Thread(target=_es_reader, daemon=True).start()

    # ── Fan-in ────────────────────────────────────────────────────────────────
    try:
        while True:
            try:
                item = await asyncio.to_thread(shared_q.get, timeout=30)
            except _queue.Empty:
                break
            if item is _DONE:
                break
            yield item
    except GeneratorExit:
        stop.set()
        raise


@router.get("/logs/stream")
async def stream_all_logs(
    tail: int = 200,
    token: str = "",
    request: Request = None,
):
    """Stream all local Docker containers + Elasticsearch as a unified SSE JSON feed.

    Auth via cookie (preferred) or ?token= fallback.
    Each event: data: {"ts","source","container","level","msg"}
    """
    from api.auth import decode_token
    _token = token or (request.cookies.get("hp1_auth") if request else "")
    try:
        decode_token(_token)
    except HTTPException:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)

    return StreamingResponse(
        _unified_log_generator(tail),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _docker_client():
    import docker
    host = os.environ.get("DOCKER_HOST", "unix:///var/run/docker.sock")
    return docker.DockerClient(base_url=host, timeout=15)


def _resolve_container(container_id: str):
    """Return (DockerClient, Container) checking agent-01 local daemon first, then DOCKER_HOST."""
    import docker
    hosts = [
        os.environ.get("AGENT01_DOCKER_HOST", "unix:///var/run/docker.sock"),
        os.environ.get("DOCKER_HOST", "unix:///var/run/docker.sock"),
    ]
    for host in hosts:
        try:
            client = docker.DockerClient(base_url=host, timeout=15)
            return client, client.containers.get(container_id)
        except docker.errors.NotFound:
            continue
    raise docker.errors.NotFound(container_id)


@router.post("/containers/{container_id}/pull")
async def pull_container(
    container_id: str,
    tag: str | None = None,
    user: str = Depends(get_current_user),
):
    return await asyncio.to_thread(_do_pull, container_id, tag)


def _is_self_container(container) -> bool:
    """Check if a container is the agent itself (hp1_agent)."""
    import re as _re
    name = _re.sub(r'^[0-9a-f]{12}_', '', container.name)
    return name == "hp1_agent" or container.name == "hp1_agent"


def _do_pull(container_id: str, tag: str | None = None) -> dict:
    try:
        client, container = _resolve_container(container_id)
        image_name = container.attrs["Config"]["Image"]

        auth_config = None
        if image_name.startswith("ghcr.io/"):
            token = os.environ.get("GHCR_TOKEN", "")
            if token:
                auth_config = {"username": "token", "password": token}

        if tag:
            bare = image_name.split("@")[0].split(":")[0]
            versioned = f"{bare}:{tag}"
            pulled = client.images.pull(versioned, auth_config=auth_config)
            current_tag = image_name.split(":")[-1] if ":" in image_name else "latest"
            pulled.tag(bare, tag=current_tag)
        else:
            client.images.pull(image_name, auth_config=auth_config)

        # For the agent's own container, use sidecar recreate (restart reuses old image)
        if _is_self_container(container):
            log.info("_do_pull: agent self-pull detected, using sidecar recreate")
            _restart_self_container()
        else:
            container.restart()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/containers/{container_id}/restart")
async def restart_container(container_id: str, user: str = Depends(get_current_user)):
    return await asyncio.to_thread(_do_restart, container_id)


def _do_restart(container_id: str) -> dict:
    try:
        _, container = _resolve_container(container_id)
        container.restart()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/containers/{container_id}/stop")
async def stop_container(container_id: str, user: str = Depends(get_current_user)):
    return await asyncio.to_thread(_do_stop, container_id)


def _do_stop(container_id: str) -> dict:
    try:
        _, container = _resolve_container(container_id)
        container.stop()
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


class UpdateImageRequest(BaseModel):
    image: str


@router.post("/services/{service_name}/update-image")
async def update_service_image(service_name: str, body: UpdateImageRequest,
                               user: str = Depends(get_current_user)):
    """Rolling update a Swarm service to a new image."""
    return await asyncio.to_thread(_do_update_image, service_name, body.image)


def _do_update_image(service_name, image):
    try:
        client = _docker_client()
        svc = client.services.get(service_name)
        old_image = (svc.attrs["Spec"]["TaskTemplate"]
                     ["ContainerSpec"].get("Image", "unknown"))
        svc.update(image=image)
        return {"ok": True, "previous_image": old_image.split("@")[0], "new_image": image}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/services/{service_name}/tasks")
async def get_service_tasks(service_name: str, user: str = Depends(get_current_user)):
    """Get current task list for a Swarm service."""
    return await asyncio.to_thread(_do_get_tasks, service_name)


def _do_get_tasks(service_name):
    try:
        client = _docker_client()
        svc = client.services.get(service_name)
        result = []
        for t in svc.tasks():
            result.append({
                "id": t.get("ID", "")[:12],
                "state": t.get("Status", {}).get("State", "unknown"),
                "desired": t.get("DesiredState", "unknown"),
                "node": t.get("NodeID", "")[:12],
                "started": t.get("Status", {}).get("Timestamp", ""),
                "image": (t.get("Spec", {}).get("ContainerSpec", {})
                           .get("Image", "").split("@")[0]),
                "error": t.get("Status", {}).get("Err", ""),
            })
        return {"ok": True, "service": service_name, "tasks": result}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/swarm/nodes/{node_id}/drain")
async def drain_node(node_id: str, user: str = Depends(get_current_user)):
    """Set a Swarm node to drain — stops scheduling new tasks."""
    return await asyncio.to_thread(_do_node_availability, node_id, "drain")


@router.post("/swarm/nodes/{node_id}/activate")
async def activate_node(node_id: str, user: str = Depends(get_current_user)):
    """Restore a drained Swarm node to active."""
    return await asyncio.to_thread(_do_node_availability, node_id, "active")


def _do_node_availability(node_id, availability):
    try:
        client = _docker_client()
        node = None
        for n in client.nodes.list():
            attrs = n.attrs
            if (attrs.get("ID", "").startswith(node_id) or
                attrs.get("Description", {}).get("Hostname", "") == node_id or
                attrs.get("Spec", {}).get("Name", "") == node_id):
                node = n
                break
        if not node:
            return {"ok": False, "error": f"Node {node_id!r} not found"}
        node.update(availability=availability)
        return {"ok": True, "node": node_id, "availability": availability}
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
    """Execute a Proxmox VM/LXC action (start/stop/reboot/shutdown) via proxmoxer.

    pve_type: 'qemu' for VMs, 'lxc' for containers.
    Reads Proxmox credentials from the connections DB — matches the cluster that owns
    the target node. Falls back to first proxmox connection or env vars if needed.
    """
    try:
        from proxmoxer import ProxmoxAPI
        from api.connections import get_connection, get_all_connections_for_platform
    except ImportError as e:
        return {"ok": False, "error": f"proxmoxer not available: {e}"}

    # Resolve credentials — find the connection whose cluster contains the target node.
    conn = None
    try:
        all_conns = get_all_connections_for_platform("proxmox")
        if len(all_conns) == 1:
            conn = all_conns[0]
        elif len(all_conns) > 1:
            # Use the proxmox_vms snapshot to match node → connection_id
            try:
                import asyncio as _asyncio
                import json as _json
                from api.db.base import get_sync_engine
                from sqlalchemy import text as _text
                with get_sync_engine().connect() as _sc:
                    row = _sc.execute(
                        _text("SELECT state FROM status_snapshots WHERE component = 'proxmox_vms' ORDER BY timestamp DESC LIMIT 1")
                    ).fetchone()
                if row:
                    state = row[0]
                    if isinstance(state, str):
                        state = _json.loads(state)
                    for cluster in state.get("clusters", []):
                        all_vms = cluster.get("vms", []) + cluster.get("lxc", [])
                        if any(v.get("node_api") == node or v.get("node") == node for v in all_vms):
                            cid = cluster.get("connection_id")
                            if cid:
                                conn = get_connection(str(cid))
                            break
            except Exception as _e:
                log.debug("_do_proxmox_action: snapshot node-match failed: %s", _e)
            # Fall back to first connection if snapshot match failed
            if not conn:
                conn = all_conns[0]
    except Exception:
        pass

    if conn:
        creds = conn.get("credentials", {}) or {}
        host = conn.get("host", "")
        port = conn.get("port") or 8006
        pve_user = creds.get("user", "")
        token_name = creds.get("token_name", "")
        token_secret = creds.get("secret", "")
    else:
        host = os.environ.get("PROXMOX_HOST", "")
        port = int(os.environ.get("PROXMOX_PORT", "8006"))
        pve_user = os.environ.get("PROXMOX_USER", "")
        # Support both PROXMOX_TOKEN_ID (user@pve!token) and separate vars
        token_id_raw = os.environ.get("PROXMOX_TOKEN_ID", "")
        if "!" in token_id_raw:
            pve_user, token_name = token_id_raw.split("!", 1)
        else:
            token_name = token_id_raw
        token_secret = os.environ.get("PROXMOX_TOKEN_SECRET", "")

    if not host:
        return {"ok": False, "error": "No Proxmox host configured. Add a proxmox connection in Settings → Connections."}

    try:
        prox = ProxmoxAPI(
            host, port=port,
            user=pve_user, token_name=token_name, token_value=token_secret,
            verify_ssl=False, timeout=10,
        )
        endpoint = getattr(prox.nodes(node), pve_type)(vmid).status
        if action == "start":
            task = endpoint.start.post()
        elif action == "stop":
            task = endpoint.stop.post()
        elif action == "reboot":
            task = endpoint.reboot.post()
        elif action == "shutdown":
            task = endpoint.shutdown.post()
        else:
            return {"ok": False, "error": f"Unknown action: {action!r}"}

        log.info("Proxmox %s: %s %s/%s vmid=%d task=%s", action, node, pve_type, action, vmid, task)
        return {"ok": True, "task_id": str(task), "node": node, "vmid": vmid, "action": action}
    except Exception as e:
        log.error("_do_proxmox_action failed: %s", e)
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
    """Pull latest image from GHCR via Docker SDK. Runs synchronously — may take up to 2 min.
    Returns {"ok": true} when pull is complete; client should then call /self-restart."""
    image = os.environ.get("HP1_IMAGE", "ghcr.io/kbreivik/hp1-ai-agent:latest")
    try:
        result = await asyncio.get_running_loop().run_in_executor(None, _pull_image, image)
        return result
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/self-restart")
async def self_restart(user: str = Depends(get_current_user)):
    """Recreate hp1_agent container with current image. Fire-and-forget — agent will go down ~5s after response."""
    asyncio.get_running_loop().run_in_executor(None, _restart_self_container)
    return {"ok": True, "message": "Recreate triggered — agent will be back in ~20s"}


def _pull_image(image: str) -> dict:
    """Pull a Docker image synchronously via Docker SDK."""
    import docker
    log.info("self-update: pulling %s", image)
    try:
        client = docker.DockerClient(base_url="unix:///var/run/docker.sock")
        client.images.pull(image)
        log.info("self-update: pull complete for %s", image)
        return {"ok": True, "image": image}
    except Exception as e:
        log.error("self-update pull failed: %s", e)
        return {"ok": False, "error": str(e)}


def _restart_self_container() -> None:
    """Recreate hp1_agent container with the newly pulled image.

    A plain container.restart() reuses the old image. Instead, we spawn a
    short-lived sidecar container on the Docker host that waits 3 seconds
    (for the HTTP response to reach the client), then stops the agent
    container, removes it, and recreates it from the new image using the
    same config. The sidecar runs on the host via the mounted Docker socket
    and outlives the agent container.

    Falls back to container.restart() if sidecar creation fails.
    """
    import re
    import docker
    import time as _t
    log.info("self-restart: finding hp1_agent container")
    try:
        client = docker.DockerClient(base_url="unix:///var/run/docker.sock")
        container = None
        for c in client.containers.list():
            clean = re.sub(r'^[0-9a-f]{12}_', '', c.name)
            if clean == 'hp1_agent' or c.name == 'hp1_agent':
                container = c
                break
        if not container:
            log.error("self-restart: hp1_agent container not found")
            return

        container_name = container.name
        image = container.image.tags[0] if container.image.tags else container.attrs["Config"]["Image"]

        # Sidecar approach: spawn a host-level container that recreates us.
        # Mounts: Docker socket, compose files + .env, compose CLI plugin from host.
        try:
            # Remove stale recreator if it exists from a previous attempt
            try:
                old = client.containers.get("hp1_agent_recreator")
                old.remove(force=True)
            except Exception:
                pass

            recreate_script = (
                "sleep 3 && "
                f"docker stop {container_name} && "
                f"docker rm {container_name} && "
                "docker compose --project-name docker "
                "-f /compose/docker-compose.yml --env-file /compose/.env "
                "up -d --force-recreate hp1_agent"
            )
            log.info("self-restart: spawning sidecar to recreate %s with image %s", container_name, image)
            client.containers.run(
                "docker:cli",
                command=["sh", "-c", recreate_script],
                detach=True,
                remove=True,
                name="hp1_agent_recreator",
                volumes={
                    "/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "rw"},
                    "/opt/hp1-agent/docker": {"bind": "/compose", "mode": "ro"},
                    "/usr/local/lib/docker/cli-plugins": {
                        "bind": "/usr/local/lib/docker/cli-plugins", "mode": "ro",
                    },
                },
                network_mode="host",
            )
            log.info("self-restart: sidecar spawned — agent will be recreated in ~5s")
            return
        except Exception as sidecar_err:
            log.warning("self-restart: sidecar failed (%s), falling back to restart", sidecar_err)

        # Fallback: plain restart (reuses old image but at least brings the agent back)
        log.info("self-restart: falling back to container.restart() for %s", container_name)
        container.restart()
    except Exception as e:
        log.error("self-restart failed: %s", e)


# ── Auto-update background loop ──────────────────────────────────────────────

_HP1_IMAGE = "ghcr.io/kbreivik/hp1-ai-agent"
_STARTUP_DELAY = 60          # seconds before first auto-update check
_COOLDOWN_AFTER_UPDATE = 600  # 10 min cooldown after any update attempt
_last_update_attempt: float = 0.0


def _is_auto_update_enabled() -> bool:
    """Check the autoUpdate setting from DB."""
    try:
        from mcp_server.tools.skills.storage import get_backend
        val = get_backend().get_setting("autoUpdate")
        if val is None:
            return False
        if isinstance(val, bool):
            return val
        return str(val).lower() in ("true", "1", "yes")
    except Exception:
        return False


def _get_running_digest() -> str:
    """Get the image digest of the running hp1_agent container."""
    import re as _re
    try:
        import docker
        client = docker.DockerClient(base_url="unix:///var/run/docker.sock")
        for c in client.containers.list():
            name = _re.sub(r'^[0-9a-f]{12}_', '', c.name)
            if name == "hp1_agent" or c.name == "hp1_agent":
                # .image.id is the local image digest (sha256:...)
                digest = c.image.id or ""
                client.close()
                return digest
        client.close()
    except Exception as e:
        log.debug("_get_running_digest failed: %s", e)
    return ""


def _get_remote_digest(image_bare: str) -> str:
    """Get the remote digest for :latest tag from GHCR via HEAD on manifest."""
    import httpx
    token = os.environ.get("GHCR_TOKEN", "")
    if not token:
        try:
            from mcp_server.tools.skills.storage import get_backend
            token = get_backend().get_setting("ghcrToken") or ""
        except Exception:
            pass
    if not token:
        return ""

    repo = image_bare[len("ghcr.io/"):]
    client = httpx.Client(trust_env=False, timeout=10, follow_redirects=False)
    try:
        # OAuth token exchange
        client.headers["User-Agent"] = "hp1-agent"
        tok_resp = client.get(
            f"https://ghcr.io/token?scope=repository:{repo}:pull&service=ghcr.io",
            auth=("token", token),
        )
        if not tok_resp.is_success:
            return ""
        bearer = tok_resp.json().get("token", "")

        # HEAD on manifest to get digest without pulling
        r = client.head(
            f"https://ghcr.io/v2/{repo}/manifests/latest",
            headers={
                "Authorization": f"Bearer {bearer}",
                "Accept": "application/vnd.docker.distribution.manifest.v2+json",
            },
        )
        if r.is_success:
            return r.headers.get("docker-content-digest", "")
    except Exception as e:
        log.debug("_get_remote_digest failed: %s", e)
    finally:
        client.close()
    return ""


def _get_local_latest_digest() -> str:
    """Get the local image ID of the :latest tag (what we'd run if container were recreated)."""
    try:
        import docker
        client = docker.DockerClient(base_url="unix:///var/run/docker.sock")
        image_name = os.environ.get("HP1_IMAGE", f"{_HP1_IMAGE}:latest")
        img = client.images.get(image_name)
        digest = img.id or ""
        client.close()
        return digest
    except Exception as e:
        log.debug("_get_local_latest_digest failed: %s", e)
    return ""


def _check_and_update() -> None:
    """Check for newer image. Pull if remote differs, recreate only if local image changed.

    Comparison strategy (avoids infinite loop):
    1. Pull :latest from GHCR (always, to get the newest image locally)
    2. Compare LOCAL pulled image ID vs RUNNING container image ID
    3. If they match → already up to date, skip recreate
    4. If they differ → new image pulled, trigger sidecar recreate
    This avoids the registry-manifest-vs-local-id format mismatch.
    """
    global _last_update_attempt
    from api.constants import APP_VERSION

    _update_status["current_version"] = APP_VERSION
    _update_status["auto_update"] = _is_auto_update_enabled()

    if not _update_status["auto_update"]:
        _schedule_next_check()
        return

    # Cooldown guard: don't check again within 10 min of last update attempt
    now = _time.monotonic()
    if _last_update_attempt and (now - _last_update_attempt) < _COOLDOWN_AFTER_UPDATE:
        log.debug("auto-update: in cooldown (%ds remaining), skipping",
                  int(_COOLDOWN_AFTER_UPDATE - (now - _last_update_attempt)))
        _schedule_next_check()
        return

    try:
        running_digest = _get_running_digest()
        _update_status["current_digest"] = running_digest
        _update_status["last_checked"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Fetch tags for version info
        try:
            tags = _fetch_ghcr_tags(_HP1_IMAGE)
            _update_status["latest_version"] = tags[0] if tags else ""
        except Exception:
            pass

        # Pull the latest image (cheap if already up to date — Docker layer caching)
        image = os.environ.get("HP1_IMAGE", f"{_HP1_IMAGE}:latest")
        pull_result = _pull_image(image)
        if not pull_result.get("ok"):
            err = pull_result.get("error", "unknown")
            log.warning("auto-update: pull failed: %s", err)
            _update_status["update_available"] = False
            _schedule_next_check()
            return

        # Compare LOCAL pulled image ID vs RUNNING container image ID
        local_digest = _get_local_latest_digest()
        _update_status["latest_digest"] = local_digest

        if not running_digest or not local_digest:
            log.debug("auto-update: missing digest (running=%s, local=%s), skipping",
                      running_digest[:20] if running_digest else "none",
                      local_digest[:20] if local_digest else "none")
            _update_status["update_available"] = False
            _schedule_next_check()
            return

        if running_digest == local_digest:
            log.info("auto-update: local digest %s matches running, skipping recreate",
                     local_digest[:20])
            _update_status["update_available"] = False
            _audit("auto_update_check", "up_to_date")
            _schedule_next_check()
            return

        # Local image differs from running → new image available, trigger recreate
        _update_status["update_available"] = True
        _last_update_attempt = _time.monotonic()
        latest_ver = _update_status.get("latest_version", "")
        log.info("auto-update: new image detected (local=%s, running=%s), triggering recreate. version=%s",
                 local_digest[:20], running_digest[:20], latest_ver)
        _audit("auto_update_check", f"update_applied | target=hp1_agent | {APP_VERSION} -> {latest_ver}")
        _restart_self_container()

    except Exception as e:
        log.warning("auto-update check failed: %s", e)
        _audit("auto_update_check", f"error | {e}")

    _schedule_next_check()


def _audit(action: str, result: str) -> None:
    """Write to skill audit log (sync, best-effort)."""
    try:
        from mcp_server.tools.orchestration import audit_log
        audit_log(action, result)
    except Exception:
        pass


def _schedule_next_check() -> None:
    """Schedule the next auto-update check using threading.Timer."""
    import threading
    global _auto_update_timer
    if _auto_update_timer is not None:
        _auto_update_timer.cancel()
    _auto_update_timer = threading.Timer(_get_auto_update_interval(), _check_and_update)
    _auto_update_timer.daemon = True
    _auto_update_timer.start()


def start_auto_update() -> None:
    """Start the auto-update timer. Called from lifespan on startup.

    Delays the first check by _STARTUP_DELAY seconds to let the container
    fully initialize (DB, collectors, skills) before checking for updates.
    """
    import threading
    global _auto_update_timer
    _auto_update_timer = threading.Timer(_STARTUP_DELAY, _check_and_update)
    _auto_update_timer.daemon = True
    _auto_update_timer.start()
    log.info("auto-update: first check in %ds (enabled=%s)", _STARTUP_DELAY, _is_auto_update_enabled())


def stop_auto_update() -> None:
    """Cancel the auto-update timer."""
    global _auto_update_timer
    if _auto_update_timer is not None:
        _auto_update_timer.cancel()
        _auto_update_timer = None


@router.get("/update-status")
def get_update_status(_: str = Depends(get_current_user)):
    """Current auto-update state with digest-based detection."""
    from api.constants import APP_VERSION
    _update_status["current_version"] = APP_VERSION
    _update_status["auto_update"] = _is_auto_update_enabled()
    return _update_status


class AutoUpdateRequest(BaseModel):
    enabled: bool


@router.post("/auto-update")
def toggle_auto_update(req: AutoUpdateRequest, _: str = Depends(get_current_user)):
    """Enable or disable the auto-update background check."""
    try:
        from mcp_server.tools.skills.storage import get_backend
        get_backend().set_setting("autoUpdate", req.enabled)
        _update_status["auto_update"] = req.enabled
        log.info("auto-update toggled: %s", req.enabled)
        if req.enabled:
            # Trigger immediate check + schedule recurring timer
            import threading
            threading.Thread(target=_check_and_update, daemon=True).start()
        else:
            stop_auto_update()
        return {"status": "ok", "auto_update": req.enabled,
                "message": f"Auto-update {'enabled' if req.enabled else 'disabled'}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── VM Hosts ─────────────────────────────────────────────────────────────────

class VMExecRequest(BaseModel):
    command: str
    args: str = ""

_VM_ALLOWED_COMMANDS = {
    "uptime", "df -h", "free -m", "uname -r",
    "journalctl", "systemctl status", "systemctl restart",
    "docker ps", "docker ps -a", "docker images",
    "docker system df", "apt list --upgradable",
}

_VM_ALLOWED_SERVICES = {
    "docker", "elasticsearch", "logstash", "kibana",
    "filebeat", "kafka", "nginx", "ssh",
}


def _vm_allowlist_check(command):
    """Return the safe command string, or None if disallowed."""
    cmd = command.strip().lower()
    for allowed in _VM_ALLOWED_COMMANDS:
        if cmd == allowed or cmd.startswith(allowed + " "):
            # Strip shell metacharacters — no pipes, redirects, semicolons
            safe = command.replace(";", "").replace("|", "").replace(">", "").replace("<", "").replace("&", "")
            return safe.strip()
    return None


def _get_vm_conn(host_id):
    """Resolve vm_host connection by connection ID or label."""
    from api.connections import get_connection, get_all_connections_for_platform
    conn = get_connection(host_id)
    if conn and conn.get("platform") == "vm_host":
        return conn
    conns = get_all_connections_for_platform("vm_host")
    match = next((c for c in conns if c.get("label") == host_id), None)
    if match:
        return get_connection(str(match["id"]))
    return None


def _vm_ssh_exec(conn, command):
    """Execute a command on a VM via SSH.

    Uses the full credential resolution chain (own creds → profile → shared fallback)
    and jump host routing, identical to the collector. This ensures vm_host connections
    that use credential profiles work correctly for reboot/update actions.
    """
    from api.collectors.vm_hosts import _resolve_credentials, _resolve_jump_host, _ssh_run
    from api.connections import get_all_connections_for_platform

    try:
        all_conns = get_all_connections_for_platform("vm_host")
        username, password, private_key = _resolve_credentials(conn, all_conns)
        jump_host = _resolve_jump_host(conn, all_conns)
    except Exception as e:
        return {"ok": False, "error": f"Credential resolution failed: {e}"}

    host = conn.get("host", "")
    port = conn.get("port") or 22
    try:
        out = _ssh_run(
            host, port, username, password, private_key, command,
            jump_host=jump_host,
            _log_meta={
                "connection_id": str(conn.get("id", "")),
                "resolved_label": conn.get("label", host),
                "triggered_by": "vm_action",
            },
        )
        return {"ok": True, "output": out}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/vm-hosts")
async def get_vm_hosts(user: str = Depends(get_current_user)):
    """Latest snapshot of all VM hosts."""
    async with get_engine().connect() as conn:
        snap = await q.get_latest_snapshot(conn, "vm_hosts")
    state = _parse_state(snap)
    return {
        "vms": state.get("vms", []),
        "health": state.get("health", "unknown"),
        "last_updated": snap.get("timestamp") if snap else None,
    }


@router.post("/vm-hosts/{host_id}/exec")
async def vm_exec(host_id: str, req: VMExecRequest, user: str = Depends(get_current_user)):
    """Run an allowlisted command on a VM host."""
    safe_cmd = _vm_allowlist_check(req.command)
    if not safe_cmd:
        raise HTTPException(400, f"Command not allowed: {req.command!r}. "
                                 f"Allowed: {sorted(_VM_ALLOWED_COMMANDS)}")
    conn = _get_vm_conn(host_id)
    if not conn:
        raise HTTPException(404, f"VM host not found: {host_id}")
    return await asyncio.to_thread(_vm_ssh_exec, conn, safe_cmd)


@router.post("/vm-hosts/{host_id}/update")
async def vm_update(host_id: str, user: str = Depends(get_current_user)):
    """Run apt update + apt upgrade -y on a VM host. Logs action + broadcasts events."""
    conn = _get_vm_conn(host_id)
    if not conn:
        raise HTTPException(404, f"VM host not found: {host_id}")
    label = conn.get("label", host_id)
    aid = record_action(label, "update_packages", owner_user=user,
                        connection_id=str(conn.get("id", "")))
    await _ws_manager.broadcast({
        "type":   "vm_action",
        "host":   label,
        "action": "update_packages",
        "status": "started",
        "user":   user,
        "action_id": aid,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    })
    cmd = (
        "export DEBIAN_FRONTEND=noninteractive && "
        "sudo apt-get update -qq && "
        "sudo apt-get upgrade -y -qq 2>&1 | tail -30"
    )
    result = await asyncio.to_thread(_vm_ssh_exec, conn, cmd)
    status = "ok" if result.get("ok") else "error"
    output = result.get("output") or result.get("error", "")
    complete_action(aid, status, output)
    await _ws_manager.broadcast({
        "type":   "vm_action",
        "host":   label,
        "action": "update_packages",
        "status": status,
        "action_id": aid,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    })
    return {"ok": result.get("ok", False), "output": output, "action_id": aid,
            "message": f"Package update complete on {label}"}


@router.post("/vm-hosts/{host_id}/reboot")
async def vm_reboot(host_id: str, user: str = Depends(get_current_user)):
    """Schedule an immediate reboot of a VM host. Logs action + broadcasts WebSocket event."""
    conn = _get_vm_conn(host_id)
    if not conn:
        raise HTTPException(404, f"VM host not found: {host_id}")
    label = conn.get("label", host_id)
    aid = record_action(label, "reboot", owner_user=user,
                        connection_id=str(conn.get("id", "")))
    await _ws_manager.broadcast({
        "type":   "vm_action",
        "host":   label,
        "action": "reboot",
        "status": "started",
        "user":   user,
        "action_id": aid,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    })
    async def _do_and_log():
        result = await asyncio.to_thread(_vm_ssh_exec, conn, "sudo shutdown -r +0")
        status = "ok" if result.get("ok") else "error"
        complete_action(aid, status, result.get("output") or result.get("error", ""))
        await _ws_manager.broadcast({
            "type":   "vm_action",
            "host":   label,
            "action": "reboot",
            "status": status,
            "action_id": aid,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        })
    asyncio.create_task(_do_and_log())
    return {"ok": True, "message": f"Reboot scheduled for {label}", "action_id": aid}


@router.post("/vm-hosts/{host_id}/service/{service_name}/restart")
async def vm_service_restart(host_id: str, service_name: str,
                             user: str = Depends(get_current_user)):
    """Restart a systemd service on a VM host. Logs action + broadcasts events."""
    if service_name not in _VM_ALLOWED_SERVICES:
        raise HTTPException(400, f"Service {service_name!r} not in allowlist")
    conn = _get_vm_conn(host_id)
    if not conn:
        raise HTTPException(404, f"VM host not found: {host_id}")
    label = conn.get("label", host_id)
    aid = record_action(label, f"restart_{service_name}", owner_user=user,
                        connection_id=str(conn.get("id", "")))
    await _ws_manager.broadcast({
        "type":   "vm_action",
        "host":   label,
        "action": f"restart_{service_name}",
        "status": "started",
        "user":   user,
        "action_id": aid,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    })
    result = await asyncio.to_thread(_vm_ssh_exec, conn, f"sudo systemctl restart {service_name}")
    status = "ok" if result.get("ok") else "error"
    output = result.get("output") or result.get("error", "")
    complete_action(aid, status, output)
    await _ws_manager.broadcast({
        "type":   "vm_action",
        "host":   label,
        "action": f"restart_{service_name}",
        "status": status,
        "action_id": aid,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    })
    return {"ok": result.get("ok", False), "output": output, "action_id": aid,
            "message": f"{service_name} restarted on {label}"}


@router.get("/vm-hosts/{host_id}/actions")
async def get_vm_actions(host_id: str, limit: int = 20,
                         _: str = Depends(get_current_user)):
    """Recent actions taken on a VM host."""
    conn = _get_vm_conn(host_id)
    label = conn.get("label", host_id) if conn else host_id
    from api.db.vm_action_log import list_recent
    return {"actions": list_recent(connection_label=label, limit=limit)}


async def _vm_journal_generator(conn: dict, service_filter: str = ""):
    """SSH to a VM host and stream journalctl -f output as SSE events."""
    import asyncio as _asyncio
    import threading
    import queue as _q

    shared_q: _q.Queue = _q.Queue(maxsize=300)
    stop = threading.Event()
    _DONE = object()

    label = conn.get("label", conn.get("host", "?"))

    cmd = "journalctl -f --no-pager --output=short-iso -n 50"
    if service_filter:
        # Safe: service name is validated against _VM_ALLOWED_SERVICES before calling
        cmd = f"journalctl -f --no-pager --output=short-iso -n 50 -u {service_filter}"

    def _reader():
        try:
            from api.collectors.vm_hosts import _resolve_credentials, _ssh_run_streaming
            from api.connections import get_all_connections_for_platform
            all_conns = get_all_connections_for_platform("vm_host")
            username, password, private_key = _resolve_credentials(conn, all_conns)
            # _ssh_run_streaming: yields lines from SSH channel as they arrive
            for line in _ssh_run_streaming(
                conn["host"], conn.get("port") or 22,
                username, password, private_key, cmd
            ):
                if stop.is_set():
                    return
                line = line.strip()
                if not line:
                    continue
                obj = json.dumps({
                    "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "source": "ssh",
                    "container": label,
                    "level": _detect_level(line),
                    "msg": line,
                })
                try:
                    shared_q.put(f"data: {obj}\n\n", timeout=1)
                except _q.Full:
                    if stop.is_set():
                        return
        except Exception as exc:
            try:
                err_obj = json.dumps({"source": "status", "msg": f"SSH stream ended: {exc}"})
                shared_q.put(f"data: {err_obj}\n\n", timeout=1)
            except Exception:
                pass
        finally:
            shared_q.put(_DONE)

    threading.Thread(target=_reader, daemon=True).start()

    try:
        while True:
            try:
                item = await asyncio.to_thread(shared_q.get, timeout=30)
            except Exception:
                break
            if item is _DONE:
                break
            yield item
    except GeneratorExit:
        stop.set()
        raise


@router.get("/vm-hosts/{host_id}/logs/stream")
async def stream_vm_logs(
    host_id: str,
    service: str = "",
    token: str = "",
    request: Request = None,
):
    """Stream journalctl from a VM host via SSH as SSE.

    service: optional systemd service name to filter (must be in _VM_ALLOWED_SERVICES).
    Auth via cookie (preferred) or ?token= fallback.
    Each event: data: {"ts","source","container","level","msg"}
    """
    from api.auth import decode_token
    _token = token or (request.cookies.get("hp1_auth") if request else "")
    try:
        decode_token(_token)
    except HTTPException:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)

    if service and service not in _VM_ALLOWED_SERVICES:
        return JSONResponse({"detail": f"Service {service!r} not allowed"}, status_code=400)

    conn = _get_vm_conn(host_id)
    if not conn:
        return JSONResponse({"detail": "VM host not found"}, status_code=404)

    return StreamingResponse(
        _vm_journal_generator(conn, service_filter=service),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/entity-history/{entity_id}")
async def entity_history_summary(
    entity_id: str,
    hours: int = Query(24, ge=1, le=720),
    _: str = Depends(get_current_user),
):
    """Combined change + event summary for entity drawer / card badge."""
    from api.db.entity_history import get_changes, get_events
    changes = get_changes(entity_id, hours=hours, limit=20)
    events  = get_events(entity_id, hours=hours, limit=20)
    return {
        "entity_id": entity_id,
        "hours": hours,
        "change_count": len(changes),
        "event_count": len(events),
        "changes": changes[:10],
        "events":  events[:10],
        "has_critical": any(e["severity"] == "critical" for e in events),
        "has_warning":  any(e["severity"] == "warning"  for e in events),
    }
