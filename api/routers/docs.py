"""User-facing doc search endpoints. Wraps api/rag/doc_search.py.

Separate from the ingest router — search is read-only and available to all roles.
"""
import logging
import os
from fastapi import APIRouter, Depends, Query
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
