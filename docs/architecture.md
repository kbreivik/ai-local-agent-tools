# Architecture

## System Components

```mermaid
graph TB
    subgraph HOST["Operator Machine"]
        subgraph LMS["LM Studio"]
            MODEL["Qwen3-Coder-30B-A3B\nGGUF Q4_K_M"]
            API["OpenAI-compatible API\nlocalhost:1234/v1"]
        end

        subgraph GUI["React GUI :5173"]
            LOGIN["LoginScreen"]
            OUTPUT["OutputPanel (WS)"]
            LOGS["LogTable"]
            INGEST_UI["IngestPanel"]
            LOCK_UI["LockBadge"]
        end
    end

    subgraph AGENT["HP1-AI-Agent Container / bare-metal :8000"]
        subgraph FASTAPI["FastAPI Backend"]
            AUTH_R["POST /api/auth/login\nJWT HS256 24h"]
            AGENT_R["POST /api/agent/run\nSSE stream"]
            MEM_R["GET/POST /api/memory/*\nMuninnDB"]
            INGEST_R["POST /api/ingest/*\napproval flow"]
            WS["WS /ws/output\nbroadcast"]
            LOCK_R["GET /api/lock/status"]
        end

        subgraph LOOP["Agent Loop"]
            ROUTER["agents/router.py\n3-agent routing\nOPERATIONS / RESEARCH / SKILL_GEN"]
            PLAN["plan_action intercept\nglobal lock"]
            CLARIFY["clarifying_question intercept"]
        end

        subgraph MCP["MCP Server (FastMCP)"]
            SWARM_T["swarm.py\n9 tools"]
            KAFKA_T["kafka.py\n5 tools"]
            ORCH_T["orchestration.py\n6 tools"]
            ELASTIC_T["elastic.py\n7 tools"]
            DE_T["docker_engine.py\n3 tools (SSH)"]
            INGEST_T["ingest.py\n3 tools"]
            SKILL_T["skills/meta_tools.py\n18+ tools"]
        end

        subgraph STORAGE["Storage Layer"]
            AUTO["auto_detect.py\nPG probe → SQLite fallback"]
            SQLITE["SqliteBackend\ndata/skills.db WAL"]
            PG["PostgresBackend\npsycopg2 pool\nJSONB + FTS"]
            REDIS["RedisCache\noptional\n300s TTL"]
        end
    end

    subgraph INFRA["Infrastructure"]
        SWARM["Docker Swarm\nSwarm SDK"]
        KAFKA["Kafka Cluster\nKRaft 3 brokers"]
        ES["Elasticsearch\nhp1-logs-* index"]
        REMOTE["Remote Debian 12\nDocker Engine SSH"]
    end

    MODEL <--> API
    API <-->|"OpenAI SDK"| LOOP
    GUI <-->|"JWT + WS"| FASTAPI
    FASTAPI --> LOOP
    LOOP --> MCP
    SWARM_T --> SWARM
    KAFKA_T --> KAFKA
    ELASTIC_T --> ES
    DE_T -->|"paramiko SSH"| REMOTE
    ORCH_T --> STORAGE
    SKILL_T --> STORAGE
    AUTO --> SQLITE
    AUTO -.->|"if available"| PG
    AUTO -.->|"if available"| REDIS
```

---

## 3-Agent Routing

Tasks are classified into one of three agent profiles, each with a filtered tool set:

```mermaid
graph LR
    TASK["User Task"] --> CLASSIFY["classify_task()\nLLM intent detection"]

    CLASSIFY -->|"upgrade / rollback\nrestart / drain"| OPS["OPERATIONS agent\nSwarm + Kafka + Elastic\n+ Orchestration tools"]
    CLASSIFY -->|"search / explain\nwhat / why / show"| RES["RESEARCH agent\nElastic + Memory\n+ Ingest tools\n(read-only subset)"]
    CLASSIFY -->|"create skill\ndiscover / generate"| SKILL["SKILL_GEN agent\nSkill system tools\n+ Service catalog"]

    OPS --> PLAN_GUARD["plan_action() guard\nrequired before destructive ops"]
    OPS --> LOCK["PlanLockManager\nglobal lock across sessions"]
```

---

## Storage Layer

