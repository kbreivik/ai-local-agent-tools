# Claude Code: Containerized Deployment for HP1-AI-Agent

## Context

HP1-AI-Agent is an existing Python MCP server + FastAPI backend + Vue GUI that manages
homelab infrastructure. It currently runs as bare Python on Windows. This prompt makes
it deployable as a Docker container that works identically on:

- Docker Desktop (Windows/Mac) — single-node dev/lab
- Docker Engine on any Linux (Debian, Ubuntu, RHEL, Arch, etc.)
- Docker Swarm — multi-node HA with rolling updates

The container is the **agent + API + GUI + MCP server + skill system** — one image, one unit.
External dependencies (Kafka, Elasticsearch, managed services) remain external and are
connected via environment variables.

**DO NOT** refactor the application code. The containerization wraps the existing project
structure. Only create Docker files, entrypoint scripts, compose files, and a thin
environment-detection bootstrap.

---

## Design Principles

1. **One image, every environment** — same Dockerfile builds for Desktop, Linux, and Swarm
2. **Config via environment** — every setting is an env var, no baked-in hostnames/IPs
3. **Persistent state via volumes** — `data/` directory is a named volume (DB, skills, exports, imports, checkpoints, audit logs)
4. **Docker socket passthrough** — the agent needs to manage Docker services on the host
5. **Airgapped-ready** — the image includes all Python deps; no pip install at runtime
6. **Graceful degradation** — missing Kafka/Elastic/LLM = tools return clean errors, agent still starts
7. **No root at runtime** — the process runs as a non-root user, Docker socket access via group

---

## Files to Create

```
docker/
├── Dockerfile                    # Multi-stage: build deps → slim runtime
├── .dockerignore                 # Exclude .git, __pycache__, node_modules, etc.
├── entrypoint.sh                 # Bootstrap: detect env, set defaults, start services
├── healthcheck.sh                # Used by Docker HEALTHCHECK
├── docker-compose.yml            # Single-node: Desktop / standalone Linux
├── docker-compose.override.yml   # Dev overrides: bind mounts, debug ports
├── swarm-stack.yml               # Docker Swarm: HA deploy with replicas + constraints
├── .env.example                  # All configurable env vars with comments
├── deploy.sh                     # One-command deploy script (detects Swarm vs Compose)
└── README.md                     # Deployment guide
```

---

## Dockerfile

Multi-stage build. Stage 1 builds wheels for compiled deps. Stage 2 is the slim runtime.

```dockerfile
# ── Stage 1: Build ──────────────────────────────────────────────────────────
FROM python:3.13-slim AS builder

WORKDIR /build

# System deps for compiled packages (paramiko, bcrypt, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev libssl-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

# ── Stage 2: Runtime ────────────────────────────────────────────────────────
FROM python:3.13-slim

# Labels for image metadata
LABEL org.opencontainers.image.title="HP1-AI-Agent" \
      org.opencontainers.image.description="Self-improving AI infrastructure agent" \
      org.opencontainers.image.source="https://github.com/kbreivik/ai-local-agent-tools"

# Runtime system deps only (no compiler)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl openssh-client jq && \
    rm -rf /var/lib/apt/lists/*

# Create non-root user with Docker group access
# GID 998 is typical for docker group on Linux; overridable at runtime
ARG DOCKER_GID=998
RUN groupadd -g ${DOCKER_GID} docker 2>/dev/null || true && \
    useradd -m -s /bin/bash -G docker agent

# Install Python deps from builder stage
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels

# Copy application code
WORKDIR /app
COPY . .

# Create data directories (will be overlaid by volume mount)
RUN mkdir -p data/skill_exports data/skill_imports data/docs \
    logs checkpoints \
    mcp_server/tools/skills/modules && \
    chown -R agent:agent /app

# Entrypoint and healthcheck
COPY docker/entrypoint.sh /entrypoint.sh
COPY docker/healthcheck.sh /healthcheck.sh
RUN chmod +x /entrypoint.sh /healthcheck.sh

# Ports: API (8000), GUI (5173), MCP stdio is internal
EXPOSE 8000 5173

# Health check — hits the API /health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD /healthcheck.sh

USER agent
ENTRYPOINT ["/entrypoint.sh"]
```

**Key decisions:**
- `openssh-client` for paramiko SSH key operations
- `curl` + `jq` for healthcheck and debugging
- Docker socket is NOT in the image — it's bind-mounted at runtime
- The `DOCKER_GID` build arg lets you match the host's docker group GID
- Non-root user `agent` runs everything; Docker socket access via group membership
- All `data/` content is designed to be a volume mount

