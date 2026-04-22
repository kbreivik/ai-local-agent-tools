# CC PROMPT — v2.38.6 — feat(agents): force-external-AI toggle

## What this does

Adds a "Send directly to External AI" toggle to the CommandPanel Run button
area. When active, the task bypasses the local agent loop entirely and goes
straight to the external AI (Claude/OpenAI/Grok), skipping both the router
decision and the confirmation modal. Confirmation is bypassed because the
operator explicitly chose to send it there.

Three-part change:
1. `RunRequest` gains `force_external: bool = False`
2. `_stream_agent` + `_maybe_route_to_external_ai` thread `force` through;
   when `True`, router decision is skipped and confirmation gate is bypassed
3. Frontend: amber toggle button in CommandPanel, `runAgent()` passes the flag

Version bump: 2.38.5 → 2.38.6.

---

## Change 1 — `api/routers/agent.py` — RunRequest

Locate the `RunRequest` class (line ~657):

```python
class RunRequest(BaseModel):
    task: str = Field(
        default="Perform a full infrastructure health check and report status.",
        max_length=4096,
    )
    session_id: str = Field(default="", max_length=128)
```

Replace with:

```python
class RunRequest(BaseModel):
    task: str = Field(
        default="Perform a full infrastructure health check and report status.",
        max_length=4096,
    )
    session_id: str = Field(default="", max_length=128)
    force_external: bool = Field(
        default=False,
        description="Skip local agent loop and route directly to external AI. "
                    "Bypasses router decision and confirmation modal.",
    )
```

---

## Change 2 — `api/routers/agent.py` — _maybe_route_to_external_ai signature + confirmation bypass

Locate the function signature for `_maybe_route_to_external_ai` (line ~801):

```python
async def _maybe_route_to_external_ai(
    *,
    session_id: str,
    operation_id: str,
    task: str,
    agent_type: str,
    messages: list[dict],
    tool_calls_made: int,
    tool_budget: int,
    diagnosis_emitted: bool,
    consecutive_tool_failures: int,
    halluc_guard_exhausted: bool,
    fabrication_detected_count: int,
    external_calls_this_op: int,
    scope_entity: str,
    is_prerun: bool,
    prior_failed_attempts_7d: int = 0,
) -> str | None:
    """Run the v2.36.1 router. If it fires, gate on v2.36.2 confirmation and
    call the v2.36.3 external AI. Return the synthesis text on success,
    None on no-op, or raise a sentinel-failure string via ExternalAIError.

    Caller treats a non-None return as the final_answer (REPLACE mode).
    """
```

Replace with:

```python
async def _maybe_route_to_external_ai(
    *,
    session_id: str,
    operation_id: str,
    task: str,
    agent_type: str,
    messages: list[dict],
    tool_calls_made: int,
    tool_budget: int,
    diagnosis_emitted: bool,
    consecutive_tool_failures: int,
    halluc_guard_exhausted: bool,
    fabrication_detected_count: int,
    external_calls_this_op: int,
    scope_entity: str,
    is_prerun: bool,
    prior_failed_attempts_7d: int = 0,
    force: bool = False,
) -> str | None:
    """Run the v2.36.1 router. If it fires, gate on v2.36.2 confirmation and
    call the v2.36.3 external AI. Return the synthesis text on success,
    None on no-op, or raise a sentinel-failure string via ExternalAIError.

    Caller treats a non-None return as the final_answer (REPLACE mode).

    force=True (v2.38.6): skip router decision and confirmation modal entirely.
    Operator explicitly chose external AI — treat as pre-approved.
    """
```

Now locate the block that runs the router decision (line ~820 area):

```python
    from api.agents.external_router import (
        should_escalate_to_external_ai, record_decision, RouterState,
    )
    from mcp_server.tools.skills.storage import get_backend

    try:
        _cap = int(get_backend().get_setting("routeMaxExternalCallsPerOp") or 3)
    except Exception:
        _cap = 3

    state = RouterState(
        agent_type=agent_type,
        task_text=task,
        scope_entity=scope_entity,
        tool_calls_made=tool_calls_made,
        tool_budget=tool_budget,
        diagnosis_emitted=diagnosis_emitted,
        consecutive_tool_failures=consecutive_tool_failures,
        halluc_guard_exhausted=halluc_guard_exhausted,
        fabrication_detected_count=fabrication_detected_count,
        external_calls_this_op=external_calls_this_op,
        external_calls_cap=_cap,
        prior_failed_attempts_7d=prior_failed_attempts_7d,
    )
    decision = should_escalate_to_external_ai(state, is_prerun=is_prerun)
    record_decision(decision)
    if not decision.escalate:
        return None
```

