# HP1-AI-Agent-v1

Local AI Infrastructure Orchestration Agent — a Python MCP server + FastAPI backend + React GUI that enables a local LLM (Qwen3-Coder-30B) to autonomously manage, inspect, upgrade, and orchestrate a Docker Swarm + Kafka cluster with enforced checks and balances at every step.

**Current version: v1.9.0**

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          HP1-AI-Agent-v1                                 │
│                                                                          │
│  ┌───────────────┐   ┌─────────────────────────────────────────────┐    │
│  │  LM Studio    │   │              FastAPI Backend                 │    │
│  │ Qwen3-30B     │   │  api/main.py  :8000                          │    │
│  │ :1234/v1      │   │  ├── /api/auth/login  (JWT)                  │    │
│  └──────┬────────┘   │  ├── /api/agent/run   (SSE stream)          │    │
│         │            │  ├── /api/memory/*    (MuninnDB)             │    │
│         │            │  ├── /api/ingest/*    (URL/PDF)              │    │
│         ▼            │  └── /ws/output       (WebSocket)            │    │
│  ┌──────────────┐    └──────────────┬──────────────────────────────┘    │
│  │  Agent Loop  │◀──────────────────┘                                   │
│  │ agent_loop.py│    ┌─────────────────────────────────────────────┐    │
│  │ 3-agent      │───▶│           MCP Server (FastMCP)               │    │
│  │ routing      │    │  mcp_server/server.py                        │    │
│  └──────────────┘    │  ├── Swarm tools (9)                         │    │
│                      │  ├── Kafka tools (5)                         │    │
│  ┌───────────────┐   │  ├── Orchestration tools (6)                 │    │
│  │  React GUI    │   │  ├── Elasticsearch tools (7)                 │    │
│  │  :5173        │   │  ├── Docker Engine SSH tools (3)             │    │
│  │  Auth + WS    │   │  ├── Ingest tools (3)                        │    │
│  └───────────────┘   │  ├── Skill system tools (18)                 │    │
│                      │  └── storage_health()                        │    │
│                      └─────────────────────────────────────────────┘    │
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

### Docker Swarm Tools (9)

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
| `node_drain(node_id)` | Safe drain before maintenance |
| `pre_upgrade_check()` | Full swarm readiness gate |

### Kafka Tools (5)

| Tool | Description |
|------|-------------|
| `kafka_broker_status()` | Broker health, leader election state |
| `kafka_consumer_lag(group)` | Lag per topic/partition |
| `kafka_topic_health(topic)` | Partition count, replication, ISR |
| `kafka_rolling_restart_safe()` | ISR check before each broker restart |
| `pre_kafka_check()` | Full Kafka readiness gate |

### Orchestration Tools (6)

| Tool | Description |
|------|-------------|
| `checkpoint_save(label)` | Snapshot state → DB + file |
| `checkpoint_restore(label)` | Load saved state for rollback |
| `audit_log(action, result)` | Structured log → DB + JSONL file |
| `escalate(reason)` | Flag high-risk decision, halt agent |
| `pre_upgrade_check_full(service)` | 6-step pre-flight gate |
| `post_upgrade_verify(service)` | Post-upgrade health + memory engram |

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
| `skill_create(description, ...)` | Generate new tool via LLM |
| `skill_execute(name, **kwargs)` | Run a dynamic skill |
| `validate_skill_live(name)` | 3-layer AST + live + LLM validation |
| `discover_environment(hosts)` | Auto-fingerprint infrastructure services |
| `skill_health_summary()` | Full skill system health report |
| `storage_health()` | DB + cache backend status |
| ... | See `mcp_server/server.py` for full list |

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
HP1-AI-Agent-v1/
├── api/
│   ├── main.py                    # FastAPI app, v1.9.0
│   ├── auth.py                    # JWT + bcrypt helpers
│   ├── lock.py                    # PlanLockManager (global destructive lock)
│   ├── session_store.py           # DB-backed WS replay
│   ├── agents/
│   │   └── router.py              # 3-agent routing + tool filter
│   ├── memory/
│   │   └── ingest_worker.py       # URL fetch, PDF parse, chunking
│   └── routers/
│       ├── agent.py               # /api/agent/* + plan_action intercept
│       ├── auth.py                # /api/auth/login, /me
│       ├── lock.py                # /api/lock/status, force-release
│       ├── ingest.py              # /api/ingest/* with approval flow
│       └── ansible.py             # /api/ansible/* test reset
├── mcp_server/
│   ├── server.py                  # FastMCP server, 50+ tools registered
│   └── tools/
│       ├── swarm.py               # Docker Swarm tools (9)
│       ├── kafka.py               # Kafka tools (5)
│       ├── orchestration.py       # Checkpoint / audit / escalate (6)
│       ├── elastic.py             # Elasticsearch tools (7)
│       ├── docker_engine.py       # Docker Engine SSH tools (3)
│       ├── ingest.py              # Ingest MCP tools (3)
│       └── skills/
│           ├── meta_tools.py      # Skill system tools (18+)
│           ├── loader.py          # Dynamic skill loader
│           ├── registry.py        # Thin delegation to storage backend
│           ├── storage/
│           │   ├── __init__.py    # Singleton get_backend() / get_cache()
│           │   ├── interface.py   # StorageBackend ABC
│           │   ├── auto_detect.py # PG probe → SQLite fallback
│           │   ├── sqlite_backend.py  # WAL, data/skills.db
│           │   ├── postgres_backend.py # psycopg2 pool, JSONB, FTS
│           │   └── cache.py       # RedisCache (optional)
│           └── modules/           # Generated skill .py files (gitignored)
├── gui/
│   └── src/
│       ├── components/            # React components
│       │   ├── LoginScreen.jsx
│       │   ├── OutputPanel.jsx
│       │   ├── LogTable.jsx
│       │   ├── LockBadge.jsx
│       │   └── IngestPanel.jsx
│       └── context/
│           └── AuthContext.jsx    # JWT state management
├── docker/
│   ├── Dockerfile                 # Multi-stage build, non-root agent user
│   ├── agent-compose.yml          # Single-node deployment + optional PG/Redis
│   ├── agent-swarm.yml            # Swarm HA deployment
│   ├── deploy.sh                  # Auto-detect GID + deploy script
│   ├── entrypoint.sh              # Container init, LM Studio URL probe
│   ├── healthcheck.sh             # /api/health probe
│   ├── .env.example               # Full env var template
│   ├── swarm-stack.yml            # Workload service (nginx)
│   └── kafka-stack.yml            # 3-broker KRaft Kafka cluster
├── tests/
│   ├── test_tools.py              # Unit tests
│   ├── test_e2e.py                # E2E integration tests
│   └── ansible/                   # Test reset playbooks
├── data/
│   ├── skills.db                  # Skill system SQLite DB (auto-created)
│   ├── hp1_agent.db               # Main app SQLite DB (auto-created)
│   ├── docs/                      # Ingested documents
│   │   └── manifest.json          # Content hash tracking
│   ├── skill_imports/             # Drop .py skills here for sneakernet import
│   └── skill_exports/             # Airgapped skill generation prompts
├── logs/                          # audit.log written here
├── checkpoints/                   # JSON state snapshots
├── run_api.py                     # Start FastAPI server
├── start.bat                      # Start API + GUI (Windows)
└── requirements.txt
```

---

## Security

- No credentials hardcoded — all via environment variables
- JWT authentication on all API endpoints
- Every tool call auto-logged to structured audit trail (DB + JSONL)
- Global destructive lock — one pending plan_action at a time across all sessions
- Agent halts immediately on any `degraded` or `failed` status
- Checkpoint saved before every risky operation
- `escalate()` creates a permanent audit record and stops the agent
- Docker Engine destructive tools require `plan_action()` approval

---

## Phase History

| Version | Features |
|---------|----------|
| v1.0 | MCP server, Swarm+Kafka tools, agent loop |
| v1.1–1.2 | FastAPI backend, React GUI, SQLite |
| v1.3 | SQLAlchemy dual backend, migrations, async logger |
| v1.4 | Background collectors, alert system, status snapshots |
| v1.5 | MuninnDB cognitive memory |
| v1.6 | Elasticsearch/Filebeat pipeline |
| v1.7 | 3-agent routing, plan guards, integration tests, feedback loop |
| v1.8 | Auth+JWT, session replay, global lock, Docker Engine SSH, Ansible/Proxmox, URL/PDF ingestion |
| v1.9 | Docker containerization, auto-detecting storage layer (SQLite→PG+Redis), skill system v3 |
