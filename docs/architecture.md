# Architecture

## System Components

```mermaid
graph TB
    subgraph HOST["Windows Host"]
        subgraph LMS["LM Studio"]
            MODEL["Qwen3-Coder-30B-A3B\nlmstudio-community/\nQwen3-Coder-30B-A3B-Instruct-GGUF\nQ4_K_M.gguf"]
            API["OpenAI-compatible API\nlocalhost:1234/v1"]
        end

        subgraph PYTHON["Python Runtime (3.13)"]
            AGENT["agent/agent_loop.py\nOpenAI SDK client\nTool dispatch loop\nHalt-on-degraded logic"]
            MCP["mcp_server/server.py\nFastMCP 3.1.0\n16 tools over stdio"]
            SWARM_T["tools/swarm.py\n7 tools\ndocker SDK"]
            KAFKA_T["tools/kafka.py\n5 tools\nkafka-python"]
            ORCH_T["tools/orchestration.py\n4 tools\ncheckpoints + audit"]
        end

        subgraph FILES["Filesystem"]
            LOG["logs/audit.log\nJSONL, one entry/action"]
            CP["checkpoints/\nlabel_timestamp.json"]
            IDX[".code-index/\njcodemunch symbols"]
        end
    end

    subgraph DOCKER["Docker Desktop (WSL2)"]
        subgraph SWARM["Docker Swarm"]
            MGR["Manager Node\ndocker-desktop"]

            subgraph WL["workload-stack"]
                W1["workload replica 1\nnginx:1.25-alpine"]
                W2["workload replica 2\nnginx:1.25-alpine"]
            end

            subgraph KS["kafka-stack"]
                K1["kafka1\napache/kafka:3.7.1\nnode_id=1\nboth broker+controller"]
                K2["kafka2\napache/kafka:3.7.1\nnode_id=2"]
                K3["kafka3\napache/kafka:3.7.1\nnode_id=3"]
            end

            NET["agent-net\noverlay network"]
        end
    end

    MODEL <--> API
    API <-->|"HTTP/JSON\nBearer token"| AGENT
    AGENT <-->|"tool calls"| MCP
    MCP --> SWARM_T
    MCP --> KAFKA_T
    MCP --> ORCH_T
    SWARM_T <-->|"npipe://\ndocker SDK"| MGR
    KAFKA_T <-->|"localhost:9092-9094\nkafka-python"| K1
    ORCH_T --> LOG
    ORCH_T --> CP
    K1 <-->|"INTERNAL\nkafka1:9092\noverlay"| K2
    K2 <-->|"INTERNAL\nkafka2:9092\noverlay"| K3
    K1 <-->|"CONTROLLER\n:9093"| K2
    K2 <-->|"CONTROLLER\n:9093"| K3
    K1 & K2 & K3 <--> NET
    W1 & W2 <--> NET
```

---

## MCP Server Tool Map

```mermaid
graph LR
    subgraph SERVER["mcp_server/server.py (FastMCP)"]
        subgraph SWARM_TOOLS["Swarm Tools"]
            SS[swarm_status]
            SL[service_list]
            SH[service_health]
            SU[service_upgrade]
            SR[service_rollback]
            ND[node_drain]
            PU[pre_upgrade_check]
        end
        subgraph KAFKA_TOOLS["Kafka Tools"]
            KB[kafka_broker_status]
            KL[kafka_consumer_lag]
            KT[kafka_topic_health]
            KR[kafka_rolling_restart_safe]
            PK[pre_kafka_check]
        end
        subgraph ORCH_TOOLS["Orchestration Tools"]
            CS[checkpoint_save]
            CR[checkpoint_restore]
            AL[audit_log]
            ES[escalate]
        end
    end

    SS & SL & SH & SU & SR & ND & PU -->|docker SDK| DOCKER[(Docker API)]
    KB & KL & KT & KR & PK -->|kafka-python| KAFKA[(Kafka Brokers)]
    CS & CR -->|JSON files| FS[(checkpoints/)]
    AL -->|JSONL append| LOG[(logs/audit.log)]
    ES --> AL
    ES -->|stdout| CONSOLE[Console Alert]

    PU --> SS
    PU --> SL
    PK --> KB
    PK --> KT
    CS --> SS
    CS --> SL
    CS --> KB
    SU --> PU
```

---

## Kafka Cluster — KRaft Mode

```mermaid
graph TB
    subgraph OVERLAY["Docker Overlay Network: agent-net"]
        subgraph K1BOX["kafka1 container"]
            K1I["INTERNAL listener\nkafka1:9092\ninter-broker"]
            K1C["CONTROLLER listener\nkafka1:9093\nKRaft quorum"]
            K1E["EXTERNAL listener\n:19092 → host:9092"]
        end
        subgraph K2BOX["kafka2 container"]
            K2I["INTERNAL listener\nkafka2:9092"]
            K2C["CONTROLLER listener\nkafka2:9093"]
            K2E["EXTERNAL listener\n:19092 → host:9093"]
        end
        subgraph K3BOX["kafka3 container"]
            K3I["INTERNAL listener\nkafka3:9092"]
            K3C["CONTROLLER listener\nkafka3:9093"]
            K3E["EXTERNAL listener\n:19092 → host:9094"]
        end

        K1C <-->|"KRaft quorum\nleader election\nmetadata log"| K2C
        K2C <-->|"KRaft quorum"| K3C
        K1I <-->|"partition replication\nfetch requests"| K2I
        K2I <-->|"partition replication"| K3I
    end

    HOST["Host machine\nPython tools / Agent"] -->|"localhost:9092"| K1E
    HOST -->|"localhost:9093"| K2E
    HOST -->|"localhost:9094"| K3E

    style K1BOX fill:#1a252f,color:#ecf0f1
    style K2BOX fill:#1a252f,color:#ecf0f1
    style K3BOX fill:#1a252f,color:#ecf0f1
```

