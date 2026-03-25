# HP1-AI-Agent MCP Tools Reference

> Scout-loaded only. 59 registered tools as of v1.10.1 build 24.
> Read H2 headers first to find the relevant section.

---

## Swarm node ID map (confirmed 2026-03-24)

| Hostname | Swarm node ID | Role | Notes |
|----------|-------------|------|-------|
| manager-01 | yxm2ust947ch | manager | ★ Raft leader |
| manager-02 | tzrptdzsvggh | manager | |
| manager-03 | z7zscpi5dxe9 | manager | |
| worker-01 | tyimr0p3dsow | worker | Kafka broker 1 :9092 |
| worker-02 | scdz8rfwou0i | worker | Kafka broker 2 :9093 |
| worker-03 | g7nkt24xs0oq | worker | Kafka broker 3 :9094 |

**CRITICAL**: `node_drain` and `node_activate` require the hex Swarm node ID, NOT the hostname.
Always call `swarm_status()` first to resolve hostname → node_id.

```python
# WRONG — agent has done this repeatedly and got stuck:
node_drain(node_id="manager-01")

# CORRECT:
# Step 1: swarm_status() → find node where hostname=="manager-01" → .id = "yxm2ust947ch"
# Step 2: node_drain(node_id="yxm2ust947ch")
```

---

## Known bugs (live 2026-03-24)

### Operations never complete (0% success rate)
All 12 operations show status="running" permanently. The agent loop does not mark
operations as completed after finishing. This is a separate bug from the node_id issue.
Fix tracked in PLAN-node-activate-fix.md Step 2.

### discover_environment requires hosts_json
Calling discover_environment() with no args fails:
`"missing 1 required positional argument: 'hosts_json'"`

Correct invocation:
```python
discover_environment(hosts_json='[{"address":"192.168.199.10"},{"address":"192.168.199.40"}]')
# hosts_json = JSON string of array, each entry has "address" and optional "port"
```

HP1 full hosts_json template:
```json
[
  {"address":"192.168.199.10"},
  {"address":"192.168.199.21"},{"address":"192.168.199.22"},{"address":"192.168.199.23"},
  {"address":"192.168.199.31"},{"address":"192.168.199.32"},{"address":"192.168.199.33"},
  {"address":"192.168.199.40"},
  {"address":"192.168.1.5","port":8006},
  {"address":"192.168.1.6","port":8006},
  {"address":"192.168.1.7","port":8006}
]
```

---

## Docker tools (3)

| Tool | Params | Destructive |
|------|--------|-------------|
| `docker_engine_check_update` | none | No |
| `docker_engine_version` | none | No |
| `docker_engine_update` | `dry_run: bool` | YES — `plan_action()` first |

---

## Elastic tools (7)

| Tool | Key params | Purpose |
|------|-----------|---------|
| `elastic_cluster_health` | none | Cluster status, shards |
| `elastic_error_logs` | `service`, `minutes` | Errors in last N min |
| `elastic_log_pattern` | `service`, `minutes` | Anomaly detection |
| `elastic_correlate_operation` | `operation_id` | Correlate logs to upgrade |
| `elastic_index_stats` | `index` | Index size, doc count |
| `elastic_kafka_logs` | `minutes` | Kafka-specific entries |
| `elastic_search_logs` | `query`, `service`, `minutes` | Free-text log search |

---

## Kafka tools (5)

| Tool | Key params | Purpose |
|------|-----------|---------|
| `kafka_broker_status` | none | Broker health — check `controller_id` field |
| `kafka_consumer_lag` | `group` | Consumer group lag |
| `kafka_topic_health` | `topic` | Partition health, ISR |
| `pre_kafka_check` | none | Pre-flight (ISR, errors) |
| `kafka_rolling_restart_safe` | `broker_id` | Safe rolling restart — `plan_action()` first |

**Known issue**: `controller_id=-1` means no controller elected — cluster broken despite "healthy".

---

## Orchestration tools (8)

