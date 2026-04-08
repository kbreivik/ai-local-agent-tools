# HP1-AI-Agent — Full Project Summary

**Generated:** 2026-04-04
**Source:** Deep audit of all 121 Python files, 38 frontend files, Docker configs, and tests.

---

## 1. Architecture Overview

```
                         +--------------------------+
                         |   Vue 3 SPA (9 tabs)     |
                         |   24 components, 6 ctx   |
                         +----+----------+----------+
                              | REST     | WebSocket
                         +----v----------v----------+
                         |     FastAPI (port 8000)   |
                         |  17 routers, JWT auth     |
                         +--+---+---+---+---+---+---+
                            |   |   |   |   |   |
           +----------------+   |   |   |   |   +----------------+
           |                    |   |   |   |                    |
    +------v------+    +-------v---v---v-------+    +-----------v---------+
    | Tool        |    |  Agent Loop            |    | Collectors          |
    | Registry    |    |  (LM Studio / Claude)  |    | (7 background       |
    | (AST-based  |    |  4 agent types         |    |  pollers)           |
    | discovery)  |    |  Step orchestrator     |    +---------------------+
    +------+------+    |  Gate rules            |
           |           |  Plan lock + confirm   |
           |           +---+----------+---------+
           |               |          |
    +------v---------------v----------v---------+
    |            MCP Server (55+ tools)          |
    |   server.py: @mcp.tool() → direct import  |
    +--+---+---+---+---+---+---+---+---+---+----+
       |   |   |   |   |   |   |   |   |   |
       v   v   v   v   v   v   v   v   v   v
    swarm kafka elastic orchestration docker_engine
    ingest network skill_meta_tools
    skills/ (meta_tools, loader, generator, validator,
             discovery, promoter, knowledge_base,
             doc_retrieval, spec_generator, live_validator)
```

---

## 2. Tool Routing (Missing from Original Audit)

### MCP Layer (server.py)
- **55 @mcp.tool()** wrappers, each doing a direct import call:
  ```python
  @mcp.tool()
  def service_upgrade(name, image): return swarm.service_upgrade(name, image)
  ```
- **Promoted skills** loaded dynamically at startup via `_make_promoted_tool()` closure
- No registry/dispatch at MCP level — pure decorator binding

### API Layer (tool_registry.py)
- **AST-based auto-discovery**: scans all `mcp_server/tools/*.py` via AST (no imports needed)
- `load_registry()` → extracts function names, docstrings, param types, builds JSON schemas
- `invoke_tool(name, params)` → dynamic import + call by name
- This is how the **agent loop calls tools** (not via MCP protocol)

### Agent Layer (agents/router.py)
- **4 agent types** with exclusive tool allowlists:
  - **observe**: read-only (swarm_status, service_health, elastic_cluster_health, etc.)
  - **investigate**: read-only + log search + correlation + ingestion
  - **execute**: domain-filtered destructive tools (kafka/swarm/proxmox/general subsets)
  - **build**: skill management only (skill_create, skill_regenerate, etc.)
- Promoted skills injected into domain allowlists at startup

---

## 3. Safety & Orchestration Layer (Missing from Original Audit)

### Gate Rules (api/agents/gate_rules.py)
3 pure-functional rules returning "GO" | "ASK" | "HALT":
- **kafka_rolling_restart**: all brokers up? ISR >= RF-1?
- **swarm_service_upgrade**: quorum maintained?
- **changelog_check**: changelog ingested? breaking changes present?

### Pre-Upgrade Check (6-step sequential gate)
1. Swarm nodes all ready
2. Kafka brokers healthy, ISR intact
3. Elastic error logs (30min) = zero
4. Error rate anomaly detection (24h)
5. Memory context activation (past failure engrams)
6. Checkpoint save (swarm + kafka state snapshot)

### Post-Upgrade Verify (4-step)
1. Replicas at desired count (20s delay for convergence)
2. No new errors in Elasticsearch (5min window)
3. Log correlation (operation_id ↔ error timestamps)
4. Store result as MuninnDB engram

