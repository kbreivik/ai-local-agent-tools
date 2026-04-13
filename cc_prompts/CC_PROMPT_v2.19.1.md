# CC PROMPT — v2.19.1 — docker logs allowlist + investigation depth rules

## What this does

Three targeted fixes:

1. **Add `docker logs` to vm_exec allowlist** — currently blocked. The agent correctly
   identifies container IDs via `docker ps` and needs to read their logs. `docker logs`
   is read-only and `>` redirects are already blocked by the metachar filter.

2. **Elastic log tools must be called before concluding** — the agent has `elastic_kafka_logs`
   and `elastic_error_logs` available but didn't call them. These contain actual Kafka JVM
   error messages, OOM events, and broker crash reasons. Update RESEARCH_PROMPT to require
   these before concluding a Kafka investigation.

3. **service_placement param correction in prompt** — agent tried `service_placement(service=...)`
   which failed, then positional which worked. Clarify in prompts that the param is `service_name`.

Version bump: 2.19.0 → 2.19.1

---

## Change 1 — mcp_server/tools/vm.py

In the `_ALLOWLIST` list inside `_validate_command()`, find the read-only section:

```python
        r'^docker ps\b', r'^docker images\b',
        r'^docker exec \S+ kafka-[a-z-]+\.sh\b',  # kafka CLI tools in containers
```

After `r'^docker ps\b', r'^docker images\b',`, add:

```python
        r'^docker logs\b',                         # read-only log fetch
```

So it becomes:

```python
        r'^docker ps\b', r'^docker images\b',
        r'^docker logs\b',                         # read-only log fetch
        r'^docker exec \S+ kafka-[a-z-]+\.sh\b',  # kafka CLI tools in containers
```

---

## Change 2 — api/agents/router.py

### 2a — Update RESEARCH_PROMPT: add investigation depth rules

Find in RESEARCH_PROMPT after the RULES section, the line:
```
8. When citing documentation, use format: [Source: kafka-docs] or [Source: nginx-docs].
```

After that line, add:

```
INVESTIGATION DEPTH RULES — follow before concluding:
Before calling audit_log() on a Kafka investigation, you MUST have attempted:
  a. elastic_kafka_logs() — get actual broker error messages from Elasticsearch
     (OOM events, broker registration failures, ISR changes, JVM crashes)
  b. vm_exec with docker logs — if service_placement found a container on a node,
     call vm_exec(host="<vm_host_label>", command="docker logs <container_id> --tail 50")
     to read the actual crash reason.
  c. kafka_exec to check from the broker's own perspective — only skip if the
     container is confirmed crashed/exiting.

For container crash loops (exit codes found via docker ps):
  - exit code 255 = JVM crash or startup failure (check docker logs for OOM/config error)
  - exit code 143 = SIGTERM (graceful shutdown — usually Swarm orchestration)
  - exit code 137 = SIGKILL (OOM kill — check free -m on the node first)
  If you see exit 137: call vm_exec(host="<node>", command="free -m") FIRST to check
  available memory — this is likely the root cause.

vm_exec docker logs usage:
  vm_exec(host="ds-docker-worker-01",
          command="docker logs kafka_broker-1.1.abc123xyz --tail 50")
  The container name or ID comes from the docker ps output you already collected.
  Use the full name from docker ps (e.g. kafka_broker-1.1.6nyfkvx1npvzk0krzzkab6kqi).
```

### 2b — Fix service_placement param in TOPOLOGY SHORTCUT section of STATUS_PROMPT

In STATUS_PROMPT, find:
```
TOPOLOGY SHORTCUT:
Instead of manually running docker service ps, use:
  service_placement("kafka_broker-1")
```

Replace with:
```
TOPOLOGY SHORTCUT:
Instead of manually running docker service ps, use:
  service_placement(service_name="kafka_broker-1")
The parameter is service_name — do NOT use service= or name=.
Positional also works: service_placement("kafka_broker-1")
```

Apply the same fix in RESEARCH_PROMPT rule 5c — change:
```
    SHORTCUT: use service_placement("kafka_broker-1") to get node + vm_host_label in one call,
```
to:
```
    SHORTCUT: use service_placement(service_name="kafka_broker-1") to get node + vm_host_label.
    (param is service_name — not service= or name=; positional also works)
```

---

## Do NOT touch

- Any collector files
- Any frontend files
- Any router files outside `api/agents/router.py` and `mcp_server/tools/vm.py`

---

## Version bump

Update `VERSION`: `2.19.0` → `2.19.1`

---

## Commit

```bash
git add -A
git commit -m "fix(agent): v2.19.1 docker logs allowlist + investigation depth rules + service_placement param fix

- vm_exec allowlist: add docker logs (read-only, metachar filter already blocks writes)
- RESEARCH_PROMPT: investigation depth rules before audit_log (elastic_kafka_logs required)
- Exit code interpretation: 137=OOM (check free -m), 255=JVM crash (read docker logs)
- vm_exec docker logs usage example added to RESEARCH_PROMPT
- service_placement param fix in both STATUS_PROMPT and RESEARCH_PROMPT (service_name=)"
git push origin main
```
