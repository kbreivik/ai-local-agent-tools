"""VM host SSH execution + infrastructure lookup tools."""
import re
from datetime import datetime, timezone


def _ts():
    return datetime.now(timezone.utc).isoformat()


def _validate_command(command):
    """Validate a command against the read-only allowlist.

    Allows pipes (cmd1 | cmd2 | cmd3) where ALL segments match the allowlist.
    Allows '2>/dev/null' (stderr discard only — not file writes).
    Blocks semicolons, backticks, $(), stdout redirects, file writes.
    'docker system df -v' is supported (the pattern matches 'docker system df' prefix).
    Returns (is_valid, cleaned_command_or_error_message).
    """
    # Strip '2>/dev/null' before metachar check — safe stderr discard.
    cleaned = re.sub(r'\s*2>/dev/null', '', command).strip()

    # Strip Go template --format arguments before metachar check.
    # Pattern: --format '{{...}}' or --format "{{...}}" — safe, read-only Docker inspect option.
    sanitized = re.sub(r"""--format\s+['"]?\{\{[^'"]*\}\}['"]?""", '--format TEMPLATE', cleaned)

    # Block remaining shell injection chars (stdout redirects, chaining, subshells)
    if any(c in sanitized for c in [';', '`', '$', '>', '<', '&&', '||']):
        return False, f"Shell metacharacters not allowed: {command!r}"

    # Split on pipe — allow up to 3 segments (e.g. du -sh /* | sort -hr | head -20)
    parts = [p.strip() for p in sanitized.split('|')]
    if len(parts) > 3:
        return False, "Maximum two pipes allowed (e.g. cmd | sort -hr | head -20)"

    _ALLOWLIST = [
        # Read-only
        r'^df\b', r'^du\b', r'^free\b', r'^uptime$', r'^uname\b',
        r'^journalctl\b', r'^find\b', r'^ps\b',
        r'^docker system df', r'^docker volume ls', r'^docker volume inspect\b',
        r'^docker container inspect\b', r'^docker inspect\b',
        r'^docker ps\b', r'^docker images\b',
        r'^docker exec \S+ kafka-[a-z-]+\.sh\b',  # kafka CLI tools in containers
        r'^docker service ps\b', r'^docker service inspect\b',
        r'^docker node inspect\b', r'^docker node ls\b',
        r'^apt list', r'^apt-cache\b',
        r'^systemctl list', r'^systemctl status\b',
        r'^cat /etc/os-release$', r'^cat /proc/[\w/]+$',
        r'^hostname$', r'^whoami$',
        r'^ls\b', r'^stat\b', r'^wc\b', r'^sort\b',
        r'^head\b', r'^tail\b', r'^grep\b', r'^awk\b', r'^cut\b',
        r'^xargs\b',
        # Write (agent enforces plan_action approval via ACTION_PROMPT rule 11)
        r'^docker image prune\b',
        r'^docker container prune\b',
        r'^docker volume prune\b',
        r'^docker system prune\b',
        r'^docker builder prune\b',
        r'^journalctl --vacuum',
        r'^apt-get autoremove\b',
        r'^apt-get clean$',
        r'^apt-get autoclean$',
    ]

    for part in parts:
        if not any(re.match(p, part) for p in _ALLOWLIST):
            return False, (
                f"Command segment not in allowlist: {part!r}. "
                "Allowed: df, du, free, uptime, journalctl, find, ps, "
                "docker system df, docker volume ls, docker volume inspect, "
                "docker container inspect, docker inspect, docker ps, apt list, "
                "systemctl, ls, stat, sort, head, tail, grep, awk, cut, "
                "docker image/container/volume/system/builder prune, "
                "journalctl --vacuum, apt-get autoremove/clean. "
                "Tip: use docker_df tool for structured Docker disk data instead."
            )

    return True, cleaned  # return cleaned (2>/dev/null stripped), NOT sanitized (template replaced)


