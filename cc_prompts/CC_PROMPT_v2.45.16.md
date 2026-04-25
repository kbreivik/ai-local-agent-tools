# CC PROMPT — v2.45.16 — refactor(agent): split dispatch_tool_calls into category handlers

## What this does

`api/agents/step_tools.py` has one function `dispatch_tool_calls` at 1165 lines —
a single giant `elif` chain handling every tool by name. This makes it hard to
read, test, or extend. Split into category handler functions, keeping
`dispatch_tool_calls` as a thin router (≤80 lines).

New private functions inside step_tools.py:

- `_handle_lifecycle_tools(fn_name, fn_args, ...)` — plan_action, audit_log,
  escalate, clarifying_question, propose_subtask (the flow-control tools)
- `_handle_kafka_tools(fn_name, fn_args, ...)` — kafka_broker_status,
  kafka_topic_health, kafka_consumer_lag, kafka_exec, kafka_rolling_restart_safe,
  pre_kafka_check, kafka_topic_inspect, kafka_topic_list
- `_handle_swarm_tools(fn_name, fn_args, ...)` — swarm_status, service_list,
  service_health, service_current_version, service_version_history,
  service_upgrade, service_rollback, node_drain, node_activate,
  swarm_node_status, swarm_service_force_update
- `_handle_elastic_tools(fn_name, fn_args, ...)` — elastic_cluster_health,
  elastic_index_stats, elastic_search_logs, elastic_error_logs,
  elastic_log_pattern, elastic_kafka_logs, elastic_correlate_operation
- `_handle_memory_tools(fn_name, fn_args, ...)` — skill_search, skill_create,
  skill_regenerate, skill_disable, skill_enable, skill_import,
  runbook_search, checkpoint_save, checkpoint_restore
- `_handle_infra_tools(fn_name, fn_args, ...)` — vm_exec, infra_lookup,
  resolve_entity, entity_history, entity_events, get_host_network,
  result_fetch, result_query
- `_handle_misc_tools(fn_name, fn_args, ...)` — everything else / fallback

Each handler returns a `result` dict or raises `NotImplementedError` if the
tool name is not in its category (so dispatch_tool_calls can chain them).

`dispatch_tool_calls` becomes:

```python
async def dispatch_tool_calls(tc, step, messages, ...):
    for tool_call in tc.tool_calls or []:
        fn_name = tool_call.function.name
        fn_args = json.loads(tool_call.function.arguments or "{}")

        result = None
        for handler in [
            _handle_lifecycle_tools,
            _handle_kafka_tools,
            _handle_swarm_tools,
            _handle_elastic_tools,
            _handle_memory_tools,
            _handle_infra_tools,
            _handle_misc_tools,
        ]:
            try:
                result = await handler(fn_name, fn_args, ...)
                break
            except NotImplementedError:
                continue

        if result is None:
            result = {"status": "error", "error": f"Unknown tool: {fn_name}"}

        # existing broadcast + message append logic
        ...
```

The broadcast logic (send_tool_result to WebSocket, append to messages,
record to DB) stays at the bottom of dispatch_tool_calls — it's shared
across all tools and should NOT be duplicated into handlers.

Version bump: 2.45.15 → 2.45.16.

---

## Implementation approach

CC: This is a large refactor. The key constraint is: DO NOT change any tool
behaviour — only reorganise the code. Each handler must call the exact same
underlying functions as the current elif chain.

Steps:
1. Read the current dispatch_tool_calls fully.
2. Group the elif branches by category (lifecycle/kafka/swarm/elastic/memory/infra).
3. Extract each group into a private async function.
4. Replace the elif chain with the handler loop.
5. Keep broadcast/message logic at the bottom of dispatch_tool_calls.
6. Run a quick syntax check.

The function signatures for each handler should match:
```python
async def _handle_X_tools(
    fn_name: str,
    fn_args: dict,
    state,
    session_id: str,
    operation_id: str,
    task: str,
    agent_type: str,
    messages: list,
    step: int,
) -> dict:
    """Handle X-category tool calls. Raises NotImplementedError if fn_name not in category."""
```

---

## Version bump

Update `VERSION`: `2.45.15` → `2.45.16`

---

## Commit

```
git add -A
git commit -m "refactor(agent): v2.45.16 split dispatch_tool_calls into category handlers"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
