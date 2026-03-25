---
description: Compress session context when utilisation exceeds 60%
argument-hint: <what to keep focus on>
---

Before compacting, write critical state:
1. Run `/handoff` to capture to state/HANDOFF.md
2. If skill code is partially written: save draft to state/drafts/<skill_name>.py
3. If Docker build is in flight: note the build tag in HANDOFF.md

Compact with these priorities:

PRESERVE:
- Current task objective
- Skill name and SKILL_META being worked on
- Errors encountered and their resolutions
- Active plan file path
- Any env vars / vault keys identified as needed
- Docker build tag if a build is in progress

DISCARD:
- Full API response bodies (already acted upon)
- Ansible/Terraform output from hp1-infra (separate project)
- Full file contents read during exploration (files still on disk)
- Repeated curl health check outputs
- Skill module file contents already saved to disk
- Docker build logs after successful build

Focus: $ARGUMENTS

After compacting, read state/HANDOFF.md to re-anchor.
