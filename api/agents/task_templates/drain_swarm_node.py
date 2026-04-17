"""Drain Swarm Node — curated task template.

Cleanly drains a Swarm worker before reboot/maintenance. Sequence:
verify node → drain → poll until task count reaches zero → return timeline.
Uses the existing plan_action gate (blast radius = node).
"""

TEMPLATE = {
    "id":          "drain_swarm_node",
    "name":        "drain_swarm_node",
    "label":       "Drain Swarm Node",
    "category":    "swarm",
    "group":       "SWARM",
    "agent_type":  "execute",
    "blast_radius": "node",
    "destructive": True,
    "inputs": [
        {"name": "node_name", "label": "Node name", "placeholder": "ds-docker-worker-03", "required": True},
        {"name": "timeout_s", "label": "Poll timeout (s)", "default": 120, "type": "number"},
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
    "example_targets": ["ds-docker-worker-01", "ds-docker-worker-02", "ds-docker-worker-03"],
    "notes": [
        "Reverses with: docker node update --availability active <node_name>. "
        "Use after maintenance completes so the node receives tasks again.",
        "Pair with reboot_proxmox_vm for drain-reboot-activate flow on Swarm workers "
        "that host stateful services (Kafka brokers, Elasticsearch nodes).",
    ],
}


def get_template() -> dict:
    """Registry accessor — matches the existing task_templates pattern."""
    return TEMPLATE
