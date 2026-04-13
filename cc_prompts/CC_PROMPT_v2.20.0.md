# CC PROMPT — v2.20.0 — Investigation quality: structured output + clarifying questions + evidence exhaustion

## What this does

Improves the quality and completeness of investigation runs:

1. **Structured 4-section output format** — replaces the freeform synthesis with a
   consistent Evidence / Root cause / Fix steps / Automatable format. The user should
   be able to read the output and know exactly what happened, why, and what to do.

2. **Clarifying question after ambiguous finding** — when the agent finds evidence but
   can't determine the root cause (e.g. container running but broker not in cluster,
   multiple possible causes for a crash), it calls clarifying_question() with targeted
   options before concluding. This avoids false conclusions on ambiguous data.

3. **Evidence exhaustion protocol** — agent must check all available read tools relevant
   to the finding before concluding. For Kafka: cluster → placement → logs → elastic.
   For containers: ps → logs → memory → elastic errors. Prevent premature conclusions.

4. **Better tool priority ordering** — route to `service_logs` before `vm_exec` for
   local containers; prefer Elastic search over raw SSH for historical error patterns.

Version bump: 2.19.1 → 2.20.0

---

## Change 1 — api/agents/router.py

### 1a — Replace RESEARCH_PROMPT RESPONSE STYLE with structured output section

Find in RESEARCH_PROMPT:
```
RESPONSE STYLE — Professional IT Support:
- Lead with what you did: "I checked X and found..."
- Be direct and specific: use exact values (IPs, versions, counts)
- No markdown headers in conversational responses
- Use bullet points only for lists of 3+ items
- Never say "I hope this helps" or "Let me know if..."
- Never pad with obvious statements
- Short sentences. Active voice.
- NEVER end with a closing announcement. Give the answer. Stop.
  Never say: "I have completed my check...", "I have finished analyzing...",
  "I will now summarize...", "This concludes my analysis.", or any similar phrase.
```

Replace with:
```
REQUIRED OUTPUT FORMAT — use this exact 4-section structure for every investigation:

EVIDENCE:
- <tool> → <finding> (e.g. "kafka_broker_status → broker 1 missing (ID=1, expected 3)")
- <tool> → <finding> (e.g. "service_placement → task on ds-docker-worker-01, Failed 14h ago")
- <tool> → <finding> (e.g. "docker logs → exit code 137, OOM kill at 09:12 UTC")
- (one bullet per tool call; omit ok/healthy results unless relevant)

ROOT CAUSE: <one sentence — specific, not speculative>
(e.g. "kafka_broker-1 is OOM-killed repeatedly on worker-01 due to insufficient heap memory")

FIX STEPS:
1. <specific action with exact command if applicable>
2. <next step>
3. ...

AUTOMATABLE (agent can run if re-run as action task):
- <step N> — <tool that would do this>
- (or "None — all steps require manual intervention")

RESPONSE STYLE:
- Be direct and specific: exact values (IPs, exit codes, timestamps, versions)
- No markdown headers — use the section labels above as plain text
- Never pad with obvious statements
- Short sentences. Active voice.
- NEVER end with a closing announcement.

WHEN TO CALL clarifying_question():
After gathering evidence, if the root cause is genuinely ambiguous (multiple equally
likely causes, or evidence points in conflicting directions), call clarifying_question()
with targeted options BEFORE concluding:
  clarifying_question(
    question="Broker-1 container is running but not joining the cluster. Most likely cause?",
    options=["Recent config change to advertised.listeners", "Network overlay issue (try force-update)", "Insufficient heap memory (check free -m)"]
  )
NEVER ask at the start of an investigation for clear tasks. Ask only when evidence is gathered
but the cause is still unclear. Ask at most once per run.
```

### 1b — Add EVIDENCE EXHAUSTION PROTOCOL section to RESEARCH_PROMPT

Find the INVESTIGATION DEPTH RULES section added in v2.19.1 and extend it.
Find the line that currently ends with:
```
  The container name or ID comes from the docker ps output you already collected.
  Use the full name from docker ps (e.g. kafka_broker-1.1.6nyfkvx1npvzk0krzzkab6kqi).
```

After that block, add:

