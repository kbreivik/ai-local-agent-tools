---
description: Run the Docker build and deployment test checklist
argument-hint: build | compose | swarm | all
---

Run the appropriate test suite based on $ARGUMENTS (default: all).

## Pre-test checks
```bash
# Verify DOCKER_GID
stat -c '%g' /var/run/docker.sock

# Verify no secrets in image layers (after build)
docker history hp1-ai-agent:latest --no-trunc | grep -i "password\|secret\|token"
```

## Build tests
```bash
# Build with correct GID
docker build \
  --build-arg DOCKER_GID=$(stat -c '%g' /var/run/docker.sock) \
  -t hp1-ai-agent:latest \
  -f docker/Dockerfile .

# Image size check — must be under 500MB
docker image inspect hp1-ai-agent:latest --format='{{.Size}}' | \
  awk '{printf "Image size: %.0f MB\n", $1/1024/1024}'
```

Checklist:
- [ ] Build succeeds without errors
- [ ] Image size < 500MB
- [ ] No secrets in `docker history` output

## Docker Compose tests
```bash
cd docker
set -a; source .env; set +a
docker compose -f docker-compose.yml up -d

# Wait for health check
sleep 20

# API responds
curl -sf http://localhost:8000/api/health | python3 -m json.tool

# GUI loads (should return HTML)
curl -sf http://localhost:8000/ | head -5

# Volumes exist
docker volume ls | grep hp1-agent

# Audit log writes to volume
docker exec hp1-agent ls -la /app/logs/

# Skills DB initialized
docker exec hp1-agent python -c \
  "from mcp_server.tools.skills.registry import init_db; init_db(); print('DB OK')"

# Dynamic skills volume accessible
docker exec hp1-agent ls /app/mcp_server/tools/skills/modules/
```

Checklist:
- [ ] `docker compose up -d` starts cleanly
- [ ] Health check passes within 30s
- [ ] `GET /api/health` returns `{"status": "ok"}`
- [ ] GUI loads at port 8000
- [ ] All 4 volumes created (data, logs, checkpoints, skills)
- [ ] Audit log directory writable
- [ ] Skills DB initializes without error
- [ ] Dynamic skills directory accessible

## Persistence test
```bash
docker compose -f docker/docker-compose.yml down
docker compose -f docker/docker-compose.yml up -d
sleep 15
# Skills should still be there
curl -s http://localhost:8000/api/skills | python3 -m json.tool
```

Checklist:
- [ ] Skills survive `down && up`
- [ ] SQLite DB data persists

## Degradation tests (graceful — agent must still start)
```bash
# Test: no Docker socket
docker run --rm hp1-ai-agent:latest 2>&1 | grep -i "docker\|warn" | head -5
# Expected: "[init] WARNING: No Docker socket found"

# Test: bad LM URL
docker run --rm -e LM_STUDIO_BASE_URL=http://127.0.0.1:9999/v1 \
  hp1-ai-agent:latest 2>&1 | head -20
# Expected: starts despite LLM being unreachable

# Test: no Kafka
docker run --rm -e KAFKA_BOOTSTRAP_SERVERS="" hp1-ai-agent:latest 2>&1 | head -20
# Expected: starts, Kafka tools return unavailable
```

Checklist:
- [ ] Missing Docker socket → starts with warning, Docker tools return errors
- [ ] Missing LLM → starts, `skill_create` returns clear error
- [ ] Missing Kafka → starts, Kafka tools return "unavailable"
- [ ] Missing Elasticsearch → starts, Elastic tools return "unavailable"

## Swarm tests (if Swarm is active)
```bash
# Deploy
cd docker && set -a; source .env; set +a
docker stack deploy -c swarm-stack.yml hp1

# Check replicas (should be 1, not 2 — SQLite constraint)
docker service ls | grep hp1_agent

# Health via Swarm routing mesh
curl -sf http://localhost:8000/api/health

# Logs
docker service logs hp1_agent --tail 20

# Rolling update test
docker service update --image hp1-ai-agent:latest hp1_agent
docker service ps hp1_agent
```

Checklist:
- [ ] Stack deploys without error
- [ ] `replicas: 1` in swarm-stack.yml (not 2 — SQLite constraint)
- [ ] Health check works via Swarm routing mesh
- [ ] Rolling update completes without container crash
- [ ] `docker service logs` shows normal startup

## Airgapped test
```bash
docker save hp1-ai-agent:latest | gzip > /tmp/hp1-agent-test.tar.gz
ls -lh /tmp/hp1-agent-test.tar.gz
docker rmi hp1-ai-agent:latest
docker load < /tmp/hp1-agent-test.tar.gz
docker run --rm hp1-ai-agent:latest 2>&1 | head -5
# Expected: "HP1-AI-Agent — Starting"
```

Checklist:
- [ ] `docker save | gzip` succeeds
- [ ] `docker load` restores image on clean host
- [ ] Container starts with no internet access

## Report results
Summarise pass/fail for each section. Flag any failures with specific error output.
