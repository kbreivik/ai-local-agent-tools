# DEATHSTAR CC Prompt Queue

Agreed improvement phases from architecture review on 2026-04-12.
Run in version order. Each file is a standalone CC prompt.

Earlier prompts (v2.6.x–v2.7.x) archived in cc_prompts/archive/.

---

## Automated Queue Runner

```bash
# Git Bash (recommended)
cd /d/claude_code/ai-local-agent-tools
bash cc_prompts/run_queue.sh --dry-run   # preview
bash cc_prompts/run_queue.sh --one       # run next one (supervised)
bash cc_prompts/run_queue.sh             # run all

# PowerShell (Windows Terminal)
cd D:\claude_code\ai-local-agent-tools
.\cc_prompts\run_queue.ps1 -DryRun
.\cc_prompts\run_queue.ps1 -One
.\cc_prompts\run_queue.ps1
```

Use `--dangerously-skip-permissions` (already in run_queue.sh) so CC runs without
per-file approval prompts. The prompts are reviewed — git is the safety net.

---

## Phase Queue

| File | Version | Theme | Status |
|---|---|---|---|
| CC_PROMPT_v2.8.0.md | v2.8.0 | AI loop: semantic tool routing + thinking memory + feedback pre-ranking | DONE (69b4e7d) |
| CC_PROMPT_v2.8.1.md | v2.8.1 | LLM temperature profile + /no_think for cheap steps | DONE (6bd67ea) |
| CC_PROMPT_v2.9.0.md | v2.9.0 | Entity state DB: change tracking + event log + image digest | DONE (8b08f17) |
| CC_PROMPT_v2.9.1.md | v2.9.1 | Entity history agent tools + context injection + GUI badge | PENDING |
| CC_PROMPT_v2.10.0.md | v2.10.0 | Lightweight coordinator pattern between agent steps | PENDING |
| CC_PROMPT_v2.10.1.md | v2.10.1 | Small fixes: alert transition badge + FortiGate filter bar + snapshot retention | PENDING |
| CC_PROMPT_v2.11.0.md | v2.11.0 | Multi-connection collectors: all platforms use get_all_connections | PENDING |
| CC_PROMPT_v2.11.1.md | v2.11.1 | PBS collector implementation | PENDING |
| CC_PROMPT_v2.12.0.md | v2.12.0 | Auth hardening: httpOnly cookies + login rate limiting | PENDING |
| CC_PROMPT_v2.12.1.md | v2.12.1 | Security dashboard: SSH capability map + new-host alerts UI | PENDING |
| CC_PROMPT_v2.13.0.md | v2.13.0 | Skill system: spec-first generation + environment discovery | PENDING |
| CC_PROMPT_v2.13.1.md | v2.13.1 | Skill system: skill_execute dispatcher + three-layer validation | PENDING |
| CC_PROMPT_v2.14.0.md | v2.14.0 | Notification system: email + webhook for critical events | PENDING |

---

## Version bump rationale

| Bump | Meaning |
|---|---|
| x.x.1 | Fix, tuning, small addition |
| x.1.x | New subsystem, architectural change, multi-file feature |

---

## Phase summaries

**v2.8.0** — Semantic tool routing via bge-small-en-v1.5 (already loaded for RAG).
LLM sees top-10 relevant tools instead of all ~20. Thinking memory extracts key facts
from `<think>` blocks for inter-step continuity. Feedback pre-ranking boosts historically
successful tools to front of manifest.

**v2.8.1** — Force-summary calls use temperature 0.3. `/no_think` for audit_log-only
steps saves 200-400 tokens. `min_p=0.1` for consistent JSON args.

**v2.9.0** — `entity_changes` + `entity_events` tables. Collectors detect field-level
diffs between polls. Image digest tracking catches silent re-deploys.

**v2.9.1** — `entity_history()` + `entity_events()` agent tools. Recent changes/events
injected into system prompt when task mentions a known entity. GUI card badges.

**v2.10.0** — Adaptive coordinator: tiny LLM call (no tools, 200 tokens, /no_think)
between steps. Decides done/continue/query/escalate. Dynamic step extension. Structured
JSON context between steps replaces prose summaries.

