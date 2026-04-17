"""Diagnose Kafka Under-Replication — curated investigate template.

Chains the v2.33.0 `kafka_topic_inspect` tool with `service_placement`,
`swarm_node_status`, and (optionally) `proxmox_vm_power(status)` into a
fixed 4-step investigation that produces a structured RCA. Pure investigate
— no mutations.
"""

TEMPLATE = {
    "id":          "diagnose_kafka_under_replicated",
    "name":        "diagnose_kafka_under_replicated",
    "label":       "Diagnose Kafka Under-Replication",
    "category":    "kafka",
    "group":       "KAFKA",
    "agent_type":  "investigate",
    "blast_radius": "none",
    "destructive": False,
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
    "example_targets": ["hp1-logs"],
    "notes": [
        "Pure investigate — no mutations. Pair with reboot_proxmox_vm or "
        "drain_swarm_node if the recommended fix requires a node-level action.",
        "Requires v2.33.0 (kafka_topic_inspect).",
    ],
}


def get_template() -> dict:
    """Registry accessor — matches the existing task_templates pattern."""
    return TEMPLATE
