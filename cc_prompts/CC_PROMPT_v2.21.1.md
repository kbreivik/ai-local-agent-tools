# CC PROMPT — v2.21.1 — Container lifecycle events + collector snapshots to Elasticsearch

## What this does

Two remaining gaps:

1. **Container restart/lifecycle events not tracked** — The Swarm collector tracks
   image digest changes but not replica count transitions or container exit events.
   When broker-1 crashes and restarts 4 times in an hour that's invisible in entity_events.
   Add write_event calls for replica count transitions (scale-up, scale-down, crash-recover).

2. **Collector snapshots not indexed to Elasticsearch** — Infrastructure health data
   (Kafka lag, Swarm health, VM metrics) never reaches ES. ES only has application logs.
   You cannot build Kibana dashboards from infrastructure state, and the agent cannot
   correlate "log spike at 09:11" with "Kafka degraded at 09:12" in a single ES query.
   After each successful collector poll, POST a flattened snapshot to `deathstar-metrics-*`
   index in ES if ELASTIC_URL is configured.

Version bump: 2.21.0 → 2.21.1

---

## Change 1 — api/collectors/swarm.py

### 1a — Track replica count changes with entity_events

In `_collect_sync()`, inside the existing image digest change detection block, add replica
count event tracking.

Find the end of the image digest change detection `try/except` block:
```python
            except Exception as _de:
                log.debug("image digest tracking failed (non-fatal): %s", _de)
```

After that block, add:

```python
            # ── Replica count event tracking ─────────────────────────────────
            try:
                from api.db.entity_history import write_event, get_last_known_values
                for svc in svc_data:
                    name = svc.get("name", "")
                    if not name:
                        continue
                    entity_id = f"swarm:service:{name}"
                    running = svc.get("running_replicas", 0)
                    desired = svc.get("desired_replicas", 0)
                    last = get_last_known_values(entity_id, ["running_replicas"])
                    old_running_str = last.get("running_replicas")
                    old_running = int(old_running_str) if old_running_str is not None else None

                    if old_running is not None and old_running != running:
                        if running == 0 and desired > 0:
                            severity = "critical"
                            event_type = "service_all_replicas_down"
                            desc = f"{name}: all replicas down (was {old_running}/{desired})"
                        elif running < old_running:
                            severity = "warning"
                            event_type = "service_replica_lost"
                            desc = f"{name}: replicas dropped {old_running} → {running} (desired {desired})"
                        elif running > old_running:
                            severity = "info"
                            event_type = "service_replica_recovered"
                            desc = f"{name}: replicas restored {old_running} → {running} (desired {desired})"
                        else:
                            continue
                        write_event(
                            entity_id=entity_id, entity_type="swarm_service",
                            event_type=event_type, severity=severity,
                            description=desc, source_collector="swarm",
                            metadata={"old_running": old_running, "new_running": running,
                                      "desired": desired},
                        )

                    # Record current running count for next poll comparison
                    if old_running_str is None or old_running != running:
                        from api.db.entity_history import write_change
                        write_change(
                            entity_id=entity_id, entity_type="swarm_service",
                            field_name="running_replicas",
                            old_value=old_running_str,
                            new_value=str(running),
                            source_collector="swarm",
                            metadata={"desired": desired},
                        )
            except Exception as _re:
                log.debug("replica tracking failed (non-fatal): %s", _re)
```

---

## Change 2 — api/collectors/base.py

### 2a — Add ES snapshot indexing to _safe_poll()

After the `after_status_snapshot` and `evaluate_triggers` calls in `_safe_poll()`:

Find:
```python
            # Memory hooks — health transition + semantic triggers
            from api.memory.hooks import after_status_snapshot
            from api.memory.triggers import evaluate_triggers
            after_status_snapshot(self.component, state)
            await evaluate_triggers(self.component, state)
```

After that block, add:

```python
            # Index snapshot to Elasticsearch (non-blocking, best-effort)
            try:
                _index_snapshot_to_es(self.component, state)
            except Exception:
                pass
```

### 2b — Add the `_index_snapshot_to_es` helper function

Add this function at the module level in base.py, before the `class BaseCollector` definition:

```python
def _index_snapshot_to_es(component: str, state: dict) -> None:
    """POST a flattened collector snapshot to Elasticsearch deathstar-metrics-* index.

    Non-blocking (called in background thread via asyncio.to_thread by caller).
    Silently no-ops if ELASTIC_URL is not set.
    Only indexes components that have useful numeric metrics.
    """
    import os
    import json as _json
    from datetime import datetime, timezone

    elastic_url = os.environ.get("ELASTIC_URL", "").rstrip("/")
    if not elastic_url:
        return

    # Only index components with useful metrics — skip unconfigured
    health = state.get("health", "unknown")
    if health == "unconfigured":
        return

    # Build a flat document from the state
    now_iso = datetime.now(timezone.utc).isoformat()
    doc: dict = {
        "@timestamp": now_iso,
        "component": component,
        "health": health,
        "deathstar.source": "collector",
    }

    # Component-specific field extraction
    if component == "kafka_cluster":
        doc["kafka.brokers.alive"] = state.get("broker_count", 0)
        doc["kafka.brokers.expected"] = state.get("expected_brokers", 0)
        doc["kafka.partitions.under_replicated"] = state.get("under_replicated_partitions", 0)
        total_lag = sum(
            v.get("total_lag", 0)
            for v in (state.get("consumer_lag") or {}).values()
        )
        doc["kafka.consumer.lag.total"] = total_lag

    elif component == "swarm":
        doc["swarm.nodes.total"] = state.get("node_count", 0)
        doc["swarm.managers.active"] = state.get("active_managers", 0)
        doc["swarm.services.total"] = state.get("service_count", 0)
        doc["swarm.services.degraded"] = len(state.get("degraded_services") or [])
        doc["swarm.services.failed"] = len(state.get("failed_services") or [])

    elif component == "elasticsearch":
        doc["es.nodes"] = state.get("nodes", 0)
        doc["es.shards.active"] = (state.get("shards") or {}).get("active", 0)
        doc["es.shards.unassigned"] = (state.get("shards") or {}).get("unassigned", 0)

    elif component == "vm_hosts":
        # Aggregate across all VMs
        vms = state.get("vms") or []
        doc["vm_hosts.total"] = len(vms)
        doc["vm_hosts.ok"] = state.get("ok", 0)
        doc["vm_hosts.issues"] = state.get("issues", 0)

    elif component == "external_services":
        svcs = state.get("services") or []
        doc["external.total"] = len(svcs)
        doc["external.reachable"] = sum(1 for s in svcs if s.get("reachable"))
        doc["external.unreachable"] = sum(1 for s in svcs if not s.get("reachable"))

    else:
        # Skip components with no useful numeric fields
        return

    try:
        import httpx
        index = f"deathstar-metrics-{datetime.now(timezone.utc).strftime('%Y.%m')}"
        httpx.post(
            f"{elastic_url}/{index}/_doc",
            content=_json.dumps(doc),
            headers={"Content-Type": "application/json"},
            timeout=3.0,
        )
    except Exception:
        pass  # never let ES failure affect the collector loop
```

### 2c — Make the ES indexing non-blocking

The `_index_snapshot_to_es` call is sync (uses httpx sync). Wrap it in asyncio.to_thread
so it doesn't block the collector loop.

Replace:
```python
            # Index snapshot to Elasticsearch (non-blocking, best-effort)
            try:
                _index_snapshot_to_es(self.component, state)
            except Exception:
                pass
```

With:
```python
            # Index snapshot to Elasticsearch (non-blocking, best-effort)
            import asyncio as _asyncio
            _asyncio.create_task(
                _asyncio.to_thread(_index_snapshot_to_es, self.component, state)
            )
```

---

## Change 3 — api/collectors/external_services.py

Track external service latency in entity_events when it degrades or recovers.

In `_probe_connection()`, after the successful probe result is built, add:

```python
        # Write latency sample for trending
        try:
            from api.db.metric_samples import write_samples
            if latency_ms is not None:
                write_samples(f"external:{platform}", {
                    "latency_ms": float(latency_ms),
                    "reachable": 1.0 if reachable else 0.0,
                })
        except Exception:
            pass
```

---

## Do NOT touch

- Any frontend files
- `api/db/metric_samples.py` — no changes (created in v2.21.0)
- Any other router

---

## Version bump

Update `VERSION`: `2.21.0` → `2.21.1`

---

## Commit

```bash
git add -A
git commit -m "feat(data): v2.21.1 container lifecycle events + collector snapshots to Elasticsearch

- swarm collector: tracks running_replicas changes in entity_changes
- swarm collector: writes entity_events on replica drop (service_replica_lost),
  all-down (service_all_replicas_down), and recovery (service_replica_recovered)
- base.py: _index_snapshot_to_es() — POSTs flattened collector state to
  deathstar-metrics-YYYY.MM ES index after each successful poll (best-effort)
- Indexed: kafka broker count/lag/under-replicated, swarm node/service health,
  elasticsearch shard health, vm_hosts summary, external service reachability
- external_services collector: writes latency_ms + reachable samples per connection
- Together with v2.21.0: full time-series coverage from PostgreSQL + Elasticsearch"
git push origin main
```
