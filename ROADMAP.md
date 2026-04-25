# DEATHSTAR — Roadmap & Architecture Reference

**Repo:** `github.com/kbreivik/ai-local-agent-tools` (MIT, public)
**Deploy target:** `agent-01` at `192.168.199.10:8000`
**Image:** `ghcr.io/kbreivik/hp1-ai-agent:latest`
**Local AI:** Qwen3-Coder-30B-A3B via LM Studio at `192.168.199.51:1234`
**Hardware:** AMD Ryzen AI MAX+ 395 / Radeon 8060S / 128GB unified
**Stack:** FastMCP + FastAPI (Python) + React (Vite) + PostgreSQL (pgvector) + MuninnDB

> **What's shipped** lives in `cc_prompts/QUEUE_STATUS.md` (261 prompts, every commit).
> **Current state** lives in `docs/STATUS_REPORT_*.md` (latest snapshot).
> This document is the forward-looking plan + architecture reference.

---

## Vision

A fully local AI infrastructure control plane. The agent inspects, plans,
upgrades, and monitors a production-grade Docker Swarm + Kafka cluster —
with checks and balances at every step, full audit logging, cognitive memory
that learns from past operations, and a live web GUI accessible over the LAN.

External AI (Claude / OpenAI / Grok) is used only for escalations the local
model flags as high-risk or beyond its confidence. Every decision is logged,
every escalation is reasoned, and the system gets smarter with every run.

---

## Architecture (Current)

```
┌──────────────────────────────────────────────────────────────────────┐
│                       Web GUI (React + Vite)                          │
│  Dashboard · Cluster · Logs · Kafka · Facts · Gates · Discovered ·    │
│  Collectors · Commands · Skills · Runbooks · Output · Tests · Docs ·  │
│  Settings · Analysis (sith_lord)                                      │
│                       LAN: 0.0.0.0:5173                               │
└─────────────────────────┬────────────────────────────────────────────┘
                          │ WebSocket + REST (cookie auth, optional TLS)
┌─────────────────────────▼────────────────────────────────────────────┐
│                  FastAPI Backend (api/)                               │
│  routers/   collectors/   agents/   facts/   memory/   db/  security/ │
│                       LAN: 0.0.0.0:8000                               │
└──┬──────────┬──────────┬──────────┬─────────────┬───────────────────┘
   │          │          │          │             │
┌──▼──┐ ┌────▼────┐ ┌───▼────┐ ┌───▼─────────┐ ┌─▼────────┐
│ MCP │ │Postgres │ │MuninnDB│ │Elasticsearch│ │External  │
│Tools│ │+pgvector│ │ + PG   │ │ + Filebeat  │ │AI router │
└──┬──┘ │(opslog +│ │engrams │ │             │ │(Claude/  │
   │    │ facts)  │ └────────┘ └─────────────┘ │ OpenAI / │
   │    └─────────┘                             │ Grok)    │
   │                                            └──────────┘
┌──▼──────────────────────────────────────────────────────────────┐
│                       Infrastructure                             │
│  Proxmox cluster · Docker Swarm 3+3 · Kafka KRaft 3-broker      │
│  PBS · TrueNAS · UniFi · FortiGate · FortiSwitch                │
└─────────────────────────────────────────────────────────────────┘
```

---

## AI Routing Policy

| Task | Model | Why |
|------|-------|-----|
| Status checks | Local (Qwen3-Coder) | Deterministic, fast, structured tools |
| Routine upgrades | Local | Well-understood patterns + plan_action gate |
| Health gate decisions | Local | Tool output is structured |
| RAG doc lookup | Local | MuninnDB / pg_engrams handles retrieval |
| Known failure patterns | Local | Memory surfaces context |
| Unknown failure mode | **External (router rule)** | No prior context, low-confidence local synthesis |
| Multi-system cascading failure | **External (router rule)** | Reasoning depth exceeds local model |
| High-risk irreversible action | **External (router rule)** | Second opinion required |
| Operator forces external | **External (force_external flag)** | Bypass router, still gated by confirmation |

