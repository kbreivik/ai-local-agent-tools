# CC PROMPT — v2.31.12 — feat(ci): Dockerfile in repo + queue runner builds and pushes image

## What this does
Fixes the broken image pipeline. The production Dockerfile and its entrypoint
and healthcheck scripts have lived only on agent-01 at `/opt/hp1-agent/docker/` —
never in the repo. That worked when someone built manually on agent-01, but
the pipeline stopped producing tagged images after v2.29.5, leaving
`:latest` frozen at the v2.31.1 build.

This prompt checks the production files into the repo and wires `docker build`
+ `docker push` into the queue runner so every future CC prompt auto-builds
and publishes `:latest` + `:<VERSION>` + `:sha-<short>`.

Five changes:
1. **NEW** `Dockerfile` at repo root (exact copy of agent-01 production Dockerfile)
2. **NEW** `docker/entrypoint.sh` (exact copy)
3. **NEW** `docker/healthcheck.sh` (exact copy)
4. **NEW** `.dockerignore` at repo root
5. **EDIT** `cc_prompts/QUEUE_RUNNER.md` — insert Step 5.5 for build + push

Then this prompt itself runs the first build + push at the end, landing
`ghcr.io/kbreivik/hp1-ai-agent:2.31.12` in GHCR with all v2.31.3..v2.31.11
changes included.

---

## Change 1 — Dockerfile — NEW FILE at repo root

Create `Dockerfile` at `D:\claude_code\ai-local-agent-tools\Dockerfile`
with the exact content below (copied from agent-01
`/opt/hp1-agent/docker/Dockerfile`):

```dockerfile
# ── Stage 1: Build GUI ──────────────────────────────────────────────────────
FROM node:20-slim AS gui-builder
WORKDIR /gui
COPY gui/package.json gui/package-lock.json ./
RUN npm ci
COPY gui/ ./
RUN npm run build
# ── Stage 2: Build Python wheels ────────────────────────────────────────────
FROM python:3.13-slim AS builder
WORKDIR /build
# System deps needed to compile wheels (paramiko, bcrypt, cryptography)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev libssl-dev && \
    rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
# Install transformers without deps to prevent PyTorch from being pulled in.
# Only tokenizers, numpy, huggingface-hub, safetensors are needed at runtime.
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt && \
    pip wheel --no-cache-dir --wheel-dir /wheels transformers --no-deps
# ── Stage 2: Runtime ────────────────────────────────────────────────────────
FROM python:3.13-slim
LABEL org.opencontainers.image.title="HP1-AI-Agent" \
      org.opencontainers.image.description="Self-improving AI infrastructure agent" \
      org.opencontainers.image.source="https://github.com/kbreivik/ai-local-agent-tools"
# Runtime system deps only — no compiler
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl openssh-client jq && \
    rm -rf /var/lib/apt/lists/*
# Non-root user with Docker group access.
# GID 994 matches the docker group on agent-01 — override with --build-arg DOCKER_GID
ARG DOCKER_GID=994
RUN groupadd -g ${DOCKER_GID} docker 2>/dev/null || true && \
    useradd -m -s /bin/bash -G docker agent
# Install Python wheels from builder (all deps, no pip at runtime)
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels && \
    python -c "import torch" 2>/dev/null && echo "ERROR: torch installed" && exit 1 || true
# Copy application code
WORKDIR /app
COPY . .
# Generate build_info.json stub if not present in build context (local builds without CI)
RUN if [ ! -f api/build_info.json ]; then \
      python -c "import json; json.dump( \
        {'version': open('VERSION').read().strip(), \
         'commit':'unknown','branch':'unknown', \
         'built_at':'unknown','build_number':'unknown'}, \
        open('api/build_info.json','w'))"; \
    fi
# Copy pre-built GUI from gui-builder stage
COPY --from=gui-builder /gui/dist /app/gui/dist
# Data directories — overlaid by volume mounts at runtime
RUN mkdir -p \
    data/skill_exports \
    data/skill_imports \
    data/docs \
    logs \
    checkpoints \
    mcp_server/tools/skills/modules && \
    chown -R agent:agent /app
# Entrypoint and healthcheck scripts
COPY docker/entrypoint.sh /entrypoint.sh
COPY docker/healthcheck.sh /healthcheck.sh
RUN chmod +x /entrypoint.sh /healthcheck.sh
# Ports: API (8000), GUI (5173), MCP stdio is internal
EXPOSE 8000 5173
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD /healthcheck.sh
USER agent
ENTRYPOINT ["/entrypoint.sh"]
```

---

## Change 2 — docker/entrypoint.sh — NEW FILE

Create the `docker/` directory at repo root if it doesn't exist, then create
`docker/entrypoint.sh` with the exact content below (copied from agent-01):

