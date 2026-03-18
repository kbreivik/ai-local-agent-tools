# Operations Runbook

---

## Starting the Stack

### Docker (recommended)

```bash
# First time: configure environment
cp docker/.env.example docker/.env
# Edit: ADMIN_PASSWORD, LM_STUDIO_BASE_URL, ANTHROPIC_API_KEY (optional)

# Start agent (SQLite, no external deps)
docker compose -f docker/agent-compose.yml up -d

# Start with PostgreSQL
docker compose --profile postgres -f docker/agent-compose.yml up -d

# Start with PostgreSQL + Redis cache
docker compose --profile postgres --profile redis -f docker/agent-compose.yml up -d

# Follow logs
docker compose -f docker/agent-compose.yml logs -f agent

# Open GUI
open http://localhost:8000
```

### Bare-metal (Windows)

```bash
pip install -r requirements.txt
cd gui && npm install && cd ..

# Start API + GUI together
start.bat

# Or separately
python run_api.py        # API :8000
cd gui && npm run dev    # GUI :5173
```

### Infrastructure (Swarm + Kafka)

```bash
# Init swarm (first time only)
docker swarm init
docker network create --driver overlay --attachable agent-net

# Deploy workload service
docker stack deploy -c docker/swarm-stack.yml workload-stack

# Deploy Kafka cluster (KRaft, 3 brokers)
docker stack deploy -c docker/kafka-stack.yml kafka-stack

# Wait ~30s for KRaft quorum, then verify
docker service ls
# Expected: all REPLICAS columns show desired/desired
```

---

## Authentication

```bash
# Login (returns JWT)
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"changeme"}'

# Store token
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"changeme"}' | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Use token
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/agent/sessions/active
```

Default credentials: `admin` / `changeme` — change via `ADMIN_PASSWORD` env var.

---

## Running the Agent

Submit tasks via the GUI at `http://localhost:8000` (login required), or via API:

```bash
curl -X POST http://localhost:8000/api/agent/run \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"task": "Check swarm health and Kafka consumer lag for group my-consumers"}'
```

### Plan Approval Flow

Destructive operations (upgrade, rollback, drain, Docker Engine update) trigger a plan approval step. The agent pauses and displays a plan in the GUI. You must check the confirmation box and click **Approve** to proceed, or **Cancel** to abort.

The global lock prevents other sessions from running destructive ops while a plan is pending.

---

## Storage Backend

### Check current backend

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/health
# Returns deploy_mode and storage info

# Via MCP tool
python -c "
from mcp_server.tools.skills.storage import get_backend, get_cache
db = get_backend()
print(db.health_check())
"
```

### Force SQLite (override auto-detect)

```bash
STORAGE_BACKEND=sqlite python run_api.py
# Or in docker/.env: STORAGE_BACKEND=sqlite
```

### Connect to PostgreSQL

```bash
# Option 1: full DSN
DATABASE_URL=postgresql://hp1:secret@localhost:5432/hp1_agent python run_api.py

# Option 2: individual vars
POSTGRES_HOST=localhost POSTGRES_USER=hp1 POSTGRES_PASSWORD=secret python run_api.py

# Option 3: Docker Compose profile (auto-detected by DNS)
docker compose --profile postgres -f docker/agent-compose.yml up -d
```

### Redis cache

```bash
REDIS_URL=redis://localhost:6379/0 python run_api.py
# Or via Docker profile:
docker compose --profile redis -f docker/agent-compose.yml up -d
```

---

## Skill System

### Discover services in your environment

```python
from mcp_server.tools.skills.meta_tools import discover_environment
result = discover_environment([
    {"address": "192.168.1.100"},
    {"address": "192.168.1.101", "port": 8006},  # Proxmox
])
print(result)
```

### Create a new skill

```bash
# Via GUI: use the agent with a task like:
# "Create a skill to check TrueNAS pool health at 192.168.1.50"

