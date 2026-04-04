"""Create pgvector extension and doc_chunks table on startup.

Runs synchronously via psycopg2. Errors are caught silently — if PostgreSQL
or pgvector is unavailable, doc search returns empty results, no crash.
"""
import logging
import os

log = logging.getLogger(__name__)

_DDL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS doc_chunks (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content       TEXT NOT NULL,
    embedding     vector(384) NOT NULL,
    tsv           tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    platform      TEXT NOT NULL,
    doc_type      TEXT NOT NULL,
    source_url    TEXT DEFAULT '',
    source_label  TEXT DEFAULT '',
    version       TEXT DEFAULT '',
    chunk_index   INTEGER DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_doc_chunks_embedding
    ON doc_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50);
CREATE INDEX IF NOT EXISTS idx_doc_chunks_tsv
    ON doc_chunks USING gin (tsv);
CREATE INDEX IF NOT EXISTS idx_doc_chunks_platform
    ON doc_chunks (platform);
CREATE INDEX IF NOT EXISTS idx_doc_chunks_doc_type
    ON doc_chunks (doc_type);
CREATE UNIQUE INDEX IF NOT EXISTS idx_doc_chunks_dedup
    ON doc_chunks (platform, source_url, chunk_index);
"""

_initialized = False


def init_doc_chunks() -> bool:
    """Create the doc_chunks table if PostgreSQL + pgvector are available.

    Returns True if table is ready, False otherwise.
    Safe to call multiple times — no-ops after first success.
    """
    global _initialized
    if _initialized:
        return True

    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        log.debug("RAG schema skip: no DATABASE_URL (SQLite mode)")
        return False

    try:
        import psycopg2
        # Build sync DSN from DATABASE_URL (strip async driver prefixes)
        dsn = database_url.replace("postgresql+asyncpg://", "postgresql://")
        conn = psycopg2.connect(dsn)
        conn.autocommit = True
        cur = conn.cursor()
        for stmt in _DDL.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                cur.execute(stmt)
        cur.close()
        conn.close()
        _initialized = True
        log.info("RAG schema: doc_chunks table ready")
        return True
    except Exception as e:
        log.warning("RAG schema init failed (pgvector may not be installed): %s", e)
        return False
