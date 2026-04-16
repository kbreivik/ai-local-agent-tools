"""Reboot Proxmox VM — curated task template.

Usage: the operator types/selects the VM name (e.g. `worker-03`) and the
agent runs a fixed tool sequence. No freeform LLM exploration — the prompt
hard-steers the model to the right calls.
"""

TEMPLATE = {
    "id":          "reboot_proxmox_vm",
    "label":       "Reboot Proxmox VM",
    "category":    "proxmox",
    "agent_type":  "execute",
    "blast_radius": "node",
    # The `{target}` token is substituted with the user's input when the
    # template is selected in the UI. If the UI doesn't support params yet,
    # the user edits the prompt inline before running.
    "prompt_template": """Reboot the Proxmox VM named `{target}`.

Required sequence — do NOT skip or reorder:

1. Call `infra_lookup` with `{target}` to confirm the VM exists and capture
   its node placement and entity_id. If it doesn't exist, stop and report.
2. Call `swarm_node_status` (if `{target}` looks like a Swarm node label)
   to record its pre-reboot state. If it's not a Swarm member, skip this.
3. Call `plan_action` with:
      summary: "Reboot VM {target} via Proxmox API"
      steps:
        - "Confirm target: {target} exists"
        - "(If Swarm worker) drain optionally — skipped unless user asks"
        - "Send Proxmox reboot command"
        - "Wait up to 180s for SSH on {target}"
        - "Report final status"
      risk_level: "medium"
      reversible: true
4. After plan approval: call `proxmox_vm_power` with vm_label={target},
   action="reboot".
5. Poll `vm_exec` with a harmless command ("uptime") against {target}
   every 10s until it returns successfully or 180s elapses. Use small
   repeated calls — do not sleep in one call.
6. When SSH returns, call `swarm_node_status` again (if applicable) to
   confirm the node re-joined the cluster with status=Ready.
7. Summarise:
      - Whether reboot succeeded
      - Wall-clock time from reboot command to SSH return
      - Any Swarm tasks that rescheduled
      - Any kafka broker that came back (if {target} ran one)

Do not use vm_exec for anything except the post-reboot liveness poll.
Do not touch other VMs.""",
    "example_targets": ["worker-03", "worker-01", "worker-02",
                        "manager-01", "manager-02", "manager-03"],
    "notes": [
        "Kafka recovery path: if {target} hosts a kafka_broker Swarm task, "
        "the broker will self-schedule on boot. No manual kafka restart needed.",
        "This template does NOT drain the node before reboot. For managers "
        "or workers with long-running stateful services, drain first via the "
        "drain_swarm_node template (shipped separately).",
    ],
}


def get_template() -> dict:
    """Registry accessor — matches whatever lookup pattern the existing
    templates use. If v2.16.1 uses a different accessor name, rename this
    function to match."""
    return TEMPLATE
