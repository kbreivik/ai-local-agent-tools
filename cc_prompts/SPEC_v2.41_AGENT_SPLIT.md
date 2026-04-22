# SPEC — agent.py _run_single_agent_step Split
# Phase v2.41 — agent.py structural decomposition

Written: 2026-04-22
Status: PLANNING — no CC prompts yet

---

## Problem

`_run_single_agent_step` is ~2540 lines (1183–3723) inside a 5523-line file.
It contains the entire agent loop: LLM calls, tool dispatch, hallucination guard,
fabrication detector, forced synthesis, fact extraction, contradiction detection,
zero-result pivot, diagnostics broadcasts, and budget enforcement — all interleaved
in a single async function with deeply nested WebSocket `manager.broadcast/send_line`
calls and shared mutable accumulators.

After v2.40.3 (gates.py) and v2.40.4 (context.py) land, agent.py will be ~5300
lines. The loop itself will still be ~2300. It cannot be safely moved wholesale
— it is stateful in ways that require care.

---

## Why naive extraction is hard

1. **Shared mutable accumulators** — 20+ variables declared at function top
   (`substantive_tool_calls`, `_run_facts`, `tools_used_names`, `tool_history`,
   `_halluc_guard_attempts`, etc.) are read and written at every sub-section.
   Closures would work in Python but make the code harder to follow, not easier.

2. **WebSocket mid-function** — `manager.broadcast()` and `manager.send_line()`
   are called ~80 times throughout the loop. Any extracted function must either
   accept `manager` + `session_id` as params, or receive callbacks.
   The former is the right choice — explicit over implicit.

3. **`nonlocal` inner functions** — `_maybe_force_empty_synthesis()` uses
   `nonlocal` to write `_empty_completion_synth_done`, `last_reasoning`,
   `_trace_step_index`. These make extraction of that function non-trivial.

4. **No clean seams** — the hallucination guard sits inside the "finish_reason=stop"
   branch, which is inside the "no tool_calls" branch, which is inside the while
   loop. Tool dispatch is in the "has tool_calls" branch at the same depth.
   These are not sequential — they are deeply nested conditionals.

---

## Strategy: StepState dataclass + section extractors

### Step 1 — Define `StepState` dataclass (api/agents/step_state.py)

Consolidate all 20+ accumulators into a single typed dataclass.
The while loop receives one `StepState` instance and passes it to
every extracted function. Mutations are explicit (no nonlocal needed).

```python
@dataclass
class StepState:
    # Identity
    session_id: str
    operation_id: str
    agent_type: str
    task: str

    # Accumulators
    tools_used_names: list = field(default_factory=list)
    tool_history: list = field(default_factory=list)
    substantive_tool_calls: int = 0
    positive_signals: int = 0
    negative_signals: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0

    # Guard state
    halluc_guard_attempts: int = 0
    halluc_guard_max: int = 3
    hallucination_block_fired: bool = False
    fabrication_min_cites: int = 3
    fabrication_score_threshold: float = 0.5
    fabrication_detected_once: bool = False

    # Synthesis
    last_reasoning: str = ""
    empty_completion_synth_done: bool = False
    render_tool_calls: int = 0

    # Loop control
    final_status: str = "completed"
    budget_nudge_fired: bool = False
    audit_logged: bool = False
    degraded_findings: list = field(default_factory=list)
    plan_action_called: bool = False
    last_blocked_tool: str | None = None
    working_memory: str = ""

    # Trace
    trace_prev_msg_count: int = 0
    trace_step_index: int = 0
    trace_is_subagent: bool = False
    trace_parent_op_id: str | None = None

    # Fact tracking
    run_facts: dict = field(default_factory=dict)
    zero_streaks: dict = field(default_factory=dict)
    nonzero_seen: dict = field(default_factory=dict)
    zero_pivot_fired: set = field(default_factory=set)

    # Propose dedup
    propose_state: object = None  # ProposeState instance
```

### Step 2 — Extract 6 section handlers

Each handles one responsibility, receives `(state: StepState, *, manager, messages, ...)`,
mutates `state` in-place, and returns a control signal if needed.