---

## Data Flow: Service Upgrade

```mermaid
sequenceDiagram
    participant A as Agent Loop
    participant L as LM Studio (Qwen3)
    participant M as MCP Server
    participant D as Docker API
    participant K as Kafka Cluster
    participant F as Filesystem

    A->>L: System prompt + task
    L-->>A: tool_calls: [swarm_status, service_list, pre_upgrade_check, pre_kafka_check]

    A->>M: swarm_status()
    M->>D: nodes.list()
    D-->>M: [{id, hostname, role, state}]
    M-->>A: {status:ok, data:{nodes:[...]}}

    A->>M: pre_kafka_check()
    M->>K: describe_cluster() + list_topics()
    K-->>M: brokers=3, topics=[]
    M-->>A: {status:ok, data:{brokers:3}}

    A->>M: pre_upgrade_check()
    M->>D: nodes.list() + services.list()
    D-->>M: all nodes ready, all services healthy
    M-->>A: {status:ok}

    A->>M: audit_log("Initial state", ...)
    M->>F: append JSONL to logs/audit.log
    F-->>M: written

    A->>M: checkpoint_save("before_upgrade")
    M->>D: swarm_status + service_list
    M->>K: kafka_broker_status
    M->>F: write checkpoints/before_upgrade_<ts>.json
    F-->>M: {status:ok, file:"..."}
    M-->>A: {status:ok, data:{file:"..."}}

    A->>L: tool results → next inference
    L-->>A: tool_calls: [service_upgrade("workload", "nginx:1.26-alpine")]

    A->>M: service_upgrade("workload-stack_workload", "nginx:1.26-alpine")
    M->>D: pre_upgrade_check() [internal gate]
    D-->>M: ok
    M->>D: service.update(image="nginx:1.26-alpine")
    D-->>M: rolling update started

    loop Poll every 2s up to 60s
        M->>D: service_health("workload-stack_workload")
        D-->>M: {running: 2, desired: 2}
    end

    M-->>A: {status:ok, message:"upgraded to nginx:1.26-alpine"}

    A->>M: service_health (post-verify)
    M->>D: tasks(desired-state=running)
    D-->>M: 2/2 running
    M-->>A: {status:ok}

    A->>M: checkpoint_save("after_upgrade")
    M->>F: write checkpoints/after_upgrade_<ts>.json

    A->>M: audit_log("Upgrade completed", ...)
    M->>F: append JSONL

    A->>L: final tool results
    L-->>A: finish_reason=stop, content="Upgrade complete..."
    A->>F: audit_log("agent_complete", {steps:5})
```

---

## Checkpoint Structure

Each checkpoint is a JSON snapshot of the entire infrastructure state at a point in time:

```
checkpoints/
├── before_upgrade_1741204069.json
├── after_upgrade_1741204115.json
└── e2e_pre_upgrade_1741204032.json
```

```json
{
  "label": "before_upgrade",
  "timestamp": "2026-03-05T19:07:49Z",
  "swarm": {
    "status": "ok",
    "data": {
      "nodes": [
        { "id": "0sj1zr8f1pcm", "hostname": "docker-desktop",
          "role": "manager", "state": "ready", "availability": "active" }
      ]
    }
  },
  "services": {
    "status": "ok",
    "data": {
      "services": [
        { "name": "workload-stack_workload",
          "image": "nginx:1.25-alpine",
          "desired_replicas": 2, "running_replicas": 2 }
      ]
    }
  },
  "kafka": {
    "status": "ok",
    "data": { "brokers": [...], "count": 3, "controller_id": 1 }
  }
}
```

---

## Audit Log Format

`logs/audit.log` — JSONL, one entry per line, append-only:

```jsonl
{"timestamp":"2026-03-05T19:07:49Z","action":"agent_start","result":{"task":"rolling_upgrade","model":"lmstudio-community/..."}}
{"timestamp":"2026-03-05T19:07:51Z","action":"tool:swarm_status","result":{"args":{},"result_status":"ok"}}
{"timestamp":"2026-03-05T19:07:52Z","action":"tool:pre_kafka_check","result":{"args":{},"result_status":"ok"}}
{"timestamp":"2026-03-05T19:07:53Z","action":"Initial system check","result":"All gates passed"}
{"timestamp":"2026-03-05T19:07:55Z","action":"checkpoint_save","result":{"label":"before_upgrade","file":"..."}}
{"timestamp":"2026-03-05T19:08:02Z","action":"tool:service_upgrade","result":{"args":{"name":"workload-stack_workload","image":"nginx:1.26-alpine"},"result_status":"ok"}}
{"timestamp":"2026-03-05T19:08:12Z","action":"Upgrade completed successfully","result":"nginx:1.26-alpine healthy 2/2"}
{"timestamp":"2026-03-05T19:08:14Z","action":"agent_complete","result":{"steps":5}}
```
