"""
GET /api/dashboard/* — Dashboard card data from DB snapshots.

All data comes from the status_snapshots table, written by background collectors.
Never calls Docker/Proxmox/external services directly — that's the collectors' job.
"""
import json

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
