# Docker Deployment Reference

> Scout-loaded only. Covers operational patterns, volume layout, env vars, and
> known caveats for the HP1-AI-Agent container.

---

## Architecture

### agent-01 (192.168.199.10) — management VM, NEVER in swarm
```
hp1-prod-agent-01 (192.168.199.10)
├── hp1_agent container        — FastAPI + MCP + GUI + MCP server on :8000
├── muninndb container         — Agent memory (MuninnDB) on :9475
├── hp1_postgres container     — PostgreSQL on :5432 (agent primary DB)
└── [other management containers as needed]
```

This VM is **protected** — `prevent_destroy = true` in Terraform, blocked in hooks.
PostgreSQL lives here permanently. SQLite is also here (fallback if PG unavailable).
Neither database ever touches the Swarm cluster.

### Swarm cluster — service test cluster only
```
Managers: 199.21 / 199.22 / 199.23
Workers:  199.31 / 199.32 / 199.33

Services deployed for testing:
- Kafka cluster (multi-broker)
- Elasticsearch
- Logstash
- Filebeat
- Any other service being tested/upgraded
```

The agent on agent-01 **manages** the swarm cluster (via Docker socket) but does **not run in it**.
Swarm VMs can be destroyed and recreated — that is their purpose.

Deploy mode: **standalone** on agent-01.

---

## Volume layout

| Volume name | Mount | Contents |
|-------------|-------|---------|
| `hp1-agent-data` | `/app/data` | SQLite DB, settings, ingested docs, skill exports/imports |
| `hp1-agent-logs` | `/app/logs` | Audit log JSONL, application logs |
| `hp1-agent-checkpoints` | `/app/checkpoints` | Agent state snapshots |
| `hp1-agent-skills` | `/app/mcp_server/tools/skills/modules` | Dynamic skill .py files |

**Volumes survive `docker compose down`** — never use `docker compose down -v` unless intentionally wiping state.

---

## Environment variables (full reference)

### Required
| Var | Default | Notes |
|-----|---------|-------|
| `ADMIN_PASSWORD` | `changeme` | GUI login — MUST be changed |
| `DOCKER_GID` | `998` | Match host: `stat -c '%g' /var/run/docker.sock` |

### LLM connection
| Var | Notes |
|-----|-------|
| `LM_STUDIO_BASE_URL` | Docker Desktop: `http://host.docker.internal:1234/v1`; Linux: `http://172.17.0.1:1234/v1` |
| `LM_STUDIO_API_KEY` | Optional, LM Studio usually unauthenticated |
| `ANTHROPIC_API_KEY` | For cloud skill generation backend |
| `SKILL_GEN_BACKEND` | `local` / `cloud` / `export` |

### Infrastructure connections
| Var | Notes |
|-----|-------|
| `KAFKA_BOOTSTRAP_SERVERS` | e.g. `kafka1:9092,kafka2:9092` — empty = Kafka tools return unavailable |
| `ELASTIC_URL` | e.g. `http://elastic-01:9200` — empty = Elastic tools return unavailable |
| `ELASTIC_FILEBEAT_STALE_MINUTES` | **Default: 10** — Filebeat alert fires if no logs in this many minutes. Increase to reduce alert flood. |
| `MUNINNDB_URL` | `http://muninndb:9475` — MuninnDB memory service |
| `DOCKER_ENGINE_HOST` | Remote host for SSH-based Docker management tools |
| `DOCKER_ENGINE_USER` | Default: `root` |
| `DOCKER_ENGINE_SSH_KEY` | Default: `/home/agent/.ssh/id_rsa` |

### Proxmox / FortiGate (for skills)
| Var | Notes |
|-----|-------|
| `PROXMOX_HOST` | Proxmox API hostname/IP (e.g. `pmox1.kbitsec.no` or `192.168.1.5`) |
| `PROXMOX_USER` | Default: `root@pam` |
| `PROXMOX_TOKEN_ID` | e.g. `terraform@pve!terraform-token` |
| `PROXMOX_TOKEN_SECRET` | Token secret UUID |
| `FORTIGATE_HOST` | FortiGate hostname/IP |
| `FORTIGATE_API_KEY` | FortiGate REST API key |

### Tuning
| Var | Notes |
|-----|-------|
| `API_WORKERS` | Default: `1` — keep at 1 with SQLite (concurrent writes corrupt DB) |
| `LOG_LEVEL` | `debug` / `info` / `warning` / `error` |

---

## Filebeat stale alert — fix

