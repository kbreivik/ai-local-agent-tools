# CC PROMPT — v2.34.0 — feat(agents): sub-agent execution in isolated sub-context

## What this does

**Architectural change.** Completes the sub-agent story. Since v2.24.0 the parent
agent can *propose* a sub-task via `propose_subtask`, and v2.33.3 nudges it to do
so when near budget exhaustion. Today those proposals render as a clickable card
the operator must manually run as a new task. That's an escalation loop, not a
delegation loop.

This change makes sub-agents actually execute: the harness takes a
`propose_subtask` call as an in-band spawn, starts a fresh agent with its own
context window, its own tool budget, and its own depth counter. Parent blocks
on a rendezvous point, receives the sub-agent's `final_answer`, and continues
with the summary in hand. Sub-agents can themselves spawn sub-sub-agents up to
a configurable depth cap.

This is the "biggest remaining gap in the agent design" flagged in the memory.
The v2.33.3 nudge creates the call site; this prompt builds the runtime.

Version bump: 2.33.20 → 2.34.0 — **new subsystem + multi-file architectural
change.** Once this ships no further 2.33.x prompts will be written.

---

## Design

### Execution model

```
┌─ parent task T1 ─────────────────────────┐
│ step 1: swarm_node_status  (1 tool call) │
│ step 2: service_placement  (1 tool call) │
│ step 3: propose_subtask(                 │
│           objective="diagnose kafka      │
│                      under-replication", │
│           agent_type="investigate",      │
│           scope_entity="kafka_broker-3", │
│           budget_tools=8)                │
│         │                                │
│         ▼ (harness intercepts)           │
│ ┌─ sub task T1-a ──────────────────────┐ │
│ │ fresh context, own budget=8           │ │
│ │ (may spawn T1-a-i if depth < cap)     │ │
│ │ final_answer: "broker 3 unscheduled"  │ │
│ └───────────────────────────────────────┘ │
│                                           │
│ step 4: [parent resumes with summary]    │
│   Injected as tool_result of             │
│   propose_subtask                         │
│ step 5: plan_action → ...                │
└───────────────────────────────────────────┘
```

### Guardrails

- **Depth cap.** Default 2. Config key `subagentMaxDepth`. Depth 0 = top-level
  task, depth 1 = first sub, depth 2 = grandchild. Depth > cap → tool returns
  an error that nudges the agent to finish without further delegation.
- **Budget cap.** Sub-agent's `budget_tools` cannot exceed parent's
  `remaining_budget - 2` (leave parent at least 2 tool calls after resume).
  Config key `subagentMinParentReserve` = 2.
- **Hard caps inherited.** Wall-clock cap, token cap, destructive cap, and
  failure cap (all from v2.31.8) apply per-agent — each sub-agent has its own
  counters, not inherited. But there is a **total-tree wall-clock cap**
  `subagentTreeWallClockS` (default 1800) to prevent runaway delegation chains.
- **Destructive operations forbidden in sub-agents** unless explicitly opted in
  via `allow_destructive: true` argument (with extra confirm at the parent's
  plan-action gate at spawn time). Default is investigate/observe only.
- **Fresh context.** Sub-agent receives:
  - The `objective` string as its task message
  - A compact 3-line parent summary: task_id, parent's last DIAGNOSIS section
    if present, and the entity scope if provided
  - **Not** the parent's entire tool history — that's the whole point of
    isolation.

### Result rendezvous

- Sub-agent runs on a separate asyncio task, writing progress to the same
  WebSocket channel as the parent but tagged with `task_id` + `parent_task_id`.
- Parent's `propose_subtask` call blocks (async await) until the sub-agent
  reaches a terminal state.
- Sub-agent's final_answer + final DIAGNOSIS (if any) + tool-call count are
  returned to the parent as the tool_result of `propose_subtask`.
- Frontend renders sub-agent activity inside the parent's OutputPanel as an
  indented sub-section with a collapsible expand.

---

## Change 1 — api/db/subagent_runs.py (new table + helpers)

