# CC PROMPT — v2.45.17 — refactor(agent): extract _stream_agent setup into pipeline functions

## What this does

`_stream_agent` is 975 lines. It builds up system_prompt and runs the agent loop
but all the setup logic is inline. Extract into pipeline functions:

**New module: `api/agents/pipeline.py`** — setup helpers for _stream_agent:

```python
# api/agents/pipeline.py

def build_system_prompt(task: str, first_intent: str) -> str:
    """Get base prompt for intent, apply runbook injection."""

def inject_memory_history(system_prompt: str, task: str, first_intent: str) -> str:
    """Inject MuninnDB history hint if memoryEnabled and hint exists."""

def inject_prior_attempts(system_prompt: str, task: str, first_intent: str,
                          session_id: str) -> str:
    """Inject coordinator prior-attempts section if coordinatorPriorAttemptsEnabled."""

def inject_capability_hint(system_prompt: str, agent_type: str) -> str:
    """Inject capability/step-cap hint."""

def inject_facts_block(system_prompt: str, task: str, agent_type: str) -> str:
    """Inject relevant FACTS block for the task domain."""

def inject_tool_signatures(system_prompt: str, first_intent: str, domain: str) -> str:
    """Inject MCP tool signatures section."""

async def run_preflight(task: str, session_id: str, operation_id: str) -> tuple[str, str]:
    """Run preflight resolution. Returns (preflight_block, error_or_empty)."""

async def broadcast_preflight(session_id: str, operation_id: str, preflight_result) -> None:
    """Broadcast preflight WS event if clarifying_needed."""
```

`_stream_agent` becomes:

```python
async def _stream_agent(task, session_id, operation_id, owner_user="admin",
                        parent_context="", parent_session_id="", force_external=False):
    from api.agents.pipeline import (
        build_system_prompt, inject_memory_history, inject_prior_attempts,
        inject_capability_hint, inject_facts_block, inject_tool_signatures,
        run_preflight, broadcast_preflight,
    )

    first_intent = classify_task(task) or "action"
    system_prompt = build_system_prompt(task, first_intent)
    system_prompt = inject_memory_history(system_prompt, task, first_intent)

    preflight_block, _ = await run_preflight(task, session_id, operation_id)
    await broadcast_preflight(session_id, operation_id, preflight_block)

    system_prompt = inject_prior_attempts(system_prompt, task, first_intent, session_id)
    system_prompt = inject_capability_hint(system_prompt, first_intent)
    system_prompt = inject_facts_block(system_prompt, task, first_intent)
    system_prompt = inject_tool_signatures(system_prompt, first_intent, detect_domain(task))

    tools_spec = filter_tools(first_intent, detect_domain(task))
    client = _make_client()

    # External AI routing (unchanged logic)
    if force_external or _maybe_route_to_external_ai(task, first_intent):
        ...

    # Coordinator (unchanged logic)
    if should_use_coordinator(task, first_intent):
        ...

    # Main agent step
    result = await _run_single_agent_step(
        task, session_id, operation_id, owner_user,
        system_prompt=system_prompt,
        tools_spec=tools_spec,
        agent_type=first_intent,
        client=client,
    )
    ...
```

Target: `_stream_agent` ≤ 200 lines after extraction. All extracted logic
lives in `api/agents/pipeline.py`.

Version bump: 2.45.16 → 2.45.17.

---

## Implementation approach

CC: This is a large refactor — be methodical.

1. Read `_stream_agent` in full (lines ~1906–2880 in agent.py).
2. Identify each coherent setup block (runbook injection, preflight, memory
   injection, prior-attempts, capability hint, facts, tool signatures).
3. Create `api/agents/pipeline.py` with one function per block. Each function
   takes exactly the params it needs (no giant god-objects).
4. Replace each inline block in `_stream_agent` with a call to the pipeline
   function.
5. Leave the external AI routing block and coordinator routing block inline
   for now (they have complex branching that's harder to isolate safely).
6. Verify no behaviour changes — same imports, same side effects.

Critical: do NOT move any WebSocket broadcast calls into pipeline.py. Broadcasts
stay in _stream_agent or _run_single_agent_step where they're currently called.

---

## Version bump

Update `VERSION`: `2.45.16` → `2.45.17`

---

## Commit

```
git add -A
git commit -m "refactor(agent): v2.45.17 extract _stream_agent setup into api/agents/pipeline.py"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
