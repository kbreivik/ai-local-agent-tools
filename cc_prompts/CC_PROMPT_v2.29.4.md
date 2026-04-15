# CC PROMPT — v2.29.4 — fix(agent): kafka_consumer_lag mandatory + Swarm Shutdown events normal

## What this does
Two targeted agent prompt fixes in api/agents/router.py:

**Fix 1 — kafka_consumer_lag never called:**
`kafka_broker_status` MCP tool only checks broker connectivity — it returns "Kafka healthy:
3 brokers" even when consumer lag is the degradation cause. The previous TRIAGE step relied
on kafka_broker_status message field, which had no lag info.
Fix: Make BOTH `kafka_broker_status` AND `kafka_consumer_lag` mandatory first calls for any
Kafka degradation investigation. Lag and broker health are independent — either can cause
degradation; both must be checked.

**Fix 2 — Swarm Shutdown events misread as failures:**
Agent called service_placement on all 3 brokers, saw "5 failed/other — issues: worker-01
Shutdown 26 hours ago" and concluded Swarm is "repeatedly restarting Kafka broker tasks".
These Shutdown events are NORMAL Swarm lifecycle — old tasks are killed when Swarm replaces
them (during updates, node reboots, or convergence). Every service accumulates Shutdown
records. This is not a problem.
Fix: Add explicit rule that service_placement Shutdown history records are normal, not failures.

Version bump: 2.29.3 → 2.29.4

---

## Change 1 — api/agents/router.py: update RESEARCH_PROMPT Kafka triage

### 1a — Replace STEP 0 triage to call both tools

FIND (exact — in RESEARCH_PROMPT):
```
5c. KAFKA DEGRADATION TRIAGE — ALWAYS follow this order first:

STEP 0 — TRIAGE (always do this first, before any other Kafka tool):
  Call kafka_broker_status(). Read the 'message' field — it tells you WHY Kafka is degraded:
    • "High consumer lag: N (threshold: T)" → CONSUMER LAG PATH (see below)
    • "N/M brokers alive" or "broker N missing" → BROKER MISSING PATH (see below)
    • "Under-replicated partitions: N" → REPLICATION PATH
  Do NOT skip triage and jump to broker checks. The message field is the root cause.
```

REPLACE WITH:
```
5c. KAFKA DEGRADATION TRIAGE — ALWAYS follow this order first:

STEP 0 — MANDATORY TRIAGE (call BOTH tools before drawing any conclusions):

  IMPORTANT: kafka_broker_status checks BROKER CONNECTIVITY only. It returns "healthy"
  even when consumer lag is the degradation cause. kafka_consumer_lag is a separate check.
  They are INDEPENDENT — either or both can be the source of degradation.

  Call 1: kafka_broker_status()
    → message "N/M brokers alive" or "broker N missing" → BROKER MISSING PATH
    → message "under-replicated" → REPLICATION PATH
    → message "healthy" or no message → brokers are fine, but lag may still be the issue

  Call 2: kafka_consumer_lag()
    → if any consumer group shows high lag → CONSUMER LAG PATH
    → call this REGARDLESS of what kafka_broker_status returned

  Only after BOTH calls can you determine the degradation type.
```

### 1b — Add Swarm Shutdown events rule after the KAFKA EXEC section

FIND (exact — in RESEARCH_PROMPT, after the KAFKA EXEC commands section):
```
    TOOL NOTE: infra_lookup(query="worker-01") — param is 'query', never 'hostname'.
               run_ssh does NOT exist — use vm_exec(host=..., command=...) instead.
```

REPLACE WITH:
```
    TOOL NOTE: infra_lookup(query="worker-01") — param is 'query', never 'hostname'.
               run_ssh does NOT exist — use vm_exec(host=..., command=...) instead.

SWARM SHUTDOWN HISTORY — THESE ARE NORMAL, NOT FAILURES:
service_placement returns ALL task history including old Shutdown records. Every time Swarm
replaces a task (during updates, node reboots, or convergence), the old task is terminated
and leaves a "Shutdown" record in history. A service with 5+ Shutdown records is completely
normal — it just means the service has been updated or its nodes rebooted 5+ times.

RULE: Do NOT report "5 Shutdown events" as evidence of a problem.
RULE: Only the CURRENT task state matters — "Running N hours/days ago" = healthy.
RULE: service_placement "failed_count" counts all non-Running historical tasks.
      This number is almost always > 0 for any long-running service. Ignore it.
RULE: A real problem is: current_state is "Failed", "Rejected", or "Pending" (not Running).
      Only current_state matters. Historical Shutdown = normal orchestration lifecycle.
```

---

## Change 2 — api/agents/router.py: update STATUS_PROMPT Kafka triage similarly

FIND (exact — in STATUS_PROMPT):
```
KAFKA INVESTIGATION — TRIAGE FIRST:
When investigating Kafka health, ALWAYS read kafka_broker_status 'message' field first:
  "High consumer lag: N" → consumer lag issue (NOT a broker problem)
  "broker N missing" → missing broker (use BROKER CHAIN below)
  "under-replicated: N" → ISR issue
```

REPLACE WITH:
```
KAFKA INVESTIGATION — TRIAGE FIRST:
kafka_broker_status checks BROKER CONNECTIVITY only. kafka_consumer_lag checks consumer lag.
They are independent. ALWAYS call BOTH for any Kafka degradation investigation:

  Call 1: kafka_broker_status() → "healthy" means brokers are fine (lag may still be an issue)
  Call 2: kafka_consumer_lag()  → check independently for high consumer lag

  After both: determine degradation type:
  "High consumer lag" from kafka_consumer_lag → consumer lag issue (NOT a broker problem)
  "broker N missing" from kafka_broker_status → missing broker (use BROKER CHAIN below)
  "under-replicated" → ISR issue
```

---

## Version bump
Update VERSION: 2.29.3 → 2.29.4

## Commit
```bash
git add -A
git commit -m "fix(agent): v2.29.4 kafka_consumer_lag mandatory in triage, Swarm Shutdown events are normal"
git push origin main
```