```python
"""
subagent_runs — links each sub-agent execution to its parent.
"""
import datetime as _dt
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Boolean, Text, JSON
from api.db.base import metadata, get_engine

subagent_runs = Table(
    "subagent_runs", metadata,
    Column("id",                 String, primary_key=True),  # uuid
    Column("parent_task_id",     String, nullable=False, index=True),
    Column("sub_task_id",        String, nullable=False, unique=True),
    Column("depth",              Integer, nullable=False, default=1),
    Column("spawned_at",         DateTime, nullable=False, default=_dt.datetime.utcnow),
    Column("completed_at",       DateTime),
    Column("objective",          Text, nullable=False),
    Column("agent_type",         String, nullable=False),
    Column("scope_entity",       String),
    Column("budget_tools",       Integer, nullable=False),
    Column("tools_used",         Integer, default=0),
    Column("allow_destructive",  Boolean, default=False),
    Column("terminal_status",    String),   # done | failed | timeout | cap_hit
    Column("final_answer",       Text),
    Column("diagnosis",          Text),
    Column("error",              Text),
)


async def record_spawn(parent_task_id, sub_task_id, depth, objective, agent_type,
                       scope_entity, budget_tools, allow_destructive):
    eng = get_engine()
    async with eng.begin() as c:
        await c.execute(subagent_runs.insert().values(
            id=f"sr_{sub_task_id}",
            parent_task_id=parent_task_id,
            sub_task_id=sub_task_id,
            depth=depth,
            objective=objective[:2000],
            agent_type=agent_type,
            scope_entity=scope_entity,
            budget_tools=budget_tools,
            allow_destructive=allow_destructive,
        ))


async def record_completion(sub_task_id, terminal_status, final_answer,
                             diagnosis, tools_used, error=None):
    eng = get_engine()
    async with eng.begin() as c:
        await c.execute(
            subagent_runs.update()
            .where(subagent_runs.c.sub_task_id == sub_task_id)
            .values(
                completed_at=_dt.datetime.utcnow(),
                terminal_status=terminal_status,
                final_answer=(final_answer or "")[:4000],
                diagnosis=(diagnosis or "")[:2000],
                tools_used=tools_used,
                error=(error or "")[:2000],
            )
        )


async def get_ancestry(task_id) -> list[dict]:
    """Return the chain of parent tasks up to the root, ordered root-first."""
    eng = get_engine()
    chain = []
    current = task_id
    async with eng.connect() as c:
        for _ in range(10):  # hard stop in case of corrupt state
            r = await c.execute(
                subagent_runs.select().where(subagent_runs.c.sub_task_id == current)
            )
            row = r.mappings().first()
            if not row:
                break
            chain.insert(0, dict(row))
            current = row["parent_task_id"]
    return chain
```

Add Alembic migration for the new table.

## Change 2 — api/routers/agent.py — subagent spawn path

Locate the harness loop in `_stream_agent` (or wherever the per-step tool-call
dispatch happens). Add a handler for `propose_subtask` calls:

```python
from api.db.subagent_runs import (
    record_spawn, record_completion, get_ancestry,
)

async def _handle_propose_subtask(
    parent_task, tool_call, ws_manager, settings,
):
    args = tool_call["arguments"]
    objective    = args["objective"]
    agent_type   = args.get("agent_type", "investigate")
    scope_entity = args.get("scope_entity")
    requested_budget = int(args.get("budget_tools", 8))
    allow_destructive = bool(args.get("allow_destructive", False))

    # Depth check
    ancestry = await get_ancestry(parent_task.id)
    depth = len(ancestry) + 1
    max_depth = int(settings.get("subagentMaxDepth", 2))
    if depth > max_depth:
        return {
            "ok": False,
            "error": f"sub-agent depth cap reached ({depth} > {max_depth}). "
                     "Complete this task yourself — no further delegation."
        }

    # Destructive gate — only allowed with explicit arg AND execute agent type
    if allow_destructive and agent_type != "execute":
        return {"ok": False, "error": "allow_destructive requires agent_type=execute"}
    if allow_destructive and depth > 1:
        return {"ok": False, "error": "destructive sub-agents only at depth 1"}

    # Budget reservation — must leave parent some headroom
    reserve = int(settings.get("subagentMinParentReserve", 2))
    parent_remaining = parent_task.budget_tools - parent_task.tools_used
    max_sub_budget = max(0, parent_remaining - reserve)
    sub_budget = min(requested_budget, max_sub_budget)
    if sub_budget < 2:
        return {"ok": False, "error": f"insufficient parent budget for sub-agent "
                                      f"(remaining={parent_remaining}, reserve={reserve})"}

    # Spawn
    sub_task_id = _uuid.uuid4().hex[:16]
    await record_spawn(
        parent_task_id=parent_task.id, sub_task_id=sub_task_id, depth=depth,
        objective=objective, agent_type=agent_type,
        scope_entity=scope_entity, budget_tools=sub_budget,
        allow_destructive=allow_destructive,
    )

    # Fire WS event so UI can render the sub-agent panel
    await ws_manager.broadcast_to_task(parent_task.id, {
        "type": "subagent_spawned",
        "sub_task_id": sub_task_id,
        "parent_task_id": parent_task.id,
        "depth": depth,
        "objective": objective,
        "budget_tools": sub_budget,
    })

    # Build fresh context for sub-agent
    sub_context = _build_subagent_context(parent_task, objective, scope_entity)

    # Run sub-agent to completion on a separate asyncio task, awaiting result
    sub_result = await _run_subagent(
        task_id=sub_task_id,
        agent_type=agent_type,
        messages=sub_context,
        budget_tools=sub_budget,
        allow_destructive=allow_destructive,
        parent_task_id=parent_task.id,
    )

    # Record completion
    await record_completion(
        sub_task_id=sub_task_id,
        terminal_status=sub_result["terminal_status"],
        final_answer=sub_result["final_answer"],
        diagnosis=sub_result.get("diagnosis"),
        tools_used=sub_result["tools_used"],
        error=sub_result.get("error"),
    )

    # Return compact result for parent
    return {
        "ok": True,
        "sub_task_id": sub_task_id,
        "terminal_status": sub_result["terminal_status"],
        "final_answer": sub_result["final_answer"],
        "diagnosis": sub_result.get("diagnosis"),
        "tools_used": sub_result["tools_used"],
    }


def _build_subagent_context(parent_task, objective, scope_entity):
    """Compact context — do NOT inherit parent's full tool history."""
    system_lines = []
    if parent_task.last_diagnosis:
        system_lines.append(f"PARENT DIAGNOSIS SO FAR: {parent_task.last_diagnosis[:500]}")
    if scope_entity:
        system_lines.append(f"SCOPE: {scope_entity}")
    system_lines.append(f"PARENT_TASK_ID: {parent_task.id}")
    system_lines.append("You are a sub-agent. Your parent delegated this task. "
                        "Be focused and return a DIAGNOSIS section.")
    return [
        {"role": "system", "content": "\n".join(system_lines)},
        {"role": "user",   "content": objective},
    ]


async def _run_subagent(task_id, agent_type, messages, budget_tools,
                        allow_destructive, parent_task_id):
    """Reuses the main agent loop but with its own task context."""
    # Implementation: instantiate AgentTask(task_id, agent_type, messages,
    # budget_tools=budget_tools, destructive_allowed=allow_destructive,
    # parent_task_id=parent_task_id) and drive the same _stream_agent loop,
    # returning {terminal_status, final_answer, diagnosis, tools_used}.
    # Existing loop code must be extracted into a reusable driver —
    # see Change 3.
```