The memory flood of "Filebeat stale: last log Xmin ago" is caused by `ELASTIC_FILEBEAT_STALE_MINUTES=10` (default).
Filebeat on the worker nodes is not shipping logs to Elasticsearch within 10 minutes.

**Quick mitigation** — raise the threshold in `docker/.env`:
```bash
ELASTIC_FILEBEAT_STALE_MINUTES=60
```
Then redeploy. This reduces alert noise while the root cause is investigated.

**Root cause investigation**:
1. Check Filebeat container on workers: `docker service logs hp1_filebeat 2>/dev/null`
2. Check if Elasticsearch is reachable from workers: `elastic_cluster_health` tool
3. Check `elastic_kafka_logs` — are Kafka logs reaching Elastic at all?
4. Filebeat config: `output.elasticsearch.hosts` must point to `192.168.199.40:9200`

---

## Build

```bash
# Standard build — match docker group GID
docker build \
  --build-arg DOCKER_GID=$(stat -c '%g' /var/run/docker.sock) \
  -t hp1-ai-agent:latest \
  -f docker/Dockerfile .

# Or use deploy.sh (auto-detects everything)
cd docker && ./deploy.sh
```

### Multi-stage stages
1. **gui-builder** (Node 20): `npm ci && npm run build` → `gui/dist/`
2. **builder** (Python 3.13): builds wheels from `requirements.txt`
3. **runtime** (Python 3.13-slim): copies wheels + gui/dist + app code, non-root `agent` user

`gui/dist/` is built INSIDE Docker — it's gitignored, never in the repo.

---

## Deploy patterns

### Standalone (current production setup)
```bash
cd docker
set -a; source .env; set +a
docker compose -f docker-compose.yml up -d
```

### Auto-detect (deploy.sh)
```bash
cd docker && ./deploy.sh
# Detects: Docker Desktop → compose, Swarm active → stack deploy
```

### Swarm (upgrade testing only — NOT for the agent itself)
```bash
cd docker
set -a; source .env; set +a   # REQUIRED — docker stack doesn't read .env
docker stack deploy -c swarm-stack.yml hp1
```

---

## SQLite-in-Swarm caveat ⚠️

The agent **does not run in swarm** — it runs standalone on agent-01.
SQLite and PostgreSQL both live on agent-01, not in the swarm cluster.
The concurrent-write issue does not apply to this architecture.

`API_WORKERS=1` is still required (uvicorn single worker with SQLite).

If you ever need to move the agent into Swarm (not recommended):
- Switch `DATABASE_URL` to PostgreSQL first
- Set `replicas: 1` (SQLite cannot handle concurrent writes from multiple replicas)
- Move PostgreSQL to its own VM before doing so

---

## Port mapping

| Port | Service | Notes |
|------|---------|-------|
| `8000` | FastAPI (API + GUI) | GUI served by FastAPI StaticFiles, not Vite |
| `5173` | Vite dev server | DEV ONLY — never expose in swarm-stack.yml |

Port 5173 was removed from production swarm-stack.yml. If it appears there, remove it.

---

## SSH key access

For `docker_engine_*` tools and generated skills that SSH to remote hosts:
```bash
# Mount SSH keys directory
SSH_KEY_DIR=~/.ssh docker compose up -d
# Keys available at /home/agent/.ssh inside container
```

The ansible2 SSH key (`~/.ssh/id_ed25519`) is what skills use to reach VLAN 199 VMs.

---

## Health check commands

```bash
# API health
curl -s http://192.168.199.10:8000/api/health | python3 -m json.tool

# Skills health
curl -s http://192.168.199.10:8000/api/skills/health

# Container health status
docker ps --filter "name=hp1" --format "table {{.Names}}\t{{.Status}}"

# Logs
docker logs hp1-agent --tail 50
# or Swarm:
docker service logs hp1_agent --tail 50
```

---

## Rebuild after code change

```bash
# Stop, rebuild, restart — volumes preserved
cd docker
docker compose down
docker compose build --build-arg DOCKER_GID=$(stat -c '%g' /var/run/docker.sock)
docker compose up -d
# Verify
curl -s http://localhost:8000/api/health
```

Dynamic skills survive rebuild because they're on `hp1-agent-skills` volume.
SQLite DB survives because it's on `hp1-agent-data` volume.

---

## .dockerignore (keep updated)

Key exclusions — `docker/.env` and `data/` must never be in the image:
```
.git / __pycache__ / *.pyc / node_modules / .venv
docker/.env / .env / *.bak
data/skills.db / data/skill_exports/* / data/skill_imports/*
logs/* / checkpoints/*
```
