#!/usr/bin/env bash
# HP1 AI Agent — start FastAPI backend + React dev server (WSL / Linux)
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

export DOCKER_HOST="${DOCKER_HOST:-npipe:////./pipe/docker_engine}"
export KAFKA_BOOTSTRAP_SERVERS="${KAFKA_BOOTSTRAP_SERVERS:-localhost:9092,localhost:9093,localhost:9094}"
export AUDIT_LOG_PATH="${PROJECT_DIR}/logs/audit.log"
export CHECKPOINT_PATH="${PROJECT_DIR}/checkpoints"
export DB_PATH="${PROJECT_DIR}/data/hp1_agent.db"
export LM_STUDIO_BASE_URL="${LM_STUDIO_BASE_URL:-http://localhost:1234/v1}"
export LM_STUDIO_MODEL="${LM_STUDIO_MODEL:-lmstudio-community/qwen3-coder-30b-a3b-instruct}"
export CORS_ALLOW_ALL=true

echo ""
echo " HP1 AI Agent"
echo " ============"
echo " API  > http://localhost:8000"
echo " GUI  > http://localhost:5173"
echo " Docs > http://localhost:8000/docs"
echo ""

MODE="${1:-both}"

if [[ "$MODE" == "api" || "$MODE" == "both" ]]; then
  cd "$PROJECT_DIR"
  python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload &
  API_PID=$!
fi

if [[ "$MODE" == "gui" || "$MODE" == "both" ]]; then
  cd "$PROJECT_DIR/gui"
  npm run dev &
  GUI_PID=$!
fi

echo " PIDs: API=${API_PID:-n/a}  GUI=${GUI_PID:-n/a}"
echo " Ctrl+C to stop all"
trap "kill ${API_PID:-} ${GUI_PID:-} 2>/dev/null; exit 0" INT TERM
wait