Every model used is recorded in `agent_llm_traces.model` and
`external_ai_calls.provider`. Local vs external ratio tracked in StatsBar.
Router rules live in `api/agents/external_router.py` (5 rules, settings-tunable).

---

## MCP Servers (development-time)

| Server | Purpose |
|--------|---------|
| `infra-agent` | Production tool registry — Docker Swarm, Kafka, Elasticsearch, vm_exec, runbooks, skills |
| `jcodemunch` | Token-efficient code navigation (AST-based) |

**Config:** `.claude/settings.json` + `.mcp.json` in project root.

---

## What Requires External AI and Why

| Situation | Why local cannot handle it | Router rule |
|-----------|---------------------------|-------------|
| Unknown failure mode with no past engrams | No memory context to reason from | `low_memory_confidence` |
| Cascading failure across Swarm + Kafka + Elastic | Too many interacting systems | `cascading_failure` |
| Repeated failed attempts on same entity | Local model stuck in same path | `prior_failed_attempts` |
| Hallucination guard or fabrication detector exhausted | Local output not trustworthy | `local_synthesis_failed` |
| Tool budget exhausted without DIAGNOSIS | Local couldn't converge | `budget_exhaustion` |

External AI receives: escalation reason + top-N memory engrams +
current status snapshot + correlated log context + last N tool results.
This grounds the response in real operational history, not just the
current error message.

Output modes: `replace` (only mode currently implemented; `augment` and
`replace+shrink` accepted by settings but fall back to `replace` at runtime —
real implementations are future work).

---

## Forward-looking work

### Code-level (queue these as CC prompts)
- `runbookInjectionMode=augment` real implementation
- External AI `augment` / `side-by-side` output modes
- FortiSwitch + `external_services` collectors writing to `known_facts_current`
- Entity timeline UI (data + schema are live; UI surface missing)
- Multi-agent parallel sub-agent execution (design pass needed first)
- Expand agent task template library (rolling kafka restart, drain-and-cordon, etc.)
- Multi-connection scope audit on `get_connection_for_platform()`

### Operational (manual / on-host)
- Reboot `worker-03` to recover Kafka RF=3
- Move WireGuard/OpenVPN endpoint from dev PC to agent-01
- Run real notification delivery smoke test (SMTP + webhook recipients)
- Run auth hardening verification checklist (cookie/TLS/rate-limit/Bearer)

### Out of scope (deliberately)
- Multi-tenancy / per-user data isolation — single-operator deployment
- Cloud-hosted deployment — homelab is a primary target
- Public API publishing — internal use only

---

## Environment variables (current)

```env
# Database
DATABASE_URL=postgresql+asyncpg://hp1user:hp1pass@localhost:5432/hp1_agent
SQLITE_PATH=data/hp1_agent.db   # fallback only

# Local AI
LM_STUDIO_BASE_URL=http://192.168.199.51:1234/v1
LM_STUDIO_API_KEY=
LM_STUDIO_MODEL=lmstudio-community/qwen3-coder-30b-a3b-instruct

# Encryption (mandatory)
SETTINGS_ENCRYPTION_KEY=<Fernet key — never commit>

# Auth
HP1_BEHIND_HTTPS=false   # set true when nginx TLS proxy in front
JWT_SECRET=<long random string>

# CORS
CORS_ALLOW_ALL=false
CORS_ORIGINS=http://localhost:5173,http://192.168.199.10:5173

# Memory
MUNINN_URL=http://muninndb:9475
MEMORY_BACKEND=muninn   # or 'pg' for pg_engrams backend, 'null' to disable

# External AI (encrypted in DB; env values are bootstrap only)
EXTERNAL_PROVIDER=claude
EXTERNAL_MODEL=claude-sonnet-4-20250514

# Agent caps
AGENT_MAX_WALL_CLOCK_S=600
AGENT_MAX_TOTAL_TOKENS=120000
AGENT_MAX_DESTRUCTIVE=3
AGENT_MAX_TOOL_FAILURES=8
AGENT_HALLUC_GUARD_MAX_ATTEMPTS=3
AGENT_FABRICATION_MIN_CITES=3
AGENT_FABRICATION_SCORE_THRESHOLD=0.5

# Sub-agent caps
SUBAGENT_MAX_DEPTH=2
SUBAGENT_MIN_PARENT_RESERVE=2
SUBAGENT_TREE_WALL_CLOCK_S=1800
SUBAGENT_NUDGE_THRESHOLD=0.60

# Elastic
ELASTIC_URL=http://elasticsearch:9200
ELASTIC_INDEX_PATTERN=hp1-logs-*
CORRELATION_WINDOW_SECONDS=300

# Kafka
KAFKA_UNDER_REPLICATED_THRESHOLD=1
```

