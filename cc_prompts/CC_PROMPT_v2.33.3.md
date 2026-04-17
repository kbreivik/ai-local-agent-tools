# CC PROMPT — v2.33.3 — Sub-agent proposal mandatory near budget exhaustion

## What this does
Strengthens the existing `propose_subtask` pathway (v2.24.0) so it actually fires
on investigations that are about to exceed their tool budget without a conclusion.
When an investigate task reaches 70% of its tool budget without emitting a
`DIAGNOSIS:` section, the harness injects a nudge and the agent is instructed
(and constrained) to propose a sub-task instead of producing a shallow summary.

Version bump: 2.33.2 → 2.33.3

## Change 1 — api/agents/router.py — RESEARCH_PROMPT constraint

Find the `RESEARCH_PROMPT` (the investigate agent's system prompt, restructured
in v2.32.0 into ═══ SECTION ═══ blocks). Locate the `═══ CONSTRAINTS ═══` section
and add a new rule:

```
═══ CONSTRAINTS ═══
...existing rules...

N. BUDGET HANDOFF RULE: If you have used 70% or more of your tool budget
   AND your output so far does not contain the literal string "DIAGNOSIS:",
   your next action MUST be propose_subtask(scope=..., reason=...) with a
   tight, single-entity scope that carries forward what you've found so far.
   Do NOT try to cram a conclusion; hand off.
```

## Change 2 — api/routers/agent.py — runtime nudge + enforcement

In the agent loop (`_stream_agent` or equivalent), after each tool call:

```python
budget = _MAX_TOOL_CALLS_BY_TYPE[agent_type]  # v2.32.5 constant
threshold = int(0.7 * budget)
combined_text = "\n".join(step_outputs)

if tools_used >= threshold and "DIAGNOSIS:" not in combined_text and not subtask_proposed:
    # Inject a system nudge as an assistant-facing message
    messages.append({
        "role": "system",
        "content": (
            f"HARNESS NUDGE: You have used {tools_used}/{budget} tool calls. "
            "No DIAGNOSIS: section emitted yet. Per BUDGET HANDOFF RULE, your "
            "next action must be propose_subtask(scope, reason). Do not produce "
            "a shallow conclusion."
        ),
    })
    # Broadcast to WS so the UI shows the nudge happened
    await ws.send_json({"event": "budget_nudge", "tools_used": tools_used, "budget": budget})
```

Track `subtask_proposed` by watching the tool-call stream for any call to
`propose_subtask`.

## Change 3 — api/routers/agent.py — emit subtask_proposed event

When `propose_subtask` is invoked, emit a WS event with the full payload:

```python
await ws.send_json({
    "event": "subtask_proposed",
    "parent_task_id": task_id,
    "scope": args.get("scope"),
    "reason": args.get("reason"),
    "id": proposal_id,  # from agent_attempts row
})
```

## Change 4 — api/db/agent_attempts.py — track outcome

Extend the attempts log so sub-task proposals are distinguishable. Add column
`was_proposal BOOLEAN DEFAULT FALSE` and set `TRUE` when the attempt originated
from an accepted `propose_subtask`. Migration block at module top:

```python
async def ensure_schema(pool):
    async with pool.acquire() as conn:
        await conn.execute("""
            ALTER TABLE agent_attempts
            ADD COLUMN IF NOT EXISTS was_proposal BOOLEAN DEFAULT FALSE;
        """)
```

## Change 5 — gui/src/components/OutputPanel.jsx — inline subtask offer card

When a `subtask_proposed` event arrives, render an inline card at the bottom of
the output stream:

```jsx
{subtaskOffer && (
  <div className="subtask-offer" style={{
    border: '1px solid var(--accent)', background: 'var(--accent-dim)',
    padding: 10, margin: '10px 0', borderRadius: 2
  }}>
    <div className="mono" style={{ fontSize: 10, color: 'var(--accent-hi)', letterSpacing: '0.15em' }}>
      ◢ SUB-TASK PROPOSED
    </div>
    <div style={{ margin: '6px 0', fontSize: 13 }}>{subtaskOffer.scope}</div>
    <div style={{ fontSize: 11, color: 'var(--text-2)', marginBottom: 8 }}>
      {subtaskOffer.reason}
    </div>
    <button className="btn" onClick={() => acceptSubtask(subtaskOffer)}>
      ACCEPT — start fresh investigate
    </button>
  </div>
)}
```

## Version bump
Update `VERSION`: 2.33.2 → 2.33.3

## Commit
```
git add -A
git commit -m "feat(agents): v2.33.3 mandatory sub-agent proposal near budget exhaustion"
git push origin main
```

## How to test after push
1. Redeploy.
2. Run investigate "kafka hp1-logs AND elasticsearch both degraded, correlate and trace common cause" — a deliberately broad multi-surface task.
3. Expect: at tool call ~12 (70% of 16), harness emits budget_nudge, agent fires propose_subtask.
4. Run investigate "status of kafka_broker-1" — narrow task — expect no proposal (no false positive).
5. Accept a proposal → verify a fresh investigate task spawns with its own budget.