### Plan Lock (api/lock.py)
- Global singleton — ONE destructive plan at a time
- 10-minute stale timeout, force-release available
- **Pre-flight enforcement**: destructive tools blocked until `plan_action()` called
- GUI confirmation flow: broadcast → wait_for_confirmation → release

### Destructive Tools (require plan_action first)
```
service_upgrade, service_rollback, node_drain,
checkpoint_restore, kafka_rolling_restart_safe,
docker_engine_update,
skill_create, skill_regenerate, skill_disable, skill_enable
```

### Escalation Flow
- Tool returns degraded/failed/escalated → auto-escalate with memory context
- Vendor mismatch in service_upgrade() → fail with escalation
- Agent calls escalate() explicitly
- Memory trigger: repeated error pattern → critical alert

### Clarification System (api/clarification.py)
- Agent calls `clarifying_question(question, options)` → GUI widget appears
- 300s timeout → "proceed with best guess"

---

## 4. Collector System (Missing from Original Audit)

**Auto-discovered BaseCollector subclasses** in `api/collectors/`:

| Collector | Component | Interval | What it Polls |
|-----------|-----------|----------|---------------|
| swarm.py | swarm | configurable | Docker Swarm nodes, services, replicas |
| kafka.py | kafka | configurable | Kafka broker status, topic replication |
| elastic.py | elastic | configurable | Elasticsearch cluster health, index stats |
| proxmox_vms.py | proxmox_vms | configurable | Proxmox VMs and LXC containers |
| docker_agent01.py | docker_agent01 | configurable | Agent-01 container list |
| external_services.py | external_services | configurable | FortiGate, TrueNAS, etc. health checks |

**Architecture:**
- `api/collectors/manager.py` discovers all subclasses, starts as asyncio background tasks
- Each poll → `log_status_snapshot()` → `check_transition()` (alert on state change) → `evaluate_triggers()` (memory hooks)
- Exception-safe: never crashes the API

---

## 5. Agent Loop Control Flow (Missing from Original Audit)

```
POST /api/agent/run
  → classify task (observe/investigate/execute/build)
  → detect domain (kafka/swarm/proxmox/elastic/general)
  → build_step_plan() (1 or 2 steps: observe-then-execute)
  → filter tools by agent type
  → inject memory context (past outcomes + docs)

  For each step:
    While step < max_steps:
      1. Call LM Studio with messages + tools_spec
      2. If stop → check plan_action called for destructive intent → done
      3. Pre-flight: destructive tool without plan_action? → block + re-prompt
      4. Lock check: locked by other session? → block
      5. For each tool call:
         a. Memory activation (before_tool_call hook)
         b. Intercept plan_action → acquire lock → GUI confirm → release
         c. Intercept clarifying_question → GUI widget → answer
         d. Normal: invoke_tool() → log → stream to GUI
         e. degraded/failed? → auto-escalate with memory → halt
         f. After-tool-call hook (store in MuninnDB)
      6. Halt? → break

  → Record outcome engrams (success/failure)
  → Return final_status, tools_used, signals
```

**Max steps by agent type:** observe=8, investigate=12, execute=20, build=15

---

## 6. Memory & Feedback System (Missing from Original Audit)

### MuninnDB Integration (api/memory/)
| Module | Purpose |
|--------|---------|
| client.py | MuninnDB REST client (engram CRUD, concept activation) |
| ingest.py | Startup runbook ingestion (Swarm, Kafka, Elasticsearch, Filebeat) |
| ingest_worker.py | Async document ingestion worker |
| hooks.py | Before/after tool call hooks, memory context injection |
| triggers.py | Semantic trigger evaluation (e.g., "on Kafka lag > 1000, activate...") |
| feedback.py | Outcome + association engrams, feedback scoring |
| fetch_docs.py | External document fetching |
| summarize.py | Operation summarization for memory storage |
| schemas.py | Data schemas (engrams, docs) |

