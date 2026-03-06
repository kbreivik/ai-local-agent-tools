# HP1-AI-Agent-v1

Local AI Infrastructure Orchestration Agent — a Python MCP server that enables a local LLM (Qwen3-Coder-30B) to autonomously manage, inspect, upgrade, and orchestrate a Docker Swarm + Kafka cluster with enforced checks and balances at every step.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        HP1-AI-Agent-v1                              │
│                                                                     │
│  ┌──────────────┐     ┌──────────────────┐     ┌────────────────┐  │
│  │  LM Studio   │────▶│   Agent Loop     │────▶│  MCP Server    │  │
│  │  (Qwen3-30B) │◀────│  agent_loop.py   │◀────│  server.py     │  │
│  │  :1234/v1    │     │                  │     │  (FastMCP)     │  │
│  └──────────────┘     └──────────────────┘     └───────┬────────┘  │
│                                                         │           │
│                              ┌──────────────────────────┤           │
│                              │                          │           │
│                    ┌─────────▼──────┐        ┌──────────▼───────┐  │
│                    │  swarm.py      │        │  kafka.py        │  │
│                    │  (7 tools)     │        │  (5 tools)       │  │
│                    └─────────┬──────┘        └──────────┬───────┘  │
│                              │                          │           │
│                    ┌─────────▼──────┐        ┌──────────▼───────┐  │
│                    │ Docker Swarm   │        │ Kafka Cluster    │  │
│                    │ (docker SDK)   │        │ (kafka-python)   │  │
│                    └────────────────┘        └──────────────────┘  │
│                                                                     │
│                    ┌───────────────────────────────────────────┐   │
│                    │  orchestration.py  (4 tools)              │   │
│                    │  checkpoint_save / restore / audit / esclate │
│                    └───────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Infrastructure Layout

```
Windows Host (Docker Desktop + WSL2)
│
├── Docker Swarm (npipe:////./pipe/docker_engine)
│   │
│   ├── Manager Node: docker-desktop
│   │   │
│   │   ├── workload-stack
│   │   │   └── workload  (nginx:1.25-alpine, 2 replicas)
│   │   │
│   │   └── kafka-stack
│   │       ├── kafka1  (apache/kafka:3.7.1, node_id=1, controller)
│   │       ├── kafka2  (apache/kafka:3.7.1, node_id=2)
│   │       └── kafka3  (apache/kafka:3.7.1, node_id=3)
│   │
│   └── Overlay Network: agent-net
│       ├── INTERNAL listener: kafka{1,2,3}:9092  (inter-broker)
│       └── EXTERNAL listener: localhost:9092/9093/9094  (host tools)
│
└── Python (3.11+)
    ├── MCP Server  (FastMCP 3.1.0)
    └── Agent Loop  (OpenAI SDK → LM Studio)
```

---

## Quick Start

### Prerequisites
- Docker Desktop (Windows, WSL2 backend)
- Python 3.11+
- LM Studio running with Qwen3-Coder-30B-A3B loaded

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Deploy infrastructure
```bash
# Init swarm (once)
docker swarm init

# Create overlay network
docker network create --driver overlay --attachable agent-net

# Deploy workload
docker stack deploy -c docker/swarm-stack.yml workload-stack

# Deploy Kafka (KRaft, 3 brokers)
docker stack deploy -c docker/kafka-stack.yml kafka-stack

# Verify (all should show REPLICAS = desired/desired)
docker service ls
```

### 3. Configure LM Studio API key
```bash
# Windows
set LM_STUDIO_API_KEY=<your-key-from-LM-Studio-Developer-settings>

# Or add to .env / mcp.json env block
```

### 4. Run the agent
```bash
python agent/agent_loop.py
```

### 5. Run tests
```bash
python -m pytest tests/ -v
```

---

## MCP Tools Reference

### Docker Swarm Tools

| Tool | Description | Returns |
|------|-------------|---------|
| `swarm_status()` | Node health, manager/worker state | nodes list, count |
| `service_list()` | All services, replicas, image versions | services list |
| `service_health(name)` | Specific service ready/degraded/failed | replica counts |
| `service_upgrade(name, image)` | Rolling upgrade with health gate | upgrade result |
| `service_rollback(name)` | Revert service to previous image | rollback status |
| `node_drain(node_id)` | Safe drain before maintenance | drain confirmation |
| `pre_upgrade_check()` | Full swarm readiness gate | gate pass/fail |

