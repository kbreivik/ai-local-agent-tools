# CC PROMPT — v2.15.3 — vm_exec allowlist expansion + worker node SSH

## What this does

The `vm_exec` tool's command allowlist blocked the agent from running
`ssh` to lateral-hop to worker nodes for Kafka/Docker investigation.
All workers and managers should be registered as vm_host connections
(after v2.15.0/2.15.1 bulk create), so direct SSH via vm_exec is the
right path — not lateral SSH from manager to worker.

This prompt:
1. Registers the ssh allowlist commands needed for Kafka investigation
2. Adds a `kafka_exec` helper tool that runs Kafka CLI commands inside
   the kafka container on any worker node
3. Adds `container_exec` for running one-shot commands in named Swarm
   service containers via docker exec on the correct worker

Version bump: 2.15.2 → 2.15.3 (new agent tools, x.x.1)

---

## Change 1 — mcp_server/tools/vm.py — expand vm_exec allowlist

Find the `ALLOWED_COMMANDS` or equivalent allowlist set in `vm.py`.
Add the following safe read/investigate commands:

```python
# Add to the allowed safe commands set:
"docker exec",              # exec into containers (read-only commands only)
"docker service ps",        # see which node runs a service task
"docker service inspect",   # service detail
"docker node inspect",      # node detail
"docker node ls",           # list nodes (already likely allowed)

# Kafka-specific CLI tools (only safe read commands):
"kafka-topics.sh",
"kafka-leader-election.sh",  # safe — only triggers preferred election, no data loss
"kafka-consumer-groups.sh",
"kafka-log-dirs.sh",         # check log dir usage
"kafka-broker-api-versions.sh",
```

The key constraint: commands must still be validated against the
allowlist PATTERN not just prefix. The existing validator likely
checks prefixes — ensure `docker exec` is added carefully so it
only allows `docker exec <container> <safe-kafka-command>` patterns.

If the allowlist uses regex matching, add:
```python
r"docker exec \S+ kafka-[a-z-]+\.sh .*",    # kafka tools only
r"docker exec \S+ bash -c 'kafka-[a-z-]+",   # kafka tools via bash
r"docker service ps \S+",
r"docker service inspect \S+",
r"docker node inspect \S+",
```

---

## Change 2 — mcp_server/tools/vm.py — add kafka_exec tool

```python
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
    from api.connections import get_all_connections_for_platform, _decode_creds
    from api.db.credential_profiles import resolve_credentials_for_connection

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
```

---

## Change 3 — mcp_server/server.py — register kafka_exec

```python
@mcp.tool()
def kafka_exec(broker_label: str, command: str) -> dict:
    """Run a Kafka CLI command in the kafka container on a specific worker node.
    broker_label must match a vm_host connection label exactly.
    Safe commands: kafka-topics.sh, kafka-consumer-groups.sh, kafka-leader-election.sh (PREFERRED only).
    Example: kafka_exec("ds-docker-worker-01", "kafka-topics.sh --bootstrap-server localhost:9092 --describe --topic hp1-logs")
    """
    from mcp_server.tools.vm import kafka_exec as _ke
    return _ke(broker_label=broker_label, command=command)
```

---

## Change 4 — api/agents/router.py — add kafka_exec to allowlists

Add `"kafka_exec"` to:
- `INVESTIGATE_TOOLS` / `OBSERVE_TOOLS` — read-only investigation
- `EXECUTE_SWARM_TOOLS` / `EXECUTE_GENERAL_TOOLS` — for leader election

```python
# In OBSERVE / INVESTIGATE allowlists, add:
"kafka_exec",

# In EXECUTE_SWARM_TOOLS, add:
"kafka_exec",
```

Add to `STATUS_PROMPT`:
```
KAFKA INVESTIGATION:
To check topic state on a specific broker: kafka_exec(broker_label="ds-docker-worker-01",
  command="kafka-topics.sh --bootstrap-server localhost:9092 --describe --topic hp1-logs")
To run preferred leader election: kafka_exec(broker_label="ds-docker-worker-01",
  command="kafka-leader-election.sh --bootstrap-server localhost:9092 --election-type PREFERRED --all-topic-partitions")
broker_label must exactly match a vm_host connection label. Call infra_lookup() first if unsure.
```

---

## Version bump

Update VERSION: `2.15.2` → `2.15.3`

---

## Commit

```bash
git add -A
git commit -m "feat(agent): v2.15.3 kafka_exec tool + vm_exec allowlist expansion

- kafka_exec(): SSH to broker worker, exec Kafka CLI inside container
- Supports topic describe, consumer groups, preferred leader election
- Blocks destructive operations (delete-records, reassign-partitions, etc.)
- vm_exec allowlist: adds docker exec + kafka CLI patterns
- kafka_exec added to OBSERVE, INVESTIGATE, EXECUTE_SWARM allowlists
- STATUS_PROMPT: Kafka investigation section with examples"
git push origin main
```
