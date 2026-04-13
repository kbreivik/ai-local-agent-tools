# CC PROMPT — v2.15.9 — Agent Swarm recovery tools + pre-flight bypass

## What this does

Four agent failures during Kafka/Swarm recovery:
1. `pre_kafka_check` halts ALL Kafka tasks including fix/restart tasks — wrong
2. No `swarm_service_force_update` tool — agent had the right answer but no path to execute it
3. No `swarm_node_status` tool — agent couldn't check which nodes were Down
4. When blocked, agent escalates instead of providing exact manual commands

Version bump: 2.15.8 → 2.15.9 (new tools + prompt fixes, x.x.1)

---

## Change 1 — mcp_server/tools/vm.py — add swarm_service_force_update()

```python
def swarm_service_force_update(service_name: str, manager_label: str = "") -> dict:
    """Force-update a Docker Swarm service to recover from network/scheduling issues.

    Runs 'docker service update --force <service>' on a Swarm manager node.
    This causes Swarm to reschedule the service with fresh network attachments,
    fixing 'network not found' errors and stale overlay network references.
    Does NOT change the image or configuration — safe for broker recovery.

    Requires plan_action() approval before calling.

    Args:
        service_name:  Exact Swarm service name (e.g. "kafka_broker-2", "logstash_logstash")
        manager_label: vm_host label of a Swarm manager node. If blank, auto-selects
                       the first available manager from vm_host connections.
    """
    from api.connections import get_all_connections_for_platform
    from api.collectors.vm_hosts import _resolve_credentials, _ssh_run

    all_conns = get_all_connections_for_platform("vm_host")

    # Resolve manager — explicit label, or find one by role/label pattern
    manager_conn = None
    if manager_label:
        manager_conn = next(
            (c for c in all_conns if c.get("label", "").lower() == manager_label.lower()),
            None
        )
    if not manager_conn:
        # Auto-select: prefer connections with 'manager' in label
        manager_conn = next(
            (c for c in all_conns if 'manager' in c.get("label", "").lower()),
            None
        )
    if not manager_conn:
        return {"status": "error",
                "message": "No Swarm manager vm_host connection found. Add a manager node in Settings → Connections.",
                "data": None, "timestamp": _ts()}

    host = manager_conn.get("host", "")
    port = manager_conn.get("port") or 22
    username, password, private_key = _resolve_credentials(manager_conn, all_conns)

    try:
        output = _ssh_run(
            host, port, username, password, private_key,
            f"docker service update --force {service_name}",
        )
        success = "converged" in output.lower() or "verify" in output.lower()
        return {
            "status": "ok" if success else "error",
            "message": f"Force-updated {service_name} on {manager_conn.get('label')}",
            "data": {
                "service": service_name,
                "manager": manager_conn.get("label"),
                "output": output.strip()[:2000],
                "converged": success,
            },
            "timestamp": _ts(),
        }
    except Exception as e:
        return {"status": "error",
                "message": f"SSH failed on {manager_conn.get('label')}: {e}",
                "data": None, "timestamp": _ts()}
```

---

## Change 2 — mcp_server/tools/vm.py — add swarm_node_status()

```python
def swarm_node_status() -> dict:
    """Get Docker Swarm node availability and service task placement.

    Runs 'docker node ls' on a manager to show all nodes with their status.
    Also checks for services with failed/not-running tasks.
    Read-only — never requires plan_action.

    Returns node list with: hostname, status (Ready/Down), availability
    (Active/Drain/Pause), manager status, engine version.
    Also returns any services with tasks not running as expected.
    """
    from api.connections import get_all_connections_for_platform
    from api.collectors.vm_hosts import _resolve_credentials, _ssh_run
    import json

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
        # Get node list
        node_out = _ssh_run(
            host, port, username, password, private_key,
            "docker node ls --format '{{.Hostname}}|{{.Status}}|{{.Availability}}|{{.ManagerStatus}}|{{.EngineVersion}}'",
        )
        nodes = []
        down_nodes = []
        for line in node_out.strip().splitlines():
            parts = line.split("|")
            if len(parts) >= 4:
                hostname, status, avail, mgr_status = parts[0], parts[1], parts[2], parts[3]
                engine = parts[4] if len(parts) > 4 else ""
                nodes.append({
                    "hostname": hostname.strip(),
                    "status": status.strip(),
                    "availability": avail.strip(),
                    "manager_status": mgr_status.strip(),
                    "engine_version": engine.strip(),
                })
                if status.strip().lower() == "down":
                    down_nodes.append(hostname.strip())

        # Get service task failures
        svc_out = _ssh_run(
            host, port, username, password, private_key,
            "docker service ps --filter desired-state=running --format '{{.Name}}|{{.CurrentState}}|{{.Error}}' $(docker service ls -q) 2>/dev/null | grep -v 'Running' | head -20",
        )
        failed_tasks = []
        for line in svc_out.strip().splitlines():
            if line and "|" in line:
                parts = line.split("|")
                failed_tasks.append({
                    "task": parts[0].strip(),
                    "state": parts[1].strip() if len(parts) > 1 else "",
                    "error": parts[2].strip() if len(parts) > 2 else "",
                })

        health = "healthy"
        if down_nodes:
            health = "critical" if len(down_nodes) > 1 else "degraded"

        return {
            "status": "ok",
            "health": health,
            "message": (
                f"{len(nodes)} nodes ({len(down_nodes)} down)"
                + (f" — DOWN: {', '.join(down_nodes)}" if down_nodes else " — all ready")
            ),
            "data": {
                "nodes": nodes,
                "down_nodes": down_nodes,
                "failed_tasks": failed_tasks[:10],
                "manager_used": manager_conn.get("label"),
            },
            "timestamp": _ts(),
        }
    except Exception as e:
        return {"status": "error",
                "message": f"swarm_node_status failed: {e}",
                "data": None, "timestamp": _ts()}
```