---

## entrypoint.sh

Detects the runtime environment, sets sane defaults, initializes the database,
and starts the application.

```bash
#!/usr/bin/env bash
set -euo pipefail

# ── Environment Detection ───────────────────────────────────────────────────
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  HP1-AI-Agent — Starting                                ║"
echo "╚══════════════════════════════════════════════════════════╝"

# Detect Docker socket type
if [ -S /var/run/docker.sock ]; then
    export DOCKER_HOST="${DOCKER_HOST:-unix:///var/run/docker.sock}"
    echo "[init] Docker socket: /var/run/docker.sock (Linux/Mac)"
elif [ -e /var/run/docker.sock.raw ]; then
    # Docker Desktop on Mac sometimes uses this
    export DOCKER_HOST="${DOCKER_HOST:-unix:///var/run/docker.sock.raw}"
    echo "[init] Docker socket: raw socket (Docker Desktop)"
else
    echo "[init] WARNING: No Docker socket found — Swarm/Docker tools will be unavailable"
    echo "[init]   Mount with: -v /var/run/docker.sock:/var/run/docker.sock"
fi

# Detect if running in Swarm
if [ -n "${DOCKER_SWARM_SERVICE_NAME:-}" ] || docker info --format '{{.Swarm.LocalNodeState}}' 2>/dev/null | grep -q "active"; then
    export HP1_DEPLOY_MODE="${HP1_DEPLOY_MODE:-swarm}"
    echo "[init] Deploy mode: Docker Swarm"
else
    export HP1_DEPLOY_MODE="${HP1_DEPLOY_MODE:-standalone}"
    echo "[init] Deploy mode: Standalone"
fi

# ── Default Configuration ───────────────────────────────────────────────────
# API
export API_PORT="${API_PORT:-8000}"
export API_HOST="${API_HOST:-0.0.0.0}"
export ADMIN_PASSWORD="${ADMIN_PASSWORD:-changeme}"

# LLM — default to host.docker.internal for Docker Desktop, localhost for Linux
if [ "$HP1_DEPLOY_MODE" = "standalone" ] && [ -z "${LM_STUDIO_BASE_URL:-}" ]; then
    # Try host.docker.internal first (Docker Desktop), fall back to host network
    if getent hosts host.docker.internal >/dev/null 2>&1; then
        export LM_STUDIO_BASE_URL="http://host.docker.internal:1234/v1"
    else
        export LM_STUDIO_BASE_URL="http://172.17.0.1:1234/v1"
    fi
fi
export LM_STUDIO_BASE_URL="${LM_STUDIO_BASE_URL:-http://host.docker.internal:1234/v1}"

# Kafka — default to common internal names
export KAFKA_BOOTSTRAP_SERVERS="${KAFKA_BOOTSTRAP_SERVERS:-kafka1:9092,kafka2:9092,kafka3:9092}"

# Elasticsearch
export ELASTIC_URL="${ELASTIC_URL:-}"

# Skill generation
export SKILL_GEN_BACKEND="${SKILL_GEN_BACKEND:-local}"

# ── Initialize Data ────────────────────────────────────────────────────────
# Ensure directories exist (volume might be empty on first run)
mkdir -p /app/data/skill_exports /app/data/skill_imports /app/data/docs
mkdir -p /app/logs /app/checkpoints
mkdir -p /app/mcp_server/tools/skills/modules

# Initialize SQLite databases
python -c "
from mcp_server.tools.skills.registry import init_db
init_db()
print('[init] Skills database initialized')
" 2>/dev/null || echo "[init] Skills DB init skipped (module not ready)"

echo "[init] Configuration:"
echo "  API:       http://${API_HOST}:${API_PORT}"
echo "  LLM:       ${LM_STUDIO_BASE_URL}"
echo "  Kafka:     ${KAFKA_BOOTSTRAP_SERVERS}"
echo "  Elastic:   ${ELASTIC_URL:-not configured}"
echo "  Skills:    ${SKILL_GEN_BACKEND} backend"
echo "  Deploy:    ${HP1_DEPLOY_MODE}"
echo ""

# ── Start Application ──────────────────────────────────────────────────────
# Run the API server (which also starts the MCP server internally)
exec uvicorn api.main:app \
    --host "$API_HOST" \
    --port "$API_PORT" \
    --workers "${API_WORKERS:-1}" \
    --log-level "${LOG_LEVEL:-info}" \
    "$@"
```

