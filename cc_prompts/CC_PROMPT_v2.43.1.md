# CC PROMPT — v2.43.1 — fix(agents): observe prompt — anti-repeat rule + overlay network guidance

## What this does

Two prompt fixes for the observe/status agent, exposed by a live trace where:
1. `service_placement` was called 8 times for 4 services (steps 2 and 10, identical calls)
2. Agent tried `docker service ls` (blocked), then `docker service ls --format ...` (blocked),
   then gave up on overlay networks without trying the already-allowed
   `docker network ls` or `docker service inspect`

Fix 1: Add an explicit "no repeat calls" rule to the numbered rules list.
Fix 2: Add a one-line overlay network hint to the DOCKER SWARM section of the prompt.

Version bump: 2.43.0 → 2.43.1.

---

## Change 1 — `api/agents/router.py` — add rule 8 to STATUS_PROMPT rules list

Locate in the observe/status system prompt the block:

```
7. ZERO-RESULT PIVOT RULE: If the same tool returns 0 results 3 times in a row,
   STOP using that filter pattern. Either (a) broaden by dropping fields,
   (b) reuse data from an earlier non-zero call of the same tool, or
   (c) switch tools / propose_subtask. Never exceed 3 consecutive zero-result
   calls to the same tool.
```

Add rule 8 immediately after it:

```
8. NO REPEAT CALLS RULE: Never call the same tool with the same arguments
   twice in one run. If you already called service_placement("kafka_broker-1")
   in step 2, you have that data — do not call it again in step 10.
   Check your tool history before deciding what to call next.
```

Apply the same addition to the INVESTIGATE_PROMPT rules list if it exists there too.

---

## Change 2 — `api/agents/router.py` — add overlay network hint to Swarm section

Find the DOCKER SWARM section in STATUS_PROMPT (or RESEARCH_PROMPT if shared).
It will contain guidance on swarm_status, service_list, swarm_node_status.

After the line(s) about `service_list` or `swarm_status`, add:

```
- Overlay networks: use vm_exec(command="docker network ls --filter driver=overlay")
  on a manager node. To see which network each service is attached to:
  vm_exec(command="docker service inspect --format '{{.Spec.Name}} {{range .Spec.TaskTemplate.Networks}}{{.Target}} {{end}}' <service>")
  Both commands are in the allowlist. Do NOT attempt 'docker service ls' for this.
```

CC: find the exact Swarm section by searching for "swarm_status" or "SWARM" in the
STATUS_PROMPT string, then insert the network guidance in the most logical position.
If STATUS_PROMPT and RESEARCH_PROMPT share a Swarm section via a shared constant,
apply the edit once to the shared constant.

---

## Verification

After deploy, run the same task from the trace:
"List all Swarm services, show replicas running vs desired, flag any that are not
converged. Show placement for any failing services. List all overlay networks."

Confirm:
1. service_placement is called at most 4 times (once per service), not 8
2. Agent uses `docker network ls --filter driver=overlay` for overlay networks
3. No blocked tool calls in the trace

---

## Version bump

Update `VERSION`: `2.43.0` → `2.43.1`

---

## Commit

```
git add -A
git commit -m "fix(agents): v2.43.1 observe prompt — no-repeat rule + overlay network guidance"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