```bash
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
```

**Line endings matter**: this file must have LF line endings (Unix), not CRLF.
If git on the dev machine is configured with `core.autocrlf=true`, the file
may end up with CRLF after add/commit and then fail to execute inside the
container. Either:
- Configure git for this file specifically: add `docker/entrypoint.sh text eol=lf`
  and `docker/healthcheck.sh text eol=lf` to `.gitattributes` (create
  `.gitattributes` at repo root if needed), or
- Verify after creating the file: `file docker/entrypoint.sh` should NOT
  say "CRLF line terminators".

---

## Change 3 — docker/healthcheck.sh — NEW FILE

Create `docker/healthcheck.sh` with this exact content (also LF line endings):

```bash
#!/usr/bin/env bash
curl -sf "http://localhost:${API_PORT:-8000}/api/health" > /dev/null 2>&1 || exit 1
```

---

## Change 4 — .dockerignore — NEW FILE at repo root

Keeps the build context small and avoids leaking repo metadata into the image:

```
# VCS / editor
.git
.github
.vscode
.idea
*.swp

# Python caches
__pycache__
*.pyc
.pytest_cache
.mypy_cache
.ruff_cache
.venv
venv

# Node / GUI intermediate (built inside the gui-builder stage)
gui/node_modules
gui/dist
gui/.vite

# Repo-only content (not needed at runtime)
cc_prompts
tests
*.md
!VERSION

# Local scratch
*.log
*.sqlite
*.db
tmp
scratch
test_output
```

---

## Change 5 — .gitattributes — NEW FILE at repo root (if not present)

If a `.gitattributes` file already exists, append the two lines below.
Otherwise create with:

```
# Shell scripts that run inside Linux containers must stay LF.
docker/entrypoint.sh text eol=lf
docker/healthcheck.sh text eol=lf
*.sh text eol=lf
```

After adding, run:
```bash
cd D:\claude_code\ai-local-agent-tools
git add --renormalize .
```
to enforce existing files conform. Safe no-op if none need renormalising.

---

## Change 6 — cc_prompts/QUEUE_RUNNER.md — insert Step 5.5

Open `cc_prompts/QUEUE_RUNNER.md`. Find the existing Step 5 header
(`### Step 5 — Commit and push`) and the Step 6 header
(`### Step 6 — Mark DONE in INDEX.md`). Insert the new Step 5.5 between them.

Find this text:

```markdown
### Step 5 — Commit and push

Use the exact commit message from the prompt's ## Commit section.

```bash
git add -A
git commit -m "<message from prompt>"
git push origin main
```

Verify push succeeded:
```bash
git log --oneline -1
```

### Step 6 — Mark DONE in INDEX.md
```

Replace with:

```markdown
### Step 5 — Commit and push

Use the exact commit message from the prompt's ## Commit section.

```bash
git add -A
git commit -m "<message from prompt>"
git push origin main
```

Verify push succeeded:
```bash
git log --oneline -1
```

### Step 5.5 — Build and push Docker image

After the git push succeeds, build the container image and push to GHCR.
Tag with `:latest`, `:<VERSION>`, and `:sha-<short>` so every build is
addressable.

Pre-requisites (verify before attempting):
- Docker Desktop must be running on the dev machine.
- `docker login ghcr.io` must have been performed once with a PAT that
  has `write:packages` scope. The login persists across runs.
- Repo root must contain `Dockerfile`, `docker/entrypoint.sh`,
  `docker/healthcheck.sh`. Added by v2.31.12.

```bash
cd D:\claude_code\ai-local-agent-tools
VER=$(cat VERSION | tr -d '[:space:]')
SHORT=$(git rev-parse --short HEAD)
COMMIT=$(git rev-parse HEAD)
BRANCH=$(git branch --show-current)

docker build \
  --build-arg BUILD_COMMIT="${COMMIT}" \
  --build-arg BUILD_BRANCH="${BRANCH}" \
  --build-arg BUILD_NUMBER=local \
  -t ghcr.io/kbreivik/hp1-ai-agent:latest \
  -t ghcr.io/kbreivik/hp1-ai-agent:${VER} \
  -t ghcr.io/kbreivik/hp1-ai-agent:sha-${SHORT} \
  .

docker push ghcr.io/kbreivik/hp1-ai-agent:latest
docker push ghcr.io/kbreivik/hp1-ai-agent:${VER}
docker push ghcr.io/kbreivik/hp1-ai-agent:sha-${SHORT}
```

If `docker build` fails:
- Do NOT mark the prompt DONE.
- Output: `PROMPT FAILED: <version> — docker build: <first error line>`
- Stop immediately. Operator inspects the Dockerfile or logs, fixes, retries.

If `docker push` fails but build succeeded:
- Do NOT mark the prompt DONE.
- Output: `PROMPT FAILED: <version> — docker push: <error>`
- Common causes: expired PAT (refresh in GitHub settings → PAT → re-run
  `docker login ghcr.io`), GHCR rate limit, network.

### Step 6 — Mark DONE in INDEX.md
```