# Direct API:
python -c "
from mcp_server.tools.skills.meta_tools import skill_create
result = skill_create(None, 'Check TrueNAS pool health and capacity', api_base='http://192.168.1.50/api/v2.0', auth_type='bearer')
print(result)
"
```

### Import skills (sneakernet / airgapped)

```bash
# Drop .py skill files into data/skill_imports/
cp my_skill.py data/skill_imports/

# Then call skill_import() via agent or directly:
python -c "
from mcp_server.tools.skills.meta_tools import skill_import
print(skill_import(None))
"
```

### Check skill health

```python
from mcp_server.tools.skills.meta_tools import skill_health_summary
print(skill_health_summary())
```

---

## URL / PDF Ingestion

### Ingest a URL

Via the GUI: open the **Ingest** panel, enter a URL, preview the content, then approve storage.

Via agent: "Fetch and store the Proxmox API docs from https://..."

### Ingest a PDF

```bash
# Copy PDF to data/docs/
cp my-runbook.pdf data/docs/

# Then via agent: "Ingest the PDF my-runbook.pdf"
# Or directly:
python -c "
from mcp_server.tools.ingest import ingest_pdf
print(ingest_pdf('my-runbook.pdf', tags=['runbook']))
"
```

---

## Stopping the Stack

```bash
# Docker Compose
docker compose -f docker/agent-compose.yml down

# Remove volumes (destroys all data)
docker compose -f docker/agent-compose.yml down -v

# Swarm services (preserves volumes)
docker stack rm workload-stack kafka-stack

# Leave swarm (resets everything)
docker swarm leave --force
```

---

## Troubleshooting

### Agent halts with "Kafka not ready"

```
HALT: Kafka not healthy
```

**Diagnosis:**
```bash
python -c "
from mcp_server.tools.kafka import kafka_broker_status
import json
print(json.dumps(kafka_broker_status(), indent=2))
"

# From inside a kafka container
KAFKA_CID=$(docker ps --filter "name=kafka-stack_kafka1" --format "{{.ID}}" | head -1)
docker exec "$KAFKA_CID" /opt/kafka/bin/kafka-topics.sh \
  --bootstrap-server kafka1:9092 --describe
```

**Fix — delete stale test topic:**
```bash
docker exec "$KAFKA_CID" /opt/kafka/bin/kafka-topics.sh \
  --bootstrap-server kafka1:9092 --delete --topic e2e-load-test
```

---

### Storage backend falls back to SQLite unexpectedly

```bash
# Check what auto_detect found
python -c "
import logging; logging.basicConfig(level=logging.DEBUG)
from mcp_server.tools.skills.storage.auto_detect import detect_backend
detect_backend()
"
```

Common causes:
| Symptom | Fix |
|---------|-----|
| `psycopg2 not installed` | `pip install psycopg2-binary` |
| `PostgreSQL connection failed` | Check `POSTGRES_HOST`, credentials, firewall |
| Port 5432 not reachable | Start postgres profile: `--profile postgres` |
| Wrong database name | Set `POSTGRES_DB=hp1_agent` |

---

### Login fails / JWT errors

```bash
# Check password
curl -X POST http://localhost:8000/api/auth/login \
  -d '{"username":"admin","password":"changeme"}'

# If container: check ADMIN_PASSWORD env var
docker inspect hp1-agent | grep -i ADMIN_PASSWORD

# Force new JWT secret (invalidates all existing tokens)
JWT_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")
```

---

### LM Studio not reachable from container

```bash
# Docker Desktop: use host.docker.internal
LM_STUDIO_BASE_URL=http://host.docker.internal:1234/v1

# Linux Docker: use bridge gateway
LM_STUDIO_BASE_URL=http://172.17.0.1:1234/v1

