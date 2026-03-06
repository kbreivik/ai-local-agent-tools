"""
GET/POST /api/memory — MuninnDB engram management endpoints.

Provides the GUI MemoryPanel with search, recent, store, and delete.
Also exposes /api/memory/health for connectivity check.
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from api.memory.client import get_client

router = APIRouter(prefix="/api/memory", tags=["memory"])


class StoreRequest(BaseModel):
    concept: str
    content: str
    tags: list[str] = []


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/health")
async def memory_health():
    """Check if MuninnDB is reachable."""
    client = get_client()
    ok = await client.health()
    return {"reachable": ok, "url": client._base}


@router.get("/recent")
async def memory_recent(limit: int = Query(20, ge=1, le=100)):
    """Return most recently stored engrams."""
    client = get_client()
    engrams = await client.recent(limit=limit)
    return {"engrams": engrams, "count": len(engrams)}


@router.get("/search")
async def memory_search(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=100),
):
    """Full-text search over stored engrams."""
    client = get_client()
    results = await client.search(q, limit=limit)
    return {"query": q, "results": results, "count": len(results)}


@router.post("/activate")
async def memory_activate(
    context: list[str],
    max_results: int = Query(5, ge=1, le=20),
):
    """Retrieve engrams most relevant to given context terms."""
    client = get_client()
    activations = await client.activate(context, max_results=max_results)
    return {"context": context, "activations": activations, "count": len(activations)}


@router.post("/store")
async def memory_store(body: StoreRequest):
    """Manually store an engram."""
    client = get_client()
    eid = await client.store(body.concept, body.content, body.tags)
    if eid is None:
        raise HTTPException(503, "MuninnDB unavailable")
    return {"id": eid, "concept": body.concept}


@router.delete("/{engram_id}")
async def memory_delete(engram_id: str):
    """Delete an engram by ID."""
    client = get_client()
    ok = await client.delete(engram_id)
    if not ok:
        raise HTTPException(404, "Engram not found or delete failed")
    return {"deleted": engram_id}