---

## healthcheck.sh

```bash
#!/usr/bin/env bash
# Simple health check — verify API is responsive
curl -sf "http://localhost:${API_PORT:-8000}/api/health" > /dev/null 2>&1 || exit 1
```

---

## docker-compose.yml — Single Node (Desktop / Linux)

Works on Docker Desktop (Win/Mac) and any Linux with Docker Engine.
This is the "just run it" configuration.

```yaml
# docker-compose.yml — HP1-AI-Agent single-node deployment
# Usage: docker compose up -d

name: hp1-agent

services:
  agent:
    build:
      context: ..
      dockerfile: docker/Dockerfile
      args:
        # Match your host's docker group GID: stat -c '%g' /var/run/docker.sock
        DOCKER_GID: ${DOCKER_GID:-998}
    image: hp1-ai-agent:latest
    container_name: hp1-agent
    restart: unless-stopped

    ports:
      - "${API_PORT:-8000}:8000"     # API
      - "${GUI_PORT:-5173}:5173"     # GUI

    volumes:
      # Persistent data — survives container recreation
      - agent-data:/app/data
      - agent-logs:/app/logs
      - agent-checkpoints:/app/checkpoints
      # Dynamic skills persist across restarts
      - agent-skills:/app/mcp_server/tools/skills/modules

      # Docker socket — required for Swarm/Docker management tools
      - /var/run/docker.sock:/var/run/docker.sock:ro

      # SSH keys — mount if using SSH-based tools (docker_engine, generated skills)
      - ${SSH_KEY_DIR:-~/.ssh}:/home/agent/.ssh:ro

    environment:
      # ── Required ──
      - ADMIN_PASSWORD=${ADMIN_PASSWORD:-changeme}

      # ── LLM Connection ──
      # Docker Desktop: http://host.docker.internal:1234/v1
      # Linux (host network): http://172.17.0.1:1234/v1
      # Remote LLM: http://<ip>:1234/v1
      - LM_STUDIO_BASE_URL=${LM_STUDIO_BASE_URL:-}
      - LM_STUDIO_API_KEY=${LM_STUDIO_API_KEY:-}

      # ── Infrastructure Connections ──
      - KAFKA_BOOTSTRAP_SERVERS=${KAFKA_BOOTSTRAP_SERVERS:-}
      - ELASTIC_URL=${ELASTIC_URL:-}
      - DOCKER_ENGINE_HOST=${DOCKER_ENGINE_HOST:-}
      - DOCKER_ENGINE_USER=${DOCKER_ENGINE_USER:-root}
      - DOCKER_ENGINE_SSH_KEY=${DOCKER_ENGINE_SSH_KEY:-/home/agent/.ssh/id_rsa}

      # ── Skill System ──
      - SKILL_GEN_BACKEND=${SKILL_GEN_BACKEND:-local}
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-}

      # ── Target Services (for skills) ──
      - PROXMOX_HOST=${PROXMOX_HOST:-}
      - PROXMOX_USER=${PROXMOX_USER:-root@pam}
      - PROXMOX_TOKEN_ID=${PROXMOX_TOKEN_ID:-}
      - PROXMOX_TOKEN_SECRET=${PROXMOX_TOKEN_SECRET:-}
      - FORTIGATE_HOST=${FORTIGATE_HOST:-}
      - FORTIGATE_API_KEY=${FORTIGATE_API_KEY:-}

    # Health check
    healthcheck:
      test: ["CMD", "/healthcheck.sh"]
      interval: 30s
      timeout: 5s
      start_period: 15s
      retries: 3

    # Resource limits
    deploy:
      resources:
        limits:
          memory: 1G
          cpus: "2.0"
        reservations:
          memory: 256M
          cpus: "0.5"

    logging:
      driver: json-file
      options:
        max-size: "50m"
        max-file: "3"

volumes:
  agent-data:
    name: hp1-agent-data
  agent-logs:
    name: hp1-agent-logs
  agent-checkpoints:
    name: hp1-agent-checkpoints
  agent-skills:
    name: hp1-agent-skills
```

---

## docker-compose.override.yml — Dev Overrides

Loaded automatically alongside `docker-compose.yml` during `docker compose up`.
Adds bind mounts for live code editing and debug ports.

