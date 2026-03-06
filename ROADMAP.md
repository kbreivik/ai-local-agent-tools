# HP1-AI-Agent-v1 — Master Roadmap

**Project Path:** `D:/claude_code/FAJK/HP1-AI-Agent-v1/`  
**Local AI:** Qwen3-Coder-30B-A3B via LM Studio (`localhost:1234`)  
**Hardware:** AMD Ryzen AI MAX+ 395 / Radeon 8060S / 128GB unified memory  
**Infrastructure:** Docker Swarm (3 mgr + 3 wkr VMs on Proxmox) + Kafka (KRaft) + Filebeat + Elasticsearch

---

## Vision

A fully local AI infrastructure control plane. The agent inspects, plans,
upgrades, and monitors a production-grade Docker Swarm + Kafka cluster —
with checks and balances at every step, full audit logging, cognitive memory
that learns from past operations, and a live web GUI accessible over the LAN.

External AI (Claude) is used only for escalations the local model flags as
high-risk or beyond its confidence. Every decision is logged, every escalation
is reasoned, and the system gets smarter with every run via MuninnDB Hebbian
learning.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Web GUI (React + Vite)                    │
│  Commands | Live Output | Status | Logs | Memory | Logs     │
│  LAN accessible: 0.0.0.0:5173                               │
└──────────────────────┬──────────────────────────────────────┘
                       │ WebSocket + REST
┌──────────────────────▼──────────────────────────────────────┐
│                   FastAPI Backend                            │
│  Tool Registry | Agent Router | Collectors | Correlator      │
│  LAN accessible: 0.0.0.0:8000                               │
└──────┬──────────┬──────────┬──────────┬─────────────────────┘
       │          │          │          │
  ┌────▼───┐ ┌───▼────┐ ┌───▼────┐ ┌──▼──────────┐
  │  MCP   │ │Postgres│ │MuninnDB│ │Elasticsearch│
  │ Server │ │(logs)  │ │(memory)│ │(infra logs) │
  └────┬───┘ └────────┘ └────────┘ └─────────────┘
       │
