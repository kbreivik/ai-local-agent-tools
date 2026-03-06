# Agent Decision Flow

The agent follows a strict **check → act → verify → continue or halt** loop.
Every branch that returns `degraded` or `failed` triggers `escalate()` and stops the agent.

---

## Main Agent Loop

```mermaid
flowchart TD
    START([Agent Start]) --> INIT[Load system prompt\nConnect to LM Studio\naudit_log: agent_start]
    INIT --> LLM{LLM inference\nchat completion}

    LLM -->|finish_reason = stop\nno tool calls| DONE([Agent Complete\naudit_log: agent_complete])
    LLM -->|tool_calls present| DISPATCH[Dispatch tool calls]

    DISPATCH --> EXEC[Execute tool\nauto audit_log every call]
    EXEC --> CHECK{tool result\nstatus?}

    CHECK -->|ok| APPEND[Append tool result\nto message history]
    CHECK -->|degraded\nor failed| ESCALATE[escalate\nreason = tool + status]

    ESCALATE --> HALT([Agent HALTED\naudit_log: agent_halted])
    APPEND --> MORE{More tool calls\nin this step?}

    MORE -->|yes| EXEC
    MORE -->|no| MAXCHECK{Step count\n≥ max_steps?}

    MAXCHECK -->|yes| MAXHALT([Agent: max steps reached\naudit_log: agent_max_steps])
    MAXCHECK -->|no| LLM
```

---

## Rolling Upgrade Flow

The sequence the agent executes for a service rolling upgrade.

```mermaid
flowchart TD
    A([Start: Rolling Upgrade Task]) --> B[swarm_status]
    B --> B2{ok?}
    B2 -->|no| HALT1([HALT + escalate])
    B2 -->|yes| C[service_list\nDiscover current state]

    C --> D[pre_kafka_check]
    D --> D2{ok?}
    D2 -->|degraded/failed| HALT2([HALT + escalate])
    D2 -->|ok| E[pre_upgrade_check]

    E --> E2{ok?}
    E2 -->|degraded/failed| HALT3([HALT + escalate])
    E2 -->|ok| F[service_health name]

    F --> F2{ok?}
    F2 -->|failed| HALT4([HALT + escalate])
    F2 -->|ok/degraded| G[audit_log\nInitial state recorded]

    G --> H[checkpoint_save\nbefore_upgrade]
    H --> H2{saved?}
    H2 -->|error| HALT5([HALT + escalate])
    H2 -->|ok| I[service_upgrade\nname → new_image]

    I --> WAIT[Wait for rolling update\nhealth-poll every 2s\nmax 60s]
    WAIT --> J{service_health\npost-upgrade}

    J -->|ok\n2/2 replicas| K[kafka_broker_status\nVerify Kafka still healthy]
    J -->|failed| ROLLBACK[service_rollback\nname]
    J -->|degraded| L[escalate\ndegraded after upgrade]

    ROLLBACK --> ROLLBACK2{rollback ok?}
    ROLLBACK2 -->|yes| HALT6([HALT — rolled back\naudit_log: rollback])
    ROLLBACK2 -->|no| HALT7([HALT — rollback failed\naudit_log: critical])

    K --> K2{ok?}
    K2 -->|degraded| M[escalate\nKafka degraded post-upgrade]
    K2 -->|ok| N[checkpoint_save\nafter_upgrade]

    N --> O[audit_log\nUpgrade completed successfully]
    O --> DONE([DONE])

    L --> HALT8([HALT])
    M --> HALT9([HALT])

    style HALT1 fill:#c0392b,color:#fff
    style HALT2 fill:#c0392b,color:#fff
    style HALT3 fill:#c0392b,color:#fff
    style HALT4 fill:#c0392b,color:#fff
    style HALT5 fill:#c0392b,color:#fff
    style HALT6 fill:#e67e22,color:#fff
    style HALT7 fill:#c0392b,color:#fff
    style HALT8 fill:#c0392b,color:#fff
    style HALT9 fill:#c0392b,color:#fff
    style DONE fill:#27ae60,color:#fff
    style A fill:#2980b9,color:#fff
```

---

## Gate Hierarchy