```yaml
# docker-compose.override.yml — development overrides
# Auto-loaded by docker compose. Delete or rename to disable.

services:
  agent:
    # Bind-mount source for live reload
    volumes:
      - ../mcp_server:/app/mcp_server:ro
      - ../api:/app/api:ro
      - ../agent:/app/agent:ro
    environment:
      - LOG_LEVEL=debug
      - API_WORKERS=1
    # Override entrypoint for reload support
    command: ["--reload"]
```

---

## swarm-stack.yml — Docker Swarm HA Deployment

For production/HA homelabs with multiple Docker nodes.
Runs 2 replicas with rolling updates and failure recovery.

```yaml
# swarm-stack.yml — HP1-AI-Agent Swarm deployment
# Usage: docker stack deploy -c docker/swarm-stack.yml hp1

version: "3.9"

services:
  agent:
    image: ${HP1_IMAGE:-hp1-ai-agent:latest}
    networks:
      - agent-net
    ports:
      - target: 8000
        published: 8000
        protocol: tcp
        mode: ingress        # Swarm load-balances across replicas
      - target: 5173
        published: 5173
        protocol: tcp
        mode: ingress

    volumes:
      # Shared data volume — must be accessible from all nodes
      # For multi-node: use NFS, GlusterFS, or a shared mount
      - agent-data:/app/data
      - agent-logs:/app/logs
      - agent-checkpoints:/app/checkpoints
      - agent-skills:/app/mcp_server/tools/skills/modules

      # Docker socket — each node mounts its own
      - /var/run/docker.sock:/var/run/docker.sock:ro

    environment:
      - ADMIN_PASSWORD=${ADMIN_PASSWORD:?Set ADMIN_PASSWORD}
      - LM_STUDIO_BASE_URL=${LM_STUDIO_BASE_URL:-http://host.docker.internal:1234/v1}
      - LM_STUDIO_API_KEY=${LM_STUDIO_API_KEY:-}
      - KAFKA_BOOTSTRAP_SERVERS=${KAFKA_BOOTSTRAP_SERVERS:-kafka1:9092,kafka2:9092,kafka3:9092}
      - ELASTIC_URL=${ELASTIC_URL:-}
      - SKILL_GEN_BACKEND=${SKILL_GEN_BACKEND:-local}
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-}
      - DOCKER_ENGINE_HOST=${DOCKER_ENGINE_HOST:-}
      - DOCKER_ENGINE_USER=${DOCKER_ENGINE_USER:-root}
      - DOCKER_ENGINE_SSH_KEY=${DOCKER_ENGINE_SSH_KEY:-/home/agent/.ssh/id_rsa}
      - PROXMOX_HOST=${PROXMOX_HOST:-}
      - PROXMOX_USER=${PROXMOX_USER:-root@pam}
      - PROXMOX_TOKEN_ID=${PROXMOX_TOKEN_ID:-}
      - PROXMOX_TOKEN_SECRET=${PROXMOX_TOKEN_SECRET:-}
      - FORTIGATE_HOST=${FORTIGATE_HOST:-}
      - FORTIGATE_API_KEY=${FORTIGATE_API_KEY:-}

    deploy:
      replicas: 2
      update_config:
        parallelism: 1
        delay: 30s
        failure_action: rollback
        monitor: 60s
        order: start-first       # New replica starts before old one stops
      rollback_config:
        parallelism: 1
        order: start-first
      restart_policy:
        condition: on-failure
        delay: 10s
        max_attempts: 5
        window: 120s
      placement:
        constraints:
          - node.role == manager  # Needs Docker socket access for swarm tools
        preferences:
          - spread: node.id       # Spread replicas across nodes
      resources:
        limits:
          memory: 1G
          cpus: "2.0"
        reservations:
          memory: 256M
          cpus: "0.5"

    healthcheck:
      test: ["CMD", "curl", "-sf", "http://localhost:8000/api/health"]
      interval: 30s
      timeout: 5s
      start_period: 20s
      retries: 3

    logging:
      driver: json-file
      options:
        max-size: "50m"
        max-file: "5"

networks:
  agent-net:
    driver: overlay
    attachable: true
    # Reuse existing agent-net if it exists (Kafka/workload stacks are on it)
    external: true

volumes:
  # For single-manager Swarm: local volumes are fine
  # For multi-node Swarm: use NFS driver or a shared storage plugin
  agent-data:
    name: hp1-agent-data
    # Uncomment for NFS:
    # driver: local
    # driver_opts:
    #   type: nfs
    #   o: addr=${NFS_SERVER},rw,nfsvers=4
    #   device: ":/exports/hp1/data"
  agent-logs:
    name: hp1-agent-logs
  agent-checkpoints:
    name: hp1-agent-checkpoints
  agent-skills:
    name: hp1-agent-skills
```