---

## Change 3 — mcp_server/tools/vm.py — add proxmox_vm_power()

```python
def proxmox_vm_power(vm_label: str, action: str) -> dict:
    """Start, stop, or reboot a Proxmox VM by label.

    Use when a Swarm worker node is completely down (STATUS=Down in docker node ls)
    and cannot be reached via SSH. This talks directly to the Proxmox API.
    Requires plan_action() approval before calling.

    Args:
        vm_label: VM name as shown in Proxmox (e.g. "hp1-prod-worker-03")
                  or the short hostname (e.g. "worker-03")
        action:   "start" | "stop" | "reboot" — reboot is preferred over stop+start
    """
    if action not in ("start", "stop", "reboot"):
        return {"status": "error",
                "message": f"Invalid action '{action}'. Use: start, stop, reboot",
                "data": None, "timestamp": _ts()}

    try:
        from api.connections import get_connection_for_platform
        from proxmoxer import ProxmoxAPI

        conn = get_connection_for_platform("proxmox")
        if not conn:
            return {"status": "error",
                    "message": "No Proxmox connection configured.",
                    "data": None, "timestamp": _ts()}

        creds = conn.get("credentials", {})
        pve = ProxmoxAPI(
            conn["host"],
            port=conn.get("port", 8006),
            user=creds.get("user"),
            token_name=creds.get("token_name"),
            token_value=creds.get("secret"),
            verify_ssl=False,
        )

        # Find VM across all nodes by name
        found = None
        for node_info in pve.nodes.get():
            node = node_info["node"]
            for vm in pve.nodes(node).qemu.get():
                name = vm.get("name", "")
                if (vm_label.lower() in name.lower() or
                        name.lower() in vm_label.lower()):
                    found = {"node": node, "vmid": vm["vmid"], "name": name,
                             "status": vm.get("status")}
                    break
            if found:
                break

        if not found:
            return {"status": "error",
                    "message": f"No VM matching '{vm_label}' found in Proxmox.",
                    "data": None, "timestamp": _ts()}

        node, vmid = found["node"], found["vmid"]
        endpoint = pve.nodes(node).qemu(vmid).status

        if action == "start":
            result = endpoint.start.post()
        elif action == "stop":
            result = endpoint.stop.post()
        else:  # reboot
            result = endpoint.reboot.post()

        return {
            "status": "ok",
            "message": f"{action.capitalize()}ed VM '{found['name']}' (vmid {vmid}) on node {node}",
            "data": {
                "vm_name": found["name"],
                "vmid": vmid,
                "node": node,
                "action": action,
                "task_id": str(result),
                "previous_status": found["status"],
            },
            "timestamp": _ts(),
        }
    except Exception as e:
        return {"status": "error",
                "message": f"proxmox_vm_power failed: {e}",
                "data": None, "timestamp": _ts()}
```

---

## Change 4 — mcp_server/server.py — register the three new tools

```python
@mcp.tool()
def swarm_service_force_update(service_name: str, manager_label: str = "") -> dict:
    """Force-update a Swarm service to recover from network/scheduling failures.
    Runs 'docker service update --force' on a manager. Requires plan_action() first.
    Use for: 'network not found' errors, tasks stuck in Rejected/Failed state.
    Example: swarm_service_force_update("kafka_broker-2")
    """
    from mcp_server.tools.vm import swarm_service_force_update as _f
    return _f(service_name=service_name, manager_label=manager_label)


@mcp.tool()
def swarm_node_status() -> dict:
    """Get Swarm node availability — which nodes are Ready/Down, any failed tasks.
    Read-only. Use first when Kafka or services are missing replicas.
    Shows: hostname, status, availability, manager status, engine version.
    """
    from mcp_server.tools.vm import swarm_node_status as _f
    return _f()


@mcp.tool()
def proxmox_vm_power(vm_label: str, action: str) -> dict:
    """Start, stop, or reboot a Proxmox VM by name label.
    Use when a worker node is completely Down and unreachable via SSH.
    action: 'start' | 'stop' | 'reboot'. Requires plan_action() first.
    Example: proxmox_vm_power("worker-03", "reboot")
    """
    from mcp_server.tools.vm import proxmox_vm_power as _f
    return _f(vm_label=vm_label, action=action)
```