def _resolve_connection(host, all_conns):
    """Resolve a host name/IP/alias to a vm_host connection.
    Resolution order: infra_inventory -> label exact -> IP exact -> label partial.
    """
    q = host.lower().strip()

    # 1. Infra inventory (hostname, aliases, IPs, partial label)
    try:
        from api.db.infra_inventory import resolve_host
        entry = resolve_host(host)
        if entry:
            conn_id = entry.get("connection_id")
            for c in all_conns:
                if str(c.get("id")) == conn_id:
                    return c
    except Exception:
        pass

    # 2. Direct connection match -- label exact -> IP exact -> label partial
    for c in all_conns:
        if c.get("label", "").lower() == q:
            return c
    for c in all_conns:
        if c.get("host", "") == host:
            return c
    for c in all_conns:
        if q in c.get("label", "").lower():
            return c

    return None


def vm_exec(host: str, command: str) -> dict:
    """Execute a command on a registered VM host via SSH.

    All allowlisted commands execute directly. Write commands (docker prune,
    journalctl vacuum, apt-get clean) are in the allowlist — the agent is
    expected to call plan_action() before invoking vm_exec for these, but
    vm_exec itself does not enforce this (no second approval gate).

    Use for: disk usage (df -h), large dirs (du -sh /* | sort -hr | head -20),
    memory (free -m), logs (journalctl -n 50), Docker storage (docker system df),
    large files (find / -size +100M -type f 2>/dev/null | head -20),
    package updates (apt list --upgradable), cleanup (docker image prune -f,
    journalctl --vacuum-size=100M, apt-get autoremove -y).

    Args:
        host: VM host label, discovered hostname, or IP address.
              The error message lists available hosts if not found.
        command: IMPORTANT: If vm_exec returns "not in allowlist", do NOT retry.
                 Use these alternatives instead:
                 - docker volume sizes → docker system df -v
                 - docker volume path  → docker volume inspect <name> --format '{{.Mountpoint}}'
                 - docker container details → docker container inspect <name>
                 - structured Docker data → use docker_df tool (preferred)

                 Read-only shell command. Rules:
                 - Up to two pipes supported (cmd | cmd | cmd)
                 - '2>/dev/null' allowed (stderr discard)
                 - NO shell variables ($var), NO while/for loops,
                   NO subshells $(), NO stdout redirects (>)

                 For Docker volume sizes use: docker system df -v
                 NOT: docker volume ls | xargs docker inspect...

                 Good examples:
                   df -h
                   du -sh /* 2>/dev/null | sort -hr | head -20
                   find /var -size +100M -type f 2>/dev/null | head -20
                   docker system df -v
                   journalctl -n 50 --no-pager
                   free -m
                   ps aux | sort -k3 -rn | head -20
    """
    valid, result_or_error = _validate_command(command)
    if not valid:
        return {"status": "error", "message": result_or_error, "data": None, "timestamp": _ts()}

    safe_cmd = result_or_error

    try:
        from api.connections import get_all_connections_for_platform
        all_conns = get_all_connections_for_platform("vm_host")
    except Exception as e:
        return {"status": "error", "message": f"Failed to load vm_host connections: {e}",
                "data": None, "timestamp": _ts()}

    if not all_conns:
        return {"status": "error",
                "message": "No vm_host connections configured. Add in Settings -> Connections -> vm_host.",
                "data": None, "timestamp": _ts()}

    conn = _resolve_connection(host, all_conns)
    if not conn:
        labels = [f"{c.get('label', '?')} ({c.get('host', '?')})" for c in all_conns]
        return {"status": "error",
                "message": (
                    f"No vm_host connection found for {host!r}. "
                    f"Available: {', '.join(labels)}. "
                    "Tip: use the connection label exactly, or call infra_lookup() "
                    "to see discovered hostnames."
                ),
                "data": None, "timestamp": _ts()}

    try:
        from api.collectors.vm_hosts import _resolve_credentials, _resolve_jump_host, _ssh_run
        username, password, private_key = _resolve_credentials(conn, all_conns)
        jump_host = _resolve_jump_host(conn, all_conns)
    except Exception as e:
        return {"status": "error", "message": f"Credential resolution failed: {e}",
                "data": None, "timestamp": _ts()}

    try:
        output = _ssh_run(
            conn["host"], conn.get("port") or 22,
            username, password, private_key,
            safe_cmd, jump_host=jump_host,
            _log_meta={"connection_id": str(conn.get("id", "")),
                       "resolved_label": conn.get("label", host),
                       "triggered_by": "vm_exec"},
        )
        label = conn.get("label", host)
        jump_note = f" (via {jump_host['host']})" if jump_host else ""
        return {
            "status": "ok",
            "message": f"Executed on {label}{jump_note}",
            "data": {
                "host":      label,
                "ip":        conn["host"],
                "command":   safe_cmd,
                "output":    output.strip()[:4000],
                "truncated": len(output) > 4000,
            },
            "timestamp": _ts(),
        }
    except Exception as e:
        return {"status": "error",
                "message": f"SSH failed on {conn.get('label', host)} ({conn['host']}): {e}",
                "data": None, "timestamp": _ts()}