**Multi-node volume strategy:**
- Single-manager Swarm (most homelabs): local volumes are fine since replicas only
  run on the manager node (constraint above)
- Multi-node Swarm: uncomment the NFS driver_opts or use a storage plugin like
  REX-Ray, Portainer Volumes, or a GlusterFS driver

---

## deploy.sh — Universal Deploy Script

One script handles every environment. Detects what's available and does the right thing.

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="${PROJECT_DIR}/docker/.env"

# ── Colors ──
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${CYAN}[info]${NC}  $*"; }
ok()    { echo -e "${GREEN}[ok]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[warn]${NC}  $*"; }
err()   { echo -e "${RED}[error]${NC} $*"; }

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  HP1-AI-Agent — Deploy                                  ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ── Detect Docker ───────────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
    err "Docker not found. Install Docker first."
    exit 1
fi

DOCKER_VERSION=$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo "unknown")
info "Docker version: ${DOCKER_VERSION}"

# ── Detect Docker socket GID (for Linux) ────────────────────────────────────
DOCKER_GID=998
if [ -S /var/run/docker.sock ]; then
    DOCKER_GID=$(stat -c '%g' /var/run/docker.sock 2>/dev/null || stat -f '%g' /var/run/docker.sock 2>/dev/null || echo 998)
    info "Docker socket GID: ${DOCKER_GID}"
fi
export DOCKER_GID

# ── Detect Swarm ────────────────────────────────────────────────────────────
SWARM_STATE=$(docker info --format '{{.Swarm.LocalNodeState}}' 2>/dev/null || echo "inactive")
IS_SWARM=false
if [ "$SWARM_STATE" = "active" ]; then
    IS_SWARM=true
    NODE_ROLE=$(docker info --format '{{.Swarm.ControlAvailable}}' 2>/dev/null || echo "false")
    SWARM_NODES=$(docker node ls --format '{{.ID}}' 2>/dev/null | wc -l || echo "1")
    info "Swarm: active (${SWARM_NODES} nodes, manager: ${NODE_ROLE})"
fi

# ── Detect LLM ──────────────────────────────────────────────────────────────
LLM_URL=""
for candidate in "http://host.docker.internal:1234" "http://172.17.0.1:1234" "http://localhost:1234"; do
    if curl -sf "${candidate}/v1/models" >/dev/null 2>&1; then
        LLM_URL="${candidate}/v1"
        ok "LLM found at ${LLM_URL}"
        break
    fi
done
if [ -z "$LLM_URL" ]; then
    warn "No local LLM detected — skill generation will use export mode"
fi

# ── Generate .env if not exists ─────────────────────────────────────────────
if [ ! -f "$ENV_FILE" ]; then
    info "Generating .env from template..."
    cp "${SCRIPT_DIR}/.env.example" "$ENV_FILE"
    # Inject detected values
    sed -i "s|^DOCKER_GID=.*|DOCKER_GID=${DOCKER_GID}|" "$ENV_FILE" 2>/dev/null || true
    if [ -n "$LLM_URL" ]; then
        sed -i "s|^LM_STUDIO_BASE_URL=.*|LM_STUDIO_BASE_URL=${LLM_URL}|" "$ENV_FILE" 2>/dev/null || true
    fi
    warn "Edit docker/.env before continuing. Then re-run this script."
    warn "  At minimum, set ADMIN_PASSWORD"
    exit 0
fi

info "Using config from docker/.env"
source "$ENV_FILE"

# ── Detect Docker Compose version ───────────────────────────────────────────
COMPOSE_CMD=""
if docker compose version &>/dev/null; then
    COMPOSE_CMD="docker compose"
elif command -v docker-compose &>/dev/null; then
    COMPOSE_CMD="docker-compose"
fi

# ── Build ───────────────────────────────────────────────────────────────────
info "Building image..."
if [ -n "$COMPOSE_CMD" ]; then
    (cd "$SCRIPT_DIR" && $COMPOSE_CMD build --build-arg DOCKER_GID="${DOCKER_GID}")
else
    docker build \
        --build-arg DOCKER_GID="${DOCKER_GID}" \
        -t hp1-ai-agent:latest \
        -f "${SCRIPT_DIR}/Dockerfile" \
        "$PROJECT_DIR"
fi
ok "Image built: hp1-ai-agent:latest"

# ── Deploy ──────────────────────────────────────────────────────────────────
MODE="${1:-auto}"

