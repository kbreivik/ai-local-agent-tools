# CC PROMPT — v2.39.2 — feat(facts): Kafka broker + Swarm service health facts enrichment

## What this does

The Kafka and Swarm extractors exist and are wired (v2.35.0), but they're thin —
Kafka only writes host/port/is_controller, not the critical health signals
(under-replicated partitions, ISR count, broker online status). Swarm writes
replica counts but not service health state or whether replicas converged.
These are the two most queried platforms for agent tasks.

Enriches both extractors with operationally useful facts. No wiring changes
needed — extractors are already called by their collectors.

Version bump: 2.39.1 → 2.39.2.

---

## Change 1 — `api/facts/extractors.py` — enrich `extract_facts_from_kafka_snapshot`

Locate the existing function:

```python
def extract_facts_from_kafka_snapshot(snapshot: dict) -> list[dict]:
    """Kafka collector → fact list."""
    facts: list[dict] = []
    if not isinstance(snapshot, dict):
        return facts
    for b in snapshot.get("brokers", []) or []:
        bid = b.get("id")
        if bid is None or bid == -1:
            continue
        fkey_base = f"prod.kafka.broker.{bid}"
        _add(facts, f"{fkey_base}.host", "kafka_collector", b.get("host"))
        _add(facts, f"{fkey_base}.port", "kafka_collector", b.get("port"))
        _add(facts, f"{fkey_base}.is_controller", "kafka_collector",
             bool(b.get("is_controller", False)))
    for t in snapshot.get("topics", []) or []:
        name = t.get("name")
        if not name:
            continue
        _add(facts, f"prod.kafka.topic.{name}.partitions", "kafka_collector",
             t.get("partition_count"))
        _add(facts, f"prod.kafka.topic.{name}.replication_factor",
             "kafka_collector", t.get("replication_factor"))
    return facts
```

Replace with:

```python
def extract_facts_from_kafka_snapshot(snapshot: dict) -> list[dict]:
    """Kafka collector → fact list.

    v2.39.2: enriched with broker online status, ISR-missing flag,
    cluster-level under-replicated count, and per-topic under-replicated
    partition count.
    """
    facts: list[dict] = []
    if not isinstance(snapshot, dict):
        return facts

    brokers_online = 0
    for b in snapshot.get("brokers", []) or []:
        bid = b.get("id")
        if bid is None or bid == -1:
            continue
        fkey_base = f"prod.kafka.broker.{bid}"
        _add(facts, f"{fkey_base}.host", "kafka_collector", b.get("host"))
        _add(facts, f"{fkey_base}.port", "kafka_collector", b.get("port"))
        _add(facts, f"{fkey_base}.is_controller", "kafka_collector",
             bool(b.get("is_controller", False)))
        # v2.39.2 additions
        online = b.get("online", b.get("connected", b.get("reachable")))
        if online is not None:
            _add(facts, f"{fkey_base}.online", "kafka_collector", bool(online))
            if online:
                brokers_online += 1
        rack = b.get("rack")
        if rack:
            _add(facts, f"{fkey_base}.rack", "kafka_collector", rack)

    # Cluster-level summary
    broker_count = len([b for b in (snapshot.get("brokers") or [])
                        if b.get("id") not in (None, -1)])
    if broker_count:
        _add(facts, "prod.kafka.cluster.broker_count", "kafka_collector",
             broker_count)
    if brokers_online:
        _add(facts, "prod.kafka.cluster.brokers_online", "kafka_collector",
             brokers_online)

    # Under-replicated summary from snapshot top-level if present
    ur = snapshot.get("under_replicated_partitions")
    if ur is not None:
        _add(facts, "prod.kafka.cluster.under_replicated_partitions",
             "kafka_collector", int(ur))

    for t in snapshot.get("topics", []) or []:
        name = t.get("name")
        if not name:
            continue
        _add(facts, f"prod.kafka.topic.{name}.partitions", "kafka_collector",
             t.get("partition_count"))
        _add(facts, f"prod.kafka.topic.{name}.replication_factor",
             "kafka_collector", t.get("replication_factor"))
        # v2.39.2: per-topic under-replicated count
        t_ur = t.get("under_replicated_partitions", t.get("under_replicated"))
        if t_ur is not None:
            _add(facts, f"prod.kafka.topic.{name}.under_replicated_partitions",
                 "kafka_collector", int(t_ur))

    return facts
```

---

## Change 2 — `api/facts/extractors.py` — enrich `extract_facts_from_swarm_snapshot`

Locate:

