---
description: Plan a Docker build, config change, or deployment action
argument-hint: <describe the change: rebuild / env change / upgrade / swarm deploy>
---

## Research phase

Spawn **service-scout** to check:
1. Current agent version: `curl -s http://192.168.199.10:8000/api/health`
2. Current container state: running build number, deploy mode
3. Recent git changes: `git log --oneline -5`

## Classify the task

### If rebuilding the image (code change):
```
Trigger: code changes to api/, mcp_server/, agent/, gui/, docker/
Action:  docker compose down → build → up
Risk:    LOW if volumes intact — skills and DB survive
Session split: not needed
```

### If changing .env config:
```
Trigger: env var change (ELASTIC_FILEBEAT_STALE_MINUTES, ADMIN_PASSWORD, etc.)
Action:  Edit docker/.env → docker compose up -d (recreates container only)
Risk:    LOW — volumes unaffected, config change only
NOTE:    docker/.env is managed by Ansible in hp1-infra
         If the var is set via vault/group_vars there, change it there, not here
```

### If deploying to Swarm (upgrade testing):
```
Trigger: testing a new service version
Action:  Use /plan-upgrade instead — it handles pre_upgrade_check, plan_action, etc.
```

### If changing Dockerfile or docker-compose.yml:
```
Risk:    MEDIUM — full rebuild needed, test with /test-docker
Must check: DOCKER_GID still correct, volumes still correct names
```

## Write plan to `state/plans/PLAN-docker-$ARGUMENTS.md`

```markdown
# Docker Plan: $ARGUMENTS
Date: <timestamp>
Status: pending

## Current state
<service-scout summary>

## Change type
[ ] Code rebuild  [ ] Config change  [ ] Dockerfile change  [ ] Swarm deploy

## Steps
1. [ ] <specific step>
   Command: `<exact command>`
2. [ ] Verify: `curl -s http://192.168.199.10:8000/api/health`
3. [ ] Check build number incremented (if code change)
4. [ ] /commit

## SQLite constraint check
replicas in swarm-stack.yml: <check — must be 1, not 2>
API_WORKERS in .env: <check — must be 1>

## Rollback
`docker compose down && docker compose up -d` (restores previous state from volumes)
```

Do NOT execute. Plan only.