## Change 3 — refactor _stream_agent into a reusable driver

The existing `_stream_agent` function couples three concerns:
- HTTP streaming to the client
- Agent loop (LLM step → tool call → LLM step)
- Terminal status resolution

Extract the middle concern into `drive_agent(task) -> AgentResult` so both
top-level tasks and sub-agents can reuse it. Streaming and WS emission become
hooks on the task object.

```python
@dataclass
class AgentTask:
    id: str
    agent_type: str                       # observe | investigate | execute | build
    messages: list[dict]
    budget_tools: int
    tools_used: int = 0
    last_diagnosis: str | None = None
    destructive_allowed: bool = False
    parent_task_id: str | None = None     # None = top-level
    # Hooks — called by the driver but set differently for top-level vs sub
    on_step: Callable | None = None
    on_tool_call: Callable | None = None
    on_done: Callable | None = None


async def drive_agent(task: AgentTask) -> AgentResult:
    # Extracted loop body — identical logic to current _stream_agent, but
    # calls task.on_*() hooks instead of emitting directly to StreamingResponse
    ...
```

Then:
- `_stream_agent` becomes thin: build an AgentTask with hooks that emit
  StreamingResponse chunks, call `drive_agent`, return.
- `_run_subagent` builds an AgentTask with hooks that emit WS events tagged
  with `parent_task_id`, calls `drive_agent`, returns the result.

## Change 4 — api/agents/router.py — prompt updates

In the investigate + observe prompts, add to the existing sub-agent section:

```
═══ DELEGATION (SUB-AGENTS) ═══
When you identify a sub-problem you cannot or should not solve inside this task,
call propose_subtask. This will IMMEDIATELY spawn a sub-agent that runs to
completion and returns its final_answer to you.

Use sub-agents when:
  - A diagnostic chain would consume >5 of your remaining budget
  - The sub-problem is out-of-scope for your agent_type (e.g. you're observe,
    but kafka requires investigate)
  - You hit an unfamiliar entity type that needs focused attention

Constraints you MUST respect:
  - You get ONE sub-agent per task (soft budget; harness may reject more)
  - Sub-agent budget cannot exceed your remaining - 2
  - Sub-agents cannot perform destructive actions unless you are execute-type
    AND you pass allow_destructive=true, AND you are the top-level parent
  - Sub-agent output replaces your own further tool calls in its area —
    synthesise from it, don't re-verify everything it did

Call shape:
  propose_subtask(
    objective: "one sentence explaining what to investigate",
    agent_type: "observe" | "investigate" | "execute",  # not "build"
    scope_entity: "platform:name:id" or null,
    budget_tools: <int, 2-8 typical>,
  )
```