if [ "$MODE" = "auto" ]; then
    if [ "$IS_SWARM" = true ]; then
        MODE="swarm"
    else
        MODE="compose"
    fi
fi

case "$MODE" in
    swarm)
        if [ "$IS_SWARM" != true ]; then
            warn "Swarm not active. Initializing..."
            docker swarm init 2>/dev/null || true
        fi

        # Create overlay network if it doesn't exist
        docker network create --driver overlay --attachable agent-net 2>/dev/null || true

        info "Deploying to Swarm..."
        docker stack deploy \
            -c "${SCRIPT_DIR}/swarm-stack.yml" \
            --with-registry-auth \
            hp1

        ok "Swarm stack deployed: hp1"
        echo ""
        info "Check status:  docker service ls"
        info "View logs:     docker service logs hp1_agent -f"
        info "Scale:         docker service scale hp1_agent=3"
        ;;

    compose)
        info "Deploying with Docker Compose..."
        (cd "$SCRIPT_DIR" && $COMPOSE_CMD up -d)

        ok "Compose stack running"
        echo ""
        info "Check status:  docker compose -f docker/docker-compose.yml ps"
        info "View logs:     docker compose -f docker/docker-compose.yml logs -f"
        info "Stop:          docker compose -f docker/docker-compose.yml down"
        ;;

    *)
        err "Unknown mode: $MODE (use: auto, swarm, compose)"
        exit 1
        ;;
esac

echo ""
ok "HP1-AI-Agent is starting"
info "  API:  http://localhost:${API_PORT:-8000}"
info "  GUI:  http://localhost:${GUI_PORT:-5173}"
echo ""
```

---

## .env.example

```bash
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  HP1-AI-Agent — Environment Configuration                                  ║
# ║  Copy to .env and edit. Values shown are defaults.                         ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

# ── Docker Build ──────────────────────────────────────────────────────────────
# Match your host's docker group GID: stat -c '%g' /var/run/docker.sock
DOCKER_GID=998

# ── API ───────────────────────────────────────────────────────────────────────
API_PORT=8000
GUI_PORT=5173
ADMIN_PASSWORD=changeme
# API_WORKERS=1     # Increase for Swarm replicas behind load balancer
# LOG_LEVEL=info    # debug | info | warning | error

# ── Local LLM (LM Studio / Ollama / vLLM) ────────────────────────────────────
# Docker Desktop (Win/Mac): http://host.docker.internal:1234/v1
# Docker on Linux:          http://172.17.0.1:1234/v1
# Remote host:              http://192.168.1.100:1234/v1
LM_STUDIO_BASE_URL=
LM_STUDIO_API_KEY=

# ── Cloud LLM (optional, for skill generation) ───────────────────────────────
ANTHROPIC_API_KEY=

# ── Skill Generation ─────────────────────────────────────────────────────────
# local = LM Studio (airgapped), cloud = Anthropic API, export = sneakernet
SKILL_GEN_BACKEND=local

# ── Kafka (leave empty if not using Kafka) ────────────────────────────────────
# Inside Swarm: kafka1:9092,kafka2:9092,kafka3:9092
# From host:    localhost:9092,localhost:9093,localhost:9094
KAFKA_BOOTSTRAP_SERVERS=

# ── Elasticsearch (leave empty if not using) ──────────────────────────────────
ELASTIC_URL=
# ELASTIC_INDEX_PATTERN=hp1-logs-*
# ELASTIC_FILEBEAT_STALE_MINUTES=10

# ── Docker Engine SSH (for remote Docker host management) ─────────────────────
DOCKER_ENGINE_HOST=
DOCKER_ENGINE_USER=root
DOCKER_ENGINE_SSH_KEY=/home/agent/.ssh/id_rsa
# DOCKER_ENGINE_SSH_PORT=22

# ── Proxmox (for proxmox_vm_status skill) ─────────────────────────────────────
PROXMOX_HOST=
PROXMOX_USER=root@pam
PROXMOX_TOKEN_ID=
PROXMOX_TOKEN_SECRET=

# ── FortiGate (for fortigate_system_status skill) ─────────────────────────────
FORTIGATE_HOST=
FORTIGATE_API_KEY=

# ── MuninnDB (memory system) ─────────────────────────────────────────────────
# MUNINNDB_URL=http://muninndb:9475
# MUNINNDB_COLLECTION=hp1

# ── SSH Keys ──────────────────────────────────────────────────────────────────
# Directory on host to mount as /home/agent/.ssh inside container
SSH_KEY_DIR=~/.ssh

