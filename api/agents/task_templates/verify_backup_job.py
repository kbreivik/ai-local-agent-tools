"""Verify Backup Job — curated observe template.

PASS/FAIL check against an SLO (max age hours) for a Proxmox VM/CT's
PBS backup. Pure observe — calls pbs_last_backup only, no mutations.
"""

TEMPLATE = {
    "id":          "verify_backup_job",
    "name":        "verify_backup_job",
    "label":       "Verify Backup Job",
    "category":    "storage",
    "group":       "STORAGE",
    "agent_type":  "observe",
    "blast_radius": "none",
    "destructive": False,
    "inputs": [
        {"name": "vm_id", "label": "VM ID (e.g. 120 or qemu/120)", "required": True},
        {"name": "max_age_hours", "label": "Max age (h)", "default": 25, "type": "number"},
    ],
    "prompt_template": (
        "Call pbs_last_backup(vm_id={vm_id!r}). "
        "If status is PASS and age_hours <= {max_age_hours}, emit:\n"
        "  STATUS: PASS\n  VM: {vm_id}\n  AGE_HOURS: <n>\n  DATASTORE: <x>\n"
        "If status is FAIL or UNKNOWN or age_hours > {max_age_hours}, emit:\n"
        "  STATUS: FAIL\n  VM: {vm_id}\n  AGE_HOURS: <n>\n  REASON: <text>\n"
        "Do not call any other tool."
    ),
    "example_targets": ["120", "qemu/120", "lxc/9221"],
    "notes": [
        "Default SLO is 25h — matches typical nightly backup schedule.",
        "Backing data comes from the PBS collector, which writes "
        "cross-reference rows into infra_inventory (platform='pbs_backup').",
    ],
}


def get_template() -> dict:
    """Registry accessor — matches the existing task_templates pattern."""
    return TEMPLATE
