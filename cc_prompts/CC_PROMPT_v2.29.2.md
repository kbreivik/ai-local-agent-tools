# CC PROMPT — v2.29.2 — Fix Kafka investigation: consumer lag path + triage-first pattern

## What this does
The agent investigated "why is Kafka degraded" and concluded "No active degradation" because:
1. kafka_broker_status returned "High consumer lag: 1153 (threshold: 1000)" — the answer
2. The RESEARCH_PROMPT's KAFKA DIAGNOSTIC CHAIN says "when a broker is missing" — so the
   agent ignored the consumer lag message and went looking for a missing broker instead
3. Found all 3 brokers up → concluded healthy — completely backwards

Fix: update RESEARCH_PROMPT and STATUS_PROMPT in api/agents/router.py to:
a) Add a "Kafka Degradation Triage" step BEFORE the broker-focused chain — reads the
   kafka_broker_status message field to understand WHY it's degraded, not just IF
b) Add a Consumer Lag investigation path that activates when lag is the root cause
c) Add kafka-consumer-groups.sh to kafka_exec guidance
d) Update the metric_trend available metrics to include consumer.lag.total
Version bump: 2.29.1 → 2.29.2

---

## Change 1 — api/agents/router.py: update RESEARCH_PROMPT

### 1a — Replace the KAFKA INVESTIGATION section in RESEARCH_PROMPT

NOTE for CC: Read api/agents/router.py first. Find the KAFKA DIAGNOSTIC CHAIN section
inside RESEARCH_PROMPT. It starts with:
```
5c. KAFKA DIAGNOSTIC CHAIN — follow this order when a broker is missing:
```

REPLACE that entire section (5c) with the following expanded version:

```
5c. KAFKA DEGRADATION TRIAGE — ALWAYS follow this order first:

STEP 0 — TRIAGE (always do this first, before any other Kafka tool):
  Call kafka_broker_status(). Read the 'message' field — it tells you WHY Kafka is degraded:
    • "High consumer lag: N (threshold: T)" → CONSUMER LAG PATH (see below)
    • "N/M brokers alive" or "broker N missing" → BROKER MISSING PATH (see below)
    • "Under-replicated partitions: N" → REPLICATION PATH
  Do NOT skip triage and jump to broker checks. The message field is the root cause.

CONSUMER LAG PATH — follow when message contains "consumer lag":
  The slow consumer is named in kafka.consumer_lag in the status (e.g. "logstash").
  That is the service that is behind on reading the Kafka topic.
  Step 1: service_placement("logstash_logstash")
          → confirm logstash Swarm task is running and on which worker node
  Step 2: vm_exec(host="<worker-from-step-1>",
          command="docker logs <logstash-container-id> --tail 100")
          → look for: Elasticsearch connection refused, bulk request errors,
            429 Too Many Requests, pipeline errors, backpressure messages
  Step 3: elastic_cluster_health()
          → if Elasticsearch is unhealthy or rejecting writes, that is why
            logstash is backing up and lag builds
  Step 4: kafka_exec(broker_label="<any-worker-label>",
          command="kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --group logstash")
          → shows per-partition lag, current offset vs log-end offset for logstash consumer group
  Root cause format: "Logstash consumer lag is N messages on topic hp1-logs.
    Logstash on <node> is <running/erroring>. <ES connection error / processing error / burst event>.
    Lag is <growing / stable / recovering>."
  Fix steps:
    1. If logstash container has ES errors: check ES health, clear write block if present
    2. If logstash is running but behind a burst: monitor metric_trend for consumer.lag.total —
       if lag is stable or decreasing, logstash is draining normally; no action needed
    3. If logstash is crashed/restarting: force-update the service to clear the state:
       swarm_service_force_update(service_name="logstash_logstash")
  IMPORTANT: Consumer lag alone (without logstash errors or crashes) may be transient —
    a burst of log events can temporarily exceed logstash throughput and self-resolve.
    Check metric_trend(entity_id="kafka_cluster", metric_name="consumer.lag.total", hours=1)
    to see if lag is growing, stable, or decreasing before recommending a restart.

BROKER MISSING PATH — follow when message contains "broker N missing" or broker count < expected:
  Step 1: kafka_broker_status() → note which broker ID is missing
  Step 2: swarm_node_status() → check if any worker node is Down
  Step 3: service_placement(service_name="kafka_broker-N")
          → find which node the task is on + vm_host_label
  Step 4: vm_exec(host=<vm_host_label>, command="docker ps --filter name=kafka")
          → verify container is actually running
  Step 5: kafka_exec(broker_label="<node-label>",
          command="kafka-topics.sh --bootstrap-server localhost:9092 --list")
          → verify broker can see the cluster from its own side
  Step 6: elastic_kafka_logs() — check historical error patterns

REPLICATION PATH — follow when message contains "under-replicated":
  Step 1: kafka_exec(broker_label="<any-worker>",
          command="kafka-topics.sh --bootstrap-server localhost:9092 --describe --topic hp1-logs")
          → shows which partitions are under-replicated and which brokers are in/out of ISR
  Step 2: kafka_broker_status() → confirm all brokers are registered
  Step 3: If a broker dropped out of ISR but is running: it may need time to catch up,
          or may need a force-update to clear a stale network attachment.

KAFKA EXEC — useful consumer group commands:
  List consumer groups:
    kafka-consumer-groups.sh --bootstrap-server localhost:9092 --list
  Describe a group (lag per partition):
    kafka-consumer-groups.sh --bootstrap-server localhost:9092 --describe --group logstash
  Describe topic (ISR, leader, replicas):
    kafka-topics.sh --bootstrap-server localhost:9092 --describe --topic hp1-logs
  Preferred leader election (fix unbalanced leaders):
    kafka-leader-election.sh --bootstrap-server localhost:9092 --election-type PREFERRED --all-topic-partitions
  broker_label must exactly match a vm_host connection label (e.g. "ds-docker-worker-01").
```