### Self-Improvement Loop
1. **Before tool call**: activate relevant engrams → inject into agent context
2. **After tool call**: store execution context
3. **On completion**: store outcome engram (task → tools → status)
4. **On success**: store tool association TWICE (Hebbian reinforcement)
5. **On failure**: store once with "failure" tag
6. **User feedback**: thumbs-up → golden engram; thumbs-down → just log
7. **Memory triggers**: repeated error patterns → critical alerts

---

## 7. Logging & Correlation (Missing from Original Audit)

### Logger (api/logger.py)
- Async batch-buffered: queue → flush every 100ms or 10 items
- `log_operation_start()` / `log_operation_complete()` → immediate write
- `log_tool_call()` / `log_status_snapshot()` / `log_escalation()` / `log_audit()` → batched

### Correlator (api/correlator.py)
- Links PostgreSQL operations ↔ Elasticsearch logs
- Time-window matching (300s default, 30s buffer per tool call)
- Anomaly detection: services with errors flagged
- Memory activation: relevant engrams surfaced

### Alert System (api/alerts.py)
- In-memory ring buffer (200 entries)
- Health state transitions → warning/critical/info alerts
- Elastic alerter (api/elastic_alerter.py) for log-derived alerts
- Memory-triggered alerts (repeated error patterns)

---

## 8. WebSocket & Session Management

### WebSocket Manager (api/websocket.py)
- JWT-authenticated connections (`/ws/output?token=<jwt>`)
- `broadcast()` → all clients + store in DB for session replay
- `send_line()` → typed messages (step, tool, reasoning, halt, done, error)
- `get_replay()` → fetch stored lines for session

### Session Store (api/session_store.py)
- Background flush every 0.2s to operation_log table
- Enables session replay from GUI

---

## 9. Settings & Configuration

### DB-Backed Settings (api/routers/settings.py)
- On first startup: seed from env vars (idempotent)
- On save: sync DB → os.environ (collectors pick up changes)
- 20+ keys with env var mappings and sensitivity flags
- Sensitive values masked in API responses

### Settings Keys (SERVER_KEYS in settings.py)
LM_STUDIO_BASE_URL, LM_STUDIO_MODEL, KAFKA_BOOTSTRAP_SERVERS, ELASTIC_URL,
ELASTIC_INDEX_PATTERN, DOCKER_HOST, MUNINNDB_URL, SKILL_GEN_BACKEND,
ANTHROPIC_API_KEY, PROXMOX_HOST, PROXMOX_USER, PROXMOX_TOKEN_ID,
PROXMOX_TOKEN_SECRET, FORTIGATE_HOST, FORTIGATE_API_KEY, TRUENAS_HOST,
TRUENAS_API_KEY, plus poll intervals and thresholds

---

## 10. Skill System (Complete Pipeline)

```
Description
  → LLM generates SKILL_SPEC (JSON, no code)
  → live_validator probes real endpoint
  → generate_code_from_spec()
  → validator.py (AST: banned imports, SKILL_META, execute())
  → save to modules/ or data/skill_modules/
  → register in DB
  → (optional) promote_skill() → first-class @mcp.tool()
```

### Skill Lifecycle States
```
auto_generated → promoted → (scrapped → restored) | purged
```

### Promotion (promoter.py)
- `promote_skill(name, domain)` → mark as promoted, assign agent domain
- `demote_skill(name)` → revert to auto_generated
- `scrap_skill(name)` → disable + move to data/skill_modules_scrapped/
- `purge_skill(name)` → hard-delete from DB + filesystem
- `restore_skill(name)` → move back from scrapped dir

---

## 11. Database Schema

### API Database (api/db/)
| Table | Purpose |
|-------|---------|
| schema_versions | Migration tracking |
| operations | Agent sessions (session_id, label, status, duration, final_answer) |
| tool_calls | Per-tool execution log (operation FK, params, result, duration, model) |
| status_snapshots | Collector poll results |
| escalations | Escalation events |
| audit_log | Structured event log |
| operation_log | WebSocket line store for session replay |

