# CC PROMPT — v2.43.0 — fix(facts+allowlist): swarm service networks in facts + docker service ls allowed

## What this does

Two gaps exposed by a live trace (2026-04-23):

1. **Fact gap**: `extract_facts_from_swarm_snapshot()` collects `svc["networks"]`
   from the collector but never writes it to known_facts. Preflight and external
   AI cannot answer "which overlay network is each service on?" from facts.
   Fix: write `prod.swarm.service.{name}.networks` on every collector poll.

2. **Allowlist gap**: `docker service ls` is not in BASE_PATTERNS. Agent
   tried it twice, got blocked both times, gave up. It's a read-only command
   lower-risk than `docker service inspect` which is already allowed.
   Fix: add `docker service ls` pattern.

Version bump: 2.42.3 → 2.43.0.

---

## Change 1 — `api/facts/extractors.py`

In `extract_facts_from_swarm_snapshot()`, locate the block that ends with:

```python
        # v2.39.2: health field if collector provides it
        if svc.get("health"):
            _add(facts, f"{fkey_base}.health", "swarm_collector", svc["health"], md)
```

Add immediately after (still inside the `for svc in ...` loop):

```python
        # v2.43.0: overlay network names — collector already captures these,
        # just wasn't written to facts. Enables preflight/external-AI to answer
        # "which overlay network is this service on?" without a tool call.
        if svc.get("networks"):
            _add(facts, f"{fkey_base}.networks", "swarm_collector",
                 svc["networks"], md)
```

Also update the docstring to mention v2.43.0:

```python
    """Docker Swarm manager snapshot → fact list.

    v2.39.2: adds service convergence flag, health, engine version, cluster counts.
    v2.43.0: adds service network names (prod.swarm.service.{name}.networks).
    """
```

---

## Change 2 — `api/db/vm_exec_allowlist.py`

In `BASE_PATTERNS`, locate:

```python
    (r'^docker service ps\b',          'Swarm service task list'),
    (r'^docker service inspect\b',     'Swarm service details'),
```

Add `docker service ls` immediately before them:

```python
    (r'^docker service ls\b',          'Swarm service list (read-only)'),
    (r'^docker service ps\b',          'Swarm service task list'),
    (r'^docker service inspect\b',     'Swarm service details'),
```

---

## Verification

After deploy, trigger a swarm collector poll and check:

```bash
curl -s http://192.168.199.10:8000/api/facts?prefix=prod.swarm.service | \
  python3 -c "import json,sys; [print(r['fact_key'], r['fact_value']) for r in json.load(sys.stdin).get('facts',[]) if 'network' in r['fact_key']]"
```

Should now show `prod.swarm.service.kafka_broker-1.networks` etc.

Also verify allowlist accepts the command (observe agent, vm_exec):
`docker service ls --format "{{.Name}} {{.Replicas}}"` — should execute, not block.

---

## Version bump

Update `VERSION`: `2.42.3` → `2.43.0`

---

## Commit

```
git add -A
git commit -m "fix(facts+allowlist): v2.43.0 swarm service networks in facts + docker service ls allowed"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
