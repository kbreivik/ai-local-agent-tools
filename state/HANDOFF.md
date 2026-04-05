# HANDOFF — 2026-04-05T12:30:00Z

## Git state
```
5699e6b perf: remove PyTorch, use raw onnxruntime for embeddings (-4.8GB)
181289e chore(release): bump to 1.13.0 — ONNX Runtime migration
0d7873e perf: replace PyTorch with ONNX Runtime (-4.8GB image size)
26e0670 chore(release): bump to 1.12.4 — auto-update toggle
4d27e49 feat(updates): auto-update toggle with digest detection, min version filter
```
Branch: `v2/plugin-architecture` (clean, pushed)
PR #15: https://github.com/kbreivik/ai-local-agent-tools/pull/15 (open)
PR #14: MERGED to main
Version: 1.13.1

## Agent state
v1.12.2 build 132 standalone on 192.168.199.10:8000 (needs rebuild for 1.13.1)
Tools registered: 67 (64 core + 3 plugins)
doc_chunks: 607 rows across 15 platforms
181 tests pass

## PR status
**PR #15**: kbreivik/ai-local-agent-tools#15 — `v2/plugin-architecture → main`
Title: "feat: plugin architecture, context optimization, self-update fixes"
Status: Open, description updated, ready for review.

## What was accomplished this session

### Plugin architecture (Phase 1-3)
- `api/plugin_loader.py` — scan_plugins(), PLUGIN_META contract validation, invoke_plugin()
- `api/tool_registry.py` — three-tier discovery: core (AST) → plugin (PLUGIN_META) → skill
- `api/agents/router.py` — _load_plugins_into_allowlists() reads agent_types from PLUGIN_META
- `plugins/pihole_dns_stats.py` — Pi-hole DNS statistics
- `plugins/truenas_pool_status.py` — TrueNAS ZFS pool health
- `plugins/technitium_dns_zones.py` — Technitium DNS zone listing
- `plugins/README.md` — contract documentation
- `docker/docker-compose.yml` — agent-plugins volume

### Context optimization
- `api/routers/agent.py` — _summarize_tool_result() compacts large results for LLM context
- RAG confidence threshold: skip chunks with RRF score < 0.02

### Self-update fixes
- `_do_pull()` detects agent self-container, uses sidecar recreate instead of restart
- Digest-based update detection (HEAD on manifests/latest, compare docker-content-digest)
- threading.Timer replaces asyncio loop for auto-update background check
- `POST /auto-update` triggers immediate check when enabling
- `MIN_SAFE_VERSION = (1, 12, 2)` — filters old versions from tag list + GUI dropdown
- `AutoUpdateToggle` component in ServiceCards.jsx agent card

### ONNX Runtime migration
- Replaced sentence-transformers/PyTorch (4.8GB) with raw onnxruntime (~100MB)
- `api/rag/doc_search.py` — ort.InferenceSession + AutoTokenizer + hf_hub_download
- `requirements.txt` — optimum/sentence-transformers → onnxruntime + tokenizers
- `docker/Dockerfile` — transformers --no-deps, torch import check fails build

### Subprocess policy
- CLAUDE.md updated: banned for LLM/user input paths, allowed for hardcoded plumbing

## Decisions made
- Raw onnxruntime over optimum (optimum pulls torch transitively)
- Pre-exported ONNX model from HF Hub (BAAI/bge-small-en-v1.5/onnx/model.onnx)
- Digest comparison for update detection (catches non-version-bump builds)
- threading.Timer over asyncio for auto-update (sync project pattern)
- MIN_SAFE_VERSION prevents rollback to broken self-update code
- Sidecar recreate pattern for all agent self-pull paths

## Dead ends
- optimum[onnxruntime] — pulls torch as transitive dependency, image grew instead of shrank

## Active issues
- Container running build 132 (v1.12.2) — needs rebuild for 1.13.1 + ONNX + plugins
- test_routers_dashboard.py::TestContainerTags — 2 pre-existing failures
- 3 plaintext secrets in settings DB (no encryption at rest)
- ADMIN_PASSWORD=changeme in production .env
- docker:cli image not pre-pulled on agent-01 (needed for sidecar recreate)

## Exact next action
Rebuild Docker image from v2/plugin-architecture, deploy to verify ONNX embedding works (384 dims, no torch), then merge PR #15 to main.

## Context files for next session
- `state/TODO.md` — categorized pending work (updated)
- `api/rag/doc_search.py` — ONNX embedding (verify after rebuild)
- `api/plugin_loader.py` — plugin scanner
- `plugins/` — 3 example plugins
- `docker/Dockerfile` — --no-deps + torch check
- PR #15: https://github.com/kbreivik/ai-local-agent-tools/pull/15