### `plan_action(summary, steps, risk_level)`
**Required before any destructive operation.** Suspends agent, waits for human approval.

Required before: `service_upgrade`, `service_rollback`, `node_drain`, `checkpoint_restore`,
`kafka_rolling_restart_safe`, `docker_engine_update(dry_run=False)`.

### `checkpoint_save(label)`
Snapshot agent state. Called automatically by `pre_upgrade_check`. Use before any multi-step destructive workflow.

### `checkpoint_restore(checkpoint_id)`
Restore state. DESTRUCTIVE — `plan_action()` first.

### `pre_upgrade_check(service)`
**6-step gate**: Swarm nodes → Kafka ISR → Elastic errors → log pattern → MuninnDB history → checkpoint save.
Returns `status: degraded` if any step fails.

### `post_upgrade_verify(service, operation_id)`
Called after `service_upgrade`. Checks replicas, Elastic errors, correlates logs.

### `clarifying_question(question, options)`, `escalate(reason, context)`, `audit_log(...)` — standard

---

## Service / Swarm / Node tools (10)

| Tool | Key params | Destructive |
|------|-----------|-------------|
| `service_list` | none | No |
| `service_health` | `name` | No |
| `service_current_version` | `name` | No |
| `service_resolve_image` | `image`, `resolve_previous` | No |
| `service_catalog_list` | none | No |
| `service_catalog_update` | `service_id`, `detected_version`, `known_latest`, `notes` | No |
| `service_upgrade` | `name`, `image` | YES — `plan_action()` + `pre_upgrade_check()` first |
| `service_rollback` | `name` | YES — `plan_action()` first |
| `node_drain` | `node_id` (HEX ID!) | YES — `plan_action()` first |
| `node_activate` | `node_id` (HEX ID!) | No |
| `swarm_status` | none | No — use to resolve hostname→node_id |

### Node operation pattern (always follow this)
```
1. swarm_status()                           → get node_id from hostname
2. plan_action(...)                         → human approval
3. node_drain(node_id="<hex>")             → drain
4. [maintenance]
5. node_activate(node_id="<hex>")          → reactivate
```

---

## Skills tools (14)

| Tool | Purpose |
|------|---------|
| `skill_search(query)` | **Always call before skill_create** |
| `skill_create(skill_description, service, backend)` | Generate new skill |
| `skill_execute(name, kwargs)` | Run skill |
| `skill_list()` | All skills |
| `skill_health_summary()` | Health summary |
| `skill_compat_check(name)` | Check one skill |
| `skill_compat_check_all()` | All skills — run after any upgrade |
| `skill_disable(name)` | Disable broken |
| `skill_enable(name)` | Re-enable |
| `skill_regenerate(name)` | Regenerate for new version |
| `skill_update_compat(name, api_version)` | Update metadata |
| `skill_export_prompt(name)` | Export prompt (airgapped) |
| `skill_generation_config()` | Show backend config |
| `skill_promote(name)` | Promote to permanent |

---

## Knowledge / Environment tools (3)

| Tool | Purpose |
|------|---------|
| `discover_environment(hosts_json)` | Scan hosts — **requires hosts_json JSON string** |
| `knowledge_ingest_changelog(content, service)` | Ingest release notes to MuninnDB |
| `knowledge_export_request(service, version)` | Request docs for export backend |

---

## Full upgrade workflow (complete sequence)

```
0. service_resolve_image(image="<image>")      → find stable tags
1. knowledge_ingest_changelog(content=<notes>, service=<n>)  → seed MuninnDB
2. pre_upgrade_check(service=<n>)              → 6-step gate + auto checkpoint
3. plan_action(summary, steps, risk_level)     → human approval
4. service_upgrade(name=<n>, image=<full:tag>) → rolling update
5. post_upgrade_verify(service=<n>, operation_id=<id>)
6. skill_compat_check_all()                    → check all skills
7. service_catalog_update(service_id, detected_version, known_latest)
```