```mermaid
graph TB
    REG["registry.py\nthin delegation layer\nall callers unchanged"] --> INIT["get_backend()\nsingleton"]

    INIT --> DETECT["auto_detect.py\ndetect_backend()"]

    DETECT -->|"STORAGE_BACKEND=sqlite"| SQLITE["SqliteBackend\ndata/skills.db\nWAL + busy_timeout=5000"]
    DETECT -->|"STORAGE_BACKEND=postgres\nor PG port reachable"| PG["PostgresBackend\npsycopg2 SimpleConnectionPool\n1-5 conns\nJSONB, TIMESTAMPTZ, GIN FTS"]
    DETECT -->|"fallback"| SQLITE

    INIT2["get_cache()\nsingleton, may be None"] --> DETECT2["detect_cache()"]
    DETECT2 -->|"REDIS_URL or port 6379 reachable"| REDIS["RedisCache\nskill TTL=300s\nservice TTL=60s"]
    DETECT2 -->|"not found"| NONE["None\ncache disabled\nnon-fatal"]

    subgraph TABLES["skills.db tables"]
        T1["skills"]
        T2["service_catalog"]
        T3["breaking_changes"]
        T4["skill_compat_log"]
        T5["audit_log"]
        T6["checkpoints"]
        T7["settings"]
    end

    SQLITE --> TABLES
```

**Auto-detection probe order:**
1. `STORAGE_BACKEND` env var override (`sqlite` | `postgres`)
2. `DATABASE_URL` env var (full DSN)
3. `POSTGRES_HOST` env var (individual vars)
4. Network probe: `postgres`, `postgresql`, `db`, `database`, `host.docker.internal`, `172.17.0.1` on port 5432
5. SQLite fallback — always available, zero config

---

## Docker Deployment

```mermaid
graph TB
    subgraph BUILD["docker/Dockerfile (multi-stage)"]
        BUILDER["builder: python:3.13-slim\ngcc, build-essential\ncompile wheels"]
        RUNTIME["runtime: python:3.13-slim\nno compiler\ninstall from /wheels\nARG DOCKER_GID=998\nnon-root agent user"]
        BUILDER -->|"COPY --from=builder /wheels"| RUNTIME
    end

    subgraph COMPOSE["agent-compose.yml"]
        SVC["agent service\nhp1-ai-agent:latest\n:8000"]
        OPT_PG["postgres:16-alpine\nprofile: postgres"]
        OPT_REDIS["redis:7-alpine\nprofile: redis"]
        SVC -.->|"depends_on required:false"| OPT_PG
        SVC -.->|"depends_on required:false"| OPT_REDIS
    end

    subgraph VOLUMES["Named Volumes"]
        V1["hp1-agent-data\n/app/data"]
        V2["hp1-agent-logs\n/app/logs"]
        V3["hp1-agent-checkpoints\n/app/checkpoints"]
        V4["hp1-agent-skills\n/app/mcp_server/tools/skills/modules"]
    end

    subgraph MOUNTS["Bind Mounts"]
        M1["/var/run/docker.sock :ro"]
        M2["~/.ssh :ro"]
    end
```

**Deploy commands:**
```bash
# Standalone
docker compose -f docker/agent-compose.yml up -d

# With PostgreSQL
docker compose --profile postgres -f docker/agent-compose.yml up -d

# With PostgreSQL + Redis
docker compose --profile postgres --profile redis -f docker/agent-compose.yml up -d

# Swarm HA (requires external overlay network)
docker stack deploy -c docker/agent-swarm.yml hp1-agent
```

---

## Skill System

```mermaid
graph LR
    subgraph DISCOVERY["Discovery"]
        DISC["discover_environment(hosts)\n4-phase: ENUMERATE → IDENTIFY\n→ CATALOG → RECOMMEND\nno LLM, pure HTTP probing"]
    end

    subgraph GENERATION["Generation"]
        SEARCH["skill_search(query)\nfull-text search"]
        CREATE["skill_create(description)\nspec-first generation\nbackend: local|cloud|export"]
        VALIDATE["validate_skill_live(name)\nLayer 1: AST checks\nLayer 2: live endpoint probe\nLayer 3: LLM critic review"]
    end

    subgraph EXECUTION["Execution"]
        EXECUTE["skill_execute(name, **kwargs)\nsingle dispatcher\nno direct fn calls"]
        HEALTH["skill_health_summary()\ncompat + error rates\n+ stale checks"]
    end

    subgraph COMPAT["Compatibility"]
        COMPAT_CHK["skill_compat_check(name)\nversion drift detection"]
        CHANGELOG["knowledge_ingest_changelog()\nbreak change analysis"]
        REGEN["skill_regenerate(name)\nbackup + regenerate\nwith current docs"]
    end

    DISC --> CREATE
    SEARCH -->|"not found"| CREATE
    CREATE --> VALIDATE
    VALIDATE --> EXECUTE
    HEALTH --> COMPAT_CHK
    CHANGELOG --> REGEN
```