---

## Change 5 — api/agents/router.py — add new tools to allowlists

```python
# Add to OBSERVE_AGENT_TOOLS and INVESTIGATE_AGENT_TOOLS:
"swarm_node_status",

# Add to EXECUTE_SWARM_TOOLS:
"swarm_node_status",
"swarm_service_force_update",

# Add to EXECUTE_KAFKA_TOOLS (Kafka degraded often means a broker node is down):
"swarm_node_status",
"swarm_service_force_update",

# Add to EXECUTE_GENERAL_TOOLS:
"swarm_node_status",
"proxmox_vm_power",
"swarm_service_force_update",
```

Also add `proxmox_vm_power` to DESTRUCTIVE_TOOLS in `api/routers/agent.py`:
```python
DESTRUCTIVE_TOOLS = frozenset({
    ...existing...,
    "swarm_service_force_update",
    "proxmox_vm_power",
})
```

---

## Change 6 — api/agents/router.py — pre-flight bypass for remediation tasks

In `ACTION_PROMPT`, find rule 3:
```
3. Before ANY Kafka operation: call pre_kafka_check(). If not ok, HALT.
```

Replace with:
```
3. Before ANY Kafka operation: call pre_kafka_check() UNLESS the task explicitly
   involves fixing, restarting, recovering, or force-updating a known-degraded
   component. Remediation tasks (fix, repair, restart, recover, force-update,
   rejoin, rebalance a broken broker) must proceed THROUGH degraded state —
   that is the point of the task. In those cases, skip pre_kafka_check and
   proceed directly to swarm_node_status → plan_action → swarm_service_force_update.
   If not a remediation task and pre_kafka_check is not ok, HALT.
```

Also add a RECOVERY WORKFLOW section to ACTION_PROMPT:
```
KAFKA/SWARM RECOVERY WORKFLOW:
When asked to fix/restart/recover a Kafka broker or Swarm service:
1. Call swarm_node_status() — find which nodes are Down
2. If a node is Down and unreachable:
   a. Call plan_action() with: "Reboot <node> via Proxmox to recover broker"
   b. After approval: call proxmox_vm_power(vm_label=..., action="reboot")
   c. Wait is not possible — tell user to verify after ~2 minutes
3. If node is Up but service failing:
   a. Call plan_action() with: "Force-update <service> to clear network state"
   b. After approval: call swarm_service_force_update(service_name=...)
   c. Report convergence status from the tool result
4. If blocked at any step: provide the EXACT manual command to run, e.g.:
   "I cannot execute this directly. Run on a manager: docker service update --force kafka_broker-3"
   NEVER escalate solely because a command is unavailable — give the manual alternative.
```

---

## Change 7 — api/agents/router.py — blocked → manual command, not escalate

Add to ACTION_PROMPT BLOCKED COMMAND RULE section:
```
BLOCKED TOOL RULE (CRITICAL):
When a tool is unavailable or blocked:
- NEVER call escalate() solely because a tool is blocked
- ALWAYS provide the exact manual command the user can run via SSH
- Format: "I cannot execute this directly. Run manually:
  ssh ubuntu@<ip> 'docker service update --force <service>'"
- Use swarm_node_status() and infra_lookup() to get the correct IP first
- escalate() is ONLY for genuine infrastructure failures where data shows
  a real problem (broker actually lost data, service not converging after restart, etc.)
```

Add same rule to STATUS_PROMPT and RESEARCH_PROMPT for consistency.

---

## Version bump

Update VERSION: `2.15.8` → `2.15.9`

---

## Commit

```bash
git add -A
git commit -m "feat(agent): v2.15.9 Swarm recovery tools + pre-flight bypass

- swarm_node_status(): docker node ls on manager, shows Down nodes + failed tasks
- swarm_service_force_update(): SSH to manager, runs docker service update --force
- proxmox_vm_power(): start/stop/reboot Proxmox VM by label for downed worker recovery
- All three added to appropriate allowlists (observe/execute/swarm/kafka/general)
- ACTION_PROMPT: pre_kafka_check bypassed for explicit remediation tasks
- RECOVERY WORKFLOW added to ACTION_PROMPT: node down → proxmox reboot path
- BLOCKED TOOL RULE: agent must provide exact manual SSH command, not just escalate"
git push origin main
```
