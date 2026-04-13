# CC PROMPT — v2.19.0 — service_placement tool: swarm service → node → vm_host

## What this does

The agent can identify a missing Kafka broker but can't connect the dots:
  "kafka_broker-1 is not in the cluster → which swarm node is that service
  running on → what is the vm_host connection label for that node → let me SSH there."

This adds `service_placement(service_name)` to `mcp_server/tools/vm.py` — a read-only
tool that SSHes to a Swarm manager, runs `docker service ps` to find which node each
task is on, then cross-references with vm_host connections to return the label and IP
for direct SSH access. This bridges the gap between service-level visibility and
node-level diagnosis.

Version bump: 2.18.1 → 2.19.0

---

## Change 1 — mcp_server/tools/vm.py

Add this new function at the end of the file, before the final blank line:

```python
def service_placement(service_name: str) -> dict:
    """Get task placement for a Swarm service: which node each task is on,
    its current state, and the matching vm_host connection for SSH access.

    Use when a service shows running replicas in Swarm but is behaving incorrectly
    (e.g. Kafka broker shows 1/1 replicas but is not visible in the cluster).
    This bridges: service name → node hostname → vm_host label → SSH-able connection.

    Read-only — never requires plan_action.

    Args:
        service_name: Exact Swarm service name (e.g. "kafka_broker-1", "kafka_broker-2").
                      Also accepts partial name (e.g. "kafka" returns all kafka services).
    """
    from api.connections import get_all_connections_for_platform
    from api.collectors.vm_hosts import _resolve_credentials, _ssh_run

    all_conns = get_all_connections_for_platform("vm_host")
    manager_conn = next(
        (c for c in all_conns if 'manager' in c.get("label", "").lower()),
        None
    )
    if not manager_conn:
        return {"status": "error",
                "message": "No manager vm_host connection found.",
                "data": None, "timestamp": _ts()}

    host = manager_conn.get("host", "")
    port = manager_conn.get("port") or 22
    username, password, private_key = _resolve_credentials(manager_conn, all_conns)

    try:
        # Find all matching services
        svc_list_out = _ssh_run(
            host, port, username, password, private_key,
            f"docker service ls --filter name={service_name} --format '{{{{.Name}}}}'",
        )
        services = [s.strip() for s in svc_list_out.strip().splitlines() if s.strip()]

        if not services:
            return {
                "status": "error",
                "message": f"No Swarm service matching '{service_name}' found.",
                "data": None, "timestamp": _ts(),
            }

        placements = []
        for svc in services:
            ps_out = _ssh_run(
                host, port, username, password, private_key,
                f"docker service ps {svc} --no-trunc "
                f"--format '{{{{.Name}}}}|{{{{.Node}}}}|{{{{.CurrentState}}}}|{{{{.DesiredState}}}}|{{{{.Error}}}}'",
            )
            for line in ps_out.strip().splitlines():
                if not line or "|" not in line:
                    continue
                parts = line.split("|")
                task_name    = parts[0].strip() if len(parts) > 0 else ""
                node_name    = parts[1].strip() if len(parts) > 1 else ""
                current_state = parts[2].strip() if len(parts) > 2 else ""
                desired_state = parts[3].strip() if len(parts) > 3 else ""
                error        = parts[4].strip() if len(parts) > 4 else ""

                # Cross-reference node hostname against vm_host connections
                vm_conn = _resolve_connection(node_name, all_conns)
                placements.append({
                    "service":       svc,
                    "task":          task_name,
                    "node":          node_name,
                    "current_state": current_state,
                    "desired_state": desired_state,
                    "error":         error,
                    "vm_host_label": vm_conn.get("label") if vm_conn else None,
                    "vm_host_ip":    vm_conn.get("host") if vm_conn else None,
                    "ssh_ready":     vm_conn is not None,
                })

        # Summary: healthy vs unhealthy tasks
        running = [p for p in placements if "running" in p["current_state"].lower()]
        failed  = [p for p in placements if p["current_state"] and "running" not in p["current_state"].lower()]
        health  = "healthy" if not failed and running else "degraded" if running else "critical"

        return {
            "status": "ok",
            "health": health,
            "message": (
                f"{len(services)} service(s), {len(running)} task(s) running, "
                f"{len(failed)} failed/other"
                + (f" — issues: {'; '.join(p['node'] + ' ' + p['current_state'] for p in failed[:3])}" if failed else "")
            ),
            "data": {
                "placements":    placements,
                "services":      services,
                "running_count": len(running),
                "failed_count":  len(failed),
                "manager_used":  manager_conn.get("label"),
                "hint": (
                    "Use vm_host_label with vm_exec() to SSH to the node. "
                    "Example: vm_exec(host='<vm_host_label>', command='docker ps --filter name=kafka')"
                ) if placements else "",
            },
            "timestamp": _ts(),
        }
    except Exception as e:
        return {"status": "error",
                "message": f"service_placement failed: {e}",
                "data": None, "timestamp": _ts()}
```

