"""Recover Worker Node — composite execute template.

Full worker-node recovery sequence: reboot the Proxmox VM, wait for the Swarm
node to rejoin, force-update under-replicated services that were scheduled on
that node, and verify Kafka ISR if a kafka_broker lived there. First template
that chains verification as part of the template itself rather than relying on
v2.32.2's post-action verify on a single tool.
"""

_RECOVER_WORKER_NODE_PROMPT = """\
You are recovering a Swarm worker node. Follow this exact sequence and do not
improvise tool calls outside of it.

STEP 1 - PRE-CHECK:
  Call swarm_node_status(node_name={node_name}).
  If node is already Ready AND has >0 running tasks, abort with final_answer:
    "Node already healthy - no action needed."
  If node does not exist in the swarm, abort with final_answer: "Node not found."

STEP 2 - SERVICE INVENTORY (before reboot):
  Call service_placement(node={node_name}) - capture which services were
  scheduled on this node. You will need this list in STEP 5.
  Record whether any of them is a kafka_broker.

STEP 3 - REBOOT:
  Call plan_action with:
    tool: proxmox_vm_power
    args: {{vm_label: {proxmox_vm_label}, action: reboot}}
  After plan is confirmed, execute.

STEP 4 - WAIT FOR READY:
  Poll swarm_node_status(node_name={node_name}) every 15 seconds.
  Stop when node state is Ready OR {ready_timeout_s} seconds have elapsed.
  If timeout, final_answer: "Node did not rejoin cluster within {ready_timeout_s}s - escalate."

STEP 5 - SERVICE RESCHEDULE:
  For each service from STEP 2 that shows 0 running tasks in the current
  swarm state, call swarm_service_force_update(service_name=<name>).
  Wait 10 seconds between calls.

STEP 6 - VERIFY:
  Call swarm_node_status(node_name={node_name}) - confirm running_tasks > 0.
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


TEMPLATE = {
    "id":          "recover_worker_node",
    "name":        "recover_worker_node",
    "label":       "Recover Worker Node",
    "category":    "swarm",
    "group":       "SWARM",
    "agent_type":  "execute",
    "description": (
        "Reboot a Proxmox VM hosting a Swarm worker, wait for it to rejoin "
        "the cluster, force-update any under-replicated services scheduled "
        "there, and verify Kafka ISR if a kafka_broker was on the node."
    ),
    "inputs": [
        {
            "key": "node_name",
            "name": "node_name",
            "label": "Swarm node name",
            "placeholder": "ds-docker-worker-03",
            "required": True,
        },
        {
            "key": "proxmox_vm_label",
            "name": "proxmox_vm_label",
            "label": "Proxmox VM label",
            "placeholder": "ds-docker-worker-03",
            "required": True,
            "hint": "Label of the Proxmox VM hosting this Swarm node.",
        },
        {
            "key": "ready_timeout_s",
            "name": "ready_timeout_s",
            "label": "Ready timeout (seconds)",
            "default": 180,
            "type": "number",
            "required": False,
        },
    ],
    "blast_radius":    "node",
    "destructive":     True,
    "plan_override":   True,
    "prompt_override": _RECOVER_WORKER_NODE_PROMPT,
    "example_targets": ["ds-docker-worker-01", "ds-docker-worker-02", "ds-docker-worker-03"],
    "notes": [
        "Chains reboot + wait + service reschedule + Kafka ISR verify in one run. "
        "Closes the manual worker-03 recovery loop.",
        "Always shows the plan modal (plan_override=True) - cluster-adjacent.",
    ],
}


def get_template() -> dict:
    """Registry accessor - matches the existing task_templates pattern."""
    return TEMPLATE