**v2.10.1** — Alert health-transition badge (healthy → degraded). FortiGate
ConnectionFilterBar. status_snapshots daily cleanup.

**v2.11.0** — `external_services.py` switches from `get_connection_for_platform()`
(LIMIT 1) to `get_all_connections_for_platform()` — every registered connection gets
its own probed card. Fixes same issue in any other collectors.

**v2.11.1** — PBS collector: PBSAPIToken auth, per-datastore usage cards, failed task
detection, STORAGE section entities.

**v2.12.0** — JWT moves from localStorage to httpOnly `SameSite=Strict` cookie.
`get_current_user()` accepts cookie OR Authorization header. `slowapi` rate limit on
login (5/min/IP).

**v2.12.1** — Settings → SSH Access tab: credential→host capability map, success rates,
new-host alert badges, recent SSH attempt log.

**v2.13.0** — `spec_generator.py`: description → SKILL_SPEC JSON before code.
`live_validator.py`: probes actual endpoints to verify spec. `fingerprints.py`: 12
service fingerprints for deterministic identification. `discover_environment()`: 4-phase
enumerate → fingerprint → catalog → recommend.

**v2.13.1** — Single `skill_execute` dispatcher replaces N individual skill tools
(context reduction). `validate_skill_live`: three-layer validation — deterministic +
live probe + optional LLM critic.

**v2.14.0** — Async SMTP email + HTTP webhook delivery. Per-event-type routing rules.
1-per-hour rate limiting. Wired into `fire_alert()` and `write_event()`. Settings →
Notifications tab with channel CRUD + delivery log.

---

## Key file paths for CC context

```
api/routers/agent.py          — agent loop, safety gates, _summarize_tool_result
api/agents/router.py          — classifier, domain detector, tool allowlists, prompts
api/agents/orchestrator.py    — step planner, verdict extraction, coordinator (v2.10+)
api/memory/hooks.py           — MuninnDB before/after_tool_call hooks
api/memory/feedback.py        — outcome recording, past_outcomes retrieval
api/rag/doc_search.py         — pgvector hybrid search (bge-small-en-v1.5 ONNX)
api/db/entity_history.py      — entity_changes + entity_events tables (v2.9.0+)
api/db/result_store.py        — large result storage + temp table queries
api/db/ssh_log.py             — SSH attempt log
api/db/ssh_capabilities.py    — credential→host capability map
api/db/infra_inventory.py     — hostname/IP SOT
api/db/notifications.py       — notification channels/rules/log (v2.14+)
api/notifications.py          — SMTP + webhook delivery engine (v2.14+)
api/collectors/external_services.py — platform health probes (multi-connection v2.11+)
api/collectors/vm_hosts.py    — SSH polling, _ssh_run, change detection (v2.9.0+)
api/collectors/swarm.py       — Docker SDK swarm polling, image digest tracking
api/collectors/pbs.py         — PBS datastore collector (v2.11.1+)
mcp_server/tools/vm.py        — vm_exec, infra_lookup, ssh_capabilities
mcp_server/tools/docker_api.py   — docker_df, docker_prune, docker_images
mcp_server/tools/result_tools.py — result_fetch, result_query
mcp_server/tools/meta_tools.py   — discover_environment, skill_execute (v2.13+)
mcp_server/tools/skills/modules/spec_generator.py — SKILL_SPEC generation (v2.13+)
mcp_server/tools/skills/modules/live_validator.py  — spec + skill validation (v2.13+)
mcp_server/tools/skills/modules/fingerprints.py    — service fingerprints (v2.13+)
plugins/unifi_network_status.py  — UniFi plugin (DB-first credentials)
gui/src/components/            — React frontend components
```

## Stack

- FastAPI + Python backend
- React + Vite frontend
- Postgres (pgvector/pg16) at 127.0.0.1:5433
- MuninnDB (Hebbian memory) at ghcr.io/scrypster/muninndb
- LM Studio (Qwen3-coder-next) at env LM_STUDIO_BASE_URL
- Docker Compose deploy on Linux 192.168.199.10:8000
- Repo: https://github.com/kbreivik/ai-local-agent-tools
