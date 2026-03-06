# Operations Runbook

---

## Starting the Stack

### Full cold start
```bash
# 1. Init swarm (first time only)
docker swarm init

# 2. Create overlay network (first time only)
docker network create --driver overlay --attachable agent-net

# 3. Deploy workload service
docker stack deploy -c docker/swarm-stack.yml workload-stack

# 4. Deploy Kafka cluster
docker stack deploy -c docker/kafka-stack.yml kafka-stack

# 5. Wait ~30s for KRaft quorum, then verify
docker service ls
# Expected: all REPLICAS columns show desired/desired
```

### Verify Kafka inter-broker comms
```bash
# From inside kafka1, reach kafka2 via overlay DNS
KAFKA_CID=$(docker ps --filter "name=kafka-stack_kafka1" --format "{{.ID}}" | head -1)
docker exec "$KAFKA_CID" bash -c \
  "/opt/kafka/bin/kafka-broker-api-versions.sh --bootstrap-server kafka2:9092" \
  | head -3
# Expected: kafka1:9092 (id: 1 rack: null) -> (Produce(0): ...
```

### Verify from host
```bash
python -c "
from mcp_server.tools.kafka import kafka_broker_status, pre_kafka_check
from mcp_server.tools.swarm import swarm_status, pre_upgrade_check
import json
print(json.dumps(kafka_broker_status(), indent=2))
print(json.dumps(pre_upgrade_check(), indent=2))
"
```

---

## Running the Agent

```bash
# Set API key (from LM Studio → Developer → API Key)
set LM_STUDIO_API_KEY=sk-lm-XXXXXXXX

# Run with default task (rolling upgrade)
python agent/agent_loop.py

# Run with custom task
python agent/agent_loop.py "Check Kafka consumer lag for group my-consumers"
```

### Expected agent output
```
=== Agent Loop Started @ 2026-03-05T19:07:49Z ===
Model: lmstudio-community/qwen3-coder-30b-a3b-instruct

--- Step 1 ---
  [swarm_status] → ok | Swarm healthy: 1 nodes
  [service_list] → ok | OK
  [pre_upgrade_check] → ok | Swarm ready for upgrade
  [pre_kafka_check] → ok | Kafka ready for operations
  ...

--- Step 2 ---
  [checkpoint_save] → ok | Checkpoint 'before_upgrade' saved
  [service_upgrade] → ok | Service upgraded to nginx:1.26-alpine
  ...

=== Agent finished after 5 steps ===
```

---

## Stopping the Stack

```bash
# Remove stacks (preserves volumes)
docker stack rm workload-stack kafka-stack

# Leave swarm (resets everything)
docker swarm leave --force

# Remove volumes (destroys Kafka data)
docker volume rm kafka-stack_kafka1-data kafka-stack_kafka2-data kafka-stack_kafka3-data
```

---

## Troubleshooting

### Agent halts with "Kafka not ready"

```
!! HALT CONDITION: pre_kafka_check returned degraded
Topics not healthy: ['some-topic']
```

**Diagnosis:**
```bash
# Check which topics are under-replicated
python -c "
from mcp_server.tools.kafka import kafka_broker_status, kafka_topic_health
import json
print(json.dumps(kafka_broker_status(), indent=2))
"

# From inside a kafka container
KAFKA_CID=$(docker ps --filter "name=kafka-stack_kafka1" --format "{{.ID}}" | head -1)
docker exec "$KAFKA_CID" bash -c \
  "/opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka1:9092 --describe"
```

**Fix — delete test/stale topic:**
```bash
docker exec "$KAFKA_CID" bash -c \
  "/opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka1:9092 --delete --topic e2e-load-test"
```

**Fix — brokers not fully up yet:** wait 30–60s, then retry.

---

### Kafka services show 0/1 replicas

```bash
docker service ps kafka-stack_kafka1 --no-trunc | head -5
```

