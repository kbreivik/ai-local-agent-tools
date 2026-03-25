---
description: Create an enriched commit with pre-commit checks
---

!`git diff --cached --stat`
!`git diff --cached`

Run pre-commit checks silently:
1. `grep -rE "192\.168\.|password|secret|token|api_key\s*=" --include="*.py"` on staged files — abort if hits
2. `python -m py_compile <each staged .py>` — abort on syntax error
3. For skill modules: verify SKILL_META dict present, execute() is sync (no async def)
4. For GUI files: `grep -r "localhost:8000\|localhost:5173" --include="*.jsx" --include="*.vue"` — abort if hits
5. For server.py changes: verify no new async def added

If all pass, create commit:
- Prefix: `feat|fix|refactor|docs|test(scope): `
- Scope examples: `skill/<n>`, `mcp`, `api`, `gui`, `docker`, `agent`, `storage`
- Imperative subject, ≤72 chars
- Body: WHY this change

Examples:
```
feat(skill/kafka): add kafka_consumer_lag skill

Consumer lag monitoring needed for proactive alert before queue backup.
Built spec-first: validated against live Kafka at bootstrap_servers env var.
Compat: kafka 3.6, version endpoint /api/v1/metadata/id, field version.

feat(mcp): register kafka_consumer_lag and kafka_topic_health tools

Two new Kafka tools registered in server.py. Both call into
mcp_server/tools/kafka_tools.py — lazy import pattern maintained.
```

Then: `git push`
