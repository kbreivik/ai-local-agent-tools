# TODO — HP1-AI-Agent

Updated: 2026-04-05

## Bugs

- [ ] Agent loop doesn't return final summary after terminal tool calls (audit_log, etc.) — model stops after audit_log without generating text response. May need forced final LLM call or post-loop summary.
- [ ] `test_routers_dashboard.py::TestContainerTags` — 2 pre-existing failures. Tests mock `httpx.get` but dashboard now uses `httpx.Client(trust_env=False)`. Mock target mismatch.
- [ ] Ansible cron jobs auto-recreate when commented out — need ansible variable to toggle (`hp1_auto_upgrade: false` in hp1-infra group_vars)
- [x] audit_log dual registration path (server.py vs orchestration.py) — fixed in `2c29fce`
- [x] Operations never complete (flush_now before complete_operation) — fixed in `03c7e6a`
- [x] stop_agent didn't update DB status — fixed in `03c7e6a`
- [x] pgvector `register_vector` transaction error — fixed in `38069be`
- [x] pgvector ingest not wired through REST confirm endpoints — fixed in `728c703`
- [x] pgvector empty platform fallback — fixed in `b00a1ca`
- [x] Self-update container.restart() reuses old image — fixed with sidecar recreate
- [x] _do_pull also used restart for agent self — fixed to use sidecar
- [x] GHCR tag pagination (n=100 insufficient for 163+ tags) — fixed to n=500

## Security

- [ ] 3 secrets stored as plaintext JSON in `settings.value` column (lmStudioApiKey, externalApiKey, proxmoxTokenSecret). API masks on GET, but psql access shows them unmasked.
- [ ] `ADMIN_PASSWORD=changeme` in production .env — rotate before public access
- [ ] ghcrToken in both DB and .env (same value) — single source of truth should be DB only
- [x] `.claude/settings.local.json` leaked LM Studio API key — removed from tracking, key scrubbed from history
- [x] Hardcoded IPs in Python files moved to env vars
- [x] Invalid CORS CIDR removed, CORS_ORIGINS env var added

## Features

- [ ] RAG Phase A: replace MuninnDB doc retrieval in `doc_retrieval.py` with pgvector `search_docs()` for skill generation
- [ ] Ingest more vendor docs into pgvector — FortiGate admin guide PDF, Wazuh docs, Ansible docs
- [ ] Skill generation for 13+ fingerprinted-but-no-skill platforms (UniFi, OPNsense, Synology, Grafana, Portainer, Kibana, NGINX, Traefik, FortiSwitch, PBS, Syncthing)
- [ ] Scheduled/proactive analysis (APScheduler or background timer for health checks)
- [ ] Plan export format (downloadable runbook for manual execution)
- [ ] Fine-tuning dataset preparation from agent operation logs
- [ ] DISCOVER_DEFAULT_HOSTS needs more hosts (Proxmox nodes on port 8006, Kibana, Grafana)
- [x] search_docs MCP tool (Phase C) — shipped
- [x] Auto-update toggle with digest-based detection — shipped
- [x] Plugin architecture (3-tier: core → plugin → skill) — shipped
- [x] 3 example plugins: pihole_dns_stats, truenas_pool_status, technitium_dns_zones — shipped

## Architecture

- [ ] Settings priority: DB wins after first seed, .env is seed-only. Document this clearly.
- [ ] `build` agent type currently gets no doc injection — should get it when Phase A lands
- [ ] Production hp1-postgres image needs Ansible role change to `pgvector/pgvector:pg16`
- [ ] pgvector platform auto-classification: when platform is "unclassified", agent should analyze content and suggest classification
- [ ] Dual tool registration (server.py for MCP, tool_registry for agent loop) — audit all tools for signature mismatches
- [ ] Pre-pull docker:cli image via Ansible (needed for self-update sidecar)
- [x] ONNX Runtime migration — removed PyTorch/sentence-transformers (-4.8GB image size)
- [x] Tool result summarization for LLM context optimization — shipped

## Airgapped Deployment
- [ ] Add image-manifest.txt listing all required Docker images
- [ ] Add scripts/export-images.sh — pulls and saves all manifest images to tar files
- [ ] Add scripts/import-images.sh — loads all tar files into local Docker
- [ ] Ansible role for local Docker registry (registry:2) on airgapped network
- [ ] GUI "Re-pull Image" should support configurable registry URL (GHCR or local)
- [ ] Pre-pull docker:cli image via Ansible (needed for self-update sidecar)
