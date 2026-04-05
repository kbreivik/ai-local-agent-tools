"""Hybrid semantic + keyword search over doc_chunks via pgvector.

All functions are synchronous (project rule). Uses psycopg2 directly
for vector operations — SQLAlchemy ORM doesn't handle pgvector well.
"""
import logging
import os
import time

log = logging.getLogger(__name__)

# ── Embedding model (lazy singleton, ONNX Runtime) ──────────────────────────

_tokenizer = None
_model = None


def _get_model():
    """Load bge-small-en-v1.5 ONNX on first use, cache for process lifetime."""
    global _tokenizer, _model
    if _model is None:
        from optimum.onnxruntime import ORTModelForFeatureExtraction
        from transformers import AutoTokenizer
        _tokenizer = AutoTokenizer.from_pretrained("BAAI/bge-small-en-v1.5")
        _model = ORTModelForFeatureExtraction.from_pretrained(
            "BAAI/bge-small-en-v1.5", export=True
        )
        log.info("RAG embedding model loaded: bge-small-en-v1.5 ONNX (384 dims)")
    return _tokenizer, _model


def embed(text: str) -> list[float]:
    """Embed a single text string. Returns 384-dim normalized float list."""
    import numpy as np
    tokenizer, model = _get_model()
    inputs = tokenizer(text, return_tensors="np", truncation=True, max_length=512)
    outputs = model(**inputs)
    emb = outputs.last_hidden_state.mean(axis=1).squeeze()
    emb = emb / np.linalg.norm(emb)
    return emb.tolist()


# ── Platform detection cache ─────────────────────────────────────────────────

_platform_cache: list[str] = []
_platform_cache_ts: float = 0.0
_PLATFORM_CACHE_TTL = 300  # 5 minutes


def _get_known_platforms(conn) -> list[str]:
    """Cached list of platforms that have indexed docs."""
    global _platform_cache, _platform_cache_ts
    if _platform_cache and (time.monotonic() - _platform_cache_ts) < _PLATFORM_CACHE_TTL:
        return _platform_cache
    try:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT platform FROM doc_chunks")
        _platform_cache = [r[0] for r in cur.fetchall()]
        _platform_cache_ts = time.monotonic()
        cur.close()
    except Exception:
        pass
    return _platform_cache


def detect_platform(task: str, conn) -> str:
    """Match task text against known platforms. Returns platform or empty string."""
    platforms = _get_known_platforms(conn)
    task_lower = task.lower()
    for p in platforms:
        if p.lower() in task_lower:
            return p
    return ""


# ── Hybrid search ────────────────────────────────────────────────────────────

_HYBRID_SQL = """
WITH vec AS (
    SELECT id, content, platform, doc_type, source_label, version,
           ROW_NUMBER() OVER (ORDER BY embedding <=> %(emb)s) AS rank_v
    FROM doc_chunks
    WHERE TRUE {where}
    ORDER BY embedding <=> %(emb)s
    LIMIT 20
),
txt AS (
    SELECT id, content, platform, doc_type, source_label, version,
           ROW_NUMBER() OVER (ORDER BY ts_rank(tsv, plainto_tsquery('english', %(query)s)) DESC) AS rank_t
    FROM doc_chunks
    WHERE tsv @@ plainto_tsquery('english', %(query)s) {where}
    ORDER BY ts_rank(tsv, plainto_tsquery('english', %(query)s)) DESC
    LIMIT 20
)
SELECT
    COALESCE(v.id, t.id) AS id,
    COALESCE(v.content, t.content) AS content,
    COALESCE(v.platform, t.platform) AS platform,
    COALESCE(v.doc_type, t.doc_type) AS doc_type,
    COALESCE(v.source_label, t.source_label) AS source_label,
    COALESCE(v.version, t.version) AS version,
    (1.0 / (60 + COALESCE(v.rank_v, 999))) + (1.0 / (60 + COALESCE(t.rank_t, 999))) AS rrf_score
FROM vec v
FULL OUTER JOIN txt t ON v.id = t.id
ORDER BY rrf_score DESC
LIMIT %(limit)s
"""


def search_docs(
    query: str,
    platform: str = "",
    doc_type_filter: list[str] | None = None,
    limit: int = 10,
    token_budget: int = 3000,
) -> list[dict]:
    """Hybrid semantic + keyword search over doc_chunks.

    Returns list of dicts with content, platform, doc_type, source_label, version, rrf_score.
    Truncates to token_budget. Returns empty list if pgvector unavailable.
    """
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        return []

    try:
        import psycopg2
        from pgvector.psycopg2 import register_vector as _register_vector
        dsn = database_url.replace("postgresql+asyncpg://", "postgresql://")
        conn = psycopg2.connect(dsn)
        conn.autocommit = True
        _register_vector(conn)
        conn.autocommit = False
    except ImportError as e:
        log.warning("RAG search: missing dependency: %s", e)
        return []
    except Exception as e:
        log.warning("RAG search: DB connection failed: %s", e)
        return []

    try:
        # Auto-detect platform from task if not provided
        if not platform:
            platform = detect_platform(query, conn)

        # Build WHERE clause fragments
        where_parts = []
        params = {"query": query, "limit": limit}

        if platform:
            where_parts.append("AND platform = %(platform)s")
            params["platform"] = platform

        if doc_type_filter:
            where_parts.append("AND doc_type = ANY(%(doc_types)s)")
            params["doc_types"] = doc_type_filter

        where_clause = " ".join(where_parts)
        sql = _HYBRID_SQL.format(where=where_clause)

        # Embed query
        import numpy as np
        query_embedding = np.array(embed(query), dtype=np.float32)
        params["emb"] = query_embedding

        cur = conn.cursor()
        cur.execute(sql, params)
        columns = [desc[0] for desc in cur.description]
        rows = [dict(zip(columns, row)) for row in cur.fetchall()]
        cur.close()
        conn.close()

        # Truncate to token budget
        results = []
        tokens_used = 0
        for row in rows:
            chunk_tokens = len(row["content"]) // 4
            if tokens_used + chunk_tokens > token_budget and results:
                break
            row["rrf_score"] = float(row["rrf_score"])
            results.append(row)
            tokens_used += chunk_tokens

        log.debug("RAG search: query=%r platform=%r → %d results (%d tokens)",
                  query[:60], platform, len(results), tokens_used)
        return results

    except Exception as e:
        log.warning("RAG search failed: %s", e)
        try:
            conn.close()
        except Exception:
            pass
        return []


def format_doc_results(results: list[dict]) -> str:
    """Format search results as a RELEVANT DOCUMENTATION prompt section."""
    if not results:
        return ""
    lines = ["RELEVANT DOCUMENTATION:"]
    for r in results:
        label = r.get("source_label") or r.get("platform", "docs")
        doc_type = r.get("doc_type", "")
        version = r.get("version", "")
        header = f"[{label}"
        if version:
            header += f" v{version}"
        header += f" — {doc_type}]"
        lines.append(f"{header}\n{r['content']}")
    return "\n\n".join(lines)
