# CC PROMPT — v2.45.7 — fix(agent): ACTION_PROMPT — block audit_log escape, add drain/activate example

## What this does

All 4 action tests fail with the same pattern:
  research tools → clarifying_question → audit_log → done (no plan_action)

The agent uses `audit_log` as a "finish and log what I did" tool after clarifying,
never committing to `plan_action`. The ACTION_PROMPT has strong guidance on
calling plan_action but doesn't explicitly block the `clarifying_question →
audit_log → done` escape route.

Two additions to `ACTION_PROMPT` in `api/agents/router.py`:

1. Add rule under CLARIFICATION RULES: after getting an answer, the next call
   MUST be plan_action (not audit_log, not escalate, not another clarifying_question).

2. Add drain/activate examples to the WORKFLOW section so the model has a clear
   template for node operations.

Version bump: 2.45.6 → 2.45.7.

---

## Change — `api/agents/router.py` — ACTION_PROMPT

Find the CLARIFICATION RULES section (ends with "NEVER call clarifying_question()
and then call escalate() — pick one path"). Add after that line:

```
- NEVER call audit_log() after clarifying_question() — audit_log is for logging
  completed actions, not for closing out a task you haven't executed yet.
- After clarifying_question() returns an answer: if the task involves a
  destructive operation, your VERY NEXT call MUST be plan_action(). No exceptions.
```

Find the DESTRUCTIVE TOOLS — MANDATORY WORKFLOW section, specifically the two
`Example:` blocks at the end. Add two more examples after them:

```
Example: task = "drain node X for maintenance"
  → swarm_node_status() →
  → plan_action(summary="Drain node X for maintenance",
                steps=["node_drain(node_id='X')", "verify services rescheduled"],
                risk_level="medium", reversible=True) →
  → wait for approval → node_drain()

Example: task = "restore node X to active"
  → swarm_node_status() →
  → plan_action(summary="Restore node X to active",
                steps=["node_activate(node_id='X')", "verify services scheduling"],
                risk_level="low", reversible=True) →
  → wait for approval → node_activate()
```

Also add after the ⚠ CRITICAL line:
```
⚠ CRITICAL: audit_log() is NOT a substitute for plan_action(). If you have
   gathered enough information and the task requires a destructive action,
   call plan_action() immediately — do NOT call audit_log() first.
```

CC: Make surgical edits to the ACTION_PROMPT string only. Do not modify any
other prompt or any other code. The ACTION_PROMPT is at line ~1116 in
api/agents/router.py.

---

## Version bump

Update `VERSION`: `2.45.6` → `2.45.7`

---

## Commit

```
git add -A
git commit -m "fix(agent): v2.45.7 ACTION_PROMPT — block audit_log escape path, add drain/activate examples"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