# ── Swarm-Only Settings ──────────────────────────────────────────────────────
# HP1_IMAGE=hp1-ai-agent:latest
# NFS_SERVER=192.168.1.10     # For multi-node shared volumes
```

---

## .dockerignore

```
.git
.gitignore
__pycache__
*.pyc
*.pyo
.mypy_cache
.pytest_cache
.code-index
node_modules
.venv
venv
*.egg-info
dist
build
docker/.env
data/skills.db
data/skill_exports/*
data/skill_imports/*
logs/*
checkpoints/*
.env
*.bak
```

---

## docker/README.md

```markdown
# HP1-AI-Agent — Docker Deployment

## Quick Start (any environment)

```bash
cd docker
./deploy.sh
```

The script auto-detects your environment and does the right thing:
- Docker Desktop → Docker Compose
- Docker Engine (Linux) → Docker Compose
- Docker Swarm active → Swarm Stack (2 replicas, rolling updates)

## Manual Deployment

### Docker Compose (single node)

```bash
cp docker/.env.example docker/.env
# Edit .env — set ADMIN_PASSWORD, LM_STUDIO_BASE_URL
docker compose -f docker/docker-compose.yml up -d
```

### Docker Swarm (HA)

```bash
# Initialize Swarm if not already
docker swarm init

# Create overlay network (shared with Kafka/workload stacks)
docker network create --driver overlay --attachable agent-net

# Build and deploy
docker build -t hp1-ai-agent:latest -f docker/Dockerfile .
docker stack deploy -c docker/swarm-stack.yml hp1
```

## Connecting to LM Studio

The container needs to reach LM Studio on the host machine:

| Platform | LM_STUDIO_BASE_URL |
|---|---|
| Docker Desktop (Win/Mac) | `http://host.docker.internal:1234/v1` |
| Docker on Linux | `http://172.17.0.1:1234/v1` |
| Remote machine | `http://192.168.1.100:1234/v1` |

## Persistent Data

All state lives in Docker volumes:

| Volume | Contents |
|---|---|
| `hp1-agent-data` | SQLite DBs, settings, ingested docs, skill exports/imports |
| `hp1-agent-logs` | Audit log (JSONL) |
| `hp1-agent-checkpoints` | Infrastructure state snapshots |
| `hp1-agent-skills` | Dynamic skill .py modules |

## Docker Socket Access

The agent needs Docker socket access to manage Swarm services.
The socket is mounted read-only (`/var/run/docker.sock:/var/run/docker.sock:ro`).

On Linux, ensure the container user can access the socket:
```bash
# Find your docker group GID
stat -c '%g' /var/run/docker.sock
# Set it in .env
DOCKER_GID=999
# Rebuild
docker compose build --build-arg DOCKER_GID=999
```

## SSH Key Access

For tools that SSH to remote hosts (docker_engine, generated skills):
```bash
# Mount your SSH key directory
SSH_KEY_DIR=~/.ssh docker compose up -d
```

## Airgapped Deployment

1. On an internet-connected machine, build the image:
   ```bash
   docker build -t hp1-ai-agent:latest -f docker/Dockerfile .
   docker save hp1-ai-agent:latest | gzip > hp1-agent.tar.gz
   ```

2. Transfer `hp1-agent.tar.gz` to the airgapped host

3. Load and run:
   ```bash
   docker load < hp1-agent.tar.gz
   cp docker/.env.example docker/.env
   # Edit .env
   docker compose -f docker/docker-compose.yml up -d
   ```

No internet needed at runtime. All Python dependencies are baked into the image.

## Monitoring

```bash
# Health check
curl http://localhost:8000/api/health

# Logs
docker compose logs -f
# or for Swarm:
docker service logs hp1_agent -f

# Skill system status
curl http://localhost:8000/api/skills/health
```

## Upgrading

### Compose
```bash
docker compose build
docker compose up -d   # Recreates container with new image
```

### Swarm (zero-downtime)
```bash
docker build -t hp1-ai-agent:v2 .
docker service update --image hp1-ai-agent:v2 hp1_agent
# Swarm does rolling update: starts new, waits for healthy, stops old
```
```

---

## Implementation Notes for Claude Code

### Health Endpoint

The application needs a `/api/health` endpoint. If one doesn't exist, add it to the
FastAPI app (this is the ONE change to existing code that's acceptable):

```python
# In api/main.py or wherever the FastAPI app is defined
@app.get("/api/health")
async def health():
    """Health check for Docker HEALTHCHECK and load balancers."""
    return {
        "status": "ok",
        "deploy_mode": os.environ.get("HP1_DEPLOY_MODE", "unknown"),
        "version": "1.6.5",
    }
```

### Docker Host Networking Quirk

When the agent container manages Docker Swarm services, it talks to the Docker daemon
via the mounted socket. The Docker daemon sees the HOST's network, not the container's.
So Kafka addresses like `kafka1:9092` work because the daemon resolves them on the
overlay network. But if a skill inside the container tries to reach `kafka1:9092` directly
via httpx/paramiko, it needs to be on the same Docker network. The compose/swarm configs
handle this by attaching to `agent-net`.

### SQLite in Swarm

SQLite doesn't support concurrent writes from multiple processes. With Swarm replicas=2:
- If using local volumes (single manager), both replicas access the SAME file — potential corruption
- Solutions:
  1. Constrain to 1 replica for the agent service (simpler, fine for homelabs)
  2. Use a shared NFS volume with WAL mode enabled (handles concurrent readers, single writer)
  3. Separate the API into a single-writer instance + read-only MCP replicas

For most homelabs, option 1 (replicas=1 with restart policy) provides enough uptime.
The Swarm stack defaults to replicas=2 but document this caveat prominently.

### Build Order

1. `docker/.dockerignore`
2. `docker/Dockerfile`
3. `docker/entrypoint.sh` + `docker/healthcheck.sh`
4. `docker/.env.example`
5. `docker/docker-compose.yml`
6. `docker/docker-compose.override.yml`
7. `docker/swarm-stack.yml`
8. `docker/deploy.sh`
9. `docker/README.md`
10. Add `/api/health` endpoint if missing
11. Test: `docker compose -f docker/docker-compose.yml build`
12. Test: `docker compose -f docker/docker-compose.yml up -d`
13. Test: `curl http://localhost:8000/api/health`
14. Test: `docker compose -f docker/docker-compose.yml down`

### Testing Checklist

#### Build
- [ ] `docker build -t hp1-ai-agent:latest -f docker/Dockerfile .` succeeds
- [ ] Image size < 500MB
- [ ] No secrets in image layers (`docker history hp1-ai-agent:latest`)

#### Docker Compose
- [ ] `docker compose up -d` starts cleanly
- [ ] Health check passes within 30s
- [ ] API responds: `curl http://localhost:8000/api/health`
- [ ] Audit log writes to volume: `docker exec hp1-agent ls -la /app/logs/`
- [ ] Skills DB initializes: `docker exec hp1-agent python -c "from mcp_server.tools.skills.registry import init_db; init_db()"`
- [ ] Container restarts after crash: `docker kill hp1-agent && sleep 10 && docker ps`
- [ ] Volumes persist after `docker compose down && docker compose up -d`

#### Docker Swarm
- [ ] `docker stack deploy -c docker/swarm-stack.yml hp1` deploys
- [ ] `docker service ls` shows desired replicas
- [ ] Rolling update: `docker service update --image hp1-ai-agent:latest hp1_agent`
- [ ] Health checks work via Swarm routing mesh
- [ ] Logs: `docker service logs hp1_agent`

#### Airgapped
- [ ] `docker save hp1-ai-agent:latest | gzip > hp1.tar.gz` works
- [ ] `docker load < hp1.tar.gz` on clean host works
- [ ] Container starts with no internet: `docker compose up -d`
- [ ] LLM connection to host works
- [ ] Skill export/import directories accessible

#### Edge Cases
- [ ] Missing Docker socket → starts but warns, Docker tools return errors
- [ ] Missing LLM → starts, skill_create returns clear error
- [ ] Missing Kafka → starts, Kafka tools return "unavailable"
- [ ] Missing Elasticsearch → starts, Elastic tools return "unavailable"
- [ ] Wrong DOCKER_GID → container can't access socket → clear error in logs

---

## Critical Constraints

- **One image** — no separate images for different environments
- **All config via env vars** — nothing hardcoded, no config files baked in
- **Volumes for state** — container is ephemeral, data survives
- **No pip at runtime** — all deps baked into image (airgapped requirement)
- **Non-root** — process runs as `agent` user, Docker socket access via GID matching
- **Graceful degradation** — every external dependency is optional; the agent starts regardless
- **deploy.sh detects everything** — the operator runs one command, it figures out the rest
- **Existing code untouched** — except adding `/api/health` if missing
