# CC PROMPT — v2.45.9 — fix(agent): ACTION_PROMPT — structural fix for plan_action escape + don't-ask-if-specified examples

## Root cause

All 4 action soft-fails share the same pattern despite v2.45.7 adding rules:
  research → clarifying_question → audit_log → done (no plan_action)

Two distinct sub-problems:

**A. Agent asks clarifying_question when task already has all details.**
  - drain-01: "drain node 0sj1zr8f1pcm" — node ID is IN the task
  - activate-01: "restore node 0sj1zr8f1pcm" — node ID is IN the task
  - rollback-01: "rollback kafka-stack_kafka1 to previous version" — service is IN the task
  - upgrade-01: "upgrade workload-stack_workload to nginx:1.27-alpine" — all details specified
  Abstract rule "If user already specified all needed details: NEVER ask" is ignored.
  Needs concrete examples of when NOT to ask.

**B. After clarifying_question(), agent calls audit_log instead of plan_action.**
  The v2.45.7 rules say "NEVER call audit_log after clarifying_question" but
  the model treats audit_log as a safe "document findings and exit" tool.
  The rule needs a concrete consequence: audit_log before plan_action is invalid.

Fix: two additions to ACTION_PROMPT in api/agents/router.py.

Version bump: 2.45.8 → 2.45.9.

---

## Change — `api/agents/router.py` — ACTION_PROMPT only

### Addition 1: Concrete "do NOT ask" examples in CLARIFICATION RULES

Find the CLARIFICATION RULES section. After the line:
```
- If user already specified all needed details: NEVER ask
```

Add:
```
  Examples of tasks that already have all details — NEVER ask clarifying_question:
  ✗ WRONG: task="drain node abc123" → asks "which node?"
  ✓ RIGHT: task="drain node abc123" → swarm_node_status() → plan_action(node_id="abc123")

  ✗ WRONG: task="restore node abc123 to active" → asks "which node?"
  ✓ RIGHT: task="restore node abc123 to active" → swarm_node_status() → plan_action(node_id="abc123")

  ✗ WRONG: task="rollback kafka-stack_kafka1 to previous version" → asks "which service?"
  ✓ RIGHT: task="rollback kafka-stack_kafka1 to previous version" → service_version_history() → plan_action(...)

  ✗ WRONG: task="upgrade workload-stack_workload to nginx:1.27-alpine" → asks "which version?"
  ✓ RIGHT: task="upgrade workload-stack_workload to nginx:1.27-alpine" → pre_upgrade_check() → plan_action(...)
```

### Addition 2: Concrete audit_log constraint after the ⚠ CRITICAL block

Find the existing ⚠ CRITICAL block (the one added in v2.45.7):
```
⚠ CRITICAL: audit_log() is NOT a substitute for plan_action(). If you have
   gathered enough information and the task requires a destructive action,
   call plan_action() immediately — do NOT call audit_log() first.
```

Replace it with:
```
⚠ CRITICAL: audit_log() is NOT a substitute for plan_action(). If you have
   gathered enough information and the task requires a destructive action,
   call plan_action() immediately — do NOT call audit_log() first.

⚠ CRITICAL: audit_log() is ONLY valid AFTER plan_action() has returned
   approved=True AND the execution tools have run. Calling audit_log()
   before plan_action() is incorrect — it documents nothing real and
   WILL be flagged as a test failure. If you find yourself about to call
   audit_log() without having called plan_action(), STOP and call plan_action()
   instead.

   The only valid action task completion sequence is:
   [pre-checks] → plan_action(approved=True) → [execute tool] → audit_log()
   
   Any deviation from this sequence (audit_log without plan_action, escalate
   after clarification, done with no plan) is an execution failure.
```

---

## Version bump

Update `VERSION`: `2.45.8` → `2.45.9`

---

## Commit

```
git add -A
git commit -m "fix(agent): v2.45.9 ACTION_PROMPT — concrete don't-ask examples + audit_log constraint"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
