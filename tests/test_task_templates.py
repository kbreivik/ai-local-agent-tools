"""Tests for agent task templates registry."""


def test_drain_swarm_node_template_shape():
    from api.agents.task_templates import TASK_TEMPLATES
    t = next((x for x in TASK_TEMPLATES if x["name"] == "drain_swarm_node"), None)
    assert t is not None
    assert t["agent_type"] == "execute"
    assert t["destructive"] is True
    assert t["blast_radius"] == "node"
    assert any(i["name"] == "node_name" for i in t["inputs"])