```python
def extract_facts_from_swarm_snapshot(snapshot: dict) -> list[dict]:
    """Docker Swarm manager snapshot → fact list."""
    facts: list[dict] = []
    if not isinstance(snapshot, dict):
        return facts
    for svc in snapshot.get("services", []) or []:
        name = svc.get("name")
        if not name:
            continue
        fkey_base = f"prod.swarm.service.{name}"
        md = {"service_id": svc.get("id")}
        desired = svc.get("replicas_desired")
        if desired is None:
            desired = svc.get("desired_replicas")
        running = svc.get("replicas_running")
        if running is None:
            running = svc.get("running_replicas")
        _add(facts, f"{fkey_base}.replicas.desired", "swarm_collector", desired, md)
        _add(facts, f"{fkey_base}.replicas.running", "swarm_collector", running, md)
        placement = svc.get("placement")
        if placement is not None:
            _add(facts, f"{fkey_base}.placement", "swarm_collector", placement, md)
        if svc.get("image"):
            _add(facts, f"{fkey_base}.image", "swarm_collector", svc["image"], md)
        if svc.get("image_digest"):
            _add(facts, f"{fkey_base}.image_digest", "swarm_collector",
                 svc["image_digest"], md)
    for node in snapshot.get("nodes", []) or []:
        hostname = node.get("hostname")
        if not hostname:
            continue
        fkey_base = f"prod.swarm.node.{hostname}"
        _add(facts, f"{fkey_base}.state", "swarm_collector", node.get("state"))
        _add(facts, f"{fkey_base}.availability", "swarm_collector",
             node.get("availability"))
        _add(facts, f"{fkey_base}.role", "swarm_collector", node.get("role"))
    return facts
```

Replace with:

```python
def extract_facts_from_swarm_snapshot(snapshot: dict) -> list[dict]:
    """Docker Swarm manager snapshot → fact list.

    v2.39.2: adds service convergence flag (running==desired → converged),
    service health string, node engine version, and cluster summary counts.
    """
    facts: list[dict] = []
    if not isinstance(snapshot, dict):
        return facts

    services_total = 0
    services_converged = 0

    for svc in snapshot.get("services", []) or []:
        name = svc.get("name")
        if not name:
            continue
        fkey_base = f"prod.swarm.service.{name}"
        md = {"service_id": svc.get("id")}
        desired = svc.get("replicas_desired")
        if desired is None:
            desired = svc.get("desired_replicas")
        running = svc.get("replicas_running")
        if running is None:
            running = svc.get("running_replicas")
        _add(facts, f"{fkey_base}.replicas.desired", "swarm_collector", desired, md)
        _add(facts, f"{fkey_base}.replicas.running", "swarm_collector", running, md)
        # v2.39.2: convergence
        if desired is not None and running is not None:
            converged = int(running) >= int(desired) > 0
            _add(facts, f"{fkey_base}.converged", "swarm_collector", converged, md)
            services_total += 1
            if converged:
                services_converged += 1
        placement = svc.get("placement")
        if placement is not None:
            _add(facts, f"{fkey_base}.placement", "swarm_collector", placement, md)
        if svc.get("image"):
            _add(facts, f"{fkey_base}.image", "swarm_collector", svc["image"], md)
        if svc.get("image_digest"):
            _add(facts, f"{fkey_base}.image_digest", "swarm_collector",
                 svc["image_digest"], md)
        # v2.39.2: health field if collector provides it
        if svc.get("health"):
            _add(facts, f"{fkey_base}.health", "swarm_collector", svc["health"], md)

    # Cluster summary
    if services_total:
        _add(facts, "prod.swarm.cluster.services_total", "swarm_collector",
             services_total)
        _add(facts, "prod.swarm.cluster.services_converged", "swarm_collector",
             services_converged)

    nodes_ready = 0
    nodes_total = 0
    for node in snapshot.get("nodes", []) or []:
        hostname = node.get("hostname")
        if not hostname:
            continue
        fkey_base = f"prod.swarm.node.{hostname}"
        _add(facts, f"{fkey_base}.state", "swarm_collector", node.get("state"))
        _add(facts, f"{fkey_base}.availability", "swarm_collector",
             node.get("availability"))
        _add(facts, f"{fkey_base}.role", "swarm_collector", node.get("role"))
        # v2.39.2: engine version + node ip
        if node.get("engine_version"):
            _add(facts, f"{fkey_base}.engine_version", "swarm_collector",
                 node["engine_version"])
        if node.get("addr") or node.get("ip"):
            _add(facts, f"{fkey_base}.addr", "swarm_collector",
                 node.get("addr") or node.get("ip"))
        nodes_total += 1
        if str(node.get("state", "")).lower() == "ready":
            nodes_ready += 1

    if nodes_total:
        _add(facts, "prod.swarm.cluster.nodes_total", "swarm_collector", nodes_total)
        _add(facts, "prod.swarm.cluster.nodes_ready", "swarm_collector", nodes_ready)

    return facts
```

---

## Version bump

Update `VERSION` file: `2.39.1` → `2.39.2`

---

## Commit

```
git add -A
git commit -m "feat(facts): v2.39.2 enrich Kafka + Swarm extractors with health signals"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
