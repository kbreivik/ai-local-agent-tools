# CC PROMPT — v2.33.2 — diagnose_kafka_under_replicated task template

## What this does
Chains the new v2.33.0 `kafka_topic_inspect` tool with existing
`service_placement`, `swarm_node_status`, and (if Proxmox conn exists)
`proxmox_vm_power(status)` into a fixed 4-step investigation that produces
a structured RCA. Pure investigate — no mutations.

Requires v2.33.0 (kafka_topic_inspect).

Version bump: 2.33.1 → 2.33.2

## Change 1 — api/agents/task_templates.py — add template

Append to `TASK_TEMPLATES` (group KAFKA, new group if absent):

```python
{
    "name": "diagnose_kafka_under_replicated",
    "label": "Diagnose Kafka Under-Replication",
    "group": "KAFKA",
    "agent_type": "investigate",
    "inputs": [
        {"name": "topic", "label": "Topic (optional)", "required": False},
    ],
    "prompt_override": (
        "═══ FIXED INVESTIGATION CHAIN — DO NOT SKIP STEPS ═══\n"
        "\n"
        "STEP 1: kafka_topic_inspect(topic={topic!r} if {topic} else None).\n"
        "  From the result, identify partitions where isr != replicas.\n"
        "  If summary.under_replicated_partitions == 0: STOP and report HEALTHY.\n"
        "\n"
        "STEP 2: For each broker id in replicas\\isr (missing brokers), call\n"
        "  service_placement('kafka_broker-' + str(broker_id)).\n"
        "  Record which Swarm node that broker is (or isn't) placed on.\n"
        "\n"
        "STEP 3: For each node identified in step 2, call swarm_node_status and\n"
        "  report its Availability and State.\n"
        "\n"
        "STEP 4: If any node is Down, optionally call proxmox_vm_power with\n"
        "  action='status' (NOT reboot) on the matching Proxmox VM to see if it's\n"
        "  running at the hypervisor level.\n"
        "\n"
        "═══ STRICT OUTPUT SHAPE ═══\n"
        "MISSING_BROKERS: [id1, id2]\n"
        "IMPACT: <partition count> partitions on <topic(s)> under-replicated\n"
        "ROOT_CAUSE: <one sentence — node X down, broker Y stuck unscheduled, etc.>\n"
        "RESPONSIBLE_NODE: <node-name> (availability=<a>, state=<s>)\n"
        "RECOMMENDED_FIX: <one sentence — e.g. reboot VM worker-03, then kafka_broker-3 will self-schedule>\n"
    ),
    "blast_radius": "none",
    "destructive": False,
}
```

## Change 2 — api/agents/router.py — honor prompt_override

When a task template has `prompt_override`, the investigate agent should use it
AS the system prompt (with light prepend of the Role/Environment sections), not
append to the default RESEARCH_PROMPT. Find the agent-type dispatch and check if
it already supports `prompt_override`. If not:

```python
def build_system_prompt(agent_type, task_context, template=None):
    base = PROMPT_BY_TYPE[agent_type]
    if template and template.get("prompt_override"):
        # Keep Role + Environment sections; replace the body.
        role_env = _extract_sections(base, ["ROLE", "ENVIRONMENT"])
        return role_env + "\n\n" + template["prompt_override"].format(**task_context)
    return base
```

## Change 3 — gui/src/components/CommandPanel.jsx — KAFKA group

If the GROUP list doesn't include KAFKA, add it after SWARM in display order.
Otherwise just ensure the new template renders under KAFKA.

## Change 4 — tests

```python
# tests/test_task_templates.py
def test_diagnose_kafka_unrepl_chain_shape():
    from api.agents.task_templates import TASK_TEMPLATES
    t = next(x for x in TASK_TEMPLATES if x["name"] == "diagnose_kafka_under_replicated")
    assert t["agent_type"] == "investigate"
    assert t["destructive"] is False
    assert "kafka_topic_inspect" in t["prompt_override"]
    assert "service_placement" in t["prompt_override"]
    assert "MISSING_BROKERS:" in t["prompt_override"]
```

## Version bump
Update `VERSION`: 2.33.1 → 2.33.2

## Commit
```
git add -A
git commit -m "feat(templates): v2.33.2 diagnose_kafka_under_replicated fixed 4-step RCA"
git push origin main
```

## How to test after push
1. Redeploy.
2. Agent panel → templates → KAFKA → diagnose_kafka_under_replicated.
3. Leave topic empty → Run.
4. Expect output in strict MISSING_BROKERS / IMPACT / ROOT_CAUSE / RESPONSIBLE_NODE / RECOMMENDED_FIX shape in ≤6 tool calls.
5. Re-run — output should name the same node/fix (determinism check).
