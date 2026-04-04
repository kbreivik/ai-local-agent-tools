# HANDOFF — 2026-04-04T20:30:00Z

## Git state
```
99d3479 feat(rag): add caddyserver, traefik, Telmate to GitHub path map
40b99e6 feat(rag): expand DOMAIN_PLATFORM_MAP, add GitHub path matching
5aa39c6 docs: comprehensive TODO with bugs, security, features, architecture
38069be fix(rag): set autocommit before register_vector to avoid transaction error
728c703 fix(rag): wire platform detection into REST ingest endpoints
50e2cb5 feat(rag): wire pgvector into agent injection and ingestion pipeline
c16784c feat(rag): add pgvector RAG pipeline core module
...plus 20 earlier commits (bugfixes, security, auto-update, docs)
```
Branch: `v2/bugfixes` (28 commits ahead of main, pushed)
PR: kbreivik/ai-local-agent-tools#14 (open, ready for merge)
Tag: `v1.10.22-stable` on main as baseline
Version: `1.11.1`

## Agent state
Running on hp1-prod-agent-01 (192.168.199.10:8000), standalone mode.
pgvector RAG pipeline fully operational:
- 607 chunks ingested across 15 platforms
- bge-small-en-v1.5 embedding model loaded and working
- Hybrid search (vector + tsvector/RRF) verified
- Tiered agent injection working (DOCUMENTATION + OPERATIONAL MEMORY sections)
- doc_chunks table: 607 rows, 0 unclassified

## PR status
**PR #14**: kbreivik/ai-local-agent-tools#14 — `v2/bugfixes → main`
Title: "v1.11: bugfixes, security hardening, auto-update, pgvector RAG pipeline"
Status: Open, ready for merge. 28 commits, 174 tests pass.

## What was accomplished this session

### Bugfixes (6 critical)
- Operation completion: flush_now() before complete_operation
- stop_agent: writes status='cancelled' to DB
- audit_log: target/details params in orchestration.py (not just server.py wrapper)
- skill_execute: params_json instead of **kwargs
- discover_environment: defaults to DISCOVER_DEFAULT_HOSTS env var
- node_drain/activate: hostname resolution with error listing

### Security
- `.claude/settings.local.json` removed + key scrubbed from git history (BFG)
- Hardcoded IPs → env vars (DISCOVER_DEFAULT_HOSTS, AGENT01_IP, PROXMOX_VM_IP_MAP, CORS_ORIGINS)
- Invalid CORS CIDR removed

### Auto-update feature
- DB-backed autoUpdate setting + background GHCR check every 5 min
- GUI toggle in OptionsModal with status display
- Audit logging on update events

### pgvector RAG pipeline (Phase B — COMPLETE)
- `api/rag/` module: schema, doc_search, chunker, ingest
- bge-small-en-v1.5 bundled (384 dims, matches MuninnDB)
- Hybrid search: vector + tsvector with Reciprocal Rank Fusion
- Adaptive chunking: 400-500 tokens ref, 800 guide, logical blocks config
- Tiered injection: 3000 tokens research/investigate, 1500 execute (api/cli only), 0 observe/build
- 19 domains + 4 GitHub path prefixes in DOMAIN_PLATFORM_MAP
- Idempotent upsert with dedup index
- 607 chunks ingested, 0 unclassified, verified in production

### DB fixes
- UUID type mismatch on tool_calls/escalations FK columns
- postgres_health: sync engine instead of async
- register_vector transaction error (autocommit before registration)

### Docs
- MIT license, README rewrite, CLAUDE.md React fix
- pgvector RAG design spec
- Comprehensive TODO.md

## Decisions made
- pgvector parallel to MuninnDB — separate DOCUMENTATION and OPERATIONAL MEMORY sections
- bge-small-en-v1.5 to match MuninnDB embedding space
- Hybrid search from day one (not vector-only)
- Tiered budgets by agent type (research 3000, execute 1500 api/cli only, observe 0)
- "unclassified" fallback for unknown URLs (not empty string)
- GitHub path matching for raw.githubusercontent.com repos
- All work on single v2/bugfixes branch

## Active issues
- test_routers_dashboard.py::TestContainerTags — 2 pre-existing failures (httpx mock mismatch)
- 3 plaintext secrets in settings DB (no encryption at rest)
- ADMIN_PASSWORD=changeme in production .env

## Exact next action
Merge PR #14 to main, tag v1.11.1, then start Phase C (search_docs MCP tool) on a new branch.

## Context files for next session
- `state/TODO.md` — categorized pending work
- `docs/superpowers/specs/2026-04-04-pgvector-rag-pipeline-design.md` — RAG design spec (Phase C section)
- `api/rag/doc_search.py` — search_docs() function (Phase C wraps this)
- PR #14: https://github.com/kbreivik/ai-local-agent-tools/pull/14
