---
description: Write session state before ending any session
---

Write `state/HANDOFF.md` (overwrite):

```markdown
# HANDOFF — <ISO timestamp>

## Git state
<run: git log --oneline -5>
<run: git status --short>

## Agent state
<curl -s http://192.168.199.10:8000/api/health | python3 -c "import sys,json; h=json.load(sys.stdin); print(f\"v{h['version']} build {h['build_info']['build_number']} {h['deploy_mode']}\")">
Skills registered: <count from /api/skills>

## Active plan
<check state/plans/ — any PLAN-*.md with status: pending?>
Plan file: <path if exists>

## What was accomplished this session
- <specific files created/modified — name them>
- <skills added: name + category>
- <MCP tools registered>
- <Docker build/deploy actions>

## Decisions made
- <why specific implementation choices>
- <any patterns established>

## Dead ends
- <approaches abandoned and why>

## Active issues
- <any errors not resolved>
- <Filebeat stale alert: ongoing — not a blocker>

## Exact next action
<one clear sentence>

## Context files for next session
- state/plans/PLAN-<n>.md (if active)
- mcp_server/tools/skills/modules/<n>.py (if in progress)
- <any other specific files>
```
