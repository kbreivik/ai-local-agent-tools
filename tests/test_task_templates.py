"""Tests for agent task templates registry and UI template catalogue.

Backend tests cover api/agents/task_templates.py (TASK_TEMPLATES registry).
Frontend tests (v2.35.8+) cover gui/src/components/TaskTemplates.jsx —
verifying the template catalogue is well-formed: unique labels within each
group, every task string is non-empty, no unresolved placeholders outside
parameterized templates, and each destructive template is flagged. These
run without LM Studio in milliseconds.
"""
from __future__ import annotations

import re
import pathlib


# ---------------------------------------------------------------------------
# Backend TASK_TEMPLATES registry tests
# ---------------------------------------------------------------------------

def test_drain_swarm_node_template_shape():
    from api.agents.task_templates import TASK_TEMPLATES
    t = next((x for x in TASK_TEMPLATES if x["name"] == "drain_swarm_node"), None)
    assert t is not None
    assert t["agent_type"] == "execute"
    assert t["destructive"] is True
    assert t["blast_radius"] == "node"
    assert any(i["name"] == "node_name" for i in t["inputs"])


def test_diagnose_kafka_unrepl_chain_shape():
    from api.agents.task_templates import TASK_TEMPLATES
    t = next(x for x in TASK_TEMPLATES if x["name"] == "diagnose_kafka_under_replicated")
    assert t["agent_type"] == "investigate"
    assert t["destructive"] is False
    assert "kafka_topic_inspect" in t["prompt_override"]
    assert "service_placement" in t["prompt_override"]
    assert "MISSING_BROKERS:" in t["prompt_override"]


# ---------------------------------------------------------------------------
# Frontend TaskTemplates.jsx catalogue integrity tests (v2.35.8)
# ---------------------------------------------------------------------------

TEMPLATES_PATH = (
    pathlib.Path(__file__).parent.parent
    / "gui" / "src" / "components" / "TaskTemplates.jsx"
)

# Labels that SHOULD contain parameter placeholders like {node_name}
PARAMETERIZED = {"Drain Swarm node", "Reboot Proxmox VM"}

# Destructive templates — safety scan makes sure these exist (so the test
# suite reminds operators the list is up to date) and that NOTHING called
# by a non-destructive template accidentally looks like one of these.
DESTRUCTIVE = {
    "Recover kafka_broker-3", "Force-update logstash",
    "Force-update kafka_broker-3", "Drain Swarm node",
    "Prune Docker images", "Journalctl vacuum",
    "Reboot worker-03", "Reboot Proxmox VM",
}


def _parse_templates():
    """Extract the TEMPLATES array from TaskTemplates.jsx as a flat
    list of (group, label, task) tuples. This is a line-level regex parse
    — good enough for the literal structure the file uses."""
    src = TEMPLATES_PATH.read_text(encoding="utf-8")
    # Each item block is one line per label + one task string (sometimes multiline).
    # We parse by finding `label: '...'` and the following `task: '...'` allowing
    # escaped quotes and multi-line template literals.
    items = []
    # Find all group blocks
    group_re = re.compile(r"group:\s*['\"]([^'\"]+)['\"]")
    label_re = re.compile(r"label:\s*['\"]([^'\"]+)['\"]")
    # task can be single or triple quoted; match up to the next `,\n` at brace-0 depth
    task_re  = re.compile(
        r"task:\s*(?P<q>['\"`])(?P<body>(?:\\.|(?!(?P=q)).)*)(?P=q)",
        re.DOTALL,
    )

    groups = list(group_re.finditer(src))
    for gi, gm in enumerate(groups):
        group_name = gm.group(1)
        start = gm.end()
        end = groups[gi + 1].start() if gi + 1 < len(groups) else len(src)
        block = src[start:end]
        labels = [m.group(1) for m in label_re.finditer(block)]
        tasks = [m.group("body") for m in task_re.finditer(block)]
        # Pair labels with tasks in order — TaskTemplates.jsx always interleaves.
        for label, task in zip(labels, tasks):
            items.append((group_name, label, task))
    return items


def test_templates_file_parses():
    items = _parse_templates()
    assert len(items) >= 30, f"expected >=30 templates, parsed {len(items)}"


def test_labels_unique_within_group():
    items = _parse_templates()
    by_group: dict[str, list[str]] = {}
    for grp, label, _ in items:
        by_group.setdefault(grp, []).append(label)
    for grp, labels in by_group.items():
        dupes = [l for l in labels if labels.count(l) > 1]
        assert not dupes, f"duplicate labels in {grp}: {set(dupes)}"


def test_task_strings_are_non_empty_and_substantive():
    items = _parse_templates()
    for grp, label, task in items:
        assert len(task.strip()) >= 30, \
            f"{grp}/{label} task is suspiciously short: {len(task)} chars"


def test_placeholders_only_in_parameterized_templates():
    """Templates like 'Drain Swarm node' use {node_name} — that's expected.
    Other templates should not contain unresolved placeholders."""
    items = _parse_templates()
    placeholder_re = re.compile(r"\{[a-z_]+\}")
    for grp, label, task in items:
        if label in PARAMETERIZED:
            continue
        matches = placeholder_re.findall(task)
        # Allow common non-placeholder patterns: {id1, id2} in example strings
        real_placeholders = [m for m in matches
                             if not re.search(r"\d", m)
                             and m not in {"{id1}", "{id2}"}]
        assert not real_placeholders, \
            f"{grp}/{label} has unresolved placeholders {real_placeholders!r}"


def test_known_destructive_labels_all_present():
    """If someone renames or removes a destructive template, a reviewer
    must either update DESTRUCTIVE here or mark the change deliberately."""
    items = _parse_templates()
    labels_in_file = {l for _, l, _ in items}
    missing = DESTRUCTIVE - labels_in_file
    assert not missing, (
        f"destructive templates removed without updating the test suite: "
        f"{sorted(missing)}. If the removal is intentional, prune this set."
    )


def test_non_destructive_templates_do_not_mention_plan_action():
    """Observe / investigate tasks should not pre-commit the agent to
    plan_action — that's a gate for execute-type tasks only."""
    items = _parse_templates()
    for grp, label, task in items:
        if label in DESTRUCTIVE:
            continue
        # Parameterized destructive-ish templates are OK
        if label in PARAMETERIZED:
            continue
        assert "plan_action" not in task.lower(), \
            (f"{grp}/{label} is not destructive but mentions plan_action; "
             "that gates the agent toward execute mode and wastes context.")


def test_all_hosts_templates_cite_available_vm_hosts(tmp_path=None):
    """v2.35.7 regression — any template that says 'all hosts' /
    'all VM hosts' / 'every host' must tell the agent to use the
    AVAILABLE VM HOSTS list. Otherwise the agent pulls hostnames from
    PREFLIGHT FACTS (Proxmox VM names) and burns vm_exec budget on
    errors."""
    items = _parse_templates()
    trigger_re = re.compile(r"all (?:registered )?(?:VM )?hosts?|every host", re.I)
    offenders = []
    for grp, label, task in items:
        if trigger_re.search(task):
            if ("AVAILABLE VM HOSTS" not in task and
                "list_connections" not in task and
                "infra_lookup" not in task):
                offenders.append(f"{grp}/{label}")
    assert not offenders, (
        f"templates mentioning 'all hosts' but not citing the authoritative "
        f"host source: {offenders}. Add an instruction to use AVAILABLE VM "
        "HOSTS / list_connections / infra_lookup — see v2.35.7 for the "
        "exact wording used elsewhere."
    )
