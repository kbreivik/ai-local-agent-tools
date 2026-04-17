"""Tests for agent task templates registry."""


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
