---
description: Research and plan a new skill or agent feature before implementing
argument-hint: <describe the skill or feature>
---

## Phase 1 — Research (spawn scouts)

**skill-scout**: Check existing skills
- Are there existing skills for this service? What patterns do they use?
- What's in SKILL_META for similar skills (compat section especially)?
- What does _template.py require?

**service-scout**: Check live service state
- Is the target service running and reachable?
- What version is it? What API endpoint can be probed for live_validator?
- Does it appear in the service_catalog?

## Phase 2 — Write the plan

Write to `state/plans/PLAN-$ARGUMENTS.md`:

```markdown
# Plan: $ARGUMENTS
Date: <timestamp>
Status: pending

## Current state
<skill-scout summary>
<service-scout summary>

## What to build
Type: [ ] new skill module | [ ] new MCP tool | [ ] new API endpoint | [ ] new Vue component

### If new skill module:
File: mcp_server/tools/skills/modules/<service>_<action>.py

SKILL_META draft:
- name: <service>_<action>
- description: <one line>
- category: compute | networking | monitoring | storage | orchestration
- parameters: <dict>
- compat:
  - service: <name>
  - api_version_built_for: <version>
  - version_endpoint: <endpoint to probe>
  - version_field: <jq path to version in response>

execute() outline:
1. Read config from env/agent_settings.json
2. <core API call>
3. Return _ok/_err/_degraded

### If new MCP tool (register in server.py):
Function name: <verb_noun>
Parameters: <list>
Calls into: mcp_server/tools/<module>.py

### If API/GUI change:
Router: api/routers/<name>.py
Endpoint: <METHOD> /api/<path>
Auth required: yes/no

## Implementation steps
1. [ ] Write the module (sync, no async, _ok/_err/_degraded returns)
2. [ ] `python -m py_compile <file>` — syntax check
3. [ ] Register in server.py if MCP tool
4. [ ] Add UFW rule in hp1-infra if new port exposed
5. [ ] Test: call via API or agent commands panel
6. [ ] `/commit`

## Vault / config changes needed
<list any new env vars or vault keys needed — human sets these>

## Out of scope
<what this plan does NOT cover>
```

Do NOT write any code yet. Plan only.
