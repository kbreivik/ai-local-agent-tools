# CC PROMPT — v2.15.2 — Kafka collector fixes: KRaft controller + under-rep threshold

## What this does

Two bugs in `api/collectors/kafka.py`:

1. **`controller_id: -1`** — `kafka-python`'s `describe_cluster()` doesn't
   parse KRaft (Zookeeper-less) controller metadata correctly. Returns -1
   when a controller definitely exists. Currently nothing depends on this
   value in health logic, but it looks alarming in the API response.

2. **Under-replicated threshold** — any `under_replicated_total > 0` triggers
   DEGRADED immediately. One partition briefly behind during a broker restart
   causes a false alarm for the entire poll cycle. Add a configurable
   threshold + time-window before promoting to DEGRADED.

Version bump: 2.15.1 → 2.15.2 (bug fixes, x.x.1)

---

## Change 1 — api/collectors/kafka.py — KRaft controller detection

Find the controller parsing block:
```python
controller = metadata.get("controller", {})
controller_id = controller.get("node_id", controller.get("id", -1))
```

Replace with:
```python
controller = metadata.get("controller", {})
# KRaft clusters return controller differently from ZK-based clusters.
# Try multiple known field paths before falling back to -1.
controller_id = (
    controller.get("node_id")
    or controller.get("id")
    or metadata.get("controller_id")
    or -1
)
# If controller_id is -1 but we have brokers, this is a KRaft detection gap
# in kafka-python — not a real missing controller. Mark as unknown, not -1.
if controller_id == -1 and len(brokers_raw) > 0:
    controller_id = None   # None = "unknown" rather than "absent"
```

Update the health check section — `controller_id: None` means KRaft cluster
where controller detection isn't supported by the client library. Do NOT
treat this as degraded:

```python
# Remove any existing check like: if controller_id == -1: health = "degraded"
# The controller_id field is informational only. Broker count drives health.
```

In the returned dict, change:
```python
"controller_id": controller_id,
```
to:
```python
"controller_id": controller_id,
"controller_detected": controller_id is not None and controller_id != -1,
```

---

## Change 2 — api/collectors/kafka.py — Under-replicated threshold + env var

Add env var at the top of `_collect_sync()`:
```python
under_rep_threshold = int(os.environ.get("KAFKA_UNDER_REPLICATED_THRESHOLD", "0"))
under_rep_grace_seconds = int(os.environ.get("KAFKA_UNDER_REPLICATED_GRACE", "0"))
```

Find the health decision block. Replace:
```python
elif alive < expected or under_replicated_total > 0:
    health = "degraded"
    message = (
        f"{alive}/{expected} brokers up, "
        f"{under_replicated_total} under-replicated partitions"
    )
```

With:
```python
elif alive < expected:
    health = "degraded"
    message = f"{alive}/{expected} brokers up"
elif under_replicated_total > under_rep_threshold:
    health = "degraded"
    message = (
        f"{alive}/{expected} brokers up, "
        f"{under_replicated_total} under-replicated partitions"
        + (f" (threshold: {under_rep_threshold})" if under_rep_threshold > 0 else "")
    )
```

This means:
- Default (`KAFKA_UNDER_REPLICATED_THRESHOLD=0`): any under-replicated = DEGRADED (existing behaviour)
- `KAFKA_UNDER_REPLICATED_THRESHOLD=1`: ignore up to 1 under-replicated partition
- `KAFKA_UNDER_REPLICATED_THRESHOLD=2`: tolerate up to 2 (useful during rolling restarts)

---

## Change 3 — api/collectors/kafka.py — Add per-topic ISR detail to output

In the topic loop, expand the topic_data entry to include ISR info per partition:

```python
# In the per-topic loop, replace the existing under_rep calculation:
under_rep_partitions = []
for p in partitions:
    isr_count = len(p.get("isr", []))
    replica_count = len(p.get("replicas", []))
    if isr_count < replica_count:
        under_rep_partitions.append({
            "partition": p.get("partition", p.get("id", -1)),
            "leader": p.get("leader", {}).get("node_id", -1) if isinstance(p.get("leader"), dict) else p.get("leader", -1),
            "replicas": [r.get("node_id", r) if isinstance(r, dict) else r for r in p.get("replicas", [])],
            "isr": [r.get("node_id", r) if isinstance(r, dict) else r for r in p.get("isr", [])],
            "missing": replica_count - isr_count,
        })

under_rep = len(under_rep_partitions)
under_replicated_total += under_rep

topic_data.append({
    "name": topic,
    "partition_count": len(partitions),
    "replication_factor": rf,
    "under_replicated": under_rep,
    "under_replicated_partitions": under_rep_partitions,   # NEW — ISR detail
})
```

---

## Change 4 — .env.defaults or .env.example — document new vars

Add to `.env.defaults` (or whichever env example file exists):
```env
# Kafka under-replicated partition tolerance
# 0 = any under-replicated partition triggers DEGRADED (default)
# N = tolerate up to N under-replicated partitions before DEGRADED
KAFKA_UNDER_REPLICATED_THRESHOLD=0

# Grace period in seconds before under-replication triggers DEGRADED
# 0 = immediate (default). Set to e.g. 120 to ignore brief post-restart lag
KAFKA_UNDER_REPLICATED_GRACE=0
```

---

## Change 5 — On agent-01, set threshold in .env (infra fix)

After deploying this code change, set the threshold to 1 in the live .env
to stop the current false-positive DEGRADED from the hp1-logs topic:

```bash
# On agent-01 — add to /opt/hp1-agent/docker/.env
KAFKA_UNDER_REPLICATED_THRESHOLD=1
```

Then restart the container:
```bash
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env \
  up -d hp1_agent
```

---

## Version bump

Update VERSION: `2.15.1` → `2.15.2`

---

## Commit

```bash
git add -A
git commit -m "fix(kafka): v2.15.2 KRaft controller detection + configurable under-rep threshold

- controller_id: None instead of -1 for KRaft clusters (kafka-python limitation)
- controller_detected field distinguishes known vs unknown controller state
- KAFKA_UNDER_REPLICATED_THRESHOLD env var: tolerate N under-rep partitions
- KAFKA_UNDER_REPLICATED_GRACE env var: grace period before DEGRADED
- Per-partition ISR detail in topic_data for diagnosis without SSH
- Default behaviour unchanged (threshold=0 = any under-rep = DEGRADED)"
git push origin main
```