| Module | Function | Lines freed | Inputs | Returns |
|---|---|---|---|---|
| `api/agents/step_llm.py` | `call_llm_step()` | ~80 | state, client, messages, tools_spec | response, finish, msg |
| `api/agents/step_guard.py` | `run_hallucination_guard()` | ~120 | state, manager, msg, messages | GuardResult (CONTINUE/RETRY/EXHAUST) |
| `api/agents/step_guard.py` | `run_fabrication_check()` | ~60 | state, manager, text | bool (rejected) |
| `api/agents/step_tools.py` | `dispatch_tool_calls()` | ~500 | state, manager, msg, messages, tools | list[ToolResult] |
| `api/agents/step_facts.py` | `extract_and_check_facts()` | ~120 | state, manager, tool_name, result | None |
| `api/agents/step_synth.py` | `run_forced_synthesis()` (wrapper) | ~150 | state, manager, reason, messages | str |

### Step 3 — Thin loop skeleton stays in agent.py

After extraction, `_run_single_agent_step` becomes a ~200-line orchestrator:

```python
async def _run_single_agent_step(...) -> dict:
    state = StepState(...)
    messages = [...]

    while state.step < max_steps:
        response, finish, msg = await call_llm_step(state, client, messages, tools_spec)

        if finish == "stop" and not msg.tool_calls:
            guard = await run_hallucination_guard(state, manager, msg, messages)
            if guard == GuardResult.RETRY:
                continue
            if guard == GuardResult.EXHAUST:
                break

            if not run_fabrication_check(state, manager, msg.content):
                continue  # retry

            state.last_reasoning = compute_final_answer(state.steps)
            break

        results = await dispatch_tool_calls(state, manager, msg, messages, tools_spec)
        for r in results:
            await extract_and_check_facts(state, manager, r)

        state.step += 1

    await _maybe_force_empty_synthesis(state, manager, messages)
    return state.to_result_dict()
```

---

## Phased CC prompts

### v2.41.0 — Define StepState dataclass (api/agents/step_state.py)
- Create the dataclass, no behaviour change
- Migrate `_run_single_agent_step` to instantiate StepState and use it internally
- All 20+ local variables replaced with `state.*`
- Function body unchanged otherwise — this is pure refactor, zero logic change
- **Acceptance**: all existing tests pass, agent runs correctly

### v2.41.1 — Extract step_llm.py (LLM call + trace)
- `call_llm_step(state, client, messages, tools_spec, *, manager)` async
- Handles: LLM call, token counting, trace persistence, step broadcast
- Returns: `(response, finish_reason, msg)`
- Wire back into _run_single_agent_step

### v2.41.2 — Extract step_guard.py (hallucination guard + fabrication)
- `run_hallucination_guard(state, manager, msg, messages) -> GuardResult`
- `run_fabrication_check(state, manager, text) -> bool`
- Both read/write `state.*` in-place
- Wire back into _run_single_agent_step

### v2.41.3 — Extract step_tools.py (tool dispatch)
- `dispatch_tool_calls(state, manager, msg, messages, tools_spec) -> list[ToolResult]`
- Handles: allowlist check, plan_lock, budget cap, destructive gate, vm_exec allowlist,
  MCP call, result summarization, render_table dispatch, meta-tool routing
- Largest extraction — ~500 lines
- Wire back into _run_single_agent_step

### v2.41.4 — Extract step_facts.py (fact extraction + contradiction + zero-pivot + diagnostics)
- `extract_and_check_facts(state, manager, tool_name, result, step)` async
- Handles: tool_extractor call, _run_facts upsert, contradiction detection,
  zero-result pivot, live diagnostics broadcast
- Wire back into _run_single_agent_step

### v2.41.5 — Final thinning + _maybe_force_empty_synthesis migration
- Move `_maybe_force_empty_synthesis` into `step_synth.py` as a proper function
  (eliminate nonlocal via StepState)
- `state.to_result_dict()` method on StepState returns the final return dict
- Verify agent.py line count ≤ 2800 (was 5523)

---

## Risk controls

- Each CC prompt ships as a pure refactor — no logic change
- Each prompt must pass `pytest tests/ -x` before push
- Version bumps are v2.41.0 through v2.41.5 — no skipping
- If any prompt fails CI, halt queue and diagnose before continuing
- The `manager` WebSocket object is passed explicitly to every extracted
  function — never accessed via import or global

---

## Acceptance criteria (final)

1. `api/routers/agent.py` ≤ 2800 lines
2. `_run_single_agent_step` ≤ 250 lines (orchestrator only)
3. All 6 new modules have their own test files
4. All existing tests pass
5. A live agent run on each agent type (observe/investigate/execute/build)
   completes successfully after v2.41.5 deploys