---

## MCP Server Tool Map

```mermaid
graph LR
    subgraph SERVER["mcp_server/server.py (FastMCP) — 50+ tools"]
        subgraph SWARM_TOOLS["Swarm (9)"]
            SS[swarm_status]
            SL[service_list]
            SH[service_health]
            SCV[service_current_version]
            SRI[service_resolve_image]
            SVH[service_version_history]
            SU[service_upgrade]
            SR[service_rollback]
            ND[node_drain]
        end
        subgraph KAFKA_TOOLS["Kafka (5)"]
            KB[kafka_broker_status]
            KL[kafka_consumer_lag]
            KT[kafka_topic_health]
            KR[kafka_rolling_restart_safe]
            PK[pre_kafka_check]
        end
        subgraph ORCH_TOOLS["Orchestration (6)"]
            CS[checkpoint_save]
            CR[checkpoint_restore]
            AL[audit_log]
            ES[escalate]
            PUF[pre_upgrade_check_full]
            PUV[post_upgrade_verify]
        end
        subgraph ELASTIC_TOOLS["Elastic (7)"]
            ECH[elastic_cluster_health]
            ESL[elastic_search_logs]
            EEL[elastic_error_logs]
            EKL[elastic_kafka_logs]
            ELP[elastic_log_pattern]
            EIS[elastic_index_stats]
            ECO[elastic_correlate_operation]
        end
    end

    SS & SL & SH & SU & SR & ND -->|docker SDK| DOCKER[(Docker API)]
    KB & KL & KT & KR & PK -->|kafka-python| KAFKA[(Kafka)]
    CS & CR -->|"DB + file"| STORE[(Storage)]
    AL -->|"DB + JSONL"| LOG[(logs/audit.log)]
    ECH & ESL & EEL & EKL & ELP -->|HTTP| ES[(Elasticsearch)]
```

---

## Audit + Checkpoint Dual-Write

Both audit entries and checkpoints are written to two places simultaneously:

```
checkpoint_save(label) / audit_log(action, result)
        │
        ├── PRIMARY: StorageBackend.save_checkpoint() / .append_audit()
        │   └── SQLite: data/skills.db  (or PostgreSQL)
        │       Survives container restarts, queryable, concurrent-safe
        │
        └── SECONDARY: filesystem
            ├── checkpoints/label_timestamp.json  (portable, tail-f)
            └── logs/audit.log  (JSONL, append-only)
```

---

## Data Flow: Service Upgrade (v1.9)

```mermaid
sequenceDiagram
    participant U as User (GUI)
    participant F as FastAPI
    participant A as Agent Loop
    participant L as LM Studio
    participant M as MCP Server
    participant D as Docker API

    U->>F: POST /api/agent/run {task, session_id}
    F->>A: run_agent(task, stream_callback)
    A->>L: system_prompt + task + tools
    L-->>A: tool_calls: [pre_upgrade_check_full]

    A->>M: pre_upgrade_check_full("workload")
    Note over M: 6 steps: swarm, kafka, elastic errors,<br/>error rate, memory context, checkpoint
    M-->>A: {status:ok, steps:[...]}

    L-->>A: tool_calls: [plan_action(summary, steps, risk=HIGH)]
    A->>F: plan_action intercepted → SSE event "plan_pending"
    F-->>U: SSE: {type:"plan", plan:{...}}
    U->>F: POST /api/agent/approve {session_id}
    F->>A: resume (approved=True)

    A->>M: service_upgrade("workload-stack_workload", "nginx:1.26-alpine")
    M->>D: service.update(image=...)
    loop poll 2s/60s
        M->>D: service_health()
        D-->>M: 2/2 running
    end
    M-->>A: {status:ok}

    A->>M: post_upgrade_verify("workload", operation_id)
    Note over M: replicas + elastic errors + correlation + memory engram
    M-->>A: {status:ok, verdict:success}

    A-->>F: stream final message
    F-->>U: SSE: {type:"done"}
```
