# CC PROMPT — v2.43.2 — fix(facts): resolve swarm network IDs to human-readable names

## What this does

The swarm collector writes `svc["networks"]` as a list of network IDs
(e.g. `["95r8omc9c2givzirxfb2xwt5i"]`). External AI can see these IDs in
facts but cannot map them to names like `kafka_kafka-internal`. The Docker
client is already open during collection — add a network ID→name lookup
before `client.close()`, then pass resolved names alongside IDs in the
snapshot so the extractor writes both.

Two-part change:
1. `api/collectors/swarm.py` — build a `net_id_to_name` map before closing
   the client, replace bare IDs with names in `svc_data`
2. `api/facts/extractors.py` — write `prod.swarm.service.{name}.network_names`
   (human-readable) in addition to the existing `.networks` (IDs, v2.43.0)

Version bump: 2.43.1 → 2.43.2.

---

## Change 1 — `api/collectors/swarm.py`

Locate the line that ends the service loop:

```python
                    "networks": svc_networks,
                    "entity_id": f"swarm:service:{name}",
                })\n\n            client.close()
```

Insert a network resolution block **between the end of the service loop and
`client.close()`**:

```python
            # v2.43.2 — Resolve overlay network IDs to human-readable names.
            # Build a map once using the already-open Docker client.
            net_id_to_name: dict[str, str] = {}
            try:
                for net in client.networks.list(filters={"driver": "overlay"}):
                    nid  = net.attrs.get("Id", "")
                    name = net.attrs.get("Name", "")
                    if nid and name:
                        net_id_to_name[nid]       = name   # full ID
                        net_id_to_name[nid[:12]]  = name   # short ID used in svc_networks
            except Exception as _ne:
                log.debug("[Swarm] network name resolution failed: %s", _ne)

            # Patch svc_data entries with resolved network names
            for svc in svc_data:
                raw_nets = svc.get("networks") or []
                svc["network_names"] = [
                    net_id_to_name.get(nid, nid)   # fall back to raw ID if unresolved
                    for nid in raw_nets
                ]

            client.close()
```

---

## Change 2 — `api/facts/extractors.py`

In `extract_facts_from_swarm_snapshot()`, locate the block added in v2.43.0:

```python
        # v2.43.0: overlay network names — collector already captures these,
        # just wasn't written to facts.
        if svc.get("networks"):
            _add(facts, f"{fkey_base}.networks", "swarm_collector",
                 svc["networks"], md)
```

Add immediately after it:

```python
        # v2.43.2: human-readable network names (resolved from IDs in collector)
        if svc.get("network_names"):
            _add(facts, f"{fkey_base}.network_names", "swarm_collector",
                 svc["network_names"], md)
```

Also update the docstring:

```
    v2.43.2: adds service network_names (human-readable, resolved from overlay IDs).
```

---

## Verification

After deploy, trigger a swarm collector poll, then:

```bash
curl -s 'http://192.168.199.10:8000/api/facts?search=network_names' | \
  python3 -c "import json,sys; [print(r['fact_key'], r['fact_value']) for r in json.load(sys.stdin).get('facts',[])]"
```

Should show entries like:
```
prod.swarm.service.kafka_broker-1.network_names ["kafka_kafka-internal"]
prod.swarm.service.logstash_logstash.network_names ["logstash_default"]
```

Run the overlay network task with ⚡ EXT AI — external AI should now report
`kafka_kafka-internal` instead of `95r8omc9c2givzirxfb2xwt5i`.

---

## Version bump

Update `VERSION`: `2.43.1` → `2.43.2`

---

## Commit

```
git add -A
git commit -m "fix(facts): v2.43.2 resolve swarm overlay network IDs to names in collector + extractor"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
