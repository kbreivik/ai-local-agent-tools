# CC PROMPT — v2.43.3 — fix(facts): swarm node addr_anomaly flag + manager-02 0.0.0.0 detection

## What this does

`prod.swarm.node.manager-02.addr = "0.0.0.0"` has been confirmed in facts
since 2026-04-22 (verify_count=1758, change_detected=true). This means Docker
is reporting manager-02's advertise-addr as unspecified. In a 3-manager Raft
cluster this is a split-brain risk if a leader election occurs — the advertised
address is used for inter-manager RPC.

The fact exists but nothing flags it as anomalous. Preflight sees `addr=0.0.0.0`
and injects it as-is — the agent has to infer that this is a problem. Fix: add
an explicit `addr_anomaly` boolean fact that preflight and external AI can use
directly, and write it whenever addr is `0.0.0.0` or empty for a manager node.

Two-part change:
1. `api/facts/extractors.py` — write `prod.swarm.node.{hostname}.addr_anomaly`
   when addr is suspicious
2. `api/agents/preflight.py` — add `0.0.0.0` and empty addr as a Tier 2
   keyword-DB match pattern so preflight proactively resolves manager nodes
   when tasks mention "split-brain", "advertise", "manager address", etc.

Version bump: 2.43.2 → 2.43.3.

---

## Change 1 — `api/facts/extractors.py`

In `extract_facts_from_swarm_snapshot()`, locate the node addr block:

```python
        if node.get(\"addr\") or node.get(\"ip\"):
            _add(facts, f\"{fkey_base}.addr\", \"swarm_collector\",
                 node.get(\"addr\") or node.get(\"ip\"))
```

Replace with:

```python
        _addr = node.get("addr") or node.get("ip") or ""
        if _addr:
            _add(facts, f"{fkey_base}.addr", "swarm_collector", _addr)
            # v2.43.3: flag anomalous advertise-addr for manager nodes.
            # 0.0.0.0 means Docker is listening on all interfaces but has no
            # specific advertised address — inter-manager Raft RPC may use
            # the wrong interface. Flag so preflight surfaces it explicitly.
            _is_manager = str(node.get("role", "")).lower() == "manager"
            _is_anomalous = _addr in ("0.0.0.0", "0.0.0.0:2377", "") or \
                            _addr.startswith("0.0.0.0:")
            if _is_manager and _is_anomalous:
                _add(facts, f"{fkey_base}.addr_anomaly", "swarm_collector",
                     True,
                     {"addr": _addr, "reason": "manager advertising 0.0.0.0 — split-brain risk"})
            elif _is_manager:
                # Explicitly record False so preflight knows it was checked
                _add(facts, f"{fkey_base}.addr_anomaly", "swarm_collector", False)
```

Also update the docstring:

```
    v2.43.3: adds node addr_anomaly flag for manager nodes advertising 0.0.0.0.
```

---

## Change 2 — `api/agents/preflight.py` — register addr_anomaly in keyword corpus

Locate the `load_keyword_corpus()` function or the keywords dict it returns.
The corpus maps trigger words to entity resolvers.

Add an entry so that tasks mentioning advertise-addr, split-brain, or Raft
issues pull in the anomalous manager node:

```python
# v2.43.3: addr anomaly — pull manager nodes when split-brain terms appear
"advertise": _lookup_addr_anomaly_nodes,
"split-brain": _lookup_addr_anomaly_nodes,
"split_brain": _lookup_addr_anomaly_nodes,
"raft": _lookup_addr_anomaly_nodes,
"0.0.0.0": _lookup_addr_anomaly_nodes,
```

Add the resolver function before `load_keyword_corpus()`:

```python
def _lookup_addr_anomaly_nodes() -> list[dict]:
    """Return manager nodes with addr_anomaly=True from known_facts."""
    try:
        from api.db.known_facts import search_facts_by_key_pattern
        rows = search_facts_by_key_pattern("prod.swarm.node.%.addr_anomaly",
                                           min_confidence=0.5)
        results = []
        for row in rows:
            if row.get("fact_value") is True or row.get("fact_value") == "true":
                # Extract hostname from fact_key: prod.swarm.node.{hostname}.addr_anomaly
                parts = row["fact_key"].split(".")
                if len(parts) >= 5:
                    hostname = parts[3]
                    results.append({
                        "entity_id": f"swarm:node:{hostname}",
                        "label": hostname,
                        "source": "keyword_db",
                        "reason": "addr_anomaly",
                    })
        return results
    except Exception as _e:
        log.debug("_lookup_addr_anomaly_nodes failed: %s", _e)
        return []
```

If `search_facts_by_key_pattern` does not exist in `api/db/known_facts`, use
a direct query instead:

```python
def _lookup_addr_anomaly_nodes() -> list[dict]:
    try:
        if not _is_pg():
            return []
        conn = _pg_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT fact_key FROM known_facts_current "
            "WHERE fact_key LIKE 'prod.swarm.node.%.addr_anomaly' "
            "AND fact_value::text = 'true' "
            "LIMIT 5"
        )
        rows = _rows_to_dicts(cur)
        cur.close(); conn.close()
        results = []
        for row in rows:
            parts = row.get("fact_key", "").split(".")
            if len(parts) >= 5:
                hostname = parts[3]
                results.append({
                    "entity_id": f"swarm:node:{hostname}",
                    "label": hostname,
                    "source": "keyword_db",
                    "reason": "addr_anomaly",
                })
        return results
    except Exception as _e:
        log.debug("_lookup_addr_anomaly_nodes failed: %s", _e)
        return []
```

---

## Verification

After deploy + collector poll, verify the new fact exists:

```bash
curl -s 'http://192.168.199.10:8000/api/facts?search=addr_anomaly' | \
  python3 -c "import json,sys; [print(r['fact_key'], r['fact_value'], r.get('metadata',{})) for r in json.load(sys.stdin).get('facts',[])]"
```

Expected:
```
prod.swarm.node.manager-02.addr_anomaly True {"addr": "0.0.0.0", "reason": "manager advertising 0.0.0.0 — split-brain risk"}
prod.swarm.node.manager-01.addr_anomaly False
prod.swarm.node.manager-03.addr_anomaly False
```

Run a task: "Is there any split-brain risk in the Swarm cluster?" — preflight
should now resolve manager-02 and inject its addr_anomaly fact directly.

---

## Note on remediation

The fix for manager-02 itself is outside the DEATHSTAR codebase — set
`--advertise-addr 192.168.199.22` in `/etc/docker/daemon.json` on ds-docker-manager-02
and restart Docker. The node is currently healthy and operational; this is a
preventive fix for election robustness. Do this during a maintenance window.

---

## Version bump

Update `VERSION`: `2.43.2` → `2.43.3`

---

## Commit

```
git add -A
git commit -m "fix(facts): v2.43.3 swarm node addr_anomaly flag + preflight keyword resolver"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
