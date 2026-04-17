# CC PROMPT — v2.33.18 — feat(templates): recover_worker_node composite task template

## What this does

Adds an execute-agent template that runs the full worker-node recovery sequence:
VM reboot → wait for Ready → force-update under-replicated services scheduled
on that node → verify Kafka ISR if the node was hosting a kafka_broker.

This closes the loop we've been running manually for worker-03. It's also the
first composite template that chains verification as part of the template itself
rather than relying on v2.32.2's post-action verify on one tool.

Current manual sequence for worker-03:
1. `proxmox_vm_power(vm=worker-03, action=reboot)`
2. Wait ~90s
3. `swarm_node_status` — confirm node is Ready
4. `swarm_service_force_update(kafka_broker-3)` — triggers scheduling
5. `kafka_topic_inspect` — confirm ISR has broker 3 back

Version bump: 2.33.17 → 2.33.18

---

## Change 1 — api/db/task_templates.py (or wherever BASE_TEMPLATES lives)

Add the template definition. Locate the SWARM template group (it holds
`drain_swarm_node` from v2.33.1) and add:

```python
{
    "id": "recover_worker_node",
    "name": "Recover Worker Node",
    "group": "SWARM",
    "agent_type": "execute",
    "description": (
        "Reboot a Proxmox VM hosting a Swarm worker, wait for it to rejoin "
        "the cluster, force-update any under-replicated services scheduled "
        "there, and verify Kafka ISR if a kafka_broker was on the node."
    ),
    "inputs": [
        {
            "key": "node_name",
            "label": "Swarm node name",
            "placeholder": "ds-docker-worker-03",
            "required": True,
        },
        {
            "key": "proxmox_vm_label",
            "label": "Proxmox VM label",
            "placeholder": "ds-docker-worker-03",
            "required": True,
            "hint": "Label of the Proxmox VM hosting this Swarm node.",
        },
        {
            "key": "ready_timeout_s",
            "label": "Ready timeout (seconds)",
            "default": 180,
            "required": False,
        },
    ],
    "blast_radius": "node",
    "destructive": True,
    "plan_override": True,   # always show plan modal — cluster-adjacent
    "prompt_override": _RECOVER_WORKER_NODE_PROMPT,
}
```

Add the prompt constant at module top:

```python
_RECOVER_WORKER_NODE_PROMPT = """\
You are recovering a Swarm worker node. Follow this exact sequence and do not
improvise tool calls outside of it.

STEP 1 — PRE-CHECK:
  Call swarm_node_status(node_name={node_name}).
  If node is already Ready AND has >0 running tasks, abort with final_answer:
    "Node already healthy — no action needed."
  If node does not exist in the swarm, abort with final_answer: "Node not found."

STEP 2 — SERVICE INVENTORY (before reboot):
  Call service_placement(node={node_name}) — capture which services were
  scheduled on this node. You will need this list in STEP 5.
  Record whether any of them is a kafka_broker.

STEP 3 — REBOOT:
  Call plan_action with:
    tool: proxmox_vm_power
    args: {{vm_label: {proxmox_vm_label}, action: reboot}}
  After plan is confirmed, execute.

STEP 4 — WAIT FOR READY:
  Poll swarm_node_status(node_name={node_name}) every 15 seconds.
  Stop when node state is Ready OR {ready_timeout_s} seconds have elapsed.
  If timeout, final_answer: "Node did not rejoin cluster within {ready_timeout_s}s — escalate."

STEP 5 — SERVICE RESCHEDULE:
  For each service from STEP 2 that shows 0 running tasks in the current
  swarm state, call swarm_service_force_update(service_name=<name>).
  Wait 10 seconds between calls.

STEP 6 — VERIFY:
  Call swarm_node_status(node_name={node_name}) — confirm running_tasks > 0.
  If kafka_broker was in STEP 2's inventory, call kafka_topic_inspect and
  confirm ISR is full (under_replicated_count == 0) or explicitly name any
  still-under-replicated topics.

FINAL ANSWER SHAPE:
  ACTION_TAKEN: <what you did>
  NODE_STATE: <Ready + N running tasks | Failed>
  SERVICES_RECOVERED: <list of services brought back>
  KAFKA_STATE: <ISR full | still under-replicated: <topics> | N/A>
  ESCALATION_NEEDED: <yes/no + reason>
"""
```

## Change 2 — api/agents/router.py — allowlist expansion

Ensure the execute agent type's tool allowlist includes:
- `swarm_node_status`
- `service_placement`
- `proxmox_vm_power`
- `swarm_service_force_update`
- `kafka_topic_inspect`

Most of these are already on the execute allowlist per v2.15.9 / v2.33.0.
Check that `service_placement` (v2.19.0) is explicitly listed for execute — it
was added to investigate but not necessarily execute.

## Change 3 — frontend: task template visible in CommandPanel

Templates auto-render from the backend list via v2.16.1 — no frontend code
changes expected. Verify the new template appears in the SWARM group in
CommandPanel after backend restart.

## Change 4 — tests

`tests/test_recover_worker_node_template.py`:

```python
def test_template_registered():
    from api.db.task_templates import BASE_TEMPLATES
    ids = [t["id"] for t in BASE_TEMPLATES]
    assert "recover_worker_node" in ids

def test_template_required_inputs():
    from api.db.task_templates import BASE_TEMPLATES
    t = next(t for t in BASE_TEMPLATES if t["id"] == "recover_worker_node")
    required_keys = {i["key"] for i in t["inputs"] if i.get("required")}
    assert required_keys == {"node_name", "proxmox_vm_label"}

def test_template_agent_type_is_execute():
    from api.db.task_templates import BASE_TEMPLATES
    t = next(t for t in BASE_TEMPLATES if t["id"] == "recover_worker_node")
    assert t["agent_type"] == "execute"
    assert t["blast_radius"] == "node"
    assert t["destructive"] is True

def test_template_prompt_names_all_steps():
    from api.db.task_templates import BASE_TEMPLATES
    t = next(t for t in BASE_TEMPLATES if t["id"] == "recover_worker_node")
    prompt = t["prompt_override"]
    for step in ["STEP 1", "STEP 2", "STEP 3", "STEP 4", "STEP 5", "STEP 6"]:
        assert step in prompt, f"missing {step}"
    assert "swarm_node_status" in prompt
    assert "proxmox_vm_power" in prompt
    assert "kafka_topic_inspect" in prompt
```

## Version bump
Update `VERSION`: 2.33.17 → 2.33.18

## Commit
```
git add -A
git commit -m "feat(templates): v2.33.18 recover_worker_node composite template"
git push origin main
```

## How to test after push
1. Redeploy.
2. Open CommandPanel → SWARM group → click "Recover Worker Node".
3. Fill inputs: `ds-docker-worker-03` / `ds-docker-worker-03`.
4. Submit.
5. Verify agent trace shows the 6-step sequence in order — no improvisation.
6. After worker-03 Ready + kafka_broker-3 rescheduled, confirm ISR includes broker 3.
7. Regression: existing templates (drain_swarm_node, diagnose_kafka_under_replicated) still render.