The existing Step 6 and Step 7 stay unchanged — they now run after Step 5.5.

---

## Commit (Changes 1-6 first)

```
git add -A
git commit -m "feat(ci): v2.31.12 Dockerfile in repo + queue runner builds and pushes image"
git push origin main
```

---

## Then — run the first build (this prompt's own Step 5.5)

After the commit pushes, execute the build + push commands from the new
Step 5.5. VERSION should already be `2.31.12` at this point (bumped earlier
in this prompt).

```bash
cd D:\claude_code\ai-local-agent-tools
VER=$(cat VERSION | tr -d '[:space:]')             # expect 2.31.12
SHORT=$(git rev-parse --short HEAD)

docker build \
  --build-arg BUILD_COMMIT=$(git rev-parse HEAD) \
  --build-arg BUILD_BRANCH=$(git branch --show-current) \
  --build-arg BUILD_NUMBER=local \
  -t ghcr.io/kbreivik/hp1-ai-agent:latest \
  -t ghcr.io/kbreivik/hp1-ai-agent:${VER} \
  -t ghcr.io/kbreivik/hp1-ai-agent:sha-${SHORT} \
  .

docker push ghcr.io/kbreivik/hp1-ai-agent:latest
docker push ghcr.io/kbreivik/hp1-ai-agent:${VER}
docker push ghcr.io/kbreivik/hp1-ai-agent:sha-${SHORT}
```

After push, verify the digest and emit a short summary so the operator knows
what was published:

```bash
docker inspect --format '{{index .RepoDigests 0}}' ghcr.io/kbreivik/hp1-ai-agent:2.31.12
echo "v2.31.12 published: :latest, :2.31.12, :sha-${SHORT}"
```

---

## How to test after completion

On agent-01:

```bash
docker pull ghcr.io/kbreivik/hp1-ai-agent:2.31.12
docker pull ghcr.io/kbreivik/hp1-ai-agent:latest
# Confirm same digest:
docker inspect --format '{{index .RepoDigests 0}}' ghcr.io/kbreivik/hp1-ai-agent:2.31.12
docker inspect --format '{{index .RepoDigests 0}}' ghcr.io/kbreivik/hp1-ai-agent:latest

cd /opt/hp1-agent/docker
docker compose pull hp1_agent
docker compose up -d hp1_agent
sleep 8
curl -s http://192.168.199.10:8000/api/health | python3 -m json.tool | head -8
# Expect: "version": "2.31.12"
```

Then walk through the stacked changes:

1. **v2.31.3 live output** — hard-refresh UI, DevTools Network WS tab:
   request URL `ws://192.168.199.10:8000/ws/output` (no `?token=`),
   status 101. Run an observe task, Output panel streams in real time.

2. **v2.31.6 Recent Actions tab** — Logs → Actions, table populates.

3. **v2.31.7 sanitiser** — run normal task, no regression.
   `docker logs hp1_agent 2>&1 | grep prompt_sanitiser` (usually empty, fine).

4. **v2.31.8 caps** —
   `docker exec hp1_agent python -c "from api.routers.agent import _AGENT_MAX_WALL_CLOCK_S; print(_AGENT_MAX_WALL_CLOCK_S)"`
   → `600`.

5. **v2.31.10 blackouts** —
   `curl -s -b /tmp/hp1.cookies http://192.168.199.10:8000/api/agent/blackouts`
   → `{"blackouts": []}`.

6. **v2.31.11 regression tests** —
   `docker exec -w /app hp1_agent python -m pytest tests/test_tool_safety.py -v`
   → all pass.

Future CC prompts now auto-build + push via the updated QUEUE_RUNNER.md.

---

## Notes

- Line endings (CRLF vs LF) on the shell scripts are the single most common
  failure mode here — if the container starts and immediately exits with
  "no such file or directory: /usr/bin/env\\r" style errors, fix via
  `.gitattributes` per Change 5 and rebuild.
- If `docker build` on Windows complains about permissions on the entrypoint
  scripts, the Dockerfile's `chmod +x` inside the runtime stage handles that —
  the files don't need to be executable on the host.
- GitHub Actions CI (no operator-online dependency) is a clean next step
  but not required. `Dockerfile` + `docker/entrypoint.sh` + `docker/healthcheck.sh`
  in the repo are prerequisites regardless.
