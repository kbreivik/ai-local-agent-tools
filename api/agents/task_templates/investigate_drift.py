"""Investigate Drift — curated investigate template.

Fires when a card's config_hash changed without a sanctioned agent_action
within ±60s. Walks entity_history + agent_actions to classify the source
(human SSH / external automation / delayed agent write) and recommend a
next step. Pure investigate — no mutations.
"""

TEMPLATE = {
    "id":          "investigate_drift",
    "name":        "investigate_drift",
    "label":       "Investigate Drift",
    "category":    "diagnostics",
    "group":       "DIAGNOSTICS",
    "agent_type":  "investigate",
    "blast_radius": "none",
    "destructive": False,
    "inputs": [
        {"name": "entity_id", "label": "Entity ID", "required": True},
    ],
    "prompt_template": (
        "The entity {entity_id} has drifted — its config_hash changed without "
        "a sanctioned agent_action within ±60s.\n"
        "STEP 1: Call entity_history_recent(entity_id={entity_id!r}, limit=5) to see "
        "recent snapshots with diff.\n"
        "STEP 2: Identify which metadata keys changed.\n"
        "STEP 3: Correlate with agent_actions for the same entity in a wider "
        "10-minute window — maybe the action was logged but delayed.\n"
        "STEP 4: Output:\n"
        "  DRIFT_KEYS: <comma-separated>\n"
        "  LIKELY_SOURCE: <human|automation|agent>\n"
        "  SEVERITY: <info|warn|critical>\n"
        "  SUGGESTED_ACTION: <one sentence>\n"
    ),
    "example_targets": ["swarm:kafka_broker-1", "docker:agent-01:hp1_agent"],
    "notes": [
        "Pure investigate — never mutates. Pair with a remediation template "
        "(e.g. service_upgrade rollback) if the drift is unintended.",
        "Source of truth is the drift_events view — if LIKELY_SOURCE=agent, "
        "check whether was_planned=TRUE was set on the originating action.",
    ],
}


def get_template() -> dict:
    """Registry accessor — matches the existing task_templates pattern."""
    return TEMPLATE
