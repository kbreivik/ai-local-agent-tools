"""Agent task templates — curated, deterministic tool sequences.

Each template module exports a TEMPLATE dict with id, label, category,
agent_type, blast_radius, prompt_template, example_targets, and notes.

Registry pattern: import each template module and register its TEMPLATE
dict keyed by id. The frontend reads these via the TaskTemplates component;
the backend can use them to pre-fill agent runs.
"""

from api.agents.task_templates import reboot_proxmox_vm
from api.agents.task_templates import drain_swarm_node
from api.agents.task_templates import diagnose_kafka_under_replicated

TEMPLATES: dict[str, dict] = {}

TEMPLATES[reboot_proxmox_vm.TEMPLATE["id"]] = reboot_proxmox_vm.TEMPLATE
TEMPLATES[drain_swarm_node.TEMPLATE["id"]] = drain_swarm_node.TEMPLATE
TEMPLATES[diagnose_kafka_under_replicated.TEMPLATE["id"]] = diagnose_kafka_under_replicated.TEMPLATE


TASK_TEMPLATES: list[dict] = [
    {**t, "name": t.get("name", t.get("id"))} for t in TEMPLATES.values()
]


def get_all_templates() -> dict[str, dict]:
    """Return all registered templates."""
    return TEMPLATES


def get_template(template_id: str) -> dict | None:
    """Look up a single template by id."""
    return TEMPLATES.get(template_id)