### 1b — Update metric_trend available metrics in RESEARCH_PROMPT

FIND (exact — the METRIC TREND QUERIES section in RESEARCH_PROMPT):
```
  kafka_cluster: brokers.alive, partitions.under_replicated, consumer.lag.total
```

REPLACE WITH:
```
  kafka_cluster: brokers.alive, partitions.under_replicated, consumer.lag.total
  (consumer.lag.total is key for consumer lag investigations — use hours=1 to see if lag
   is growing, stable, or decreasing. Decreasing = logstash is draining, no action needed.
   Growing = logstash is stuck or ES is rejecting writes.)
```

---

## Change 2 — api/agents/router.py: update STATUS_PROMPT

### 2a — Update the KAFKA INVESTIGATION section in STATUS_PROMPT

FIND (exact — in STATUS_PROMPT):
```
KAFKA INVESTIGATION:
When kafka_broker_status returns degraded (missing broker):
1. Call swarm_node_status() — check if the worker node is Down
```

REPLACE THE ENTIRE KAFKA INVESTIGATION SECTION with:

```
KAFKA INVESTIGATION — TRIAGE FIRST:
When investigating Kafka health, ALWAYS read kafka_broker_status 'message' field first:
  "High consumer lag: N" → consumer lag issue (NOT a broker problem)
  "broker N missing" → missing broker (use BROKER CHAIN below)
  "under-replicated: N" → ISR issue

CONSUMER LAG (when message contains "consumer lag"):
1. service_placement("logstash_logstash") — confirm logstash is running
2. vm_exec(host="<logstash-worker>", command="docker logs <container> --tail 50")
   → look for ES write errors, connection refused, 429 responses
3. elastic_cluster_health() — if ES is unhealthy, that causes logstash backpressure
4. metric_trend(entity_id="kafka_cluster", metric_name="consumer.lag.total", hours=1)
   → if lag is decreasing: logstash is draining, self-resolving
   → if lag is growing: logstash is stuck, needs investigation

BROKER MISSING CHAIN (when message contains "broker N missing"):
1. Call swarm_node_status() — check if the worker node is Down
2. If node is Up: call vm_exec(host="<any-manager-label>",
   command="docker service ps kafka_broker-1 --format '{{.Node}}|{{.CurrentState}}|{{.Error}}'")
   This shows which node the broker task is on and its state.
3. Then call kafka_exec(broker_label="<node-label-from-step-2>",
   command="kafka-topics.sh --bootstrap-server localhost:9092 --list")
   to verify the broker can see the cluster from its own perspective.
4. If task is Running but broker not in cluster: network issue — use service_placement()
   tool if available, or vm_exec to check docker service ps output.

TOPOLOGY SHORTCUT:
Instead of manually running docker service ps, use:
  service_placement(service_name="kafka_broker-1")
The parameter is service_name — do NOT use service= or name=.
Positional also works: service_placement("kafka_broker-1")
This returns: which node the task is on, its state, error message if any,
AND the exact vm_host_label to pass to vm_exec() or kafka_exec().
```

---

## Change 3 — api/agents/router.py: add kafka_consumer_lag to OBSERVE_AGENT_TOOLS + INVESTIGATE_AGENT_TOOLS

NOTE for CC: `kafka_consumer_lag` is already in INVESTIGATE_AGENT_TOOLS. Verify it is also
in OBSERVE_AGENT_TOOLS. If not, add it.

FIND (in OBSERVE_AGENT_TOOLS frozenset):
```
    "kafka_broker_status", "kafka_topic_health",
    "kafka_consumer_lag", "elastic_cluster_health",
```

If `kafka_consumer_lag` is missing from OBSERVE_AGENT_TOOLS, add it alongside
`kafka_broker_status` and `kafka_topic_health`.

---

## Version bump
Update VERSION: 2.29.1 → 2.29.2

## Commit
```bash
git add -A
git commit -m "fix(agent): v2.29.2 Kafka triage-first pattern — consumer lag path, broker path, replication path"
git push origin main
```
