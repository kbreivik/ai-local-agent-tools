"""User-facing doc search endpoints. Wraps api/rag/doc_search.py.

Separate from the ingest router — search is read-only and available to all roles.
"""
import logging
import os
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
import json
from api.auth import get_current_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/docs", tags=["docs"])


@router.get("/search")
def search_docs_endpoint(
    q: str = Query(..., min_length=1, max_length=500, description="Search query"),
    platform: str = Query("", description="Platform filter (empty = all)"),
    doc_type: str = Query("", description="doc_type filter (empty = all)"),
    limit: int = Query(12, ge=1, le=50),
    _: str = Depends(get_current_user),
):
    """Hybrid semantic + keyword search over ingested doc_chunks."""
    if not os.environ.get("DATABASE_URL", ""):
        return {"results": [], "query": q, "message": "pgvector unavailable (SQLite mode)"}
    try:
        from api.rag.doc_search import search_docs
        doc_type_filter = [doc_type] if doc_type else None
        results = search_docs(
            query=q,
            platform=platform or "",
            doc_type_filter=doc_type_filter,
            limit=limit,
            token_budget=8000,
        )
        return {"results": results, "query": q, "total": len(results)}
    except Exception as e:
        log.warning("docs/search failed: %s", e)
        return {"results": [], "query": q, "error": str(e)}


@router.get("/sources")
def list_doc_sources(_: str = Depends(get_current_user)):
    """List all ingested sources grouped by platform with chunk counts and doc_types."""
    if not os.environ.get("DATABASE_URL", ""):
        return {"platforms": []}
    try:
        import psycopg2
        from pgvector.psycopg2 import register_vector
        dsn = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
        conn = psycopg2.connect(dsn)
        conn.autocommit = True
        register_vector(conn)
        cur = conn.cursor()
        cur.execute("""
            SELECT
                platform,
                doc_type,
                source_label,
                source_url,
                COUNT(*) AS chunk_count,
                MAX(created_at) AS last_updated
            FROM doc_chunks
            GROUP BY platform, doc_type, source_label, source_url
            ORDER BY platform, source_label
        """)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.close(); conn.close()

        # Group by platform
        platforms = {}
        for row in rows:
            p = row["platform"]
            if p not in platforms:
                platforms[p] = {"platform": p, "total_chunks": 0, "sources": []}
            platforms[p]["total_chunks"] += row["chunk_count"]
            platforms[p]["sources"].append({
                "doc_type":     row["doc_type"],
                "source_label": row["source_label"],
                "source_url":   row["source_url"],
                "chunk_count":  row["chunk_count"],
                "last_updated": row["last_updated"].isoformat() if row["last_updated"] else None,
            })

        return {"platforms": sorted(platforms.values(), key=lambda x: x["platform"])}
    except Exception as e:
        log.warning("docs/sources failed: %s", e)
        return {"platforms": [], "error": str(e)}


@router.get("/chunks/around")
def get_chunks_around(
    platform: str = Query(...),
    source_url: str = Query(...),
    chunk_index: int = Query(...),
    window: int = Query(2, ge=1, le=5),
    _: str = Depends(get_current_user),
):
    """Fetch ±window chunks around a given chunk_index for context expansion."""
    if not os.environ.get("DATABASE_URL", ""):
        return {"chunks": []}
    try:
        import psycopg2
        from pgvector.psycopg2 import register_vector
        dsn = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
        conn = psycopg2.connect(dsn)
        conn.autocommit = True
        register_vector(conn)
        cur = conn.cursor()
        cur.execute("""
            SELECT chunk_index, content FROM doc_chunks
            WHERE platform = %s AND source_url = %s
              AND chunk_index BETWEEN %s AND %s
            ORDER BY chunk_index
        """, (platform, source_url, max(0, chunk_index - window), chunk_index + window))
        cols = [d[0] for d in cur.description]
        chunks = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.close(); conn.close()
        return {"chunks": chunks}
    except Exception as e:
        log.warning("docs/chunks/around failed: %s", e)
        return {"chunks": [], "error": str(e)}


@router.post("/ask")
def ask_docs(
    body: dict,
    _: str = Depends(get_current_user),
):
    """Grounded doc Q&A — retrieve chunks, call LM Studio, stream SSE response.

    Request body: {"question": str, "platform": str (optional)}
    Streams SSE: data: {"type": "chunk"|"source"|"done"|"error", ...}
    """
    question = (body.get("question") or "").strip()
    platform  = (body.get("platform") or "").strip()
    if not question:
        raise HTTPException(400, "question is required")
    if len(question) > 1000:
        raise HTTPException(400, "question too long (max 1000 chars)")

    def generate():
        # 1. Retrieve relevant chunks
        try:
            from api.rag.doc_search import search_docs
            results = search_docs(
                query=question,
                platform=platform,
                limit=8,
                token_budget=6000,
            )
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': f'Search failed: {e}'})}\n\n"
            return

        if not results:
            yield f"data: {json.dumps({'type': 'error', 'message': 'No relevant documentation found. Try ingesting docs first or use Browse mode.'})}\n\n"
            return

        # 2. Emit source references so frontend can display them immediately
        sources = []
        seen = set()
        for r in results:
            key = (r.get("platform", ""), r.get("source_label", ""), r.get("source_url", ""))
            if key not in seen:
                seen.add(key)
                sources.append({
                    "platform":     r.get("platform", ""),
                    "source_label": r.get("source_label", ""),
                    "source_url":   r.get("source_url", ""),
                    "doc_type":     r.get("doc_type", ""),
                    "version":      r.get("version", ""),
                })
        yield f"data: {json.dumps({'type': 'sources', 'sources': sources})}\n\n"

        # 3. Build system prompt with retrieved context
        doc_context = []
        for i, r in enumerate(results):
            label = r.get("source_label") or r.get("platform") or "doc"
            doc_context.append(f"[{i+1}] {label}\n{r['content']}")

        system_prompt = (
            "You are a technical documentation assistant for an infrastructure platform. "
            "Answer the question using ONLY the provided documentation excerpts. "
            "Cite sources using [1], [2], etc. matching the excerpt numbers. "
            "If the documentation does not contain enough information to answer, say so clearly. "
            "Be concise and specific. Do not invent details not present in the documentation.\n\n"
            "DOCUMENTATION EXCERPTS:\n\n" + "\n\n".join(doc_context)
        )

        # 4. Call LM Studio and stream
        lm_url = os.environ.get("LM_STUDIO_URL", "http://192.168.199.51:1234/v1")
        lm_key  = os.environ.get("LM_STUDIO_API_KEY", "lm-studio")
        model   = os.environ.get("MODEL_NAME", "")

        import urllib.request
        req_body = json.dumps({
            "model": model or "local-model",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": question},
            ],
            "stream": True,
            "temperature": 0.1,
            "max_tokens": 1024,
        }).encode()

        try:
            req = urllib.request.Request(
                f"{lm_url}/chat/completions",
                data=req_body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {lm_key}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:]
                    if payload == "[DONE]":
                        break
                    try:
                        delta = json.loads(payload)
                        text = delta.get("choices", [{}])[0].get("delta", {}).get("content", "")
                        if text:
                            yield f"data: {json.dumps({'type': 'chunk', 'text': text})}\n\n"
                    except Exception:
                        pass
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': f'LM Studio unreachable: {e}. Use Browse mode to search docs directly.'})}\n\n"
            return

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
