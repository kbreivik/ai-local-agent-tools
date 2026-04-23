# CC PROMPT — v2.43.3 — fix(facts): swarm node manager_addr fact + addr_anomaly keyed to ManagerStatus.Addr

## What this does

Fact-check (2026-04-23) found that `prod.swarm.node.manager-02.addr = 0.0.0.0`
is `Status.Addr` — the node's data-plane address stored at join time. This is
a cosmetic artifact. The actual Raft address is `ManagerStatus.Addr`, which is
correctly `192.168.199.22:2377`. Reachability=reachable. NOT a split-brain risk.

The swarm collector currently captures only `st.get("Addr")` (Status.Addr).
`ManagerStatus.Addr` (`mgr.get("Addr")`) is not collected at all. The correct
anomaly to flag is `ManagerStatus.Addr = 0.0.0.0` — that would indicate actual
Raft participation failure.

Three-part change:
1. Collector: also capture `manager_addr` from `mgr.get("Addr")`
2. Extractor: write `prod.swarm.node.{hostname}.manager_addr` + flag
   `addr_anomaly = True` only when manager_addr is 0.0.0.0/empty
3. Preflight: keyword resolver for split-brain/Raft terms (unchanged intent,
   now correctly keyed to manager_addr fact)

Version bump: 2.43.2 → 2.43.3.

---

## Change 1 — `api/collectors/swarm.py`

Locate the node dict assembly block:

```python
                node_data.append({
                    "id": attrs.get("ID", "")[:12],
                    "hostname": spec.get("Name", desc.get("Hostname", "unknown")),
                    "role": role,
                    "state": state,
                    "availability": avail,
                    "leader": mgr.get("Leader", False),
                    "addr": st.get("Addr", ""),
                    "engine_version": engine.get("EngineVersion", ""),
                    "os": f"{platform.get('OS','')}/{platform.get('Architecture','')}",
                })
```

Add `manager_addr` to capture ManagerStatus.Addr:

```python
                node_data.append({
                    "id": attrs.get("ID", "")[:12],
                    "hostname": spec.get("Name", desc.get("Hostname", "unknown")),
                    "role": role,
                    "state": state,
                    "availability": avail,
                    "leader": mgr.get("Leader", False),
                    "addr": st.get("Addr", ""),
                    "manager_addr": mgr.get("Addr", ""),   # v2.43.3: Raft address
                    "engine_version": engine.get("EngineVersion", ""),
                    "os": f"{platform.get('OS','')}/{platform.get('Architecture','')}",
                })
```

---

## Change 2 — `api/facts/extractors.py`

In `extract_facts_from_swarm_snapshot()`, locate the addr block added in v2.43.3's
predecessor (if landed) or the v2.39.2 addr block:

```python
        if node.get("addr") or node.get("ip"):
            _add(facts, f"{fkey_base}.addr", "swarm_collector",
                 node.get("addr") or node.get("ip"))
```

Replace with:

```python
        _status_addr = node.get("addr") or node.get("ip") or ""
        if _status_addr:
            _add(facts, f"{fkey_base}.addr", "swarm_collector", _status_addr)

        # v2.43.3: Raft address (ManagerStatus.Addr) — distinct from Status.Addr.
        # Status.Addr = data-plane address stored at join time (can be 0.0.0.0, cosmetic).
        # ManagerStatus.Addr = Raft consensus address (0.0.0.0 here = actual Raft risk).
        _mgr_addr = node.get("manager_addr", "")
        _is_manager = str(node.get("role", "")).lower() == "manager"
        if _is_manager and _mgr_addr:
            _add(facts, f"{fkey_base}.manager_addr", "swarm_collector", _mgr_addr)
            _mgr_anomalous = _mgr_addr.startswith("0.0.0.0") or _mgr_addr == ""
            _add(facts, f"{fkey_base}.addr_anomaly", "swarm_collector",
                 _mgr_anomalous,
                 {"checked": "ManagerStatus.Addr", "value": _mgr_addr})
```

Also update the docstring:

```
    v2.43.3: adds node manager_addr (ManagerStatus.Addr / Raft address) and
             addr_anomaly flag (True only if ManagerStatus.Addr is 0.0.0.0).
```

---

## Change 3 — `api/agents/preflight.py` — keyword resolver

Same resolver as originally planned, but the DB query now looks for
`addr_anomaly = true` which will only fire if ManagerStatus.Addr is bad:

Locate `load_keyword_corpus()` and add:

```python
"split-brain": _lookup_addr_anomaly_nodes,
"split_brain": _lookup_addr_anomaly_nodes,
"raft": _lookup_addr_anomaly_nodes,
"advertise": _lookup_addr_anomaly_nodes,
```

Add the resolver function before `load_keyword_corpus()`:

```python
def _lookup_addr_anomaly_nodes() -> list[dict]:
    """Return manager nodes with addr_anomaly=True (ManagerStatus.Addr is 0.0.0.0)."""
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

## Expected outcome after deploy

After next swarm collector poll:
- `prod.swarm.node.manager-02.manager_addr = "192.168.199.22:2377"` (correct)
- `prod.swarm.node.manager-02.addr_anomaly = False` (ManagerStatus.Addr is fine)
- `prod.swarm.node.manager-01.manager_addr = "192.168.199.21:2377"`
- `prod.swarm.node.manager-01.addr_anomaly = False`

The `addr=0.0.0.0` fact for manager-02 (Status.Addr) will remain — it is accurate,
just cosmetically odd. No fix needed on the infrastructure side.

---

## Note on the 2375 exposure

All three managers run `-H tcp://0.0.0.0:2375` (no TLS, no auth). This is how
DEATHSTAR's swarm collector connects. Acceptable on an isolated LAN, but worth
documenting: anyone on the 192.168.199.x network can reach the Docker API on
each manager. Consider restricting to the DEATHSTAR host IP if the network is
not fully trusted.

---

## Version bump

Update `VERSION`: `2.43.2` → `2.43.3`

---

## Commit

```
git add -A
git commit -m "fix(facts): v2.43.3 swarm node manager_addr fact + addr_anomaly keyed to ManagerStatus.Addr"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
