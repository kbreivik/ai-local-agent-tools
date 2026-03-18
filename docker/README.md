# HP1-AI-Agent — Docker Deployment

## Quick Start

```bash
cd docker
chmod +x deploy.sh
./deploy.sh
```

The script auto-detects your environment:
- Docker Desktop (Win/Mac) → Docker Compose
- Docker Engine on Linux → Docker Compose
- Docker Swarm active → Swarm Stack (rolling updates, restart policy)

On first run it creates `docker/.env` from the template and exits — edit that file (set `ADMIN_PASSWORD` at minimum), then run `./deploy.sh` again.

---

## Manual Deployment

### Docker Compose (single node)

```bash
cp docker/.env.example docker/.env
# Edit .env — set ADMIN_PASSWORD, LM_STUDIO_BASE_URL
docker compose -f docker/agent-compose.yml up -d
docker compose -f docker/agent-compose.yml logs -f
```

### Docker Swarm (HA / multi-node)

```bash
# Initialize Swarm (skip if already active)
docker swarm init

# Create overlay network (shared with Kafka/observability stacks)
docker network create --driver overlay --attachable agent-net

# Build image first
docker build -t hp1-ai-agent:latest -f docker/Dockerfile .

# Deploy stack
docker stack deploy -c docker/agent-swarm.yml hp1

# Watch it come up
docker service ps hp1_agent
docker service logs hp1_agent -f
```

---

## Connecting to LM Studio

The agent container needs to reach LM Studio running on the host:

| Platform | `LM_STUDIO_BASE_URL` |
|---|---|
| Docker Desktop (Win/Mac) | `http://host.docker.internal:1234/v1` |
| Docker on Linux | `http://172.17.0.1:1234/v1` |
| Remote machine | `http://192.168.1.100:1234/v1` |

Set this in `docker/.env` before deploying.

---

## Persistent Data

State lives in Docker volumes — survives container recreation:

| Volume | Contents |
|---|---|
| `hp1-agent-data` | SQLite DBs, settings, ingested docs, skill exports/imports |
| `hp1-agent-logs` | Audit log (JSONL) |
| `hp1-agent-checkpoints` | Infrastructure state snapshots |
| `hp1-agent-skills` | Dynamic skill `.py` modules |

---

## Docker Socket Access

The agent needs Docker socket access to manage Swarm services.
The socket is mounted read-only: `/var/run/docker.sock:/var/run/docker.sock:ro`.

On Linux, the container user must be in the same group as the socket:
```bash
# Find your docker group GID
stat -c '%g' /var/run/docker.sock   # e.g. 999

# Set in docker/.env
DOCKER_GID=999

# Rebuild
docker compose -f docker/agent-compose.yml build
```

The `deploy.sh` script detects and sets this automatically.

---

## SSH Key Access

For tools that SSH to remote hosts (docker_engine, generated skills):
```bash
# In docker/.env:
SSH_KEY_DIR=~/.ssh
```

The `~/.ssh` directory is mounted read-only into `/home/agent/.ssh`.

---

## Development Mode (live reload)

```bash
docker compose \
  -f docker/agent-compose.yml \
  -f docker/agent-compose.override.yml \
  up -d
```

This bind-mounts `mcp_server/`, `api/`, and `agent/` into the container with `--reload` enabled — code changes are picked up automatically without a rebuild.

---

## Airgapped Deployment

Build the image on an internet-connected machine, transfer, load on the airgapped host:

```bash
# Build and export
docker build -t hp1-ai-agent:latest -f docker/Dockerfile .
docker save hp1-ai-agent:latest | gzip > hp1-agent.tar.gz

# Transfer hp1-agent.tar.gz to airgapped host, then:
docker load < hp1-agent.tar.gz
cp docker/.env.example docker/.env
# Edit .env
docker compose -f docker/agent-compose.yml up -d
```

No internet access needed at runtime — all Python dependencies are baked in.

---

## SQLite and Swarm Replicas

SQLite doesn't support concurrent writes from multiple processes.

- **Single-manager Swarm with `replicas=1`** (default): safe — one writer, strong restart policy provides uptime.
- **Multi-replica**: use Postgres via `DATABASE_URL=postgresql://...` in `.env`. Set `HP1_REPLICAS=2` in `.env` once Postgres is configured.

---

## Upgrading

### Compose
```bash
docker compose -f docker/agent-compose.yml build
docker compose -f docker/agent-compose.yml up -d   # Recreates with new image
```

### Swarm (zero-downtime rolling update)
```bash
docker build -t hp1-ai-agent:v1.9.0 -f docker/Dockerfile .
docker service update --image hp1-ai-agent:v1.9.0 hp1_agent
# Swarm: starts new replica, waits for healthy, stops old
```

---

## Monitoring

```bash
# Health
curl http://localhost:8000/api/health

# Logs
docker compose -f docker/agent-compose.yml logs -f
docker service logs hp1_agent -f  # Swarm

# Skill system
curl -H "Authorization: Bearer <token>" http://localhost:8000/api/agent \
  -d '{"task": "skill_health_summary"}'
```
