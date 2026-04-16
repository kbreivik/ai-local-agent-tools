# CC PROMPT — v2.31.9 — feat(templates): reboot_proxmox_vm agent task template

## What this does
Codifies the worker-03 recovery workflow into a first-class agent task template
so an operator can run "reboot worker-03" with one button-press and get a plan
that: verifies the VM is the intended target, reboots via Proxmox API, waits
for SSH to return, reports back. This is the first concrete template that
follows the pattern from the architecture review — the rest (drain_swarm_node,
diagnose_kafka_under_replicated, etc.) can follow the same shape.

Scope: a pre-fillable task template with deterministic tool sequence,
blast-radius tagging, and integration into the CommandPanel Templates strip
(shipped in v2.16.1).

Two changes:
1. **NEW** `api/agents/task_templates/reboot_proxmox_vm.py` — template definition
2. **EDIT** `api/agents/task_templates/__init__.py` (or the existing registry
   file that v2.16.1 set up) — register the new template

---

## Pre-flight — inspect the existing template registry

Before writing Change 1, open the file that v2.16.1 shipped for agent task
templates. Most likely at `api/agents/task_templates/__init__.py` or a
similar registry module referenced from `gui/src/components/CommandPanel.jsx`.

If templates today are just prompt strings keyed by name, the new template
should follow that exact shape. If templates are objects with fields like
`{id, label, prompt_text, category}`, match that.

**The goal:** the new template should appear in the existing "TEMPLATES" chip
strip next to `Docker`, `Kafka`, `Proxmox`, `Swarm` etc. (visible in the
user's screenshot) under the label **"Reboot Proxmox VM"**.

If the existing v2.16.1 system is purely prompt-string-based, this prompt
just needs to add a curated prompt that steers the agent correctly — see
Change 1 below. If it supports structured fields, use them.

---

## Change 1 — api/agents/task_templates/reboot_proxmox_vm.py — NEW FILE

```python
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
```

---

## Change 2 — register the template

Inspect the existing template registry (likely `api/agents/task_templates/__init__.py`
or whatever v2.16.1 created). Add an import + registration for the new
template.

Pattern — adapt to the existing registry shape:

```python
from api.agents.task_templates import reboot_proxmox_vm

TEMPLATES["reboot_proxmox_vm"] = reboot_proxmox_vm.TEMPLATE
```

Or if the registry auto-discovers modules, just dropping the new file in
the directory is sufficient — verify by reading the existing registry code
before modifying.

---

## Change 3 — verify the chip appears in CommandPanel

After the backend changes, the frontend `CommandPanel.jsx` should already
render the new chip automatically if it reads the template list from an
existing endpoint (v2.16.1 shipped that wiring). If not, the chip strip
in the screenshot is hardcoded — in that case, edit
`gui/src/components/CommandPanel.jsx` and add `"Reboot Proxmox VM"` to
wherever the chip labels are defined.

No frontend change is needed beyond that — clicking the chip fills the
task box with the rendered `prompt_template`.

---

## Commit
```
git add -A
git commit -m "feat(templates): v2.31.9 reboot_proxmox_vm task template"
git push origin main
```

---

## How to test

1. **Template appears** — open Commands panel, confirm a "Reboot Proxmox VM"
   chip exists in the Templates strip.

2. **Click fills the task** — clicking the chip populates the task input with
   the template text (either raw with `{target}` for manual edit, or a
   prompt for the VM name depending on what v2.16.1 supports).

3. **End-to-end dry run** — with worker-03 still Down from the original
   issue, run the template with `{target}` = `worker-03`. Expect:
   - `plan_action` modal appears with the five steps listed
   - On approve, `proxmox_vm_power` fires
   - The agent polls `vm_exec uptime` every ~10s
   - SSH returns within 180s
   - `swarm_node_status` shows worker-03 back as Ready
   - `kafka_broker-3` self-schedules (visible in a later dashboard refresh)

4. **Audit trail** — Logs → Actions tab should show the full sequence with
   `was_planned: true` on `proxmox_vm_power` and blast_radius=`node`.

5. **Negative test** — run the template with `{target}` = `worker-99`
   (doesn't exist). Step 1 should halt with "VM not found"; no destructive
   calls should fire.
