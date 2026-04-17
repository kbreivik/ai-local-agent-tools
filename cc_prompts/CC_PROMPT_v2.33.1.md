# CC PROMPT — v2.33.1 — drain_swarm_node task template

## What this does
Adds a `drain_swarm_node` agent task template that cleanly drains a Swarm worker
before reboot/maintenance. Sequence: verify node → drain → poll until task count
reaches zero → return timeline. Surfaces in CommandPanel dropdown under the
"SWARM" group. Uses the existing plan_action gate (blast radius = node).

Version bump: 2.33.0 → 2.33.1

## Change 1 — api/agents/task_templates.py — add template

Find the existing `TASK_TEMPLATES` list/dict (where `reboot_proxmox_vm` from
v2.31.9 lives). Append:

```python
{
    "name": "drain_swarm_node",
    "label": "Drain Swarm Node",
    "group": "SWARM",
    "agent_type": "execute",
    "inputs": [
        {"name": "node_name", "label": "Node name", "placeholder": "ds-docker-worker-03", "required": True},
        {"name": "timeout_s",   "label": "Poll timeout (s)", "default": 120, "type": "number"},
    ],
    "prompt_template": (
        "Drain Swarm node {node_name} cleanly.\n\n"
        "STEP 1: Call swarm_node_status to confirm the node exists and is currently "
        "Active. If it's already Drain or Down, report and stop.\n"
        "STEP 2: Propose a plan_action with these commands (must run from a manager "
        "node): `docker node update --availability drain {node_name}`.\n"
        "STEP 3: After plan is approved and executed, poll `docker node ps {node_name} "
        "--filter desired-state=running` every 10 seconds up to {timeout_s} seconds "
        "until the running task count is 0.\n"
        "STEP 4: Return a structured summary:\n"
        "  NODE: <name>\n"
        "  AVAILABILITY: drain\n"
        "  TASKS_SHED: <count>\n"
        "  ELAPSED_S: <seconds>\n"
        "  STATUS: DRAINED | TIMEOUT\n"
    ),
    "blast_radius": "node",
    "destructive": True,
}
```

## Change 2 — gui/src/components/CommandPanel.jsx — expose in dropdown

Find where templates are grouped/listed. If there's an existing SWARM group,
insert the new entry. If templates are auto-populated from the backend API,
no frontend changes needed beyond ensuring the group "SWARM" displays in the
group order — check the existing GROUP_ORDER / groupLabels constants.

If templates are hard-coded in the component, mirror the template object
above into the expected JSX shape.

## Change 3 — api/routers/agent.py — ensure template preserves plan_action

Check the template → agent invocation path. The existing `reboot_proxmox_vm`
already triggers plan_action correctly; the new template must inherit the same
behavior because `agent_type: "execute"` + `destructive: True` routes through
the same gate. Verify by reading the template execution handler (usually in
`api/routers/agent.py::run_template` or similar). No code change expected if
the handler is generic — only confirm.

## Change 4 — tests — add basic dispatch test

`tests/test_task_templates.py` — add:

```python
def test_drain_swarm_node_template_shape():
    from api.agents.task_templates import TASK_TEMPLATES
    t = next((x for x in TASK_TEMPLATES if x["name"] == "drain_swarm_node"), None)
    assert t is not None
    assert t["agent_type"] == "execute"
    assert t["destructive"] is True
    assert t["blast_radius"] == "node"
    assert any(i["name"] == "node_name" for i in t["inputs"])
```

## Version bump
Update `VERSION`: 2.33.0 → 2.33.1

## Commit
```
git add -A
git commit -m "feat(templates): v2.33.1 drain_swarm_node task template (Swarm group)"
git push origin main
```

## How to test after push
1. Redeploy.
2. Open Agent panel → task dropdown → SWARM → drain_swarm_node.
3. Enter node=ds-docker-worker-03, timeout=120.
4. Run → verify plan_action modal shows the exact `docker node update --availability drain`.
5. Approve → verify poll loop runs and returns DRAINED (or TIMEOUT).
