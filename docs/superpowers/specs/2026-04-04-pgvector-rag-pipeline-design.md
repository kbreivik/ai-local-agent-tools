# pgvector RAG Pipeline Design

**Date**: 2026-04-04
**Status**: Approved
**Approach**: C — Staged (pre-task injection first, search_docs tool second)

## Problem

The agent lacks vendor documentation context. When asked "configure OSPF on FortiGate," it has no reference material. MuninnDB handles operational memory (tool outcomes, escalations, patterns) but is symbol-based (Hebbian activation), not semantic. Documentation retrieval needs embedding-based similarity search.

## Constraints

- PostgreSQL 16 already running (hp1-postgres)
- Agent is sync-only (no async/await)
- Embedding model must run locally (no cloud APIs)
- MuninnDB stays for operational memory — pgvector is parallel, not a replacement
- 15 target platforms, mixed source material (HTML, PDF, config files)

## Architecture

Two retrieval systems feeding the same injection point:

```
Task arrives
    ├── pgvector: search_docs(task) → DOCUMENTATION section (semantic + keyword)
    └── MuninnDB: activate(task) → OPERATIONAL MEMORY section (Hebbian)
         ↓
    Combined context prepended to system prompt
         ↓
    Agent loop runs with full context
```

## Schema

Single table in the `hp1_agent` PostgreSQL database:

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE doc_chunks (
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

CREATE INDEX idx_doc_chunks_embedding ON doc_chunks
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50);
CREATE INDEX idx_doc_chunks_tsv ON doc_chunks USING gin (tsv);
CREATE INDEX idx_doc_chunks_platform ON doc_chunks (platform);
CREATE INDEX idx_doc_chunks_doc_type ON doc_chunks (doc_type);
CREATE UNIQUE INDEX idx_doc_chunks_dedup ON doc_chunks (platform, source_url, chunk_index);
```

Decisions:
- IVFFlat over HNSW — simpler, no build-time tuning, sufficient for <100K chunks
- `tsvector` as generated column — PostgreSQL maintains automatically
- Dedup index makes ingestion idempotent via `ON CONFLICT DO UPDATE`
- No FK to other tables — independent, queryable by any consumer
- SQLite fallback: not supported for pgvector; doc search returns empty results gracefully

Valid `doc_type` values: `api_reference`, `cli_reference`, `admin_guide`, `config_example`, `tutorial`.

## Embedding Model

- Model: `BAAI/bge-small-en-v1.5` (384 dimensions, ~130MB)
- Same model MuninnDB uses — consistent embedding space
- Loaded via `sentence-transformers` in-process, lazily on first use
- Cached as module singleton — ~200MB RAM overhead, acceptable for 4GB container

## Hybrid Search

Both vector similarity and full-text search, merged via Reciprocal Rank Fusion:

```
RRF_score(doc) = 1/(60 + rank_vector) + 1/(60 + rank_text)
```

Function signature in `api/rag/doc_search.py`:

```python
def search_docs(
    query: str,
    platform: str = "",
    doc_type_filter: list[str] | None = None,
    limit: int = 10,
    token_budget: int = 3000,
) -> list[dict]:
```

- Two queries in one round-trip (CTE): vector top-20 + tsvector top-20
- Deduped by chunk ID, sorted by RRF score
- Truncated to token_budget (len(content) // 4 approximation)
- Platform and doc_type filters applied to both queries
- Uses psycopg2 (sync) via `get_sync_engine()` — no async

## Ingestion Pipeline

### Chunking (`api/rag/chunker.py`)

Adaptive by doc_type:

| doc_type | Strategy | Target size | Overlap |
|----------|----------|-------------|---------|
| `api_reference`, `cli_reference` | Split on headings / double-newline | 400-500 tokens | 50 tokens |
| `admin_guide`, `tutorial` | Split on headings / paragraphs | 800 tokens | 50 tokens |
| `config_example` | Split on logical blocks (`server {`, `- name:`, `resource "`) | 600 tokens | 0 (natural boundaries) |

### Ingestion (`api/rag/ingest.py`)

```python
def ingest_chunks(
    chunks: list[str],
    platform: str,
    doc_type: str,
    source_url: str = "",
    source_label: str = "",
    version: str = "",
) -> int:
```

For each chunk: embed → upsert with `ON CONFLICT (platform, source_url, chunk_index) DO UPDATE`. Returns row count.

### Integration with existing pipelines

`ingest_worker.chunk_and_store()` stores chunks in MuninnDB. A parallel call to `ingest_chunks()` stores the same chunks (with embeddings) in pgvector. Both stores get the same content.

### URL-to-platform auto-detection

```python
DOMAIN_PLATFORM_MAP = {
    "pve.proxmox.com": ("proxmox", "admin_guide"),
    "docs.fortinet.com": ("fortigate", "admin_guide"),
    "docs.truenas.com": ("truenas", "admin_guide"),
    "docs.pi-hole.net": ("pihole", "admin_guide"),
    "documentation.wazuh.com": ("wazuh", "admin_guide"),
    "docs.securityonion.net": ("security_onion", "admin_guide"),
    "caddyserver.com": ("caddy", "admin_guide"),
    "doc.traefik.io": ("traefik", "admin_guide"),
    "docs.ansible.com": ("ansible", "api_reference"),
    "registry.terraform.io": ("terraform", "api_reference"),
    "docs.netbox.dev": ("netbox", "api_reference"),
    "nginx.org": ("nginx", "admin_guide"),
    "docs.syncthing.net": ("syncthing", "admin_guide"),
    "technitium.com": ("technitium", "admin_guide"),
}
```

User can always override platform and doc_type at ingestion time.

## Agent Injection

### Injection point

`_stream_agent()` in `api/routers/agent.py`. Existing injection block (lines 667-708) is extended with a pgvector search before the MuninnDB activation.

### Tiered budgets by agent type

| Agent Type | DOCUMENTATION budget | doc_type filter | OPERATIONAL MEMORY budget |
|---|---|---|---|
| `research` / `investigate` | 3000 tokens | all | 1500 tokens |
| `execute` | 1500 tokens | `api_reference`, `cli_reference` only | 1500 tokens |
| `observe` | 0 | — | 500 tokens |
| `build` | 0 (future: priority A) | — | 500 tokens |

### Platform detection

Task text matched against `SELECT DISTINCT platform FROM doc_chunks` (cached 5 min). If task mentions a known platform, search is scoped. Otherwise unscoped.

### Prompt format

```
RELEVANT DOCUMENTATION:
[FortiGate Admin Guide v7.4 — api_reference]
config router ospf
  set router-id 10.0.0.1
  ...

OPERATIONAL MEMORY:
[outcome:upgrade:kafka — 2026-03-28]
Last Kafka upgrade from 3.6→3.7 succeeded after ISR check.
```

Each chunk prefixed with `[source_label — doc_type]` for provenance.

Sections are separate — the LLM distinguishes "docs say this" from "we tried this before."

## Delivery Phases

### Phase B (3 days) — Pre-task injection
- `api/rag/__init__.py` — module init
- `api/rag/doc_search.py` — embedding model, hybrid search, RRF
- `api/rag/chunker.py` — adaptive chunking
- `api/rag/ingest.py` — embed + upsert pipeline
- `api/rag/schema.py` — sync startup function: `CREATE EXTENSION IF NOT EXISTS vector` + `CREATE TABLE IF NOT EXISTS doc_chunks`. Errors caught silently — if PostgreSQL or pgvector unavailable, doc search returns empty results, no crash.
- Modify `api/routers/agent.py` — inject DOCUMENTATION section
- Modify `api/memory/ingest_worker.py` — parallel write to pgvector
- Add `sentence-transformers`, `pgvector` to `requirements.txt`
- Tests for chunker, search, ingestion, and injection

### Phase C (+1 day) — search_docs MCP tool
- `search_docs` wrapper in `mcp_server/server.py`
- Shim in `mcp_server/tools/skill_meta_tools.py` for tool_registry
- Agent can call `search_docs(query="ospf fortigate", platform="fortigate")` mid-task

### Phase A (future) — Skill generation upgrade
- Replace MuninnDB doc retrieval in `doc_retrieval.py` with pgvector search
- Same `search_docs()` function, different caller

## Dependencies

- `sentence-transformers>=2.2.0` (bundles `bge-small-en-v1.5` on first use)
- `pgvector>=0.3.0` (psycopg2 integration for vector type)
- PostgreSQL 16 with `pgvector` extension installed

## What this does NOT change

- MuninnDB stays for operational memory (tool outcomes, escalations, patterns)
- Existing `doc_retrieval.py` stays for skill generation (Phase A upgrades it later)
- SQLite fallback mode — doc search returns empty, agent works without docs
- No GUI changes in v1