def infra_lookup(query: str = "", platform: str = "") -> dict:
    """Look up infrastructure entities by hostname, IP, alias, or label.

    Searches the infra_inventory automatically populated by collectors
    (vm_hosts, proxmox, swarm). Use to resolve user-provided names to
    actual connections, find IPs, or list all known hosts.

    Args:
        query: hostname, IP address, alias, or partial label to search.
               Leave blank to list all known entities.
        platform: optional filter -- vm_host, proxmox, docker_host, etc.
    """
    try:
        from api.db.infra_inventory import resolve_host, list_inventory

        if query:
            entry = resolve_host(query)
            if entry:
                return {
                    "status": "ok",
                    "message": f"Found: {entry['label']} ({entry.get('hostname') or '?'})",
                    "data": {
                        "connection_id": entry["connection_id"],
                        "platform":      entry["platform"],
                        "label":         entry["label"],
                        "hostname":      entry.get("hostname", ""),
                        "ips":           entry.get("ips", []),
                        "aliases":       entry.get("aliases", []),
                        "meta":          entry.get("meta", {}),
                        "last_discovered": str(entry.get("last_discovered", "")),
                    },
                    "timestamp": _ts(),
                }
            return {"status": "error",
                    "message": f"No infrastructure entity found for {query!r}",
                    "data": None, "timestamp": _ts()}
        else:
            entries = list_inventory(platform=platform)
            summary = [
                {
                    "label":    e["label"],
                    "hostname": e.get("hostname", ""),
                    "ips":      e.get("ips", []),
                    "platform": e["platform"],
                    "meta":     {k: v for k, v in (e.get("meta") or {}).items()
                                 if k in ("os", "role", "os_type")},
                }
                for e in entries
            ]
            return {
                "status": "ok",
                "message": f"{len(summary)} infrastructure entities known",
                "data": {"entities": summary},
                "timestamp": _ts(),
            }
    except Exception as e:
        return {"status": "error", "message": f"infra_lookup error: {e}",
                "data": None, "timestamp": _ts()}