```mermaid
flowchart LR
    subgraph GATES["Safety Gates — must all pass before upgrade"]
        G1[pre_kafka_check\nAll brokers up\nAll topics healthy\nNo under-replicated partitions]
        G2[pre_upgrade_check\nAll swarm nodes ready\nAll services at desired replicas]
        G3[service_health name\nTarget service 2/2 running]
        G4[checkpoint_save\nState snapshot on disk]
    end

    G1 -->|PASS| G2
    G2 -->|PASS| G3
    G3 -->|PASS| G4
    G4 -->|SAVED| ACTION[service_upgrade]

    G1 -->|FAIL| E1([escalate + halt])
    G2 -->|FAIL| E2([escalate + halt])
    G3 -->|FAIL| E3([escalate + halt])
    G4 -->|FAIL| E4([escalate + halt])

    style ACTION fill:#27ae60,color:#fff
    style E1 fill:#c0392b,color:#fff
    style E2 fill:#c0392b,color:#fff
    style E3 fill:#c0392b,color:#fff
    style E4 fill:#c0392b,color:#fff
```

---

## Tool Call Lifecycle

```mermaid
sequenceDiagram
    participant LLM as LLM (Qwen3)
    participant Loop as Agent Loop
    participant Tool as Tool Module
    participant Audit as Audit Log
    participant Infra as Docker/Kafka

    Loop->>LLM: chat.completions.create(messages, tools)
    LLM-->>Loop: response(tool_calls=[...])

    loop For each tool_call
        Loop->>Tool: dispatch(name, args)
        Tool->>Infra: API call (docker SDK / kafka-python)
        Infra-->>Tool: raw result
        Tool-->>Loop: {status, data, timestamp, message}
        Loop->>Audit: audit_log(tool:name, {args, status})
        alt status == degraded or failed
            Loop->>Tool: escalate(reason)
            Tool->>Audit: audit_log(ESCALATE, entry)
            Loop-->>Loop: HALT — stop all processing
        else status == ok
            Loop->>Loop: append tool result to messages
        end
    end

    Loop->>LLM: next inference with tool results
```

---

## Status State Machine

```mermaid
stateDiagram-v2
    [*] --> ok : Tool call succeeds\nall checks pass

    ok --> degraded : Partial failure\n(e.g. 1/3 replicas down\nunder-replicated topic)

    ok --> failed : Complete failure\n(0 replicas running\nbroker unreachable)

    ok --> error : Exception / connection error\nDocker or Kafka unreachable

    degraded --> escalated : Agent triggers escalate()
    failed --> escalated : Agent triggers escalate()
    error --> escalated : Agent triggers escalate()

    escalated --> [*] : Agent halts\nHuman review required

    ok --> [*] : Task complete\nAgent finishes normally

    note right of escalated
        Permanent audit record written.
        No further tool calls.
        Human must investigate.
    end note
```

---

## ASCII Flow (terminal-friendly)

```
AGENT START
    │
    ▼
┌─────────────────────────────────────────┐
│  STEP 1: Environment Discovery          │
│  swarm_status() ──────────── ok? ──NO──▶ HALT
│  service_list()                          │
│  pre_upgrade_check() ─────── ok? ──NO──▶ HALT
│  pre_kafka_check() ───────── ok? ──NO──▶ HALT
│  kafka_broker_status()                   │
│  service_health(workload) ── ok? ──NO──▶ HALT
└───────────────────────┬─────────────────┘
                        │ ALL OK
                        ▼
┌─────────────────────────────────────────┐
│  STEP 2: Pre-Action Safety              │
│  audit_log("initial state", ...)        │
│  checkpoint_save("before_upgrade")      │
└───────────────────────┬─────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────┐
│  STEP 3: Execute Upgrade                │
│  service_upgrade("workload",            │
│                  "nginx:1.26-alpine")   │
│  ┌── poll service_health every 2s ──┐  │
│  │   until ok or timeout (60s)      │  │
│  └───────────────────────────────────┘  │
│  result: failed? ──────────────────────▶ service_rollback() ──▶ HALT
│  result: degraded? ────────────────────▶ escalate() ──────────▶ HALT
└───────────────────────┬─────────────────┘
                        │ ok
                        ▼
┌─────────────────────────────────────────┐
│  STEP 4: Post-Upgrade Verification      │
│  service_health() ────────── ok?        │
│  swarm_status() ──────────── ok?        │
│  kafka_broker_status() ────── ok?       │
└───────────────────────┬─────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────┐
│  STEP 5: Finalise                       │
│  checkpoint_save("after_upgrade")       │
│  audit_log("Upgrade completed", ...)    │
└───────────────────────┬─────────────────┘
                        │
                        ▼
                   AGENT DONE
```