Many runtime tunables also live in the Settings registry (`api/routers/settings.py`)
and are operator-editable without redeploy.

---

## Entity ID format

```
proxmox:{name}:{vmid}              e.g. proxmox:graylog:119
cluster:proxmox:{cluster_name}     e.g. cluster:proxmox:Pmox Cluster KB
unifi:device:{mac}
pbs:{label}:{datastore}
truenas:pool:{name}
fortigate:iface:{name}
fortiswitch:port:{port_id}
swarm:service:{name}
swarm:node:{hostname}
kafka:broker:{id}
kafka:topic:{name}
docker:{label}:{container_name}
vm_host:{label}
external_services:{slug}
connection:{id}
```

---

## Key paths

```
api/main.py                        — FastAPI lifespan + DB init + background loops
api/maintenance.py                 — periodic background tasks (extracted v2.45.33)
api/scheduler.py                   — test schedule executor (v2.45.19)
api/routers/agent.py               — agent loop entry, _stream_agent + _run_single_agent_step
api/agents/                        — split agent loop modules
  ├── pipeline.py                  — _stream_agent setup
  ├── orchestrator.py              — step planner, coordinator, contradiction detection
  ├── router.py                    — task classifier, allowlists, prompts
  ├── step_state.py                — StepState dataclass (per-run accumulators)
  ├── step_llm.py                  — LLM call + trace
  ├── step_tools.py                — tool dispatch loop (split by category)
  ├── step_facts.py                — fact extraction, contradiction, zero-pivot guards
  ├── step_guard.py                — hallucination guard + fabrication detector
  ├── step_synth.py                — forced synthesis paths
  ├── step_persist.py              — agent_observation fact writer (v2.45.25)
  ├── gates.py                     — gate functions (preamble, terminal classification)
  ├── context.py                   — prompt context builders
  ├── preflight.py                 — entity preflight + 3-tier extractor
  ├── runbook_classifier.py        — semantic runbook match (bge-small-en-v1.5)
  ├── external_router.py           — external AI escalation rules
  ├── external_ai_client.py        — Claude/OpenAI/Grok synthesis
  └── task_templates/              — bundled investigation/action templates

api/collectors/                    — auto-discovered platform collectors
api/facts/extractors.py            — collector → known_facts extraction
api/db/                            — module-managed schema + queries
api/memory/                        — MuninnDB + pg_engrams clients

mcp_server/tools/                  — MCP tool implementations
plugins/                           — per-platform plugin scaffolding

gui/src/components/                — React components
gui/src/context/                   — global contexts (auth, dashboard, agent output)

cc_prompts/                        — improvement queue (write CC prompt → run_queue.sh)
docs/                              — architecture + status reports
scripts/check_sensors.py           — sensor stack runner (ruff/bandit/gitleaks/eslint)
```

---

## Sensor stack

`make check` — full run (ruff, bandit, gitleaks, eslint).
`make check-agent` — agent-optimized output (failures only with HINTs).
`make check-all` — also runs mypy.

CI runs `make check` on PR + push to main. See `.github/workflows/sensors.yml`.

Configs: `.ruff.toml`, `.bandit`, `.gitleaks.toml`, `.eslintrc.sensors.json`.
