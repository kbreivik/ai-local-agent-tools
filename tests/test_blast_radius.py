def test_vm_exec_is_node():
    from api.agents.tool_metadata import radius_of
    assert radius_of("vm_exec", {"command": "uptime"}) == "node"


def test_kafka_exec_list_is_none():
    from api.agents.tool_metadata import radius_of
    assert radius_of("kafka_exec", {"command": "list topics"}) == "none"


def test_swarm_force_update_is_service():
    from api.agents.tool_metadata import radius_of
    assert radius_of("swarm_service_force_update") == "service"


def test_connection_delete_is_fleet():
    from api.agents.tool_metadata import radius_of
    assert radius_of("connection_delete") == "fleet"
