# Upgrade Workflow Reference

> Scout-loaded only. Read H2 headers first.

---

## Architecture

```
agent-01 (199.10) — MANAGEMENT VM         Swarm cluster — SERVICE TEST
─────────────────────────────────         ─────────────────────────────────
hp1_agent (standalone)          ───→     manager-01 (199.21) ★ LEADER: yxm2ust947ch
muninndb (:9475)                          manager-02 (199.22): tzrptdzsvggh
postgresql (:5432)                        manager-03 (199.23): z7zscpi5dxe9
                                          worker-01  (199.31): tyimr0p3dsow ← Kafka :9092
                                          worker-02  (199.32): scdz8rfwou0i ← Kafka :9093
                                          worker-03  (199.33): g7nkt24xs0oq ← Kafka :9094

Services deployed for testing:
Kafka cluster (3 brokers) / Elasticsearch / Logstash / Filebeat / services under test
```

Agent manages swarm. Agent never runs IN swarm.

---

## Pre-upgrade check gate (6 steps)

Called via `pre_upgrade_check(service="kafka")`. ALL must pass.

| Step | Tool | Failure action |
|------|------|---------------|
| 1. Swarm nodes ready | internal | Abort — fix degraded nodes first |
| 2. Kafka ISR intact | `kafka_broker_status` | Abort — ISR must be whole |
| 3. Elastic errors 30min | `elastic_error_logs` | Abort if errors on target service |
| 4. Log pattern anomaly | `elastic_log_pattern` | Abort if anomalous |
| 5. MuninnDB history | internal engram lookup | Warn if past failures |
| 6. Checkpoint save | `checkpoint_save` | Always auto-saved |

**NOTE**: Step 5 currently returns noise (`alert:filebeat` engrams) until
PLAN-filebeat-alerts-fix.md is executed. After fix, reads useful `outcome:*` engrams.

---

## Full upgrade sequence

### Phase 0 — Resolve target image tag
```python
service_resolve_image(image="confluentinc/cp-kafka")
# Returns: current_stable, previous_major, all_stable[]
# Pick target from all_stable
```

### Phase 1 — Pre-work (fresh session)
```python
knowledge_ingest_changelog(content=<release_notes>, service="kafka")
pre_upgrade_check(service="kafka")  # 6-step gate
# Must return status: ok on all 6 steps
```

### Phase 2 — Plan and approve
```python
plan_action(
    summary="Upgrade Kafka 3.6 → 3.7 on Swarm cluster",
    steps=["service_upgrade kafka", "post_upgrade_verify", "skill_compat_check_all"],
    risk_level="medium"
)
# Suspends agent — human approves or cancels
```

### Phase 3 — Execute
```python
service_upgrade(name="kafka", image="confluentinc/cp-kafka:3.7.0")
# tip: service_resolve_image first to find stable tags
# post_upgrade_verify called automatically
```

### Phase 4 — Verify
```python
post_upgrade_verify(service="kafka", operation_id=<from upgrade response>)
skill_compat_check_all()  # check all skills against new version
```

### Phase 5 — Skill remediation (if needed)
```python
skill_regenerate(name="kafka_consumer_lag")
skill_execute(name="kafka_consumer_lag")     # verify works
skill_update_compat(name, api_version="3.7")
```

### Phase 6 — Close out
```python
service_catalog_update(
    service_id="kafka",
    detected_version="3.7.0",
    known_latest="3.7.0",
    notes="Upgraded 2026-03-24. Skills checked OK."
)
```

---

## Node operations (always use node ID, never hostname)

```python
# Step 1: Get node IDs
swarm_status()  # Returns nodes with 'hostname' and 'id' fields

# Step 2: Resolve
# manager-01 → yxm2ust947ch
# worker-01  → tyimr0p3dsow

# Step 3: Plan and execute
plan_action(summary="Drain worker-01 for maintenance", risk_level="low",
            steps=["node_drain worker-01", "maintenance", "node_activate"])
node_drain(node_id="tyimr0p3dsow")   # HEX ID, not hostname
# ... maintenance ...
node_activate(node_id="tyimr0p3dsow")
```

---

## Rollback

```python
service_rollback(name="kafka")           # Swarm service rollback
# Or direct Docker (if agent unreachable):
# docker service rollback hp1_kafka
```

---

## Service-specific notes

### Kafka
- Check `controller_id` in `kafka_broker_status` — must be >= 0 (not -1)
- controller_id=-1 = broken cluster, fix before upgrading
- ISR must be intact before any broker restart
- `kafka_rolling_restart_safe` restarts one broker at a time with ISR gate

### Elasticsearch
- Cluster health must be GREEN before upgrade
- elastic-01 (199.40) is standalone, not in swarm — upgrade via image pull on that host

### Filebeat
- Alert threshold: `ELASTIC_FILEBEAT_STALE_MINUTES=10` (raise to 60 while debugging)
- Root cause: Filebeat on workers not shipping logs to Elasticsearch
- Check: `elastic_kafka_logs` — are Kafka logs reaching Elastic at all?

### Docker Engine
- `docker_engine_check_update` first — is there actually a new version?
- `docker_engine_update(dry_run=True)` — simulate
- `docker_engine_update(dry_run=False)` — actual upgrade (requires plan_action)
- Updates per-host — must run on each manager/worker separately

---

## Session splits for upgrades

**Session 1** — Preparation
```
knowledge_ingest_changelog(...)
pre_upgrade_check(service)
/handoff
```

**Session 2** — Execution
```
/prime  ← reads HANDOFF.md
plan_action(...)  # human approves
service_upgrade(...)
post_upgrade_verify(...)
/handoff
```

**Session 3** — Skill remediation (if needed)
```
/prime
skill_compat_check_all()
skill_regenerate(...)
service_catalog_update(...)
/commit
```