Replace with:

```python
    from api.agents.external_router import (
        should_escalate_to_external_ai, record_decision, RouterState,
    )
    from mcp_server.tools.skills.storage import get_backend

    try:
        _cap = int(get_backend().get_setting("routeMaxExternalCallsPerOp") or 3)
    except Exception:
        _cap = 3

    if force:
        # v2.38.6 — operator explicitly chose external AI; skip router.
        # Still respect per-op cap as hard safety limit.
        if external_calls_this_op >= _cap:
            await manager.send_line(
                "step",
                f"[external-ai] force=True but per-op cap reached "
                f"({external_calls_this_op}/{_cap}) — not calling external AI",
                status="warning", session_id=session_id,
            )
            return None
        try:
            from api.metrics import EXTERNAL_ROUTING_DECISIONS
            EXTERNAL_ROUTING_DECISIONS.labels(
                decision="escalated", rule="force_external",
            ).inc()
        except Exception:
            pass
    else:
        state = RouterState(
            agent_type=agent_type,
            task_text=task,
            scope_entity=scope_entity,
            tool_calls_made=tool_calls_made,
            tool_budget=tool_budget,
            diagnosis_emitted=diagnosis_emitted,
            consecutive_tool_failures=consecutive_tool_failures,
            halluc_guard_exhausted=halluc_guard_exhausted,
            fabrication_detected_count=fabrication_detected_count,
            external_calls_this_op=external_calls_this_op,
            external_calls_cap=_cap,
            prior_failed_attempts_7d=prior_failed_attempts_7d,
        )
        decision = should_escalate_to_external_ai(state, is_prerun=is_prerun)
        record_decision(decision)
        if not decision.escalate:
            return None
```

Now locate the confirmation gate block:

```python
    # Confirmation gate
    confirm_decision = await wait_for_external_ai_confirmation(
        session_id=session_id,
        operation_id=operation_id,
        provider=provider,
        model=model,
        rule_fired=decision.rule_fired,
        reason=decision.reason,
        output_mode=output_mode,
    )
    if confirm_decision != "approved":
```

Replace with:

```python
    # Confirmation gate — skipped when force=True (operator already chose this)
    if force:
        confirm_decision = "approved"
        await manager.send_line(
            "step",
            f"[external-ai] force=True — bypassing confirmation gate "
            f"({provider}/{model or 'default'})",
            status="ok", session_id=session_id,
        )
    else:
        confirm_decision = await wait_for_external_ai_confirmation(
            session_id=session_id,
            operation_id=operation_id,
            provider=provider,
            model=model,
            rule_fired=decision.rule_fired,
            reason=decision.reason,
            output_mode=output_mode,
        )
    if confirm_decision != "approved":
```

---

## Change 3 — `api/routers/agent.py` — _stream_agent signature + prerun call

Locate `_stream_agent` signature (line ~3916):

```python
async def _stream_agent(task: str, session_id: str, operation_id: str,
                        owner_user: str = "admin", parent_context: str = "",
                        parent_session_id: str = ""):
    """Run the full agent loop, streaming every step to WebSocket clients."""
```

Replace with:

```python
async def _stream_agent(task: str, session_id: str, operation_id: str,
                        owner_user: str = "admin", parent_context: str = "",
                        parent_session_id: str = "",
                        force_external: bool = False):
    """Run the full agent loop, streaming every step to WebSocket clients."""
```

Locate the prerun `_maybe_route_to_external_ai` call (line ~4275):

```python
        _prerun_synth = await _maybe_route_to_external_ai(
            session_id=session_id, operation_id=operation_id,
            task=task, agent_type=first_intent,
            messages=[{"role": "system", "content": system_prompt},
                      {"role": "user", "content": task}],
            tool_calls_made=0, tool_budget=16, diagnosis_emitted=False,
            consecutive_tool_failures=0,
            halluc_guard_exhausted=False, fabrication_detected_count=0,
            external_calls_this_op=0,
            scope_entity=_scope_entity,
            is_prerun=True,
            prior_failed_attempts_7d=_prior_failed,
        )
```

Replace with:

```python
        _prerun_synth = await _maybe_route_to_external_ai(
            session_id=session_id, operation_id=operation_id,
            task=task, agent_type=first_intent,
            messages=[{"role": "system", "content": system_prompt},
                      {"role": "user", "content": task}],
            tool_calls_made=0, tool_budget=16, diagnosis_emitted=False,
            consecutive_tool_failures=0,
            halluc_guard_exhausted=False, fabrication_detected_count=0,
            external_calls_this_op=0,
            scope_entity=_scope_entity,
            is_prerun=True,
            prior_failed_attempts_7d=_prior_failed,
            force=force_external,
        )
```

---

## Change 4 — `api/routers/agent.py` — run_agent endpoint threads force_external

Locate (line ~4838):

```python
    background_tasks.add_task(_stream_agent, req.task, session_id, operation_id, user)
```

Replace with:

```python
    background_tasks.add_task(
        _stream_agent, req.task, session_id, operation_id, user,
        force_external=req.force_external,
    )
```

---

## Change 5 — `gui/src/api.js` — runAgent passes force_external

Locate:

```javascript
export async function runAgent(task, sessionId = '') {
  const r = await fetch(`${BASE}/api/agent/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ task, session_id: sessionId }),
  })
  return r.json()
}
```

Replace with:

```javascript
export async function runAgent(task, sessionId = '', forceExternal = false) {
  const r = await fetch(`${BASE}/api/agent/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ task, session_id: sessionId, force_external: forceExternal }),
  })
  return r.json()
}
```

---

## Change 6 — `gui/src/components/CommandPanel.jsx` — force-external toggle

Locate the `runAgentTask` function:

```javascript
  const runAgentTask = async () => {
    if (!task.trim() || runState !== 'idle') return
    // Immediately go amber — don't wait for API
    setRunState('running')
    setAgentMsg('')
    clearChoices()
    markRunning()
    try {
      const r = await runAgent(task)
      setAgentMsg(`Session ${r.session_id?.slice(0, 8)}`)
      onResult?.()
    } catch (e) {
      setAgentMsg(`Error: ${e.message}`)
      setRunState('idle')
      markDone(false)
    }
  }
```

Replace with:

```javascript
  const [forceExternal, setForceExternal] = useState(false)

  const runAgentTask = async () => {
    if (!task.trim() || runState !== 'idle') return
    setRunState('running')
    setAgentMsg('')
    clearChoices()
    markRunning()
    const _force = forceExternal
    setForceExternal(false)   // reset after submit — explicit per-run decision
    try {
      const r = await runAgent(task, '', _force)
      setAgentMsg(`Session ${r.session_id?.slice(0, 8)}`)
      onResult?.()
    } catch (e) {
      setAgentMsg(`Error: ${e.message}`)
      setRunState('idle')
      markDone(false)
    }
  }
```

Now locate the `TrafficLightButton` usage inside the task input div:

```jsx
        <TrafficLightButton
          runState={runState}
          onRun={runAgentTask}
          taskEmpty={!task.trim()}
        />
        {agentMsg && <p className="text-xs text-slate-400 mt-1">{agentMsg}</p>}
```

Replace with:

```jsx
        <div className="flex items-center gap-2 mt-2">
          <TrafficLightButton
            runState={runState}
            onRun={runAgentTask}
            taskEmpty={!task.trim()}
          />
          <button
            onClick={() => setForceExternal(f => !f)}
            disabled={runState !== 'idle'}
            title={forceExternal ? 'External AI: ON — click to cancel' : 'Send directly to External AI'}
            className={`text-xs px-2 py-1 border font-mono uppercase tracking-wider transition-colors ${
              forceExternal
                ? 'border-[var(--amber)] text-[var(--amber)] bg-[rgba(204,136,0,0.12)]'
                : 'border-slate-600 text-slate-500 hover:border-slate-400 hover:text-slate-300'
            } disabled:opacity-40 disabled:cursor-not-allowed`}
            style={{ borderRadius: 'var(--radius-btn)' }}
          >
            {forceExternal ? '⚡ EXT AI ON' : '⚡ Ext AI'}
          </button>
        </div>
        {agentMsg && <p className="text-xs text-slate-400 mt-1">{agentMsg}</p>}
```

Note: `useState` is already imported on line 1 of CommandPanel.jsx — no import change needed.

---

## Version bump

Update `VERSION` file: `2.38.5` → `2.38.6`

---

## Commit

```
git add -A
git commit -m "feat(agents): v2.38.6 force-external-AI toggle — bypass router + confirmation gate"
git push origin main
```

Then deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