def kafka_exec(broker_label: str, command: str) -> dict:
    """Run a Kafka CLI command inside the kafka container on a specific broker node.

    Finds the vm_host connection matching broker_label, SSHes to that node,
    finds the kafka container, and runs the command inside it.

    Args:
        broker_label: vm_host connection label (e.g. "ds-docker-worker-01")
        command:      Kafka CLI command without 'docker exec <container>' prefix
                      e.g. "kafka-topics.sh --bootstrap-server localhost:9092 --describe --topic hp1-logs"

    Safe commands only: kafka-topics.sh, kafka-consumer-groups.sh,
    kafka-leader-election.sh (PREFERRED only), kafka-log-dirs.sh.
    Blocked: kafka-delete-records, kafka-reassign-partitions (destructive).
    """
    from api.connections import get_all_connections_for_platform
    from api.collectors.vm_hosts import _resolve_credentials, _ssh_run

    # Safety: block destructive kafka commands
    BLOCKED = ["delete-records", "reassign-partitions", "--delete", "--reset-offsets"]
    for b in BLOCKED:
        if b in command:
            return {"status": "error",
                    "message": f"Blocked: '{b}' is a destructive Kafka operation. Use Kafka admin directly.",
                    "data": None, "timestamp": _ts()}

    # Find the vm_host connection
    all_conns = get_all_connections_for_platform("vm_host")
    conn = next((c for c in all_conns if c.get("label", "").lower() == broker_label.lower()), None)
    if not conn:
        available = [c.get("label") for c in all_conns]
        return {"status": "error",
                "message": f"No vm_host connection '{broker_label}'. Available: {available}",
                "data": None, "timestamp": _ts()}

    host = conn.get("host", "")
    port = conn.get("port") or 22
    username, password, private_key = _resolve_credentials(conn, all_conns)

    try:
        # SSH to the worker, find the kafka container, exec the command
        find_cmd = "docker ps --filter name=kafka --format '{{.Names}}' | head -1"
        container_name = _ssh_run(host, port, username, password, private_key, find_cmd).strip()
        if not container_name:
            return {"status": "error",
                    "message": f"No kafka container found on {broker_label} ({host})",
                    "data": None, "timestamp": _ts()}

        full_cmd = f"docker exec {container_name} {command}"
        output = _ssh_run(host, port, username, password, private_key, full_cmd)

        return {
            "status": "ok",
            "data": {
                "host": host,
                "container": container_name,
                "command": command,
                "output": output,
            },
            "message": f"Executed on {broker_label} ({host}) in {container_name}",
            "timestamp": _ts(),
        }
    except Exception as e:
        return {"status": "error", "message": str(e), "data": None, "timestamp": _ts()}


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


def ssh_capabilities(host: str = "", days: int = 7) -> dict:
    """Query the SSH capability map — which credentials can reach which hosts.

    Returns verified credential→host pairs with success rates and latency.
    Use to understand available SSH access before planning operations,
    or to audit which credentials have broad access.

    Args:
        host: optional target host to filter by (label or IP). Blank = all.
        days: look-back window in days (default 7, max 90).
    """
    try:
        from api.db.ssh_capabilities import query_capabilities, get_capability_summary
        if host:
            target = host
            try:
                from api.db.infra_inventory import resolve_host
                entry = resolve_host(host)
                if entry and entry.get("ips"):
                    target = entry["ips"][0]
            except Exception:
                pass
            rows = query_capabilities(target_host=target, days=days)
            if not rows:
                rows = [r for r in query_capabilities(days=days)
                        if host.lower() in (r.get("resolved_label", "") or "").lower()
                        or host.lower() in (r.get("target_host", "") or "").lower()]
        else:
            rows = query_capabilities(verified_only=True, days=days)

        summary = get_capability_summary()
        return {
            "status": "ok",
            "message": f"{len(rows)} credential→host pair(s)" + (f" for {host!r}" if host else "") + f" (last {days}d)",
            "data": {
                "pairs": [{"credential_label": r.get("resolved_label") or r.get("target_host"),
                           "target_host": r.get("target_host"), "username": r.get("username"),
                           "verified": r.get("verified"),
                           "last_success": str(r.get("last_success", ""))[:19],
                           "success_rate_pct": r.get("success_rate_pct", 0),
                           "avg_latency_ms": r.get("avg_latency_ms"),
                           "jump_host": r.get("jump_host"),
                           "new_host_alert": r.get("new_host_alert", False),
                           "attempts_7d": r.get("attempts_7d", 0)} for r in rows[:20]],
                "summary": summary,
            },
            "timestamp": _ts(),
        }
    except Exception as e:
        return {"status": "error", "message": f"ssh_capabilities error: {e}", "data": None, "timestamp": _ts()}