**6 migrations** applied at startup (indexes, columns, tables, feedback fields)

### Skills Database (mcp_server/tools/skills/storage/)
| Table | Purpose |
|-------|---------|
| skills | Skill metadata, metrics, lifecycle state |
| service_catalog | Detected versions, docs ingested flags |
| breaking_changes | Version-specific breaking changes |
| skill_compat_log | Compatibility check history |
| skill_audit_log | Skill system audit trail |
| checkpoints | Pre-operation state snapshots |
| settings | DB-backed settings |

---

## 12. Complete File Inventory

### Python (121 files, 23,888 LOC)
| Directory | Files | Purpose |
|-----------|-------|---------|
| api/ | 8 | Core (main, auth, alerts, lock, logger, correlator, etc.) |
| api/routers/ | 17 | REST endpoints |
| api/agents/ | 3 | Agent routing, orchestration, gate rules |
| api/collectors/ | 7 | Background data pollers |
| api/db/ | 5 | SQLAlchemy models, queries, migrations |
| api/memory/ | 10 | MuninnDB integration |
| agent/ | 1 | Standalone agent loop (LM Studio direct) |
| mcp_server/ | 2 | FastMCP server entry |
| mcp_server/tools/ | 8 | Tool implementations |
| mcp_server/tools/skills/ | 13 | Skill system core |
| mcp_server/tools/skills/modules/ | 4 | Skill modules (+template) |
| mcp_server/tools/skills/storage/ | 5 | Storage backends |
| scripts/ | 1 | Build info generation |
| tests/ | 17 | Unit + integration tests |

### Frontend (38 files)
| Directory | Files | Purpose |
|-----------|-------|---------|
| gui/src/components/ | 24 | UI components |
| gui/src/context/ | 6 | State management |
| gui/src/dev/ | 1 | Layout test harness |
| gui/src/utils/ | 2 | Version badge, version check |
| gui/src/ | 3 | App.jsx, main.jsx, api.js |
| gui/ | 2 | vite.config.js, eslint.config.js |

### Docker
| File | Purpose |
|------|---------|
| docker/Dockerfile | Multi-stage: Node 20 (GUI) → Python 3.13 → slim runtime |
| docker/docker-compose.yml | Dev: postgres, pgadmin, muninndb, hp1_agent |
| docker/swarm-stack.yml | Swarm deployment (1 replica, overlay network) |
| docker/entrypoint.sh | Container startup |
| docker/healthcheck.sh | Health check script |

### Dependencies (23 packages in requirements.txt)
FastAPI, Uvicorn, FastMCP, SQLAlchemy, asyncpg, aiosqlite, Docker SDK,
kafka-python, OpenAI SDK, Anthropic SDK, Pydantic, PyJWT, bcrypt, passlib,
Paramiko, Proxmoxer, Redis, trafilatura, pypdf, websockets, httpx

---

## 13. GUI (9 tabs, all functional)

| Tab | Component | Description |
|-----|-----------|-------------|
| Dashboard | DashboardCards | 6 status cards (Nodes, Brokers, Services, Elastic, Muninn, Summary) |
| Cluster | NodeMap | Visual grid: 3 managers + 3 workers with Kafka broker placement |
| Commands | CommandPanel | Agent prompt execution with tool/skill picker |
| Skills | SkillsPanel | Skill browser with execution forms, promote/demote |
| Logs | LogsPanel | 5 sub-tabs: Live Logs, Tool Calls, Operations, Escalations, Stats |
| Memory | MemoryPanel | MuninnDB engram browser, patterns, doc fetching |
| Output | OutputPanel | Real-time agent execution feed |
| Tests | TestsPanel | Integration test runner (dropdown) |
| Ingest | IngestPanel | Document ingestion with preview (dropdown) |

**Supporting components:** AlertToast, CardFilterBar, ChoiceBar, ClarificationWidget,
ElasticStatus, LockBadge, LoginScreen, LogTable, OptionsModal, PlanConfirmModal,
ServiceCards, SparkLine, StatsBar, StatusPanel, VersionBadge

