---
description: Plan a safe service upgrade through the Swarm test cluster
argument-hint: <service> from <old_version> to <new_version>
---

## Research phase

Spawn **upgrade-scout** to analyse:
1. Current version of `$ARGUMENTS` service in service_catalog
2. Skills in modules/ that have compat.service matching this service
3. Known breaking changes in knowledge_base for this version jump
4. Swarm service state — is it currently deployed?

## Write upgrade plan to `state/plans/PLAN-upgrade-$ARGUMENTS.md`

```markdown
# Upgrade Plan: $ARGUMENTS
Date: <timestamp>
Status: pending

## Version jump
From: <current_version>
To: <target_version>
Service: <service_name>
Swarm service: hp1_<service>

## Skills at risk
<table: skill_name | compat.api_version_built_for | risk>

## Known breaking changes
<from upgrade-scout — list API changes that affect skills>

## Pre-upgrade checklist
- [ ] Swarm cluster healthy: 3 managers ready, 3 workers ready
- [ ] Current version deployed and skills verified working
- [ ] Checkpoint saved: POST /api/agent/checkpoint

## Upgrade steps
1. [ ] Deploy OLD version to swarm (baseline)
   `docker service update --image <image>:<old_tag> hp1_<service>`
2. [ ] Run affected skills — confirm they pass
   <list specific skills to test>
3. [ ] HUMAN APPROVES upgrade
4. [ ] Update to NEW version
   `docker service update --image <image>:<new_tag> hp1_<service>`
5. [ ] Monitor rollout: `docker service ps hp1_<service>`
6. [ ] Run affected skills again — note any failures
7. [ ] If failures: trigger skill regen via agent
   POST /api/agent/run { "task": "regenerate skills for <service> <new_version>" }
8. [ ] If unrecoverable: rollback
   `docker service rollback hp1_<service>`
9. [ ] Document outcome in knowledge_base

## Rollback command
`docker service rollback hp1_<service>`

## Success criteria
All skills in "Skills at risk" return status: ok after upgrade.

## Session split
Session 1: Deploy old version + baseline skill verification
Session 2: Upgrade + skill testing + regen if needed
```
