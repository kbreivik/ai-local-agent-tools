"""URL/PDF ingestion REST endpoints with approval flow."""
import asyncio
import logging
import os
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from api.auth import get_current_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/memory/ingest", tags=["ingest"])

DOCS_DIR = Path(__file__).parent.parent.parent / "data" / "docs"

# Pending ingest jobs (in-memory, pre-approval)
_pending_jobs: dict[str, dict] = {}


class IngestUrlRequest(BaseModel):
    url: str
    tags: list[str] = []
    label: Optional[str] = None


@router.post("/url/preview")
async def preview_url(req: IngestUrlRequest, user: str = Depends(get_current_user)):
    """
    Fetch URL and return a preview + diff info (does NOT store yet).
    User must call /url/confirm to actually store.
    """
    from api.memory.ingest_worker import fetch_url, check_if_updated, _url_key, detect_breaking_changes_llm

    try:
        _, content = await fetch_url(req.url)
    except Exception as e:
        raise HTTPException(400, f"Failed to fetch URL: {e}")

    source_key = _url_key(req.url)
    update_info = check_if_updated(source_key, content)

    # LLM analysis if it's an update
    llm_analysis = None
    if update_info["is_updated"] and update_info.get("diff_snippet"):
        llm_analysis = await detect_breaking_changes_llm(update_info["diff_snippet"], req.url)

    job_id = str(uuid.uuid4())
    _pending_jobs[job_id] = {
        "type": "url",
        "url": req.url,
        "tags": req.tags,
        "label": req.label or req.url,
        "content": content,
        "update_info": update_info,
    }

    return {
        "job_id": job_id,
        "preview": content[:600],
        "char_count": len(content),
        "is_new": update_info["is_new"],
        "is_updated": update_info["is_updated"],
        "diff_snippet": update_info.get("diff_snippet", "")[:1000] if update_info.get("diff_snippet") else None,
        "breaking_changes_llm": llm_analysis,
    }


class ConfirmRequest(BaseModel):
    job_id: str
    approved: bool


@router.post("/url/confirm")
async def confirm_url_ingest(req: ConfirmRequest, user: str = Depends(get_current_user)):
    """Confirm (or cancel) a pending URL ingest job."""
    job = _pending_jobs.pop(req.job_id, None)
    if not job:
        raise HTTPException(404, f"Job '{req.job_id}' not found or expired")
    if not req.approved:
        return {"status": "cancelled", "message": "Ingest cancelled"}

    from api.memory.ingest_worker import _save_local, _url_key, chunk_and_store, _load_manifest, _save_manifest, _ts

    source_key = _url_key(job["url"])
    content = job["content"]
    local_path = _save_local(source_key, content, ".txt")

    engram_ids = await chunk_and_store(
        content=content,
        source=job["label"],
        tags=job["tags"] + ["url", "documentation"],
        source_key=source_key,
        local_path=local_path,
    )

    manifest = _load_manifest()
    manifest[source_key] = {
        "source_url": job["url"],
        "source_label": job["label"],
        "local_path": local_path,
        "content_hash": job["update_info"]["new_hash"],
        "muninndb_ids": engram_ids,
        "stored_at": _ts(),
        "chunk_count": len(engram_ids),
    }
    _save_manifest(manifest)

    return {
        "status": "ok",
        "source_key": source_key,
        "chunk_count": len(engram_ids),
        "local_path": local_path,
        "message": f"Ingested {len(engram_ids)} chunks from {job['url']}",
    }


@router.post("/pdf/upload")
async def upload_pdf(
    file: UploadFile = File(...),
    tags: str = Form(""),
    label: Optional[str] = Form(None),
    user: str = Depends(get_current_user),
):
    """Upload a PDF, parse it, return preview. Confirm with /pdf/confirm."""
    from api.memory.ingest_worker import parse_pdf, check_if_updated, detect_breaking_changes_llm
    import re

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files accepted")

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    dest = DOCS_DIR / file.filename
    content_bytes = await file.read()
    dest.write_bytes(content_bytes)

    try:
        content = parse_pdf(str(dest))
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, f"Failed to parse PDF: {e}")

    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    source_key = re.sub(r'[^\w.-]', '_', file.filename)[:80]
    update_info = check_if_updated(source_key, content)

    llm_analysis = None
    if update_info["is_updated"] and update_info.get("diff_snippet"):
        llm_analysis = await detect_breaking_changes_llm(update_info["diff_snippet"], file.filename)

    job_id = str(uuid.uuid4())
    _pending_jobs[job_id] = {
        "type": "pdf",
        "filename": file.filename,
        "local_path": str(dest),
        "tags": tag_list,
        "label": label or file.filename,
        "content": content,
        "update_info": update_info,
        "source_key": source_key,
    }

    return {
        "job_id": job_id,
        "filename": file.filename,
        "preview": content[:600],
        "char_count": len(content),
        "is_new": update_info["is_new"],
        "is_updated": update_info["is_updated"],
        "diff_snippet": update_info.get("diff_snippet", "")[:1000] if update_info.get("diff_snippet") else None,
        "breaking_changes_llm": llm_analysis,
    }


@router.post("/pdf/confirm")
async def confirm_pdf_ingest(req: ConfirmRequest, user: str = Depends(get_current_user)):
    """Confirm (or cancel) a pending PDF ingest job."""
    job = _pending_jobs.pop(req.job_id, None)
    if not job:
        raise HTTPException(404, f"Job '{req.job_id}' not found or expired")
    if not req.approved:
        return {"status": "cancelled", "message": "Ingest cancelled"}

    from api.memory.ingest_worker import chunk_and_store, _load_manifest, _save_manifest, _ts

    engram_ids = await chunk_and_store(
        content=job["content"],
        source=job["label"],
        tags=job["tags"] + ["pdf", "documentation"],
        source_key=job["source_key"],
        local_path=job["local_path"],
    )

    manifest = _load_manifest()
    manifest[job["source_key"]] = {
        "source_url": None,
        "source_label": job["label"],
        "local_path": job["local_path"],
        "content_hash": job["update_info"]["new_hash"],
        "muninndb_ids": engram_ids,
        "stored_at": _ts(),
        "chunk_count": len(engram_ids),
    }
    _save_manifest(manifest)

    return {
        "status": "ok",
        "source_key": job["source_key"],
        "chunk_count": len(engram_ids),
        "local_path": job["local_path"],
        "message": f"Ingested {len(engram_ids)} chunks from {job['filename']}",
    }


@router.get("/connectivity")
async def check_connectivity(user: str = Depends(get_current_user)):
    from api.memory.ingest_worker import check_internet_connectivity
    return await check_internet_connectivity()


@router.get("/docs")
async def list_docs(user: str = Depends(get_current_user)):
    """List all locally stored ingested documents."""
    from api.memory.ingest_worker import _load_manifest
    manifest = _load_manifest()
    docs = []
    for key, entry in manifest.items():
        docs.append({
            "source_key": key,
            "source_label": entry.get("source_label", key),
            "source_url": entry.get("source_url"),
            "stored_at": entry.get("stored_at"),
            "chunk_count": entry.get("chunk_count", 0),
            "local_path": entry.get("local_path"),
        })
    return {"docs": sorted(docs, key=lambda d: d.get("stored_at", ""), reverse=True)}