---

## 14. What the Original Audit Missed

| Area | Status | Impact |
|------|--------|--------|
| Tool routing (tool_registry.py AST discovery + invoke_tool) | **Not audited** | Core to understanding how agent calls tools |
| Agent type routing (4 types + tool allowlists) | **Not audited** | Critical safety layer |
| Gate rules (3 pre-flight rules) | **Not audited** | Safety invariant |
| Plan lock + confirmation flow | **Not audited** | Prevents race conditions on destructive ops |
| Clarification system | **Not audited** | Agent ↔ human interaction |
| Collector system (7 background pollers) | **Not audited** | Data source for dashboard |
| Alert system (ring buffer + state transitions) | **Not audited** | Notification layer |
| Correlator (operations ↔ Elasticsearch logs) | **Not audited** | Observability |
| Memory hooks (before/after tool calls) | **Not audited** | Self-improvement engine |
| Feedback loop (outcome + association engrams) | **Not audited** | Hebbian learning |
| Session store + replay | **Not audited** | GUI session replay |
| Step orchestrator (multi-step decomposition) | **Not audited** | Task planning |
| Skill promotion lifecycle (5 states) | **Not audited** | Skill lifecycle management |
| Vendor switch guard in service_upgrade | **Not audited** | Safety invariant |
| Dashboard router (15+ endpoints, VM/container actions) | **Not audited** | Major GUI data source |
| Dead code: mcp_server/tools/skill_meta_tools.py | **Not flagged** | Legacy file, not imported |
| Dead code: ./doc_retrieval.py (project root) | **Not flagged** | Stale copy outside package |
| api/elastic_alerter.py | **Not audited** | Log-derived alert rules |
| api/confirmation.py | **Not audited** | Plan confirmation blocking |
| api/constants.py | **Not audited** | App name, version, defaults |
| api/session_store.py | **Not audited** | WebSocket line persistence |
| scripts/gen_build_info.py | **Not audited** | Docker build metadata |
| data/skill_imports/processed/sneakernet_test.py | **Not audited** | Sneakernet import test file |

---

## 15. Known Issues & Blockers

### Critical
1. **Operations never complete** — flush timing bug in agent.py (HANDOFF.md)
2. **stop_agent doesn't update DB** — cancelled ops stay "running" forever
3. **4 tool signature bugs** — audit_log, discover_environment, skill_execute, node_drain/activate

### Important
4. **1 test failure** — test_collectors_proxmox_vms.py patches non-existent `_get_disk_usage`
5. **MuninnDB not running** — memory panel, ingest, RAG, triggers, feedback all non-functional
6. **Dead code** — `mcp_server/tools/skill_meta_tools.py` and root `doc_retrieval.py` are unused
7. **No agent_settings.json** — referenced in CLAUDE.md but doesn't exist in codebase

### Minor
8. Only 3 skill modules — pipeline works but hasn't generated more
9. 16 of 19 audited platforms have zero tools
10. No rate limiting on tool calls
11. No cron/scheduled task support

---

## 16. Recommendations (Prioritized)

1. **Fix operation completion bug** — add `flush_now()` before `complete_operation` in agent.py
2. **Fix stop_agent** — update DB status on cancellation
3. **Fix 4 tool signature bugs** — enable LLM to call all tools correctly
4. **Get MuninnDB running** — unlocks memory, RAG, feedback, triggers (Phase 5)
5. **Fix failing test** — update patch target in test_collectors_proxmox_vms.py
6. **Remove dead code** — skill_meta_tools.py and root doc_retrieval.py
7. **Generate TrueNAS skill** — validate auto-generation pipeline end-to-end
8. **Add fingerprints** — NetBox, Wazuh, Security Onion, PBS, Technitium, Syncthing
9. **Connect to live infrastructure** — set env vars, validate tools against real services
10. **Add scheduled task support** — cron-like background agent tasks
