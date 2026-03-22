"""
GET/POST /api/memory — MuninnDB engram management endpoints.

Provides the GUI MemoryPanel with search, recent, store, and delete.
Also exposes /api/memory/health for connectivity check.
"""
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

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
    total = await client.count()
    ok = total is not None
    return {
        "status": "ok" if ok else "unconfigured",
        "reachable": ok,
        "url": client._base,
        "total_engrams": total or 0,
    }


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


@router.get("/patterns")
async def memory_patterns():
    """
    Aggregate outcome engrams into pattern summary.
    Used by the Memory → Patterns tab in the GUI.
    """
    from api.memory.summarize import get_patterns
    return await get_patterns()


@router.get("/docs")
async def memory_docs_status():
    """Return ingestion status for each documentation source."""
    from api.memory.fetch_docs import get_docs_status
    return {"sources": await get_docs_status()}


class FetchDocsRequest(BaseModel):
    component: Optional[str] = None   # None = all components
    force: bool = False


@router.post("/fetch-docs")
async def memory_fetch_docs(req: FetchDocsRequest, background_tasks: BackgroundTasks):
    """
    Trigger documentation ingestion into MuninnDB.
    Runs in background — returns immediately.
    """
    from api.memory.fetch_docs import ingest_all, SOURCES
    components = [req.component] if req.component else None

    # Validate component name
    valid = {s["component"] for s in SOURCES}
    if components:
        unknown = set(components) - valid
        if unknown:
            raise HTTPException(400, f"Unknown component(s): {unknown}. Valid: {valid}")

    background_tasks.add_task(ingest_all, components, req.force)
    return {
        "status":  "started",
        "message": f"Fetching {'all' if not components else req.component} docs in background",
    }
