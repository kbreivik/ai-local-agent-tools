# HP1-AI-Agent

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Open-source local AI infrastructure orchestration agent. A Python MCP server + FastAPI backend + React GUI that enables a local LLM (Qwen3-Coder-30B) to autonomously manage, inspect, upgrade, and orchestrate homelab infrastructure with enforced safety checks at every step.

**Current version: v1.10.22** | **55+ MCP tools** | **4 agent types** | **6 background collectors** | **16 fingerprinted services**

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│                            HP1-AI-Agent                                  │
│                                                                          │
│  ┌───────────────┐   ┌─────────────────────────────────────────────┐    │
│  │  LM Studio    │   │              FastAPI Backend                 │    │
│  │ Qwen3-30B     │   │  api/main.py  :8000                          │    │
│  │ :1234/v1      │   │  ├── /api/auth/login  (JWT)                  │    │
│  └──────┬────────┘   │  ├── /api/agent/run   (WebSocket stream)    │    │
│         │            │  ├── /api/dashboard/*  (6 collectors)        │    │
│         │            │  ├── /api/memory/*     (MuninnDB)            │    │
│         ▼            │  ├── /api/ingest/*     (URL/PDF)              │    │
│  ┌──────────────┐    │  └── /ws/output        (WebSocket)           │    │
│  │  Agent Loop  │◀───┘                                               │    │
│  │ 4-type       │    ┌─────────────────────────────────────────────┐ │    │
│  │ routing +    │───▶│           MCP Server (FastMCP)               │ │    │
│  │ safety gates │    │  mcp_server/server.py — 55+ tools            │ │    │
│  └──────────────┘    │  ├── Swarm tools (15)                        │ │    │
│                      │  ├── Kafka tools (6)                         │ │    │
│  ┌───────────────┐   │  ├── Orchestration tools (6)                 │ │    │
│  │  React GUI    │   │  ├── Elasticsearch tools (7)                 │ │    │
│  │  9 tabs       │   │  ├── Docker Engine SSH tools (3)             │ │    │
│  │  Auth + WS    │   │  ├── Ingest tools (3)                        │ │    │
│  └───────────────┘   │  ├── Skill system tools (18+)                │ │    │
│                      │  └── storage_health()                        │ │    │
│  ┌───────────────┐   └─────────────────────────────────────────────┘ │    │
│  │  6 Collectors │   Background pollers → status snapshots → alerts  │    │
│  └───────────────┘                                                   │    │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  Storage Layer (auto-detect)                                      │   │
│  │  data/skills.db (SQLite WAL)  ──or──  PostgreSQL + Redis cache   │   │
│  └──────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## Quick Start

### Option A: Docker (recommended)

```bash
# First time: copy and edit the env file
cp docker/.env.example docker/.env
# Edit ADMIN_PASSWORD and LM_STUDIO_BASE_URL at minimum

# Start agent only (SQLite, no external DB)
docker compose -f docker/agent-compose.yml up -d

# Start with PostgreSQL + Redis
docker compose --profile postgres --profile redis -f docker/agent-compose.yml up -d

# View logs
docker compose -f docker/agent-compose.yml logs -f

# Open GUI
open http://localhost:8000
```

### Option B: Bare-metal (Windows)

#### Prerequisites
- Python 3.11+ (`python` command on PATH)
- Node.js 18+ (for GUI)
- Docker Desktop with WSL2 backend
- LM Studio running with Qwen3-Coder-30B-A3B loaded

```bash
# Install dependencies
pip install -r requirements.txt
cd gui && npm install && cd ..

# Start everything
start.bat

# Or separately:
python run_api.py       # API + agent backend :8000
cd gui && npm run dev   # React GUI :5173
```

### Deploy infrastructure (Swarm + Kafka)

```bash
docker swarm init
docker network create --driver overlay --attachable agent-net
docker stack deploy -c docker/swarm-stack.yml workload-stack
docker stack deploy -c docker/kafka-stack.yml kafka-stack
docker service ls   # all should show desired/desired
```

---

## Agent Routing

The agent classifies each task and routes it to one of 4 specialized agent types, each with its own tool allowlist and step limit:

| Agent Type | Purpose | Max Steps | Tool Access |
|------------|---------|-----------|-------------|
| **Observe** | Read-only status checks | 8 | `swarm_status`, `service_health`, `kafka_broker_status`, `elastic_cluster_health`, `agent_status`, etc. |
| **Investigate** | Deep research + log analysis | 12 | Observe tools + `elastic_search_logs`, `elastic_correlate_operation`, `ingest_url`, `ingest_pdf` |
| **Execute** | Destructive operations | 20 | Domain-filtered: kafka/swarm/proxmox/general subsets. Requires `plan_action()` approval for destructive tools. |
| **Build** | Skill management | 15 | `skill_create`, `skill_regenerate`, `skill_execute`, `validate_skill_live`, `discover_environment` |

Multi-step tasks are decomposed by the orchestrator (`api/agents/orchestrator.py`) into observe-then-execute sequences, with GO/ASK/HALT verdicts between steps.

---

## Safety Layer

### Gate Rules (`api/agents/gate_rules.py`)

Pre-flight checks return **GO**, **ASK**, or **HALT** before destructive operations:

- **Kafka rolling restart**: All brokers up? ISR >= RF-1?
- **Swarm service upgrade**: Quorum maintained? Majority managers up?
- **Changelog check**: Changelog ingested? Breaking changes present?

### Plan Lock (`api/lock.py`)

Global singleton — only ONE destructive plan at a time across all sessions. 10-minute stale timeout. Destructive tools are blocked until `plan_action()` is called and user approves via GUI.

### Destructive Tools Requiring Approval

`service_upgrade`, `service_rollback`, `node_drain`, `checkpoint_restore`, `kafka_rolling_restart_safe`, `docker_engine_update`, `skill_create`, `skill_regenerate`, `skill_disable`, `skill_enable`

### Vendor Switch Guard

`service_upgrade()` blocks vendor/image changes unless the task explicitly contains "switch image", "change vendor", or "migrate to".

### Pre/Post Upgrade Checks

**Pre-upgrade (6-step gate)**: Swarm nodes ready → Kafka ISR intact → Elastic errors=0 (30min) → Error rate anomaly (24h) → Memory context activation → Checkpoint save

**Post-upgrade (4-step verify)**: 20s settle → Replicas at desired count → No new Elastic errors (5min) → Log correlation → Store result as MuninnDB engram

---

## Background Collectors

6 collectors poll infrastructure and feed the dashboard:

| Collector | Component | What it polls |
|-----------|-----------|---------------|
| `swarm.py` | Docker Swarm | Nodes, services, replicas |
| `kafka.py` | Kafka | Broker status, topic replication |
| `elastic.py` | Elasticsearch | Cluster health, index stats |
| `proxmox_vms.py` | Proxmox | VMs and LXC containers across nodes |
| `docker_agent01.py` | Agent host | Container list on agent-01 |
| `external_services.py` | External | FortiGate, TrueNAS, etc. health checks |

Collectors run as asyncio background tasks. Each poll produces a status snapshot → stored in DB → triggers alerts on state transitions → evaluates memory hooks.

---

## GUI

9 tabs served by FastAPI at port 8000:

| Tab | Description |
|-----|-------------|
| **Dashboard** | 6 status cards (Nodes, Brokers, Services, Elastic, Muninn, Summary) |
| **Cluster** | NodeMap visual grid (3 managers + 3 workers) with Kafka broker placement |
| **Commands** | Agent prompt execution with tool/skill picker, live feedback |
| **Skills** | Skill browser with execution forms, promote/demote lifecycle |
| **Logs** | 5 sub-tabs: Live Logs, Tool Calls, Operations, Escalations, Stats |
| **Memory** | MuninnDB engram browser, patterns, doc fetching, engram activation |
| **Output** | Real-time agent execution feed (WebSocket) |
| **Tests** *(dropdown)* | Integration test runner with pass/fail |
| **Ingest** *(dropdown)* | Document ingestion with preview and breaking changes |

24 React components, 6 contexts. Supporting components include AlertToast, CardFilterBar, ChoiceBar, ClarificationWidget, LockBadge, PlanConfirmModal, ServiceCards, SparkLine, and more.

---

## Authentication

All `/api/*` endpoints (except `/api/health` and `/api/auth/login`) require a JWT Bearer token.

```bash
# Login
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"changeme"}'
# Returns: {"access_token": "...", "token_type": "bearer"}

# Use token
curl -H "Authorization: Bearer <token>" http://localhost:8000/api/agent/sessions/active
```

Default credentials: `admin` / `changeme` (set via `ADMIN_PASSWORD` env var).

WebSocket: `ws://localhost:8000/ws/output?token=<jwt>`

---

## MCP Tools Reference

### Docker Swarm Tools (15)

| Tool | Description |
|------|-------------|
| `swarm_status()` | Node health, manager/worker state |
| `service_list()` | All services, replicas, image versions |
| `service_health(name)` | Specific service ready/degraded/failed |
| `service_current_version(name)` | Currently running image tag |
| `service_resolve_image(image)` | Latest stable semver tag from Docker Hub |
| `service_version_history(image, count)` | Last N stable versions for downgrade |
| `service_upgrade(name, image)` | Rolling upgrade with health gate |
| `service_rollback(name)` | Revert service to previous image |
| `node_drain(node_id)` | Safe drain before maintenance (accepts hostname or hex ID) |
| `node_activate(node_id)` | Re-activate a drained node |
| `pre_upgrade_check()` | Full swarm readiness gate |
| `postgres_health()` | PostgreSQL connection, DB size, row counts |
| `service_logs(service_name)` | Fetch recent logs from a Swarm service |
| `docker_engine_version_tool()` | Docker Engine version on remote host |
| `docker_engine_check_update_tool()` | Check for available Docker update |

### Kafka Tools (6)

| Tool | Description |
|------|-------------|
| `kafka_broker_status()` | Broker health, leader election state |
| `kafka_consumer_lag(group)` | Lag per topic/partition |
| `kafka_topic_health(topic)` | Partition count, replication, ISR |
| `kafka_topic_list()` | All topics with partition/replication info |
| `kafka_rolling_restart_safe()` | ISR check before each broker restart |
| `pre_kafka_check()` | Full Kafka readiness gate |

### Orchestration Tools (6)

| Tool | Description |
|------|-------------|
| `agent_status()` | Agent health, version, WS clients, success rate |
| `checkpoint_save(label)` | Snapshot state before risky ops |
| `checkpoint_restore(label)` | Load saved state for rollback |
| `audit_log(action, result, target, details)` | Structured log to DB + JSONL |
| `escalate(reason)` | Flag high-risk decision, halt agent |
| `pre_upgrade_check_full(service)` | 6-step pre-flight gate |

### Elasticsearch Tools (7)

| Tool | Description |
|------|-------------|
| `elastic_cluster_health()` | Cluster status, nodes, shards |
| `elastic_search_logs(query, service, ...)` | Full-text log search |
| `elastic_error_logs(service, minutes_ago)` | Recent error/critical logs |
| `elastic_kafka_logs(broker_id, ...)` | Kafka broker log analysis |
| `elastic_log_pattern(service, hours)` | Error rate trend, anomaly flag |
| `elastic_index_stats()` | hp1-logs-* index stats |
| `elastic_correlate_operation(operation_id)` | Correlate op with log events |

### Docker Engine SSH Tools (3)

| Tool | Description |
|------|-------------|
| `docker_engine_version_tool()` | Docker Engine version on remote host |
| `docker_engine_check_update_tool()` | Check for available update |
| `docker_engine_update_tool(dry_run)` | Upgrade Docker Engine via apt-get |

### Ingest Tools (3)

| Tool | Description |
|------|-------------|
| `ingest_url(url, tags, label)` | Fetch URL → store in MuninnDB |
| `ingest_pdf(filename, tags)` | Ingest PDF from data/docs/ |
| `check_internet_connectivity()` | Check agent host internet access |

### Skill System Tools (18+)

| Tool | Description |
|------|-------------|
| `skill_search(query)` | Find skills by keyword |
| `skill_list(category)` | List all dynamic skills |
| `skill_info(name)` | Skill details, call count, errors |
| `skill_create(description, ...)` | Generate new tool via LLM |
| `skill_execute(name, params_json)` | Run a dynamic skill |
| `skill_disable(name)` / `skill_enable(name)` | Toggle skill availability |
| `skill_regenerate(name)` | Regenerate with current docs/versions |
| `skill_import()` / `skill_export_prompt(...)` | Sneakernet/airgapped workflow |
| `validate_skill_live(name)` | 3-layer AST + live + LLM validation |
| `discover_environment()` | Auto-fingerprint infrastructure services |
| `service_catalog_list()` / `service_catalog_update(...)` | Version tracking |
| `skill_compat_check(name)` / `skill_compat_check_all()` | Compatibility checks |
| `skill_health_summary()` | Full skill system health report |
| `knowledge_ingest_changelog(...)` | Parse changelogs for breaking changes |
| `skill_recommend_updates(service_id)` | Skills needing update |
| `storage_health()` | DB + cache backend status |

---

## MuninnDB (Cognitive Memory)

Optional cognitive memory layer for self-improvement. When running:

- **Pre-task**: Activate relevant engrams → inject into agent system prompt
- **Post-tool**: Store execution context (tool, params, result, duration)
- **On success**: Store outcome engram 2x (Hebbian reinforcement)
- **On failure**: Store once with `failure` tag
- **User feedback**: Thumbs-up → golden engram; thumbs-down → logged only
- **Repeated errors**: Fire critical alert via memory trigger

Modules: `api/memory/client.py` (REST client), `hooks.py` (tool call hooks), `feedback.py` (outcome storage), `triggers.py` (semantic evaluation), `ingest_worker.py` (document chunking).

---

## Supported Platforms

16 services are fingerprinted by the discovery pipeline (`mcp_server/tools/skills/fingerprints.py`). Status indicates current tool coverage:

| Service | Category | Status | Notes |
|---------|----------|--------|-------|
| Docker Swarm | Compute | 15 tools + collector | Most complete platform |
| Kafka | Monitoring | 6 tools + collector | Native kafka-python (not HTTP) |
| Elasticsearch | Monitoring | 7 tools + collector | Log search, correlation, anomaly detection |
| Proxmox VE | Compute | Skill + collector | `proxmox_vm_status` module |
| FortiGate | Networking | Skill + collector | `fortigate_system_status` module |
| TrueNAS SCALE | Storage | Collector only | Fingerprinted, no skill module yet |
| UniFi Controller | Networking | Fingerprinted | Port 8443 |
| OPNsense | Networking | Fingerprinted | Port 443 |
| Synology NAS | Storage | Fingerprinted | Port 5001 |
| Pi-hole | Networking | Fingerprinted | `/admin/api.php` |
| AdGuard Home | Networking | Fingerprinted | Port 3000 |
| Grafana | Monitoring | Fingerprinted | Port 3000 |
| Portainer | Compute | Fingerprinted | Port 9443 |
| Kibana | Monitoring | Fingerprinted | Port 5601 |
| NGINX | Networking | Fingerprinted | HTTP probe |
| Traefik | Networking | Fingerprinted | `/api/version` |
| FortiSwitch | Networking | Fingerprinted | Port 443 |

Additional services listed but not yet fingerprinted: NetBox, Wazuh, Security Onion, PBS, Technitium, Syncthing, Trilium, BookStack, Ansible, Terraform.

The `discover_environment()` tool scans hosts automatically and recommends `skill_create()` calls for uncovered services.

---

## Response Schema

Every tool returns a consistent structured dict:

```python
{
    "status":    "ok" | "degraded" | "failed" | "error" | "escalated",
    "data":      { ... },           # tool-specific payload
    "timestamp": "2026-03-05T...", # UTC ISO-8601
    "message":   "Human-readable summary"
}
```

`status == "degraded"` or `"failed"` triggers agent halt and escalation.

---

## Environment Variables

### Authentication
| Variable | Default | Description |
|----------|---------|-------------|
| `ADMIN_PASSWORD` | `changeme` | Admin login password |
| `ADMIN_USER` | `admin` | Admin username |
| `JWT_SECRET` | *(random)* | JWT signing secret |
| `JWT_EXPIRE_HOURS` | `24` | Token lifetime |

### LLM
| Variable | Default | Description |
|----------|---------|-------------|
| `LM_STUDIO_BASE_URL` | `http://localhost:1234/v1` | LM Studio OpenAI endpoint |
| `LM_STUDIO_MODEL` | `lmstudio-community/qwen3-coder-30b-a3b-instruct` | Model ID |
| `LM_STUDIO_API_KEY` | *(required)* | LM Studio API token |
| `ANTHROPIC_API_KEY` | *(optional)* | For cloud skill generation |

### Infrastructure
| Variable | Default | Description |
|----------|---------|-------------|
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092,...` | Kafka brokers |
| `ELASTIC_URL` | *(optional)* | Elasticsearch endpoint |
| `DOCKER_HOST` | platform default | Docker socket |

### Docker Engine SSH
| Variable | Default | Description |
|----------|---------|-------------|
| `DOCKER_ENGINE_HOST` | *(required)* | Remote host IP/hostname |
| `DOCKER_ENGINE_USER` | `root` | SSH user |
| `DOCKER_ENGINE_SSH_KEY` | `~/.ssh/id_rsa` | SSH private key path |
| `DOCKER_ENGINE_SSH_PORT` | `22` | SSH port |

### Storage
| Variable | Default | Description |
|----------|---------|-------------|
| `STORAGE_BACKEND` | *(auto)* | `sqlite` or `postgres` to override |
| `DATABASE_URL` | *(optional)* | Full PostgreSQL DSN |
| `POSTGRES_HOST` | *(optional)* | PostgreSQL host |
| `POSTGRES_PORT` | `5432` | PostgreSQL port |
| `POSTGRES_DB` | `hp1_agent` | Database name |
| `POSTGRES_USER` | `hp1` | Database user |
| `POSTGRES_PASSWORD` | *(required)* | Database password |
| `REDIS_URL` | *(optional)* | Redis connection URL |

### Memory
| Variable | Default | Description |
|----------|---------|-------------|
| `MUNINN_URL` | `http://muninndb:9475` | MuninnDB REST endpoint |
| `MUNINNDB_URL` | *(alias)* | Alternative env var name (both accepted) |

### Operations
| Variable | Default | Description |
|----------|---------|-------------|
| `AUDIT_LOG_PATH` | `./logs/audit.log` | JSONL audit log |
| `CHECKPOINT_PATH` | `./checkpoints` | State snapshots |
| `API_PORT` | `8000` | FastAPI listen port |
| `LOG_LEVEL` | `info` | Logging level |

---

## Project Structure

```
ai-local-agent-tools/
├── api/
│   ├── main.py                    # FastAPI app, CORS, health, static mount
│   ├── auth.py                    # JWT + bcrypt helpers
│   ├── lock.py                    # PlanLockManager (global destructive lock)
│   ├── logger.py                  # Batch-buffered async DB writes
│   ├── correlator.py              # PostgreSQL ops ↔ Elasticsearch log linking
│   ├── alerts.py                  # In-memory alert ring buffer (200 entries)
│   ├── elastic_alerter.py         # Log-derived alert rules
│   ├── session_store.py           # DB-backed WebSocket replay
│   ├── websocket.py               # JWT-authenticated WS, broadcast + replay
│   ├── tool_registry.py           # AST-based auto-discovery of MCP tools
│   ├── agents/
│   │   ├── router.py              # 4-agent routing + tool allowlists
│   │   ├── orchestrator.py        # Multi-step task decomposition
│   │   └── gate_rules.py          # GO/ASK/HALT pre-flight checks
│   ├── collectors/
│   │   ├── manager.py             # Auto-discovers and starts collectors
│   │   ├── base.py                # BaseCollector: poll → snapshot → alert
│   │   ├── swarm.py               # Docker Swarm poller
│   │   ├── kafka.py               # Kafka broker poller
│   │   ├── elastic.py             # Elasticsearch poller
│   │   ├── proxmox_vms.py         # Proxmox VM/LXC poller
│   │   ├── docker_agent01.py      # Agent host container poller
│   │   └── external_services.py   # FortiGate, TrueNAS, etc.
│   ├── memory/
│   │   ├── client.py              # MuninnDB REST client
│   │   ├── hooks.py               # Before/after tool call memory injection
│   │   ├── feedback.py            # Outcome engrams, Hebbian reinforcement
│   │   ├── triggers.py            # Semantic trigger evaluation
│   │   ├── ingest_worker.py       # Document chunking + ingestion
│   │   └── summarize.py           # Operation summarization
│   ├── db/
│   │   ├── base.py                # SQLAlchemy engine (asyncpg / aiosqlite)
│   │   ├── tables.py              # Schema definitions
│   │   ├── queries.py             # Query functions
│   │   └── migrate_sqlite.py      # Schema migrations
│   └── routers/
│       ├── agent.py               # /api/agent/* + plan_action intercept
│       ├── auth.py                # /api/auth/login, /me
│       ├── dashboard.py           # /api/dashboard/* (collector snapshots)
│       ├── settings.py            # /api/settings (DB-backed, 20 keys)
│       ├── skills.py              # /api/skills/* (execute, list)
│       ├── tools.py               # /api/tools/* (registry, invoke)
│       ├── lock.py                # /api/lock/status, force-release
│       ├── ingest.py              # /api/ingest/* with approval flow
│       └── ansible.py             # /api/ansible/* test reset
├── mcp_server/
│   ├── server.py                  # FastMCP server, 55+ tools registered
│   └── tools/
│       ├── swarm.py               # Docker Swarm tools (15)
│       ├── kafka.py               # Kafka tools (6)
│       ├── orchestration.py       # Checkpoint / audit / escalate (6)
│       ├── elastic.py             # Elasticsearch tools (7)
│       ├── docker_engine.py       # Docker Engine SSH tools (3)
│       ├── ingest.py              # Ingest MCP tools (3)
│       ├── skill_meta_tools.py    # Shim for tool_registry auto-discovery
│       └── skills/
│           ├── meta_tools.py      # Skill system tools (18+)
│           ├── loader.py          # Dynamic skill loader + hot-reload
│           ├── registry.py        # Thin delegation to storage backend
│           ├── validator.py       # AST validation (blocks dangerous imports)
│           ├── generator.py       # 3 backends: local LLM, cloud API, export
│           ├── spec_generator.py  # SKILL_SPEC before code (spec-first)
│           ├── live_validator.py   # Validate against real endpoints
│           ├── discovery.py       # 4-phase environment discovery pipeline
│           ├── fingerprints.py    # 16 known service fingerprints
│           ├── knowledge_base.py  # Compat checking, breaking changes
│           ├── doc_retrieval.py   # MuninnDB document retrieval
│           ├── prompt_builder.py  # LLM prompt construction
│           ├── promoter.py        # Lifecycle: promote/demote/scrap/purge
│           ├── storage/
│           │   ├── __init__.py    # Singleton get_backend() / get_cache()
│           │   ├── interface.py   # StorageBackend ABC
│           │   ├── auto_detect.py # PG probe → SQLite fallback
│           │   ├── sqlite_backend.py  # WAL, data/skills.db
│           │   ├── postgres_backend.py # psycopg2 pool, JSONB, FTS
│           │   └── cache.py       # RedisCache (optional)
│           └── modules/           # Generated skill .py files
│               ├── _template.py   # Contract: SKILL_META + execute()
│               ├── proxmox_vm_status.py
│               ├── fortigate_system_status.py
│               └── http_health_check.py
├── agent/                         # Agent loop utilities
├── gui/
│   └── src/
│       ├── App.jsx                # Tab router (9 tabs)
│       ├── api.js                 # API client with JWT
│       ├── components/            # 24 React components
│       │   ├── ServiceCards.jsx   # Dashboard status cards
│       │   ├── OutputPanel.jsx    # Real-time agent feed
│       │   ├── LogsPanel.jsx      # 5 sub-tab log viewer
│       │   ├── OptionsModal.jsx   # Settings editor
│       │   ├── DocsTab.jsx        # Document coverage viewer
│       │   └── ...
│       └── context/               # 6 React contexts
│           ├── AuthContext.jsx    # JWT state management
│           ├── OptionsContext.jsx # Settings sync
│           └── AgentOutputContext.jsx  # WebSocket state
├── docker/
│   ├── Dockerfile                 # Multi-stage build (Node → Python → slim)
│   ├── agent-compose.yml          # Single-node + optional PG/Redis profiles
│   ├── swarm-stack.yml            # Swarm HA deployment
│   ├── kafka-stack.yml            # 3-broker KRaft Kafka cluster
│   ├── deploy.sh                  # Auto-detect GID + deploy script
│   ├── entrypoint.sh              # Container init, LM Studio probe
│   ├── healthcheck.sh             # /api/health probe
│   └── .env.example               # Full env var template
├── tests/                         # 17 test files, 174+ tests
├── data/
│   ├── skills.db                  # Skill system SQLite DB (auto-created)
│   ├── hp1_agent.db               # Main app SQLite DB (auto-created)
│   ├── docs/                      # Ingested documents
│   ├── skill_imports/             # Drop .py skills here for sneakernet import
│   └── skill_exports/             # Airgapped skill generation prompts
├── logs/                          # audit.log JSONL
├── state/                         # HANDOFF.md, plans, audit
├── requirements.txt               # 23 Python dependencies
└── run_api.py                     # Start FastAPI server
```

---

## Database Schema

### API Database (SQLAlchemy — asyncpg / aiosqlite)

| Table | Purpose |
|-------|---------|
| `schema_versions` | Migration tracking |
| `operations` | Agent sessions (session_id, label, status, duration, final_answer) |
| `tool_calls` | Per-tool execution log (operation FK, params, result, duration, model) |
| `status_snapshots` | Collector poll results |
| `escalations` | Escalation events |
| `audit_log` | Structured event log |
| `operation_log` | WebSocket line store for session replay |

### Skills Database (psycopg2 / sqlite3 via auto_detect.py)

| Table | Purpose |
|-------|---------|
| `skills` | Metadata, metrics, lifecycle state |
| `service_catalog` | Detected versions, docs ingested flags |
| `breaking_changes` | Version-specific breaking changes |
| `skill_compat_log` | Compatibility check history |
| `skill_audit_log` | Skill system audit trail |
| `checkpoints` | Pre-operation state snapshots |
| `settings` | DB-backed settings (20 keys) |

---

## Security

- No credentials hardcoded — all via environment variables
- JWT authentication on all API endpoints
- Every tool call auto-logged to structured audit trail (DB + JSONL)
- Global destructive lock — one pending plan_action at a time across all sessions
- Agent halts immediately on any `degraded` or `failed` status
- Checkpoint saved before every risky operation
- `escalate()` creates a permanent audit record and stops the agent
- Destructive tools require `plan_action()` approval
- Vendor switch guard blocks accidental image changes
- Skill validator blocks dangerous imports (subprocess, os.system, eval, exec)

---

## Phase History

| Version | Features |
|---------|----------|
| v1.0 | MCP server, Swarm + Kafka tools, agent loop |
| v1.1–1.2 | FastAPI backend, React GUI, SQLite |
| v1.3 | SQLAlchemy dual backend, migrations, async logger |
| v1.4 | Background collectors, alert system, status snapshots |
| v1.5 | MuninnDB cognitive memory |
| v1.6 | Elasticsearch/Filebeat pipeline |
| v1.7 | 3-agent routing, plan guards, integration tests, feedback loop |
| v1.8 | Auth + JWT, session replay, global lock, Docker Engine SSH, Ansible/Proxmox, URL/PDF ingestion |
| v1.9 | Docker containerization, auto-detecting storage (SQLite → PG + Redis), skill system v3 |
| v1.10 | 4-agent routing, gate rules, vendor switch guard, 6 collectors, 9 GUI tabs, spec-first skill generation, live validation, 16 service fingerprints, operation completion fixes |

---

## License

This project is licensed under the [MIT License](LICENSE).
