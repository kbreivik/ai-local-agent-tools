# CC PROMPT — v2.43.4 — fix(facts): write prod.swarm.cluster.overlay_networks fact from collector

## What this does

The swarm collector (v2.43.2) already builds `net_id_to_name` — a full map of
all overlay networks from `docker.networks.list(driver=overlay)`. This is used
only to resolve per-service network names. The map itself is then discarded.

Live fact-check (2026-04-23) shows 4 overlay networks exist:
  - ingress / kafka_default / kafka_kafka-internal / logstash_default

None of these appear as a standalone cluster-level fact. External AI answering
"list all overlay networks" can only get partial info (2 out of 4, from service
attachments). The other 2 (ingress, kafka_default) are invisible to facts.

Fix: write `prod.swarm.cluster.overlay_networks` as a list of all overlay
network names, and `prod.swarm.cluster.overlay_network_count` as an int.
One-line addition to the extractor — the data is already in the snapshot.

Version bump: 2.43.3 → 2.43.4.

---

## Change 1 — `api/collectors/swarm.py`

The `net_id_to_name` map is built in v2.43.2 and used to patch `svc_data`.
After patching svc_data, also add the network list to the snapshot dict.

Locate the section added in v2.43.2 that ends with:

```python
            # Patch svc_data entries with resolved network names
            for svc in svc_data:
                raw_nets = svc.get("networks") or []
                svc["network_names"] = [
                    net_id_to_name.get(nid, nid)
                    for nid in raw_nets
                ]

            client.close()
```

Add one line before `client.close()` to stash the full network list:

```python
            # v2.43.4: stash full overlay network list for cluster-level fact
            overlay_networks_list = sorted(set(net_id_to_name.values()))

            client.close()
```

Then locate where the final snapshot dict is assembled and returned. It will
look something like:

```python
            return {
                "health": health,
                "services": svc_data,
                "nodes": node_data,
                ...
            }
```

Add `"overlay_networks": overlay_networks_list` to the dict:

```python
            return {
                "health": health,
                "services": svc_data,
                "nodes": node_data,
                "overlay_networks": overlay_networks_list,   # v2.43.4
                ...
            }
```

---

## Change 2 — `api/facts/extractors.py`

In `extract_facts_from_swarm_snapshot()`, locate the cluster summary block:

```python
    if nodes_total:
        _add(facts, "prod.swarm.cluster.nodes_total", "swarm_collector", nodes_total)
        _add(facts, "prod.swarm.cluster.nodes_ready", "swarm_collector", nodes_ready)

    return facts
```

Add overlay network facts before `return facts`:

```python
    # v2.43.4: cluster-level overlay network list
    overlay_nets = snapshot.get("overlay_networks") or []
    if overlay_nets:
        _add(facts, "prod.swarm.cluster.overlay_networks", "swarm_collector",
             overlay_nets)
        _add(facts, "prod.swarm.cluster.overlay_network_count", "swarm_collector",
             len(overlay_nets))

    return facts
```

Also update the docstring:

```
    v2.43.4: adds cluster-level overlay_networks list and overlay_network_count.
```

---

## Verification

After deploy + collector poll:

```bash
curl -s 'http://192.168.199.10:8000/api/facts?prefix=prod.swarm.cluster' | \
  python3 -c "import json,sys; [print(f['fact_key'], '=', f['fact_value']) for f in json.load(sys.stdin).get('facts',[])]"
```

Expected new entries:
```
prod.swarm.cluster.overlay_networks    = ["ingress", "kafka_default", "kafka_kafka-internal", "logstash_default"]
prod.swarm.cluster.overlay_network_count = 4
```

Run the overlay task with ⚡ EXT AI — external AI should now answer the full
network list from facts alone, including ingress and kafka_default.

---

## Version bump

Update `VERSION`: `2.43.3` → `2.43.4`

---

## Commit

```
git add -A
git commit -m "fix(facts): v2.43.4 write prod.swarm.cluster.overlay_networks from collector net_id_to_name map"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
