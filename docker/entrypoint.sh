#!/usr/bin/env bash
set -euo pipefail

echo "╔══════════════════════════════════════════════════════════╗"
echo "║  HP1-AI-Agent — Starting                                ║"
echo "╚══════════════════════════════════════════════════════════╝"

# ── Docker connectivity ───────────────────────────────────────────────────────
if echo "${DOCKER_HOST:-}" | grep -q "^tcp://"; then
    echo "[init] Docker: TCP remote → ${DOCKER_HOST}"
elif [ -S /var/run/docker.sock ]; then
    export DOCKER_HOST="${DOCKER_HOST:-unix:///var/run/docker.sock}"
    echo "[init] Docker socket: /var/run/docker.sock"
elif [ -e /var/run/docker.sock.raw ]; then
    export DOCKER_HOST="${DOCKER_HOST:-unix:///var/run/docker.sock.raw}"
    echo "[init] Docker socket: raw socket (Docker Desktop)"
else
    echo "[init] WARNING: DOCKER_HOST not set and no socket found — Swarm/Docker tools unavailable"
    echo "[init]   Set DOCKER_HOST=tcp://<manager>:2375 or mount the Docker socket"
fi

# ── Deploy mode detection ────────────────────────────────────────────────────
if [ -n "${DOCKER_SWARM_SERVICE_NAME:-}" ] || docker info --format '{{.Swarm.LocalNodeState}}' 2>/dev/null | grep -q "active"; then
    export HP1_DEPLOY_MODE="${HP1_DEPLOY_MODE:-swarm}"
    echo "[init] Deploy mode: Docker Swarm (service: ${DOCKER_SWARM_SERVICE_NAME:-standalone-swarm-node})"
else
    export HP1_DEPLOY_MODE="${HP1_DEPLOY_MODE:-standalone}"
    echo "[init] Deploy mode: Standalone"
fi

# ── Default configuration ────────────────────────────────────────────────────
export API_PORT="${API_PORT:-8000}"
export API_HOST="${API_HOST:-0.0.0.0}"

# LLM: auto-detect host.docker.internal (Docker Desktop) or bridge gateway
if [ -z "${LM_STUDIO_BASE_URL:-}" ]; then
    if getent hosts host.docker.internal >/dev/null 2>&1; then
        export LM_STUDIO_BASE_URL="http://host.docker.internal:1234/v1"
    else
        export LM_STUDIO_BASE_URL="http://172.17.0.1:1234/v1"
    fi
fi

export KAFKA_BOOTSTRAP_SERVERS="${KAFKA_BOOTSTRAP_SERVERS:-kafka1:9092,kafka2:9092,kafka3:9092}"
export SKILL_GEN_BACKEND="${SKILL_GEN_BACKEND:-local}"
export LOG_LEVEL="${LOG_LEVEL:-info}"

# ── Initialize data directories (volume may be empty on first run) ───────────
mkdir -p \
    /app/data/skill_exports \
    /app/data/skill_imports \
    /app/data/docs \
    /app/logs \
    /app/checkpoints \
    /app/mcp_server/tools/skills/modules

# Initialize skills database
python -c "
from mcp_server.tools.skills.registry import init_db
init_db()
print('[init] Skills database initialized')
" 2>/dev/null || echo "[init] Skills DB init skipped"

echo ""
echo "[init] Configuration:"
echo "  API:       http://${API_HOST}:${API_PORT}"
echo "  Docker:    ${DOCKER_HOST:-not configured}"
echo "  LLM:       ${LM_STUDIO_BASE_URL}"
echo "  Kafka:     ${KAFKA_BOOTSTRAP_SERVERS}"
echo "  Elastic:   ${ELASTIC_URL:-not configured}"
echo "  Skills:    ${SKILL_GEN_BACKEND} backend"
echo "  Deploy:    ${HP1_DEPLOY_MODE}"
echo ""

# ── Start application ────────────────────────────────────────────────────────
exec uvicorn api.main:app \
    --host "$API_HOST" \
    --port "$API_PORT" \
    --workers "${API_WORKERS:-1}" \
    --log-level "${LOG_LEVEL}" \
    "$@"