### Kafka Tools

| Tool | Description | Returns |
|------|-------------|---------|
| `kafka_broker_status()` | Broker health, leader election state | brokers list, controller |
| `kafka_consumer_lag(group)` | Lag per topic/partition | lag per partition |
| `kafka_topic_health(topic)` | Partition count, replication, ISR | health status |
| `kafka_rolling_restart_safe()` | ISR check before each broker restart | per-broker safety |
| `pre_kafka_check()` | Full Kafka readiness gate | gate pass/fail |

### Orchestration Tools

| Tool | Description | Returns |
|------|-------------|---------|
| `checkpoint_save(label)` | Snapshot state before risky ops | checkpoint file path |
| `checkpoint_restore(label)` | Load saved state for rollback | snapshot contents |
| `audit_log(action, result)` | Structured log of every decision | log confirmation |
| `escalate(reason)` | Flag high-risk decision, halt agent | escalation record |

---

## Response Schema

Every tool returns a consistent structured dict:

```python
{
    "status":    "ok" | "degraded" | "failed" | "error" | "escalated",
    "data":      { ... },          # tool-specific payload
    "timestamp": "2026-03-05T...", # UTC ISO-8601
    "message":   "Human-readable summary"
}
```

**Halt conditions:** `status == "degraded"` or `status == "failed"` triggers automatic escalation and agent halt.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DOCKER_HOST` | `npipe:////./pipe/docker_engine` | Docker socket |
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092,localhost:9093,localhost:9094` | Kafka brokers |
| `AUDIT_LOG_PATH` | `./logs/audit.log` | Structured audit log |
| `CHECKPOINT_PATH` | `./checkpoints` | Checkpoint snapshots |
| `LM_STUDIO_BASE_URL` | `http://localhost:1234/v1` | LM Studio OpenAI endpoint |
| `LM_STUDIO_MODEL` | `lmstudio-community/qwen3-coder-30b-a3b-instruct` | Model ID |
| `LM_STUDIO_API_KEY` | *(required)* | LM Studio API token |

---

## Project Structure

```
HP1-AI-Agent-v1/
├── agent/
│   └── agent_loop.py          # LLM agent: tool dispatch, halt logic, audit
├── mcp_server/
│   ├── server.py              # FastMCP server, all 16 tools registered
│   └── tools/
│       ├── swarm.py           # Docker Swarm tools (7)
│       ├── kafka.py           # Kafka tools (5)
│       └── orchestration.py   # Checkpoint / audit / escalate (4)
├── docker/
│   ├── swarm-stack.yml        # Workload service (nginx, 2 replicas)
│   └── kafka-stack.yml        # 3-broker KRaft Kafka cluster
├── docs/
│   ├── architecture.md        # Detailed architecture diagrams
│   ├── agent-flow.md          # Agent decision flow (Mermaid)
│   └── runbook.md             # Operations runbook
├── tests/
│   ├── test_tools.py          # 14 unit tests
│   └── test_e2e.py            # 13 E2E + security tests
├── logs/                      # audit.log written here
├── checkpoints/               # JSON state snapshots
├── .code-index/               # jcodemunch symbol index
├── .mcp.json                  # MCP server config
└── requirements.txt
```

---

## Security

- No credentials hardcoded — all via environment variables
- Every tool call auto-logged to structured audit trail
- Agent halts immediately on any `degraded` or `failed` status
- Checkpoint saved before every risky operation
- `escalate()` creates a permanent audit record and stops the agent
- Tests verify no hardcoded secrets in any tool module

---

## Kafka Network Design

```
Docker Overlay Network (agent-net)
┌─────────────────────────────────────────┐
│                                         │
│  kafka1  ←─── INTERNAL:9092 ──────────▶ kafka2
│  kafka2  ←─── INTERNAL:9092 ──────────▶ kafka3
│  kafka3  ←─── CONTROLLER:9093 ─────── kafka1
│                                         │
│  (KRaft quorum: 1@kafka1, 2@kafka2,    │
│                 3@kafka3)               │
└─────────────────────────────────────────┘
          │              │              │
     EXTERNAL        EXTERNAL       EXTERNAL
     :19092          :19092         :19092
          │              │              │
     host:9092      host:9093      host:9094
          │              │              │
          └──────────────┴──────────────┘
                Python tools / agent
         KAFKA_BOOTSTRAP_SERVERS=localhost:9092,...
```