## Change 5 — gui/src/components/OutputPanel.jsx — sub-agent rendering

Handle the `subagent_spawned`, `subagent_step`, `subagent_done` WS events.
Render nested under the parent's OutputPanel with a light indent and a
collapse button. The existing `AgentDiagnostics` overlay (v2.33.15) should
also show depth-aware budget tracking when a sub-agent is active.

Schematically:

```jsx
{subAgents.map(sa => (
  <SubAgentPanel
    key={sa.sub_task_id}
    {...sa}
    parentTaskId={task.id}
    expanded={sa.status !== 'done'}
  />
))}
```

`SubAgentPanel` is a new component — structurally a mini OutputPanel scoped to
the sub-task's WS stream, rendered inside an indented, bordered container with
a header like `↳ SUB-AGENT (investigate) — kafka_broker-3`.

## Change 6 — api/db/settings — new config keys

Register three new setting keys with defaults:

- `subagentMaxDepth` = 2
- `subagentMinParentReserve` = 2
- `subagentTreeWallClockS` = 1800

Expose in InfrastructureTab or AIServicesTab of OptionsModal. If a natural
place already exists for agent caps (from v2.31.8), add them there.

## Change 7 — tests

`tests/test_subagent_runtime.py`:

```python
@pytest.mark.asyncio
async def test_sub_agent_runs_and_returns_result(fake_llm, authed_client):
    """End-to-end: parent proposes subtask, sub-agent runs, parent resumes."""
    fake_llm.set_parent_script([
        {"tool_call": "swarm_node_status", "result": {...}},
        {"tool_call": "propose_subtask", "arguments": {
            "objective": "Check kafka broker 3 status",
            "agent_type": "investigate",
            "budget_tools": 4,
        }},
        {"final_answer": "Parent summary based on sub-agent output"},
    ])
    fake_llm.set_sub_script([
        {"tool_call": "kafka_topic_inspect", "result": {...}},
        {"final_answer": "broker 3 unscheduled", "diagnosis": "missing broker"},
    ])
    result = await run_task("check kafka", agent_type="investigate")
    assert "Parent summary" in result["final_answer"]
    # Sub-agent row exists in DB
    runs = await get_subagent_runs(parent_task_id=result["task_id"])
    assert len(runs) == 1
    assert runs[0]["terminal_status"] == "done"
    assert runs[0]["tools_used"] == 1


@pytest.mark.asyncio
async def test_depth_cap_blocks_grandchild(fake_llm):
    # Set subagentMaxDepth=1 → grandchild spawn must be refused
    ...


@pytest.mark.asyncio
async def test_budget_reservation_respected():
    # Parent has 10 tools budget, used 7 → remaining=3, reserve=2 → max sub = 1
    # Agent requests 5 → capped to 1
    # If remaining-reserve < 2 → error returned
    ...


@pytest.mark.asyncio
async def test_destructive_forbidden_from_non_execute_parent():
    # Parent is investigate, sub tries allow_destructive=true → error
    ...


@pytest.mark.asyncio
async def test_context_isolation():
    """Sub-agent does not receive parent's tool history in its messages."""
    # Verify the messages passed to sub-agent contain only system + user,
    # not the parent's prior tool_calls/tool_results.
    ...


@pytest.mark.asyncio
async def test_subagent_counts_toward_metrics():
    """Prometheus counters (v2.33.5) tick for sub-agents too."""
    ...
```

## Version bump
Update `VERSION`: 2.33.20 → 2.34.0

## Commit
```
git add -A
git commit -m "feat(agents): v2.34.0 sub-agent execution in isolated sub-context"
git push origin main
```

## How to test after push
1. Redeploy, run Alembic upgrade.
2. Open a kafka investigate task: `Diagnose why kafka_broker-3 is not running`.
3. Watch the agent trace — when it hits ~70% budget without a DIAGNOSIS, the
   v2.33.3 nudge should fire and the agent should call propose_subtask.
4. Instead of the old "subtask offer card" rendering, the UI should show a
   new indented sub-agent panel that begins executing immediately.
5. Sub-agent runs to completion; parent resumes with the sub-agent's summary.
6. Final_answer from parent should cite the sub-agent's finding.
7. Database: `SELECT * FROM subagent_runs` shows one row linking parent and sub.
8. Regression:
   - Observe and execute tasks still work without sub-agents.
   - v2.33.3 budget nudge still fires when no delegation is appropriate.
   - Operator can still manually open the sub-task proposal card (for tasks
     the agent chose not to delegate in-band).
9. Try to provoke depth > max: set subagentMaxDepth=1, run a task that
   delegates, and make the sub-agent try to delegate again. Should see
   "sub-agent depth cap reached" in the sub-agent's output.