# Check from container
docker exec hp1-agent curl -s http://host.docker.internal:1234/v1/models
```

The `entrypoint.sh` auto-probes these URLs on startup if `LM_STUDIO_BASE_URL` is not set.

---

### Docker Engine SSH tool fails

```bash
# Test SSH connectivity manually
ssh -i ~/.ssh/id_rsa -p 22 root@<DOCKER_ENGINE_HOST> "docker version"

# Check settings
cat data/agent_settings.json | python -m json.tool

# Required env vars
DOCKER_ENGINE_HOST=192.168.1.10
DOCKER_ENGINE_USER=root
DOCKER_ENGINE_SSH_KEY=/home/agent/.ssh/id_rsa
```

---

### Kafka services show 0/1 replicas

```bash
docker service ps kafka-stack_kafka1 --no-trunc | head -5
```

| Error | Fix |
|-------|-----|
| `No such image` | `docker pull apache/kafka:3.7.1` |
| `port already allocated` | Another process on 9092-9094 |
| Container exits immediately | `docker service logs kafka-stack_kafka1` |
| Stale KRaft data | Remove volumes, redeploy |

---

### service_rollback fails

Docker Swarm requires a previous spec for rollback. If the service has only one version:

```bash
docker service update --image nginx:1.25-alpine workload-stack_workload
```

---

## Restoring from Checkpoint

Checkpoints are stored in both the database and `checkpoints/`. They do not auto-apply — the agent reads them and decides what to restore.

```python
from mcp_server.tools.orchestration import checkpoint_restore
from mcp_server.tools.swarm import service_upgrade

# Load checkpoint
cp = checkpoint_restore("before_upgrade")
snapshot = cp["data"]["snapshot"]

# Restore each service to its snapshotted image
for svc in snapshot["services"]["data"]["services"]:
    result = service_upgrade(svc["name"], svc["image"].split("@")[0])
    print(result["message"])
```

---

## Tests

```bash
# Unit tests (no Docker/Kafka needed)
python -m pytest tests/test_tools.py -v

# Full E2E (requires live Docker + Kafka)
python -m pytest tests/test_e2e.py -v

# All tests
python -m pytest tests/ -v --tb=short

# With Ansible test reset (resets infra between test suites)
python -m pytest tests/test_e2e.py --ansible-reset-suite -v
```

---

## Viewing Logs and Audit Trail

### Audit log (JSONL file)

```bash
# Last 20 entries
python -c "
import json
with open('logs/audit.log') as f:
    for line in list(f)[-20:]:
        print(json.dumps(json.loads(line), indent=2))
        print('---')
"

# Filter escalations
python -c "
import json
with open('logs/audit.log') as f:
    for line in f:
        e = json.loads(line)
        if 'ESCALAT' in e.get('action',''):
            print(json.dumps(e, indent=2))
"
```

### Audit log (database)

```python
from mcp_server.tools.skills.storage import get_backend
db = get_backend()
rows = db.query_audit(limit=50)
for row in rows:
    print(row)
```

### Storage health

```python
from mcp_server.server import storage_health
print(storage_health())
# {"status":"ok","data":{"database":{"ok":true,"backend":"sqlite",...},"cache":{...}}}
```

---

## File Locations

| Path | Purpose |
|------|---------|
| `data/skills.db` | Skill system DB (skills, catalog, audit, checkpoints) |
| `data/hp1_agent.db` | Main app DB (sessions, operations, memory) |
| `data/agent_settings.json` | Agent settings (Docker Engine SSH config, etc.) |
| `data/docs/` | Ingested documents |
| `data/docs/manifest.json` | Content hash tracking for change detection |
| `data/skill_imports/` | Drop .py skill files here for sneakernet import |
| `data/skill_exports/` | Airgapped skill generation prompts |
| `logs/audit.log` | Every agent decision and tool call, JSONL |
| `checkpoints/` | JSON state snapshots, `label_timestamp.json` |
| `docker/.env` | Local environment overrides (gitignored) |
| `docker/.env.example` | Full env var template |
