#!/usr/bin/env bash
# deploy.sh — Universal HP1-AI-Agent deploy script
# Detects the environment and does the right thing.
#
# Usage:
#   ./deploy.sh           # auto-detect (Compose or Swarm)
#   ./deploy.sh compose   # force Docker Compose
#   ./deploy.sh swarm     # force Swarm stack deploy
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="${SCRIPT_DIR}/.env"
COMPOSE_FILE="${SCRIPT_DIR}/agent-compose.yml"
SWARM_FILE="${SCRIPT_DIR}/agent-swarm.yml"

# ── Color helpers ────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${CYAN}[info]${NC}  $*"; }
ok()    { echo -e "${GREEN}[ok]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[warn]${NC}  $*"; }
err()   { echo -e "${RED}[error]${NC} $*" >&2; }

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║  HP1-AI-Agent — Deploy                                  ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ── Docker check ─────────────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
    err "Docker not found. Install Docker first: https://docs.docker.com/get-docker/"
    exit 1
fi
DOCKER_VERSION=$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo "unknown")
info "Docker version: ${DOCKER_VERSION}"

# ── Detect docker group GID ──────────────────────────────────────────────────
DOCKER_GID=998
if [ -S /var/run/docker.sock ]; then
    # Linux: stat -c; macOS: stat -f
    DOCKER_GID=$(stat -c '%g' /var/run/docker.sock 2>/dev/null || \
                 stat -f '%g' /var/run/docker.sock 2>/dev/null || echo 998)
    info "Docker socket GID: ${DOCKER_GID}"
fi
export DOCKER_GID

# ── Detect Swarm ─────────────────────────────────────────────────────────────
SWARM_STATE=$(docker info --format '{{.Swarm.LocalNodeState}}' 2>/dev/null || echo "inactive")
IS_SWARM=false
if [ "$SWARM_STATE" = "active" ]; then
    IS_SWARM=true
    SWARM_NODES=$(docker node ls --format '{{.ID}}' 2>/dev/null | wc -l | tr -d ' ' || echo "1")
    IS_MANAGER=$(docker info --format '{{.Swarm.ControlAvailable}}' 2>/dev/null || echo "false")
    info "Swarm: active (${SWARM_NODES} node(s), manager: ${IS_MANAGER})"
fi

# ── Detect LLM ───────────────────────────────────────────────────────────────
LLM_FOUND=""
for candidate in "http://host.docker.internal:1234" "http://172.17.0.1:1234" "http://localhost:1234"; do
    if curl -sf --max-time 2 "${candidate}/v1/models" >/dev/null 2>&1; then
        LLM_FOUND="${candidate}/v1"
        ok "LLM detected at ${LLM_FOUND}"
        break
    fi
done
if [ -z "$LLM_FOUND" ]; then
    warn "No local LLM detected — set LM_STUDIO_BASE_URL in .env manually"
fi

# ── Generate .env from template if not present ───────────────────────────────
if [ ! -f "$ENV_FILE" ]; then
    info "Creating docker/.env from template..."
    cp "${SCRIPT_DIR}/.env.example" "$ENV_FILE"
    # Inject detected values
    if command -v sed &>/dev/null; then
        sed -i "s|^DOCKER_GID=.*|DOCKER_GID=${DOCKER_GID}|" "$ENV_FILE" 2>/dev/null || true
        if [ -n "$LLM_FOUND" ]; then
            sed -i "s|^LM_STUDIO_BASE_URL=.*|LM_STUDIO_BASE_URL=${LLM_FOUND}|" "$ENV_FILE" 2>/dev/null || true
        fi
    fi
    warn "docker/.env created. Edit it now (at minimum: set ADMIN_PASSWORD)."
    warn "Then re-run: ./deploy.sh"
    exit 0
fi

info "Using config: docker/.env"
# shellcheck source=/dev/null
set -o allexport; source "$ENV_FILE"; set +o allexport

# ── Detect compose command ───────────────────────────────────────────────────
COMPOSE_CMD=""
if docker compose version &>/dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
elif command -v docker-compose &>/dev/null; then
    COMPOSE_CMD="docker-compose"
fi

# ── Build image ──────────────────────────────────────────────────────────────
info "Building hp1-ai-agent:latest ..."
if [ -n "$COMPOSE_CMD" ]; then
    (cd "$PROJECT_DIR" && $COMPOSE_CMD -f "$COMPOSE_FILE" build --build-arg DOCKER_GID="${DOCKER_GID}")
else
    docker build \
        --build-arg DOCKER_GID="${DOCKER_GID}" \
        -t hp1-ai-agent:latest \
        -f "${SCRIPT_DIR}/Dockerfile" \
        "$PROJECT_DIR"
fi
ok "Image built: hp1-ai-agent:latest"

# ── Deploy ───────────────────────────────────────────────────────────────────
MODE="${1:-auto}"
if [ "$MODE" = "auto" ]; then
    MODE=$( [ "$IS_SWARM" = true ] && echo "swarm" || echo "compose" )
fi

case "$MODE" in
    swarm)
        if [ "$IS_SWARM" != true ]; then
            warn "Swarm not active — initializing single-node Swarm..."
            docker swarm init 2>/dev/null || true
        fi

        # Ensure overlay network exists
        docker network create --driver overlay --attachable agent-net 2>/dev/null || \
            info "overlay network agent-net already exists"

        info "Deploying Swarm stack: hp1 ..."
        docker stack deploy \
            -c "${SWARM_FILE}" \
            --with-registry-auth \
            hp1

        ok "Swarm stack deployed: hp1"
        echo ""
        info "Status:    docker service ls"
        info "Logs:      docker service logs hp1_agent -f"
        info "Scale:     docker service scale hp1_agent=2"
        info "Update:    docker service update --image hp1-ai-agent:latest hp1_agent"
        ;;

    compose)
        if [ -z "$COMPOSE_CMD" ]; then
            err "Docker Compose not found. Install it or use Docker Desktop."
            exit 1
        fi

        info "Deploying with Docker Compose ..."
        (cd "$PROJECT_DIR" && $COMPOSE_CMD -f "$COMPOSE_FILE" up -d)

        ok "Container running"
        echo ""
        info "Status:    docker compose -f docker/agent-compose.yml ps"
        info "Logs:      docker compose -f docker/agent-compose.yml logs -f"
        info "Stop:      docker compose -f docker/agent-compose.yml down"
        ;;

    *)
        err "Unknown mode: $MODE  (valid: auto, compose, swarm)"
        exit 1
        ;;
esac

echo ""
ok "HP1-AI-Agent is starting"
info "  API:  http://localhost:${API_PORT:-8000}"
info "  Auth: admin / ${ADMIN_PASSWORD:-changeme}"
echo ""