---

## Change 2 — mcp_server/server.py

Add the registration after the existing `swarm_node_status` tool registration.

Find:
```python
@mcp.tool()
def proxmox_vm_power(vm_label: str, action: str) -> dict:
```

Before that line, insert:

```python
@mcp.tool()
def service_placement(service_name: str) -> dict:
    """Find which Swarm nodes a service's tasks are running on, and the vm_host
    connection for each node. Cross-references task placement with SSH-accessible
    hosts so you can immediately follow up with vm_exec() or kafka_exec().
    Read-only. Use when a service reports running replicas but behaves incorrectly.
    Example: service_placement("kafka_broker-1")
    """
    from mcp_server.tools.vm import service_placement as _sp
    return _sp(service_name=service_name)

```

---

## Change 3 — api/agents/router.py

### 3a — Add service_placement to OBSERVE_AGENT_TOOLS

Find:
```python
    "swarm_node_status",
})
```
(the closing of OBSERVE_AGENT_TOOLS)

Replace with:
```python
    "swarm_node_status",
    "service_placement",
})
```

### 3b — Add service_placement to INVESTIGATE_AGENT_TOOLS

Find the `"swarm_node_status",` entry in INVESTIGATE_AGENT_TOOLS and add after it:
```python
    "service_placement",
```

### 3c — Update Kafka diagnostic chain in STATUS_PROMPT

Find the line added in v2.18.1:
```
    This chain narrows: cluster view → swarm view → task placement → broker self-check.
```

Replace with:
```
    This chain narrows: cluster view → swarm view → task placement → broker self-check.

TOPOLOGY SHORTCUT:
Instead of manually running docker service ps, use:
  service_placement("kafka_broker-1")
This returns: which node the task is on, its state, error message if any,
AND the exact vm_host_label to pass to vm_exec() or kafka_exec().
Example workflow:
  1. service_placement("kafka_broker-1")
     → {node: "ds-docker-worker-01", vm_host_label: "ds-docker-worker-01", current_state: "Running 3 hours ago"}
  2. vm_exec(host="ds-docker-worker-01", command="docker ps --filter name=kafka")
     → verify the container is actually running
  3. kafka_exec(broker_label="ds-docker-worker-01",
     command="kafka-topics.sh --bootstrap-server localhost:9092 --describe --topic hp1-logs")
     → check broker's view of the cluster
```

### 3d — Update Kafka chain in RESEARCH_PROMPT rule 5c

Find in RESEARCH_PROMPT:
```
    This chain narrows: cluster view → swarm view → task placement → broker self-check.
```

Replace with:
```
    This chain narrows: cluster view → swarm view → task placement → broker self-check.
    SHORTCUT: use service_placement("kafka_broker-1") to get node + vm_host_label in one call,
    then vm_exec(host=<vm_host_label>, ...) to SSH to that exact node.
```

---

## Do NOT touch

- `api/routers/agent.py` — no changes
- Any collector files
- Any frontend files

---

## Version bump

Update `VERSION`: `2.18.1` → `2.19.0`

---

## Commit

```bash
git add -A
git commit -m "feat(tools): v2.19.0 service_placement tool — swarm service → node → vm_host

- service_placement(service_name) in mcp_server/tools/vm.py
- SSHes to manager, runs docker service ps, cross-references node hostname to vm_host connections
- Returns: task name, node, current/desired state, error, vm_host_label, vm_host_ip, ssh_ready
- Partial service name supported (e.g. 'kafka' finds all kafka_broker-* services)
- Registered in mcp_server/server.py
- Added to OBSERVE_AGENT_TOOLS and INVESTIGATE_AGENT_TOOLS allowlists
- STATUS_PROMPT + RESEARCH_PROMPT: topology shortcut section with example workflow
- Closes the gap: missing broker → which node → vm_exec → kafka_exec chain"
git push origin main
```