Common causes:
| Error | Fix |
|-------|-----|
| `No such image` | `docker pull apache/kafka:3.7.1` |
| `port already allocated` | Another process on 9092-9094; stop it |
| Container exits immediately | Check logs: `docker service logs kafka-stack_kafka1` |
| Stale KRaft data | Remove volumes and redeploy (see above) |

---

### LM Studio API key rejected

```
Error: Malformed LM Studio API token provided
```

1. Open LM Studio → Developer tab → copy API Key
2. `set LM_STUDIO_API_KEY=<copied-key>`
3. Verify: `curl -H "Authorization: Bearer <key>" http://localhost:1234/v1/models`

---

### No model loaded in LM Studio

```
# v1/models returns empty list
{"data": []}
```

Load the model in LM Studio UI → My Models → click Qwen3-Coder-30B → Load.
Or use the LM Studio API to load it programmatically.

---

### Docker swarm not initialized

```
Error: This node is not a swarm manager
```

```bash
docker swarm init
docker network create --driver overlay --attachable agent-net
```

---

### service_rollback fails

The Docker Swarm rollback API requires the service to have a previous spec stored.
If the service was freshly created with only one version, there's nothing to roll back to.

**Manual rollback:**
```bash
docker service update --image nginx:1.25-alpine workload-stack_workload
```

---

## Restoring from Checkpoint

Checkpoints store a full snapshot but **do not auto-apply** state — the agent reads them and decides what to restore. To manually restore:

```python
from mcp_server.tools.orchestration import checkpoint_restore
from mcp_server.tools.swarm import service_upgrade
import json

# Load checkpoint
cp = checkpoint_restore("before_upgrade")
snapshot = cp["data"]["snapshot"]

# Restore each service to its snapshotted image
for svc in snapshot["services"]["data"]["services"]:
    service_upgrade(svc["name"], svc["image"].split("@")[0])
```

---

## Tests

```bash
# Unit tests only (no Docker/Kafka needed for most)
python -m pytest tests/test_tools.py -v

# Full E2E (requires live Docker + Kafka)
python -m pytest tests/test_e2e.py -v

# All tests
python -m pytest tests/ -v --tb=short

# Single test
python -m pytest tests/test_e2e.py::TestE2ERollingUpgrade::test_step9_rolling_upgrade_with_kafka_load -v -s
```

---

## Viewing the Audit Log

```bash
# Last 20 entries, pretty-printed
python -c "
import json
with open('logs/audit.log') as f:
    for line in list(f)[-20:]:
        print(json.dumps(json.loads(line), indent=2))
        print('---')
"

# Filter for escalations only
python -c "
import json
with open('logs/audit.log') as f:
    for line in f:
        entry = json.loads(line)
        if 'ESCALAT' in entry.get('action',''):
            print(json.dumps(entry, indent=2))
"

# Count tool calls by name
python -c "
import json, collections
counts = collections.Counter()
with open('logs/audit.log') as f:
    for line in f:
        entry = json.loads(line)
        if entry['action'].startswith('tool:'):
            counts[entry['action']] += 1
for k, v in counts.most_common():
    print(f'{v:4d}  {k}')
"
```

---

## Re-indexing with jcodemunch

```bash
python -c "
import os
os.environ['CODE_INDEX_PATH'] = 'D:/claude_code/FAJK/HP1-AI-Agent-v1/.code-index'
from jcodemunch_mcp.server import index_folder
result = index_folder('D:/claude_code/FAJK/HP1-AI-Agent-v1')
print(result)
"
```

---

## File Locations

| File | Purpose |
|------|---------|
| `logs/audit.log` | Every agent decision and tool call, JSONL |
| `logs/e2e_audit.log` | E2E test audit trail |
| `checkpoints/` | JSON snapshots, named `label_timestamp.json` |
| `.code-index/` | jcodemunch symbol index (auto-generated) |
| `.mcp.json` | MCP server registration for Claude / LM Studio |
| `mcp.json` | Legacy config (superseded by `.mcp.json`) |
