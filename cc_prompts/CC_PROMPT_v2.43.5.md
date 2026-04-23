# CC PROMPT — v2.43.5 — fix(facts+agents): entity name mapping — swarm hostname↔connection label cross-reference

## Problem

Three separate namespaces exist for the same physical machine, with no link between them:

| Namespace | Example (manager-02) |
|---|---|
| connections DB label | `ds-docker-manager-02` (SSH target) |
| infra_inventory | label=`ds-docker-manager-02`, hostname=`manager-02` |
| Swarm facts | `prod.swarm.node.manager-02.*` |
| Proxmox facts | `prod.proxmox.vm.hp1-prod-manager-02.*` |
| vm_host facts | `prod.vm_host.ds-docker-manager-02.*` (empty — SSH failing) |

When the agent sees `manager-02` in Swarm output and needs to use
`docker node inspect manager-02`, it works. But if it substitutes the
connection label `ds-docker-manager-02` as the Docker node name, Docker
rejects it — Docker only knows the Swarm hostname.

Additionally, `prod.vm_host.*` facts are completely absent from known_facts,
indicating the vm_hosts collector SSH is failing for all hosts (timeout or
auth issue), producing an empty `vms: []` list which the extractor silently
skips.

This prompt adds:
1. A `connection_label` fact to swarm node facts so agents can look up the
   SSH target from the Swarm hostname
2. A prompt section explicitly teaching the name mapping distinction
3. Logging improvement so vm_hosts SSH failures are visible in operations logs

Version bump: 2.43.4 → 2.43.5.

---

## Change 1 — `api/collectors/swarm.py` — capture which connection label owns each node

The swarm collector connects through a manager connection. Nodes reported by
that manager all belong to the same cluster. After the node loop, we know
`node.hostname` (Swarm name, e.g. `manager-02`) but not the connection label.

The vm_hosts connections have the same hostnames stored in `infra_inventory`.
Add a lookup: for each Swarm node, find the matching vm_host connection label
via `infra_inventory.resolve_host(hostname)`.

Locate the node dict assembly (inside the `for node in nodes:` loop):

```python
                node_data.append({
                    "id": attrs.get("ID", "")[:12],
                    "hostname": spec.get("Name", desc.get("Hostname", "unknown")),
                    ...
                    "manager_addr": mgr.get("Addr", ""),   # v2.43.3
                    ...
                })
```

After the entire node loop (outside the `for node in nodes:` loop), add a
one-time batch resolution of hostnames to connection labels:

```python
            # v2.43.5: enrich nodes with vm_host connection_label
            # so facts can map Swarm hostname → SSH connection label
            try:
                from api.db.infra_inventory import resolve_host
                for node in node_data:
                    hn = node.get("hostname", "")
                    if not hn:
                        continue
                    entry = resolve_host(hn)
                    if entry:
                        node["connection_label"] = entry.get("label", "")
                        node["connection_ip"]    = (entry.get("ips") or [""])[0]
            except Exception as _nl:
                log.debug("[Swarm] node label resolution failed: %s", _nl)
```

---

## Change 2 — `api/facts/extractors.py` — write connection_label and connection_ip facts

In `extract_facts_from_swarm_snapshot()`, inside the `for node in snapshot.get("nodes") ...` loop, after the existing addr/engine_version block, add:

```python
        # v2.43.5: cross-reference Swarm hostname → vm_host connection label/IP
        if node.get("connection_label"):
            _add(facts, f"{fkey_base}.connection_label", "swarm_collector",
                 node["connection_label"])
        if node.get("connection_ip"):
            _add(facts, f"{fkey_base}.connection_ip", "swarm_collector",
                 node["connection_ip"])
```

After this ships, the agent will find:
```
prod.swarm.node.manager-02.connection_label = "ds-docker-manager-02"
prod.swarm.node.manager-02.connection_ip    = "192.168.199.22"
```

---

## Change 3 — `api/agents/router.py` — add ENTITY NAME MAPPING section to prompts

In the STATUS_PROMPT (observe agent), find the ENTITY HISTORY section or the
vm_exec guidance. Add a new section before vm_exec guidance:

```
═══ ENTITY NAME MAPPING ═══
Infrastructure entities have multiple names depending on context. Always use
the correct name for the context:

vm_exec(host=...)       — use the connection label (e.g. "ds-docker-manager-02")
                          OR the short Swarm hostname (e.g. "manager-02") — both work.
                          vm_exec resolves via suffix matching.

docker node inspect     — use the SWARM hostname (e.g. "manager-02"), NOT the
                          connection label. Swarm does not know connection labels.
                          Source: prod.swarm.node.{hostname}.* facts.

docker service inspect  — use the SERVICE NAME (e.g. "kafka_broker-1"), NOT the
                          container ID or image name.

Known mappings (from facts):
  Swarm hostname → connection label: prod.swarm.node.{n}.connection_label
  Swarm hostname → IP:               prod.swarm.node.{n}.connection_ip
  Proxmox VM name → status:          prod.proxmox.vm.{n}.status
```

Apply the same section to INVESTIGATE_PROMPT (research agent).

---

## Change 4 — `api/collectors/vm_hosts.py` — louder failure logging

The vm_hosts collector is producing `vms: []` (SSH failing for all hosts),
so `prod.vm_host.*` facts are completely absent. The failure is swallowed
silently. Make it visible.

Locate the `_collect_sync` return that handles a failed poll:

```python
        except Exception as e:
            return {"health": "error", "vms": [], "error": str(e)}
```

And the per-VM failure in the ThreadPoolExecutor:

```python
                except Exception as e:
                    c = futures[future]
                    vms.append({
                        "id": c.get("label", c.get("host")),
                        ...
                        "problem": str(e)[:120],
                    })
```

Add a `log.warning` call in the per-VM failure path so SSH failures appear
in the DEATHSTAR operation logs:

```python
                except Exception as e:
                    c = futures[future]
                    log.warning(
                        "[vm_hosts] SSH poll failed for %s (%s): %s",
                        c.get("label"), c.get("host"), str(e)[:200],
                    )
                    vms.append({...})
```

---

## Verification

After deploy + collector poll:

1. Check cross-reference facts exist:
```bash
curl -s 'http://192.168.199.10:8000/api/facts?prefix=prod.swarm.node.manager' | \
  python3 -c "import json,sys; [print(f['fact_key'], '=', f['fact_value']) for f in json.load(sys.stdin).get('facts',[]) if 'connection' in f['fact_key']]"
```

Expected:
```
prod.swarm.node.manager-01.connection_label = ds-docker-manager-01
prod.swarm.node.manager-01.connection_ip    = 192.168.199.21
prod.swarm.node.manager-02.connection_label = ds-docker-manager-02
prod.swarm.node.manager-02.connection_ip    = 192.168.199.22
prod.swarm.node.manager-03.connection_label = ds-docker-manager-03
prod.swarm.node.manager-03.connection_ip    = 192.168.199.23
```

2. Check vm_hosts SSH error logs appear in application logs:
```bash
docker logs $(docker ps -q --filter name=hp1_agent) 2>&1 | grep "vm_hosts.*SSH poll failed"
```

If SSH errors appear, investigate the credential profile for vm_host connections.

---

## Version bump

Update `VERSION`: `2.43.4` → `2.43.5`

---

## Commit

```
git add -A
git commit -m "fix(facts+agents): v2.43.5 swarm→connection_label cross-ref facts + entity name mapping prompt"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
