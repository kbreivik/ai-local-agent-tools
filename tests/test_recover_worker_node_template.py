"""Tests for the v2.33.18 recover_worker_node composite task template."""


def test_template_registered():
    from api.agents.task_templates import TASK_TEMPLATES
    ids = [t["id"] for t in TASK_TEMPLATES]
    assert "recover_worker_node" in ids


def test_template_required_inputs():
    from api.agents.task_templates import TASK_TEMPLATES
    t = next(x for x in TASK_TEMPLATES if x["id"] == "recover_worker_node")
    required_keys = {i["key"] for i in t["inputs"] if i.get("required")}
    assert required_keys == {"node_name", "proxmox_vm_label"}


def test_template_agent_type_is_execute():
    from api.agents.task_templates import TASK_TEMPLATES
    t = next(x for x in TASK_TEMPLATES if x["id"] == "recover_worker_node")
    assert t["agent_type"] == "execute"
    assert t["blast_radius"] == "node"
    assert t["destructive"] is True


def test_template_prompt_names_all_steps():
    from api.agents.task_templates import TASK_TEMPLATES
    t = next(x for x in TASK_TEMPLATES if x["id"] == "recover_worker_node")
    prompt = t["prompt_override"]
    for step in ["STEP 1", "STEP 2", "STEP 3", "STEP 4", "STEP 5", "STEP 6"]:
        assert step in prompt, f"missing {step}"
    assert "swarm_node_status" in prompt
    assert "proxmox_vm_power" in prompt
    assert "kafka_topic_inspect" in prompt


def test_template_execute_allowlist_has_required_tools():
    """The composite template uses these tools — execute swarm allowlist must include them."""
    from api.agents.router import EXECUTE_SWARM_TOOLS
    required = {
        "swarm_node_status",
        "service_placement",
        "proxmox_vm_power",
        "swarm_service_force_update",
        "kafka_topic_inspect",
    }
    missing = required - set(EXECUTE_SWARM_TOOLS)
    assert not missing, f"EXECUTE_SWARM_TOOLS missing: {missing}"
