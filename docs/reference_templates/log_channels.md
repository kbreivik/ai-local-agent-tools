DEATHSTAR has five distinct log destinations. Knowing which goes where saves
time when debugging — tailing the wrong stream returns nothing.

| Log marker / source | Destination | How to read |
|---|---|---|
| Python `log.info`/`log.warning`/`log.debug` calls | Container stdout | `docker logs hp1_agent --since Xh` |
| `manager.send_line(...)` and `manager.broadcast(...)` | `operation_log` PG table + WS | `SELECT ... FROM operation_log WHERE session_id=...` OR live tail in GUI Output panel. **NOT in container stdout.** |
| `[harness]`, `[step]`, `[clarify→plan]`, `[budget]`, `[plan]`, `[safety]`, `[clarification]`, `[lock]`, `[subagent]`, `[blackout]`, `[fact_age]` | `operation_log` (via `manager.send_line`) | Same as above. Searching `docker logs` for these will return zero results. |
| Tool calls (params + result) | `tool_calls` PG table | `SELECT ... FROM tool_calls WHERE operation_id=...` |
| LLM rounds (messages + response) | `agent_llm_traces` PG table | Trace tab in the GUI, or query `agent_llm_traces` joined to `operations` |
| Prometheus metrics | `/metrics` HTTP endpoint (auth-gated since v2.45.21) | `curl http://localhost:8000/metrics` requires Bearer token. Counters only appear AFTER first `.inc()`. |

## Common pitfalls

- **`docker logs` shows nothing useful for agent runs.** The agent emits via `manager.send_line` which goes to `operation_log`, not stdout. Container logs only carry framework messages, exceptions, and Python `log.*` calls.
- **An empty `/metrics | grep counter_name`** can mean: counter never `.inc()`'d (silent), OR endpoint is 401-gated (no body). Distinguish by `curl -sv http://localhost:8000/metrics 2>&1 | grep '^< HTTP'`.
- **`operation_log.session_id` ≠ `operations.id`.** Join via `session_id`, not `id`.
- **`operations.label` carries the user task text, not `operations.task`.** No column named `task` exists.

## Quick reference — where each marker lives

```
[harness]         api/agents/step_tools.py + api/routers/agent.py — operation_log
[step]            api/routers/agent.py — operation_log
[clarify→plan]    api/agents/step_tools.py:_handle_clarifying_question — operation_log
[budget]          api/routers/agent.py:_run_single_agent_step — operation_log
[plan]            api/agents/step_tools.py:_handle_plan_action — operation_log
[halluc-guard]    api/agents/step_guard.py — operation_log
[external-ai]     api/routers/agent.py:_maybe_route_to_external_ai — operation_log
[safety]          api/agents/step_tools.py — operation_log
agent_start       api/routers/agent.py:_stream_agent — WS broadcast + operation_log
plan_pending      api/agents/step_tools.py:_handle_plan_action — WS broadcast + operation_log
clarification_needed  api/agents/step_tools.py:_handle_clarifying_question — WS broadcast + operation_log
done              api/routers/agent.py — WS broadcast (terminal)
escalation_recorded   api/agents/step_tools.py + api/routers/escalations.py — WS broadcast + DB
```