┌──────▼────────────────────────────────────────┐
│              Infrastructure                    │
│  Docker Swarm: 3 managers + 3 workers          │
│  Kafka: 1 KRaft broker per worker (3 total)    │
│  Filebeat: 1 per node → Elasticsearch          │
└───────────────────────────────────────────────┘
```

---

## AI Routing Policy

| Task | Model | Why |
|------|-------|-----|
| Status checks | Local (Qwen3-Coder) | Deterministic, fast |
| Routine upgrades | Local | Well-understood patterns |
| Health gate decisions | Local | Tool output is structured |
| RAG doc lookup | Local | MuninnDB handles retrieval |
| Known failure patterns | Local | MuninnDB memory surfaces context |
| Unknown failure mode | **Claude (external)** | Unfamiliar territory |
| Multi-system cascading failure | **Claude (external)** | Too complex for local |
| High-risk irreversible action | **Claude (external)** | Second opinion required |

Every model used is recorded in `tool_calls.model_used`. Local vs external
ratio tracked in StatsBar. Escalations stored as MuninnDB engrams.

---

## MCP Servers

| Server | Purpose |
|--------|---------|
| `infra-agent` | Docker Swarm + Kafka + Orchestration tools |
| `jcodemunch` | Token-efficient code navigation (AST-based) |

**Config:** `.claude/settings.json` + `.mcp.json` in project root.

jcodemunch reduces token usage by up to 99% on large codebases by
retrieving only the exact symbols needed instead of full files.

---

## Phase Overview

| Phase | Status | Delivers |
|-------|--------|---------|
| 1-2 | ✅ Complete | FastAPI + React GUI + Tool Registry + WebSocket streaming |
| 3 | ✅ Complete | PostgreSQL logging + SQLite fallback + audit trail |
| 4 | 🔲 Next | Live Swarm + Kafka status panels + NodeMap + alerting |
| 5 | 🔲 | MuninnDB memory + docs RAG + semantic triggers |
| 6 | 🔲 | Filebeat + Elasticsearch + log correlation + full observability |

---

## Phase 1-2: Web GUI + FastAPI + Tool Registry

**Goal:** Working GUI shell. Tool registry auto-discovers MCP tools.
Agent output streams live to the browser over WebSocket.

### What Was Built
- `api/` — FastAPI backend, 4 routers, WebSocket manager
- `api/tool_registry.py` — auto-discovers `mcp_server/tools/*.py`
- `api/db.py` — SQLite with 3 tables: operations, tool_calls, status_snapshots
- `gui/` — Vite + React + Tailwind, 4 components
- `start.bat` — one-command startup for Windows

### Key Design Decisions
- Tool registry is dynamic — add a `.py` file to `tools/` = auto-appears in GUI
- WebSockets for streaming (not polling) — agent output appears instantly
- SQLite first — zero infrastructure dependency for prototype
- Backend binds `0.0.0.0:8000` — LAN accessible from Proxmox network

### GUI Layout
```
┌──────────────┬──────────────────────┬───────────────┐
│   COMMANDS   │    LIVE OUTPUT       │    STATUS     │
│  (tool list) │  (WebSocket stream)  │  (placeholders│
│              │  ✓ ✗ ⚡ ⚠           │   Phase 4)    │
├──────────────┴──────────────────────┴───────────────┤
│  LOGS  [filter: all | success | failure | escalated] │
└─────────────────────────────────────────────────────┘
```

### Claude Code Prompt — Phase 1-2
```
You are operating with full autonomy. Do not ask for permission before taking 
action. Make decisions, implement, test, and iterate independently.

## Project: HP1-AI-Agent-v1 — Phase 1-2: Web GUI + FastAPI Backend + Tool Registry

### Project Path
D:/claude_code/FAJK/HP1-AI-Agent-v1/

### Context
This is Phase 1-2 of a local AI infrastructure orchestration platform.
The existing project already has:
- mcp_server/ with Docker Swarm + Kafka + orchestration tools
- agent/agent_loop.py connecting to LM Studio (Qwen3-Coder-30B-A3B)
- docker/ with swarm and kafka stacks
- .mcp.json and .claude/settings.json configured

Do not break or remove anything already built. Extend the project.

### What to Build

#### 1. FastAPI Backend (api/)
- api/main.py — FastAPI app entry point
- api/routers/tools.py — tool registry endpoints
- api/routers/agent.py — agent execution endpoint
- api/routers/status.py — infrastructure status endpoint
- api/routers/logs.py — log retrieval endpoint
- api/websocket.py — WebSocket manager for streaming agent output to GUI
- api/tool_registry.py — auto-discovers tools from mcp_server/tools/*.py
  - Reads each tool file, extracts function names, docstrings, parameters
  - Exposes as structured JSON for the GUI to render dynamically
  - Adding a new .py file to mcp_server/tools/ = auto-appears in GUI
- api/db.py — SQLite setup using aiosqlite
  - Tables: operations, tool_calls, status_snapshots
  - operations: id, session_id, label, started_at, completed_at, status
  - tool_calls: id, operation_id, tool_name, params, result, status, 
                model_used, duration_ms, timestamp
  - status_snapshots: id, component, state_json, timestamp
- api/logger.py — writes every tool call and agent decision to SQLite
- Bind to 0.0.0.0:8000 for LAN access (Proxmox network)
- CORS enabled for React dev server and LAN IPs
- LM Studio connection: http://localhost:1234/v1
- Model: lmstudio-community/qwen3-coder-30b-a3b-instruct

#### 2. React Web GUI (gui/)
Bootstrap with Vite + React + Tailwind CSS

Layout — 3 panel design:
┌─────────────────────────────────────────────────────┐
│  HP1 AI Agent                          ● LAN: 8000  │
├──────────────┬──────────────────────┬───────────────┤
│   COMMANDS   │    LIVE OUTPUT       │    STATUS     │
│              │                      │               │
│  [Tool list  │  Streaming agent     │  Swarm: ●     │
│  auto-built  │  output via          │  Kafka: ●     │
│  from tool   │  WebSocket.          │  Elastic: ●   │
│  registry]   │  Full log per step.  │               │
│              │  Color-coded:        │  Last updated │
│  Click tool  │  ✓ success           │  timestamp    │
│  → param     │  ✗ failure           │               │
│    form      │  ⚡ running          │               │
│  → execute   │  ⚠ escalated         │               │
│              │                      │               │
├──────────────┴──────────────────────┴───────────────┤
│  LOGS  [filter: all | success | failure | escalated] │
│  Tabular view from SQLite — session, tool, result    │
└─────────────────────────────────────────────────────┘

GUI components to build:
- gui/src/components/CommandPanel.jsx
- gui/src/components/OutputPanel.jsx
- gui/src/components/StatusPanel.jsx
- gui/src/components/LogTable.jsx
- gui/src/App.jsx
- gui/src/api.js

#### 3. Project Structure After Phase 1-2
HP1-AI-Agent-v1/
├── api/
│   ├── main.py
│   ├── tool_registry.py
│   ├── websocket.py
│   ├── db.py
│   ├── logger.py
│   └── routers/
│       ├── tools.py
│       ├── agent.py
│       ├── status.py
│       └── logs.py
├── gui/
│   ├── package.json
│   ├── vite.config.js
│   ├── tailwind.config.js
│   ├── index.html
│   └── src/
│       ├── App.jsx
│       ├── api.js
│       └── components/
│           ├── CommandPanel.jsx
│           ├── OutputPanel.jsx
│           ├── StatusPanel.jsx
│           └── LogTable.jsx
├── mcp_server/
├── agent/
├── docker/
├── data/
│   └── hp1_agent.db
├── requirements.txt
├── start.bat
└── README.md

### Constraints
- FastAPI + aiosqlite + uvicorn for backend
- Vite + React + Tailwind for frontend (no Next.js)
- WebSockets for streaming — not polling
- Tool registry must be dynamic — no hardcoded tool lists
- All IPs/ports via environment variables with sensible defaults
- Backend: 0.0.0.0:8000 | Frontend: 0.0.0.0:5173
- Windows-compatible paths and start scripts

### AI Routing
Every agent execution logs which model was used:
- Local: lmstudio-community/qwen3-coder-30b-a3b-instruct via LM Studio
- External: only if local model unavailable or tool returns escalate()
- model_used column in tool_calls table captures this always

### Execution Order
1. Update requirements.txt
2. Build api/db.py
3. Build api/tool_registry.py
4. Build api/routers/
5. Build api/websocket.py
6. Build api/main.py, test with curl
7. Scaffold gui/ with Vite
8. Build React components
9. Wire gui/src/api.js and App.jsx
10. Test full flow: click tool → streams → logs → LogTable
11. Create start.bat
12. Index: index_folder({ "path": "D:/claude_code/FAJK/HP1-AI-Agent-v1" })
13. Output: confirmed LAN URLs + any issues

Begin now. No check-ins needed until step 13.
```

---

## Phase 3: PostgreSQL Migration + Production Logging

**Goal:** Replace SQLite with PostgreSQL (SQLite fallback retained).
Enhanced schema, paginated log APIs, stats endpoint, StatsBar in GUI.

### What to Build
- `api/db/` module — connection factory picks Postgres or SQLite via `DATABASE_URL`
- `api/db/migrations.py` — versioned schema, runs on startup, never drops data
- New tables: `escalations`, `audit_log`, `schema_versions`
- `api/db/queries.py` — all SQL centralised, no inline queries elsewhere
- Enhanced `api/routers/logs.py` — operations view, escalations, stats endpoint
- `gui/src/components/StatsBar.jsx` — success rate, avg duration, local AI %
- `docker/docker-compose.yml` — postgres:16-alpine service
- `api/db/migrate_sqlite.py` — one-time migration script, idempotent

### Schema
```
operations    — sessions grouping related tool calls
tool_calls    — every tool invocation, result, model used, duration
status_snapshots — point-in-time infrastructure state
escalations   — high-risk decisions flagged for review
audit_log     — immutable event log
schema_versions — migration tracking
```

### Key Design Decision
`DATABASE_URL` env var controls backend. Not set = SQLite. Set = Postgres.
Zero code changes to switch. Swap by setting one env var and restarting.

### Claude Code Prompt — Phase 3
```
You are operating with full autonomy. Do not ask for permission before taking
action. Make decisions, implement, test, and iterate independently.

## Project: HP1-AI-Agent-v1 — Phase 3: PostgreSQL Migration + Production Logging

### Project Path
D:/claude_code/FAJK/HP1-AI-Agent-v1/

### Context
Phase 1-2 is complete. The project has:
- FastAPI backend running on 0.0.0.0:8000
- React GUI on 0.0.0.0:5173
- SQLite logging at data/hp1_agent.db
- Tool registry auto-discovering mcp_server/tools/*.py
- WebSocket streaming to OutputPanel
- MCP server with Docker Swarm + Kafka tools

Do not break anything already working. This phase migrates logging to
PostgreSQL, adds a Postgres container to the stack, and enhances the
logging architecture for production use. SQLite remains as a fallback.

### What to Build

#### 1. PostgreSQL Container (docker/)
- postgres:16-alpine, named volume hp1_pgdata, port 5432 internal only
- Database: hp1_agent, user/pass via ENV, health check before FastAPI starts

#### 2. Database Migration Layer (api/db/)
- api/db/base.py — picks Postgres or SQLite from DATABASE_URL
- api/db/migrations.py — versioned, runs on startup, never drops data
- api/db/models.py — SQLAlchemy Core table definitions (no ORM)
- api/db/queries.py — ALL queries here, no inline SQL elsewhere

New tables:
  schema_versions: id, version, applied_at, description
  escalations: id, operation_id FK, tool_call_id FK, reason, context JSON,
               resolved BOOL, resolved_at, timestamp
  audit_log: id, event_type, entity_id, entity_type, detail JSON,
             timestamp, source

Enhanced tables:
  tool_calls: add error_detail TEXT
  operations: add triggered_by TEXT, total_duration_ms INTEGER

#### 3. Enhanced Logging (api/logger.py)
- log_operation_start / log_operation_complete
- log_tool_call / log_status_snapshot
- log_escalation / log_audit
- All async, non-blocking, batch writes buffered 100ms

#### 4. Enhanced Log API (api/routers/logs.py)
- GET /api/logs — paginated, filterable
- GET /api/logs/operations + /{id}
- GET /api/logs/escalations + /{id}/resolve
- GET /api/logs/audit
- GET /api/logs/stats → success_rate, avg_duration, top tools, local_vs_external

#### 5. GUI Updates
- StatsBar.jsx: total runs | success rate | avg duration | local AI % | escalations
- LogTable: add Operations / Escalations / Audit / Stats tab views
- Stats view: top 5 tools bar chart (recharts or CSS bars)

#### 6. Environment + Migration
- .env.example with DATABASE_URL, SQLITE_PATH, LM Studio, API, GUI vars
- start.bat: if DATABASE_URL set → start postgres first, wait health check
- api/db/migrate_sqlite.py: migrate existing SQLite → Postgres, idempotent

### Constraints
- SQLAlchemy Core only (no ORM), asyncpg + aiosqlite
- UUID primary keys, JSONB for Postgres / JSON text for SQLite (transparent)
- Non-blocking logging — agent never waits on DB write
- Migrations run automatically on startup

### Execution Order
1. Add postgres to docker-compose, test starts healthy
2. Build api/db/ module, test connection factory
3. Write migrations.py, verify schema creates cleanly
4. Rewrite api/logger.py
5. Update api/routers/logs.py
6. Test full pipeline: tool run → DB → API
7. Update GUI: StatsBar + extended LogTable
8. Write migrate_sqlite.py, test against existing DB
9. Update start.bat + .env.example + README
10. End-to-end: GUI → execution → Postgres → log views
11. Index: index_folder({ "path": "D:/claude_code/FAJK/HP1-AI-Agent-v1" })
12. Output: DB backend confirmed + stats endpoint response + issues

Begin now. No check-ins needed until step 12.
```

---

## Phase 4: Live Infrastructure Status (Swarm + Kafka)

**Goal:** Real live data in StatusPanel. Background collectors poll Swarm
and Kafka every 30s. NodeMap shows all 6 nodes at a glance. Alerting fires
on health transitions. Elastic placeholder becomes real.

### What to Build
- `api/collectors/` — async background pollers, auto-discovered
- `SwarmCollector` — node health, service replicas, swarm health score
- `KafkaCollector` — broker health, consumer lag, under-replicated partitions
- `ElasticCollector` — cluster health, filebeat index presence
- `api/alerts.py` — threshold-based alerting → audit_log + GUI queue
- `StatusPanel.jsx` rewrite — real data, collapsible sections, traffic lights
- `NodeMap.jsx` — visual 3+3 grid of all cluster nodes
- `SparkLine.jsx` — 24h health history inline charts
- `AlertToast.jsx` — dismissible toast notifications

### Health States
```
healthy  → all nodes active, all services at desired replicas
degraded → 1+ nodes drain/pause OR services under-replicated
critical → manager quorum at risk OR majority services failed
```

### Collector Pattern
Drop a `.py` file in `api/collectors/` → auto-registered on startup.
Each collector: async poll loop → write to `status_snapshots` → alerts check.

### Claude Code Prompt — Phase 4
```
You are operating with full autonomy. Do not ask for permission before taking
action. Make decisions, implement, test, and iterate independently.

## Project: HP1-AI-Agent-v1 — Phase 4: Live Infrastructure Status

### Project Path
D:/claude_code/FAJK/HP1-AI-Agent-v1/

### Context
Phases 1-3 complete. Adding live infrastructure collectors and real
StatusPanel data. Do not break anything already working.

### Infrastructure
- Docker Swarm: 3 manager VMs + 3 worker VMs (Proxmox LAN)
- Kafka: 1 KRaft broker per worker (3 brokers total)
- Filebeat: 1 per node → Elasticsearch
- Elasticsearch: single node prototype
- Windows dev machine, Docker Desktop WSL2 backend

### What to Build

#### api/collectors/
- base.py — BaseCollector: async poll loop, configurable interval,
  writes via logger.log_status_snapshot(), handles failures gracefully
- swarm.py — SwarmCollector(BaseCollector), polls every 30s:
  node list, service list, swarm health (healthy/degraded/critical)
- kafka.py — KafkaCollector(BaseCollector), polls every 30s:
  broker list, controller, topic health, consumer lag per group
- elastic.py — ElasticCollector(BaseCollector), polls every 60s:
  cluster health, node count, filebeat index presence
- manager.py — CollectorManager: starts all on startup, stops on shutdown,
  auto-discovers collectors in api/collectors/

#### api/routers/status.py — full rewrite
- GET /api/status — latest snapshot per component
- GET /api/status/history/{component}?hours=24
- GET /api/status/nodes — swarm node detail
- GET /api/status/services — swarm service detail
- GET /api/status/brokers — kafka broker metrics
- GET /api/status/lag — consumer group lag all groups

#### api/alerts.py
- Threshold alerts on health transitions: healthy→degraded, degraded→critical
- Writes to audit_log + asyncio.Queue
- GET /api/alerts/recent for GUI polling

#### GUI Components
- StatusPanel.jsx — complete rewrite: traffic lights, collapsible sections,
  node table, service table, broker table, consumer lag table, auto-refresh 15s
- NodeMap.jsx — 3 managers top, 3 workers bottom, health color per node,
  kafka broker badge on workers, click → detail panel
- SparkLine.jsx — inline health history chart (recharts or CSS)
- AlertToast.jsx — polls /api/alerts/recent every 10s, dismissible toasts,
  yellow=degraded red=critical, auto-dismiss 10s
- App.jsx — add Cluster tab showing NodeMap full-width

#### .env.example additions
  DOCKER_HOST=npipe:////./pipe/docker_engine
  SWARM_POLL_INTERVAL=30
  KAFKA_BOOTSTRAP_SERVERS=<worker1>:9092,<worker2>:9092,<worker3>:9092
  KAFKA_POLL_INTERVAL=30
  KAFKA_LAG_THRESHOLD=1000
  ELASTIC_URL=http://<elastic-ip>:9200
  ELASTIC_POLL_INTERVAL=60

### Constraints
- docker-py for Swarm, confluent-kafka AdminClient for Kafka, httpx for Elastic
- All collectors handle connection refused / timeout — mark unhealthy, never crash
- New collectors auto-discovered — drop file in api/collectors/, restart API

### Execution Order
1. Build api/collectors/base.py + manager.py
2. Build SwarmCollector, test against local Docker
3. Build KafkaCollector, test against Kafka bootstrap servers
4. Build ElasticCollector, test or mock if Elastic not deployed
5. Wire CollectorManager into FastAPI startup/shutdown
6. Rewrite api/routers/status.py
7. Build api/alerts.py + AlertToast.jsx
8. Rewrite StatusPanel.jsx with real data
9. Build NodeMap.jsx + SparkLine.jsx
10. Add Cluster tab to App.jsx
11. End-to-end: collectors → DB → API → GUI live
12. Test graceful degradation: stop Kafka → degraded shown, no crash
13. Index: index_folder({ "path": "D:/claude_code/FAJK/HP1-AI-Agent-v1" })
14. Output: live status URLs, collector poll results, connectivity issues

Begin now. No check-ins needed until step 14.
```

---

## Phase 5: MuninnDB Operational Memory + Local Docs RAG

**Goal:** Agent learns from past operations. MuninnDB stores every tool call
as an engram. Before acting, agent activates relevant memories. Local docs
(Docker, Kafka, Elastic, Filebeat, runbooks) indexed for RAG. Semantic
triggers fire proactive alerts when relevant knowledge surfaces.

### Why MuninnDB over ChromaDB

| Need | ChromaDB | MuninnDB |
|------|----------|---------|
| Similarity search | ✅ | ✅ |
| Agent remembers past decisions | ❌ manual | ✅ ACT-R decay |
| "What failed last time?" | ❌ you build it | ✅ Hebbian links |
| Proactive push alerts | ❌ | ✅ Semantic triggers |
| Surfaces what matters NOW | ❌ cosine only | ✅ recency + frequency |

MuninnDB install: `curl -fsSL https://muninndb.com/install.sh | sh`

### Memory Flow
```
Before tool call:
  ACTIVATE("kafka rolling restart") → top 5 engrams → injected into agent prompt

After tool call:
  STORE engram (result, status, component) → Hebbian links auto-strengthen

On escalation:
  ACTIVATE(reason) → package with status snapshot → send to Claude as context
  Store Claude's response as engram → linked to escalation
```

### Engram Types
- `OperationalMemory` — tool call results, failures, escalations
- `DocMemory` — documentation chunks (Docker, Kafka, Elastic, Filebeat)
- `StatusMemory` — infrastructure state transitions (stored on change only)

### Semantic Triggers
1. `"kafka broker failure rolling restart risk"` → escalate
2. `"swarm node drain manager quorum"` → high-priority alert
3. `"repeated error same service upgrade"` → warn before next upgrade

### Claude Code Prompt — Phase 5
```
You are operating with full autonomy. Do not ask for permission before taking
action. Make decisions, implement, test, and iterate independently.

## Project: HP1-AI-Agent-v1 — Phase 5: MuninnDB Operational Memory + RAG

### Project Path
D:/claude_code/FAJK/HP1-AI-Agent-v1/

### Context
Phases 1-4 complete. Adding MuninnDB as the cognitive memory layer.
MuninnDB replaces ChromaDB. Postgres remains source of truth for logs.
MuninnDB is the intelligence layer for retrieval and memory.
Do not break anything already working.

### Install MuninnDB
curl -fsSL https://muninndb.com/install.sh | sh && muninn init

Add to docker-compose.yml:
  muninndb:
    image: muninndb/muninndb:latest
    ports: ["8474:8474", "8475:8475", "8750:8750"]
    volumes: [muninn_data:/data]
    environment: [MUNINN_VAULT=hp1_agent]

### What to Build

#### api/memory/
- client.py — async REST client: store(), activate(), associate(),
  subscribe_trigger(). Falls back gracefully if MuninnDB unavailable.
- schemas.py — OperationalMemory, DocMemory, StatusMemory engram types
- hooks.py — after_tool_call(), after_status_snapshot(), before_tool_call()
  Wire into api/logger.py and agent/agent_loop.py
- ingest.py — chunks + indexes docs into MuninnDB:
  Docker Swarm, Kafka, Elasticsearch, Filebeat official docs
  All .md files in docs/ folder. Idempotent (URL hash dedup).
- triggers.py — registers 3 semantic triggers on startup, callbacks → alerts

#### DB Migration
Add memory_context JSONB column to tool_calls table

#### Agent Loop Update (agent/agent_loop.py)
before_tool_call() injects top 5 engrams into system prompt:
  "Before acting, here is relevant memory from past operations:
  {activated_engrams}
  Use this context. If past failures are present, address them."
500ms timeout on activation — skip if slower, never block execution.

#### Escalation Enhancement
escalate(): ACTIVATE(reason) → top 5 engrams → package with status snapshot
→ send to Claude as grounded context. Store Claude response as engram.

#### docs/runbooks/
Create 5 runbook templates:
  kafka_rolling_restart.md, swarm_node_drain.md,
  service_upgrade_rollback.md, elastic_reindex.md, filebeat_reconfigure.md
Format: Prerequisites / Pre-flight Checks / Steps / Verification /
        Rollback / Known Issues
Ingest all into MuninnDB on startup.

#### GUI
- MemoryPanel.jsx — new "Memory" tab:
  Memory search (ACTIVATE query), recent operational memory,
  docs search (doc engrams only), memory stats
- api/routers/memory.py: POST /activate, GET /recent, GET /docs,
  GET /stats, GET /engram/{id}

#### .env.example additions
  MUNINN_URL=http://localhost:8475
  MUNINN_MCP_URL=http://localhost:8750
  MUNINN_VAULT=hp1_agent
  MUNINN_TRIGGER_WS=ws://localhost:8475/triggers

### Constraints
- httpx only for MuninnDB — no SDK (alpha software, minimize dependency risk)
- Store ops: fire and forget — never block tool execution
- Activation: 500ms timeout
- Doc ingestion: idempotent, URL hash dedup
- MuninnDB unavailable: log warning, agent continues

### Execution Order
1. Add MuninnDB to docker-compose, verify REST API responds
2. Build api/memory/client.py, test store + activate
3. Build api/memory/hooks.py, wire into logger.py
4. Add memory_context migration to tool_calls
5. Wire before_tool_call into agent_loop.py
6. Build api/memory/ingest.py, run against docs
7. Create docs/runbooks/, ingest all 5
8. Build api/memory/triggers.py, test all 3 fire
9. Build api/routers/memory.py
10. Build MemoryPanel.jsx + Memory tab in App.jsx
11. Wire escalation context enhancement
12. End-to-end: run tool → engram stored → activate → past run surfaces
13. Test semantic trigger: degrade Kafka → trigger fires → purple toast
14. Run 5 operations → verify Hebbian links forming in memory stats
15. Index: index_folder({ "path": "D:/claude_code/FAJK/HP1-AI-Agent-v1" })
16. Output: engram count, trigger status, doc index size, issues

Begin now. No check-ins needed until step 16.
```

---

## Phase 6: Filebeat + Elasticsearch Full Observability

**Goal:** Agent reads actual infrastructure logs before acting. Filebeat ships
logs from all 6 Swarm nodes. Elasticsearch stores and indexes them. Log
correlation ties agent operations to the log events that happened during them.
Post-mortem becomes trivial.

### What to Build
- Filebeat global Swarm service (1 per node, auto via `mode: global`)
- Elasticsearch 8.x single node + optional Kibana
- `mcp_server/tools/elastic.py` — 6 new tools for the agent
- Enhanced `pre_upgrade_check()` — now reads Elastic logs as gate 3+4
- `post_upgrade_verify()` — new mandatory post-upgrade tool
- `api/correlator.py` — ties Postgres operations to Elastic log windows
- `LogsPanel.jsx` — live log stream, error summary, log pattern chart
- `ElasticStatus.jsx` — real Filebeat status replacing placeholder
- Correlation view embedded in LogTable operation detail rows
- `ElasticAlerter` — Elastic-sourced alerts into AlertToast

### Enhanced Pre-flight Check (6 gates)
```
Gate 1: swarm_status()                     — all nodes healthy
Gate 2: pre_kafka_check()                  — all brokers, ISR healthy
Gate 3: elastic_error_logs(minutes_ago=30) — no recent errors on target
Gate 4: elastic_log_pattern(service)       — error rate not anomalous
Gate 5: MuninnDB activate("upgrade {svc}") — no past upgrade failures
Gate 6: checkpoint_save("pre_upgrade_...")  — state snapshot
→ All 6 must pass. Any failure = halt with specific reason.
```

### Log Correlation
```
correlate(operation_id):
  Fetch operation time window from Postgres
  → Query Elastic for logs in that window from involved services
  → Match errors to specific tool_call timestamps
  → Store summary as MuninnDB engram
  → Hebbian link: correlation ↔ operation ↔ error engrams
```

### Claude Code Prompt — Phase 6
```
You are operating with full autonomy. Do not ask for permission before taking
action. Make decisions, implement, test, and iterate independently.

## Project: HP1-AI-Agent-v1 — Phase 6: Filebeat + Elasticsearch Observability

### Project Path
D:/claude_code/FAJK/HP1-AI-Agent-v1/

### Context
Phases 1-5 complete. ElasticCollector already built (Phase 4).
Adding full Filebeat → Elasticsearch pipeline, agent log tools,
and log correlation. Do not break anything already working.

### Infrastructure
- Filebeat: 1 per Swarm node (global service), ships to Elasticsearch
- Elasticsearch: 8.x single node, security disabled for prototype
- Kibana: optional, ENABLE_KIBANA env var

### What to Build

#### docker/
- filebeat/filebeat.yml: Docker container logs, Kafka logs, system logs,
  add_docker_metadata, add_host_metadata, output to hp1-logs-%{+yyyy.MM.dd}
- filebeat/docker-compose.filebeat.yml: global Swarm service, mounts
  /var/lib/docker/containers + /var/run/docker.sock + /var/log read-only
- elastic/docker-compose.elastic.yml: ES 8.x single node, 2GB heap,
  hp1_elastic_data volume, port 9200 LAN-exposed
  Kibana optional behind ENABLE_KIBANA flag, port 5601
- deploy_observability.bat: deploy Elastic → wait green → deploy Filebeat
  → verify hp1-logs-* index exists + doc count > 0

#### mcp_server/tools/elastic.py (6 new tools)
- elastic_cluster_health()
- elastic_search_logs(query, service, node, minutes_ago, size)
- elastic_error_logs(service, minutes_ago)
- elastic_kafka_logs(broker_id, minutes_ago) — ISR, LeaderElection events
- elastic_log_pattern(service, hours) — error rate + anomaly flag
- elastic_index_stats() — hp1-logs-* stats + Filebeat last ingest time
- elastic_correlate_operation(operation_id) — log events in operation window

#### mcp_server/tools/orchestration.py updates
- pre_upgrade_check(): add gates 3+4 (elastic_error_logs + elastic_log_pattern)
- post_upgrade_verify(service, operation_id): NEW mandatory post-upgrade tool
  service_health + elastic_error_logs(5min) + elastic_correlate_operation
  + MuninnDB engram storage

#### api/correlator.py
- correlate(operation_id, window_seconds=300) → CorrelationResult
- store_correlation(result) → MuninnDB engram + Hebbian links
- GET /api/correlate/{operation_id}

#### api/routers/elastic.py
  GET /api/elastic/health
  GET /api/elastic/logs
  GET /api/elastic/errors
  GET /api/elastic/pattern/{service}
  GET /api/elastic/kafka
  GET /api/elastic/stats

#### api/alerts.py — ElasticAlerter extension
- error_rate > threshold → yellow alert
- log_pattern anomaly → yellow alert
- Filebeat stale > 10min → yellow alert
- Kafka OfflinePartitions in logs → red alert (immediate)
- critical log in last 5min → red alert

#### api/memory/hooks.py extensions
- after_elastic_error(): store as OperationalMemory engram
- after_correlation(): store anomalies as high-confidence engrams
- New trigger: "repeated error same service upgrade" → escalate()

#### GUI
- LogsPanel.jsx: live log stream (poll /api/elastic/logs every 5s),
  error summary with red badges, log pattern bar chart per service
- ElasticStatus.jsx: replace placeholder in StatusPanel —
  doc count, last Filebeat ingest (green <5min / red stale), cluster health
- LogTable operation detail: add Correlated Logs section,
  timeline of tool_calls overlaid with log events

#### docs/runbooks/ updates
- Update kafka_rolling_restart.md: add elastic_kafka_logs() check
- Update service_upgrade_rollback.md: add 6-gate pre-check + post_upgrade_verify
- New: filebeat_troubleshoot.md (actual content)
- Re-ingest all runbooks into MuninnDB

#### .env.example additions
  ELASTIC_URL=http://<elastic-ip>:9200
  ELASTIC_INDEX_PATTERN=hp1-logs-*
  ELASTIC_ERROR_RATE_THRESHOLD=10
  ELASTIC_FILEBEAT_STALE_MINUTES=10
  ENABLE_KIBANA=false
  KIBANA_URL=http://<elastic-ip>:5601
  CORRELATION_WINDOW_SECONDS=300

### Constraints
- httpx for all Elasticsearch queries — no elasticsearch-py SDK
- Build ES query DSL manually
- Filebeat: 1 config for all nodes via ENV (NODE_ROLE from Swarm label)
- Elastic security disabled — document in README
- Correlation runs post-operation — never blocks agent
- If Elastic unavailable: tools return {status: "unavailable"}, agent continues

### Execution Order
1. Deploy Elasticsearch, verify /_cluster/health green
2. Deploy Filebeat global service, verify hp1-logs-* index created
3. Confirm doc count increasing
4. Build mcp_server/tools/elastic.py, test each tool
5. Update pre_upgrade_check() with gates 3+4
6. Build post_upgrade_verify(), wire into service_upgrade()
7. Build api/correlator.py, test against a real operation
8. Build api/routers/elastic.py
9. Update api/alerts.py with ElasticAlerter
10. Extend MuninnDB hooks
11. Add "repeated error" semantic trigger, test it fires
12. Build LogsPanel.jsx
13. Build ElasticStatus.jsx, wire into StatusPanel
14. Wire correlation view into LogTable operation detail
15. Update + re-ingest runbooks
16. Full end-to-end:
    a. Upgrade → 6-gate check → execute → post_verify → correlation stored
    b. Inject error → ElasticAlerter → AlertToast → engram stored →
       next upgrade surfaces past error from memory
    c. Simulate Filebeat stale → stale badge + alert
17. Enable Kibana if ENABLE_KIBANA=true, verify loads
18. Index: index_folder({ "path": "D:/claude_code/FAJK/HP1-AI-Agent-v1" })
19. Output: log pipeline confirmed, doc count, alert results,
    correlation example, issues

Begin now. No check-ins needed until step 19.
```

---

## Project Structure (Final — After Phase 6)

```
HP1-AI-Agent-v1/
├── .claude/
│   └── settings.json           ← Claude Code permissions
├── .mcp.json                   ← MCP server config
├── .env.example                ← all environment variables documented
├── api/
│   ├── main.py
│   ├── tool_registry.py
│   ├── websocket.py
│   ├── logger.py
│   ├── alerts.py
│   ├── correlator.py
│   ├── collectors/
│   │   ├── base.py
│   │   ├── manager.py
│   │   ├── swarm.py
│   │   ├── kafka.py
│   │   └── elastic.py
│   ├── db/
│   │   ├── base.py
│   │   ├── migrations.py
│   │   ├── models.py
│   │   ├── queries.py
│   │   └── migrate_sqlite.py
│   ├── memory/
│   │   ├── client.py
│   │   ├── schemas.py
│   │   ├── hooks.py
│   │   ├── ingest.py
│   │   └── triggers.py
│   └── routers/
│       ├── tools.py
│       ├── agent.py
│       ├── status.py
│       ├── logs.py
│       ├── memory.py
│       └── elastic.py
├── gui/
│   └── src/
│       ├── App.jsx
│       ├── api.js
│       └── components/
│           ├── CommandPanel.jsx
│           ├── OutputPanel.jsx
│           ├── StatusPanel.jsx
│           ├── LogTable.jsx
│           ├── StatsBar.jsx
│           ├── NodeMap.jsx
│           ├── SparkLine.jsx
│           ├── AlertToast.jsx
│           ├── MemoryPanel.jsx
│           ├── LogsPanel.jsx
│           └── ElasticStatus.jsx
├── mcp_server/
│   ├── server.py
│   └── tools/
│       ├── swarm.py
│       ├── kafka.py
│       ├── orchestration.py
│       └── elastic.py
├── agent/
│   └── agent_loop.py
├── docker/
│   ├── swarm-stack.yml
│   ├── kafka-stack.yml
│   ├── docker-compose.yml      ← postgres + muninndb
│   ├── filebeat/
│   │   ├── filebeat.yml
│   │   └── docker-compose.filebeat.yml
│   └── elastic/
│       └── docker-compose.elastic.yml
├── docs/
│   └── runbooks/
│       ├── kafka_rolling_restart.md
│       ├── swarm_node_drain.md
│       ├── service_upgrade_rollback.md
│       ├── elastic_reindex.md
│       ├── filebeat_reconfigure.md
│       └── filebeat_troubleshoot.md
├── data/
│   └── hp1_agent.db            ← SQLite fallback
├── logs/
│   └── audit.log
├── checkpoints/
├── .code-index/                ← jcodemunch symbol index
├── requirements.txt
├── start.bat
└── README.md
```

---

## Environment Variables Reference

```env
# Database
DATABASE_URL=postgresql+asyncpg://hp1user:hp1pass@localhost:5432/hp1_agent
SQLITE_PATH=data/hp1_agent.db

# LM Studio (local AI)
LM_STUDIO_URL=http://localhost:1234/v1
LM_STUDIO_API_KEY=
LM_STUDIO_MODEL=lmstudio-community/qwen3-coder-30b-a3b-instruct

# Docker Swarm
DOCKER_HOST=npipe:////./pipe/docker_engine
SWARM_POLL_INTERVAL=30

# Kafka
KAFKA_BOOTSTRAP_SERVERS=<w1>:9092,<w2>:9092,<w3>:9092
KAFKA_POLL_INTERVAL=30
KAFKA_LAG_THRESHOLD=1000

# Elasticsearch
ELASTIC_URL=http://<elastic-ip>:9200
ELASTIC_INDEX_PATTERN=hp1-logs-*
ELASTIC_ERROR_RATE_THRESHOLD=10
ELASTIC_FILEBEAT_STALE_MINUTES=10
ELASTIC_POLL_INTERVAL=60

# Kibana (optional)
ENABLE_KIBANA=false
KIBANA_URL=http://<elastic-ip>:5601

# MuninnDB
MUNINN_URL=http://localhost:8475
MUNINN_MCP_URL=http://localhost:8750
MUNINN_VAULT=hp1_agent
MUNINN_TRIGGER_WS=ws://localhost:8475/triggers

# Correlation
CORRELATION_WINDOW_SECONDS=300

# API
API_HOST=0.0.0.0
API_PORT=8000

# GUI
VITE_API_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000
```

---

## MCP Configuration

### `.mcp.json` (project root — Claude Code)
```json
{
  "mcpServers": {
    "infra-agent": {
      "command": "python",
      "args": ["-m", "mcp_server.server"],
      "cwd": "D:/claude_code/FAJK/HP1-AI-Agent-v1",
      "env": {
        "DOCKER_HOST": "npipe:////./pipe/docker_engine",
        "KAFKA_BOOTSTRAP_SERVERS": "localhost:9092,localhost:9093,localhost:9094",
        "AUDIT_LOG_PATH": "D:/claude_code/FAJK/HP1-AI-Agent-v1/logs/audit.log",
        "CHECKPOINT_PATH": "D:/claude_code/FAJK/HP1-AI-Agent-v1/checkpoints",
        "CODE_INDEX_PATH": "D:/claude_code/FAJK/HP1-AI-Agent-v1/.code-index"
      }
    },
    "jcodemunch": {
      "command": "jcodemunch-mcp",
      "env": {
        "CODE_INDEX_PATH": "D:/claude_code/FAJK/HP1-AI-Agent-v1/.code-index"
      }
    }
  }
}
```

### `.claude/settings.json` (Claude Code permissions)
```json
{
  "permissions": {
    "allow": [
      "Bash(*)", "Read(*)", "Write(*)", "Edit(*)",
      "MultilineEdit(*)", "NotebookEdit(*)",
      "mcp__infra-agent__*", "mcp__jcodemunch__*"
    ]
  },
  "security": {
    "allowCompoundCommands": true,
    "allowCdWithRedirection": true
  }
}
```

---

## What Requires External AI and Why

| Situation | Why Local Cannot Handle It |
|-----------|---------------------------|
| Unknown failure mode with no past engrams | No memory context to reason from |
| Cascading failure across Swarm + Kafka + Elastic simultaneously | Too many interacting systems, reasoning depth exceeds local model |
| High-risk irreversible action (e.g. node removal from quorum) | Second opinion required — cost of mistake too high |
| Agent confidence score below threshold | Local model self-reports uncertainty |

External AI receives: escalation reason + top 5 MuninnDB engrams + current
status snapshot + correlated log context. This grounds the external AI
response in real operational history, not just the current error message.

---

*HP1-AI-Agent-v1 — Built for Proxmox + Docker Swarm + Kafka*
*Local AI first. External AI only when it matters.*
