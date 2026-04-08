# Plan: kafka-controller-fix
Date: 2026-03-24
Status: pending — EXECUTE AFTER node-activate-fix

## Objective
Restore Kafka controller election (controller_id = -1 means no controller).

## Background
3 Kafka brokers running on swarm workers (199.31:9092, 199.32:9093, 199.33:9094).
All brokers report healthy but controller_id = -1.
Without a controller: no partition leadership, no consumer group assignment,
no topic creation. Cluster is functionally broken despite "healthy" status.

## Pre-conditions (all must be true before executing)
- [ ] All 3 workers in state=ready, availability=active (check swarm_status)
- [ ] Kafka bootstrap servers reachable: kafka_broker_status returns 3 brokers
- [ ] NO active upgrade in progress
- [ ] pre_upgrade_check NOT required (this IS the fix, not an upgrade)

---

## Step 1 — Assess Kafka mode: ZooKeeper vs KRaft  (NO REBUILD)
**Risk**: NONE — read only

The fix differs depending on Kafka mode. Check via agent task:
```
Task: Run kafka_broker_status and report the full result including
any metadata about ZooKeeper or KRaft mode. Also check if there
are any Kafka-related error logs: elastic_error_logs(service='kafka', minutes=120)
```

### ZooKeeper mode indicators
- `zookeeper.connect` in broker config
- ZooKeeper container in swarm services

### KRaft mode indicators  
- `process.roles=broker,controller` or `process.roles=broker` in config
- No ZooKeeper container
- `kafka-metadata-quorum.sh` available

---

## Step 2 — Trigger controller re-election  (NO REBUILD)
**Risk**: LOW — rolling restart, one broker at a time

**Wait until PLAN-node-activate-fix is complete first** — need working node_drain/activate.

### If ZooKeeper mode
```bash
# On swarm manager, find ZooKeeper container
docker service ls | grep -i zoo

# Check ZooKeeper controller znode
docker exec <zookeeper-container> zkCli.sh get /controller
# If empty or stale: delete and wait for re-election
docker exec <zookeeper-container> zkCli.sh delete /controller
# ZooKeeper triggers new election automatically
```

### If KRaft mode
```bash
# Check quorum status on one broker
docker exec <kafka-broker-container> kafka-metadata-quorum.sh \
  --bootstrap-server localhost:9092 describe --status
# If quorum is healthy but no controller: rolling restart
```

### Rolling restart sequence (use kafka_rolling_restart_safe tool)
```
1. pre_kafka_check()                      # Verify ISR intact
2. plan_action(summary="Kafka rolling restart to fix controller_id=-1", risk_level="medium")
3. kafka_rolling_restart_safe(broker_id=1)  # worker-01
   # Wait for ISR recovery before next
4. kafka_rolling_restart_safe(broker_id=2)  # worker-02
5. kafka_rolling_restart_safe(broker_id=3)  # worker-03
6. kafka_broker_status()                  # Confirm controller_id != -1
```

---

## Step 3 — Verify and update service catalog  (NO REBUILD)

```bash
# Confirm controller elected
curl -s http://192.168.199.10:8000/api/status | \
  python3 -c "import sys,json; d=json.load(sys.stdin); \
  k=d.get('kafka',{}); print('controller_id:', k.get('controller_id')); \
  print('health:', k.get('health'))"
# Expected: controller_id >= 0 (not -1)

# Update catalog
service_catalog_update(service_id="kafka", notes="Controller restored via rolling restart 2026-03-24")
```

---

## Rebuild schedule
None required — broker restarts happen via Docker Swarm, not container rebuilds.

## Session plan
**Session A**: Step 1 (assess mode) — read only, 5 minutes
**Session B** (after node-activate-fix): Steps 2+3 — rolling restart, 15-20 minutes

## Downtime risk
Rolling restart: one broker at a time, ISR check between each.
Consumer lag will spike briefly per broker restart — normal.
If ISR fails to recover: STOP and rollback (kafka_rolling_restart_safe has built-in ISR gate).
