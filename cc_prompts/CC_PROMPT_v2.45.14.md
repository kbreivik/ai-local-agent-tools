# CC PROMPT — v2.45.14 — fix(agent): add pre_kafka_check to INVESTIGATE_AGENT_TOOLS + fix routing

## Root cause

`pre_kafka_check` lives only in `EXECUTE_KAFKA_TOOLS` (the action/execute agent's
Kafka tool set). It is NOT in `INVESTIGATE_AGENT_TOOLS` or `OBSERVE_AGENT_TOOLS`.

Tasks that say "use the pre_kafka_check tool" get routed to the STATUS agent
(because "kafka" is a STATUS_KEYWORD). The status agent doesn't have
`pre_kafka_check` so falls back to `kafka_broker_status` + `kafka_consumer_lag`.

Two fixes:
1. Add `pre_kafka_check` to `INVESTIGATE_AGENT_TOOLS` — it's a read-only
   pre-flight check, perfectly valid for research agents.
2. Add "verify" and "pre-flight" to RESEARCH_KEYWORDS so tasks containing those
   words route to research, not status.

Version bump: 2.45.13 → 2.45.14.

---

## Change 1 — `api/agents/router.py` — INVESTIGATE_AGENT_TOOLS

Find `INVESTIGATE_AGENT_TOOLS = frozenset({` and locate the kafka tools section
within it. Add `pre_kafka_check` alongside the other kafka tools.

If the current INVESTIGATE_AGENT_TOOLS has `kafka_broker_status` in it, add
`pre_kafka_check` right before or after it:

```python
    "pre_kafka_check",   # v2.45.14: pre-flight check — valid for research agents
    "kafka_broker_status", ...
```

If `kafka_broker_status` is not in INVESTIGATE_AGENT_TOOLS, add `pre_kafka_check`
to the kafka block alongside whatever kafka tools are present.

---

## Change 2 — `api/agents/router.py` — RESEARCH_KEYWORDS

Find `RESEARCH_KEYWORDS = frozenset({`. Add two entries:

```python
    "verify", "pre-flight",   # v2.45.14: pre-flight check tasks should route research
```

---

## Version bump

Update `VERSION`: `2.45.13` → `2.45.14`

---

## Commit

```
git add -A
git commit -m "fix(agent): v2.45.14 add pre_kafka_check to INVESTIGATE_AGENT_TOOLS + verify to RESEARCH_KEYWORDS"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