```
EVIDENCE EXHAUSTION — check in this order for Kafka issues:
  Tier 1 (always): kafka_broker_status → service_placement → swarm_node_status
  Tier 2 (if container exists): vm_exec(docker ps) → vm_exec(docker logs --tail 50)
  Tier 3 (memory/resource): vm_exec(free -m) if exit 137 seen
  Tier 4 (log correlation): elastic_kafka_logs() → elastic_error_logs(service="kafka")
  Conclude only after Tier 1+2 are done and at least one of Tier 3 or 4.

TOOL PRIORITY FOR CONTAINER LOGS:
  1. service_logs(service_name=...) — ONLY for containers on the local Docker host (agent-01)
     This uses Docker SDK on the local socket. Does NOT reach remote Swarm workers.
  2. vm_exec(host="<worker-label>", command="docker logs <container_id> --tail 50")
     Use this for containers on Swarm workers. Requires the container ID from docker ps first.
  Never call service_logs() for a Kafka broker — it's on a Swarm worker, not local.
```

### 1c — Add tool priority ordering to STATUS_PROMPT

In STATUS_PROMPT, find the KAFKA INVESTIGATION section and add after the TOPOLOGY SHORTCUT block:

```
INVESTIGATION TOOL ORDER (for degraded Kafka):
  1. kafka_broker_status() — identify which broker is missing
  2. service_placement(service_name="kafka_broker-N") — find node + task state
  3. vm_exec(host=<vm_host_label>, command="docker ps --filter name=kafka")
     — verify current container name/ID
  4. vm_exec(host=<vm_host_label>, command="docker logs <container_id> --tail 50")
     — read actual crash reason (OOM, config error, JVM crash)
  5. vm_exec(host=<vm_host_label>, command="free -m") if exit code 137 seen
     — confirm OOM kill
  6. elastic_kafka_logs() — check historical error patterns in Elasticsearch

Only skip a tier if: the tool returns an error (not in allowlist), the component is
confirmed unreachable, or you already have definitive root cause from earlier steps.
```

---

## Change 2 — api/routers/agent.py

### 2a — Add structured output to the synthesis calls

The synthesis LLM call prompt (in the `_degraded_findings` synthesis blocks) currently asks for
"root cause + numbered fix steps + automatable steps". Update ALL THREE synthesis call prompts
(audit_log completion path, finish=stop path, and the max-steps else branch) to request
the structured 4-section format.

Find the synthesis system message (appears in all three locations):
```python
                                        "You are a concise infrastructure ops assistant. "
                                        "Based on the findings, provide:\n"
                                        "1. Root cause in one sentence\n"
                                        "2. What was checked (bullet list: tool → result)\n"
                                        "3. Numbered fix steps (specific commands or actions)\n"
                                        "4. Which fix steps the agent can run automatically "
                                        "if re-run with an action task\n"
                                        "Plain text only. No markdown headers."
```

Replace ALL three instances with:
```python
                                        "You are a concise infrastructure ops assistant. "
                                        "Produce a 4-section investigation report in plain text:\n\n"
                                        "EVIDENCE:\n"
                                        "- (one bullet per finding: tool → result)\n\n"
                                        "ROOT CAUSE: (one specific sentence)\n\n"
                                        "FIX STEPS:\n"
                                        "1. (specific action with exact command if known)\n"
                                        "2. ...\n\n"
                                        "AUTOMATABLE (if re-run as action task):\n"
                                        "- (step N — tool that would execute it)\n\n"
                                        "No markdown headers. No padding. Be specific: use exact "
                                        "exit codes, IPs, container names, and timestamps from the findings."
```

---

## Do NOT touch

- Any collector files
- Any frontend files  
- `mcp_server/tools/vm.py` — vm_exec allowlist was updated in v2.19.1

---

## Version bump

Update `VERSION`: `2.19.1` → `2.20.0`

---

## Commit

```bash
git add -A
git commit -m "feat(agent): v2.20.0 investigation quality — structured output + clarifying questions + evidence exhaustion

- RESEARCH_PROMPT: 4-section required output format (Evidence/Root cause/Fix steps/Automatable)
- RESEARCH_PROMPT: clarifying_question() guidance — call after gathering ambiguous evidence, not upfront
- RESEARCH_PROMPT: evidence exhaustion tiers (cluster → placement → logs → elastic)
- RESEARCH_PROMPT: tool priority for container logs (service_logs=local only; vm_exec for workers)
- STATUS_PROMPT: investigation tool order for degraded Kafka (numbered 1-6 with exact commands)
- agent.py: all 3 synthesis calls use structured 4-section format with Evidence/Root cause/Fix/Auto"
git push origin main
```
