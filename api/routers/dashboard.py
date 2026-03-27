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

from fastapi import APIRouter, Depends, HTTPException
from starlette.responses import JSONResponse, StreamingResponse

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

    # GHCR v2 API requires OAuth token exchange — PAT cannot be used directly as Bearer.
    try:
        tok_resp = httpx.get(
            f"https://ghcr.io/token?scope=repository:{repo}:pull&service=ghcr.io",
            auth=("token", token),
            timeout=10,
        )
    except Exception as exc:
        raise IOError(f"GHCR unreachable: {exc}") from exc
    if tok_resp.status_code in (401, 403):
        raise RuntimeError(f"GHCR auth failed: HTTP {tok_resp.status_code}")
    if not tok_resp.is_success:
        raise IOError(f"GHCR token error: HTTP {tok_resp.status_code}")
    bearer = tok_resp.json().get("token", "")

    headers = {"Authorization": f"Bearer {bearer}"}
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
        if not r.is_success:
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
        return JSONResponse(status_code=404, content={"error": "container not found"})

    image = container.get("image", "")
    if not image.startswith("ghcr.io/"):
        return {"tags": [], "error": "not a ghcr image"}

    bare = image.split("@")[0].split(":")[0]   # ghcr.io/kbreivik/hp1-ai-agent

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
):
    """Stream container stdout/stderr as SSE. Auth via ?token= (EventSource can't send headers)."""
    from api.auth import decode_token
    try:
        decode_token(token)
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
                            if isinstance(src.get("container"), dict):
                                container_name = src["container"].get("name", "")
                            elif isinstance(src.get("host"), dict):
                                container_name = src["host"].get("name", "")
                            level_raw = "info"
                            if isinstance(src.get("log"), dict):
                                level_raw = src["log"].get("level") or "info"
                            _emit({
                                "ts": ts,
                                "source": "es",
                                "container": container_name,
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
):
    """Stream all local Docker containers + Elasticsearch as a unified SSE JSON feed.

    Auth via ?token= (EventSource cannot send custom headers).
    Each event: data: {"ts","source","container","level","msg"}
    """
    from api.auth import decode_token
    try:
        decode_token(token)
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
            # Pull the versioned image, then re-tag it as the container's current image
            # so container.restart() uses the new version.
            bare = image_name.split("@")[0].split(":")[0]
            versioned = f"{bare}:{tag}"
            pulled = client.images.pull(versioned, auth_config=auth_config)
            current_tag = image_name.split(":")[-1] if ":" in image_name else "latest"
            pulled.tag(bare, tag=current_tag)
        else:
            client.images.pull(image_name, auth_config=auth_config)

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
    """Restart the hp1_agent container. Fire-and-forget — agent will go down ~5s after response."""
    asyncio.get_running_loop().run_in_executor(None, _restart_self_container)
    return {"ok": True, "message": "Restart triggered — agent will be back in ~15s"}


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
    """Find the hp1_agent container by partial name match and restart it."""
    import re
    import docker
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
        log.info("self-restart: restarting %s", container.name)
        container.restart()
    except Exception as e:
        log.error("self-restart failed: %s", e)
