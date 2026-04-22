# CC PROMPT — v2.41.0 — refactor(agents): StepState dataclass — foundation for agent.py split

## Context

SPEC: `cc_prompts/SPEC_v2.41_AGENT_SPLIT.md`

`_run_single_agent_step` is ~2540 lines with 20+ shared mutable accumulators
declared as locals and mutated throughout the function. This prompt introduces
a `StepState` dataclass that consolidates all accumulators into one typed object.

This is a pure refactor — zero logic change. The while loop and all conditional
branches stay in agent.py, unchanged except that `state.x` replaces `_x`.

All subsequent v2.41.x prompts depend on this. Tests must pass before proceeding.

Version bump: 2.40.4 → 2.41.0.

---

## Change 1 — create `api/agents/step_state.py`

Create new file:

```python
"""StepState — shared mutable accumulator for one agent loop run.

Extracted from api/routers/agent.py (v2.41.0). All accumulators that were
previously declared as locals in _run_single_agent_step and passed around
via nonlocal / closure are consolidated here.

Subsequent v2.41.x modules receive a StepState instance and mutate it in-place.
The orchestrator (_run_single_agent_step) calls state.to_result_dict() at the end.
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class StepState:
    # ── Identity (immutable after init) ──────────────────────────────────────
    session_id: str
    operation_id: str
    agent_type: str
    task: str
    parent_session_id: str = ""

    # ── Tool tracking ─────────────────────────────────────────────────────────
    tools_used_names: list = field(default_factory=list)
    tool_history: list = field(default_factory=list)       # v2.33.13: for contradiction detection
    substantive_tool_calls: int = 0                        # v2.34.8: hallucination guard counter

    # ── Signal counters ───────────────────────────────────────────────────────
    positive_signals: int = 0
    negative_signals: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0

    # ── Execution flags ───────────────────────────────────────────────────────
    audit_logged: bool = False                             # at most one audit_log per run
    degraded_findings: list = field(default_factory=list) # research agents: degraded = findings
    plan_action_called: bool = False
    last_blocked_tool: str | None = None
    working_memory: str = ""                               # compact facts from <think> blocks
    budget_nudge_fired: bool = False                       # v2.33.3: 70% nudge fires at most once

    # ── Hallucination guard ───────────────────────────────────────────────────
    hallucination_block_fired: bool = False                # v2.34.8: legacy flag
    halluc_guard_attempts: int = 0                         # v2.34.14: retry counter
    halluc_guard_max: int = 3                              # from env AGENT_HALLUC_GUARD_MAX_ATTEMPTS

    # ── Fabrication detector ──────────────────────────────────────────────────
    fabrication_min_cites: int = 3                         # from env AGENT_FABRICATION_MIN_CITES
    fabrication_score_threshold: float = 0.5              # from env AGENT_FABRICATION_SCORE_THRESHOLD
    fabrication_detected_once: bool = False

    # ── Synthesis ─────────────────────────────────────────────────────────────
    last_reasoning: str = ""
    empty_completion_synth_done: bool = False              # v2.35.14/15: idempotency guard
    render_tool_calls: int = 0                             # v2.36.9

    # ── Loop status ───────────────────────────────────────────────────────────
    final_status: str = "completed"

    # ── LLM trace ─────────────────────────────────────────────────────────────
    trace_prev_msg_count: int = 0                          # v2.34.14: delta-index for trace writes
    trace_step_index: int = 0
    trace_is_subagent: bool = False
    trace_parent_op_id: str | None = None

    # ── Zero-result pivot ─────────────────────────────────────────────────────
    zero_streaks: dict = field(default_factory=dict)       # tool_name → consecutive zero count
    nonzero_seen: dict = field(default_factory=dict)       # tool_name → best non-zero count seen
    zero_pivot_fired: set = field(default_factory=set)     # tools already nudged

    # ── In-run fact tracking ──────────────────────────────────────────────────
    run_facts: dict = field(default_factory=dict)          # v2.35.2: key → {value, step, tool, ...}

    # ── Propose dedup ─────────────────────────────────────────────────────────
    propose_state: object = None                           # ProposeState instance

    def to_result_dict(self) -> dict:
        """Return the dict that _run_single_agent_step currently returns."""
        return {
            "output":                 self.last_reasoning,
            "tools_used":             self.tools_used_names,
            "substantive_tool_calls": self.substantive_tool_calls,
            "tool_history":           self.tool_history,
            "final_status":           self.final_status,
            "positive_signals":       self.positive_signals,
            "negative_signals":       self.negative_signals,
            "steps_taken":            0,   # caller sets this: state.steps_taken = step
            "prompt_tokens":          self.total_prompt_tokens,
            "completion_tokens":      self.total_completion_tokens,
            "run_facts":              self.run_facts,
            "fabrication_detected":   bool(self.fabrication_detected_once),
            "render_tool_calls":      self.render_tool_calls,
        }
```

Also add `steps_taken: int = 0` to the dataclass fields (caller sets it at end of loop).

---

## Change 2 — `api/routers/agent.py` — migrate _run_single_agent_step to use StepState

CC must:

1. Add import near top of agent.py:
   ```python
   from api.agents.step_state import StepState
   ```

2. Inside `_run_single_agent_step`, after the `messages` list is built,
   replace the entire accumulator block (all ~25 local variable declarations,
   from `_propose_state = ProposeState()` through `_run_facts: dict = {}`)
   with a single StepState instantiation:

   ```python
   import os as _os
   from api.agents.propose_dedup import ProposeState
   state = StepState(
       session_id=session_id,
       operation_id=operation_id,
       agent_type=agent_type,
       task=task,
       parent_session_id=parent_session_id,
       plan_action_called=plan_already_approved,
       halluc_guard_max=int(_os.environ.get("AGENT_HALLUC_GUARD_MAX_ATTEMPTS", "3")),
       fabrication_min_cites=int(_os.environ.get("AGENT_FABRICATION_MIN_CITES", "3")),
       fabrication_score_threshold=float(_os.environ.get("AGENT_FABRICATION_SCORE_THRESHOLD", "0.5")),
       trace_is_subagent=bool(parent_session_id),
       propose_state=ProposeState(),
   )
   ```

3. After the StepState init, move the async `_trace_parent_op_id` resolution
   block into a small inline try/except that sets `state.trace_parent_op_id`.

4. Replace every reference to the old local variables with `state.*`:
   - `_propose_state` → `state.propose_state`
   - `tools_used_names` → `state.tools_used_names`
   - `tool_history` → `state.tool_history`
   - `substantive_tool_calls` → `state.substantive_tool_calls`
   - `positive_signals` → `state.positive_signals`
   - `negative_signals` → `state.negative_signals`
   - `total_prompt_tokens` → `state.total_prompt_tokens`
   - `total_completion_tokens` → `state.total_completion_tokens`
   - `_audit_logged` → `state.audit_logged`
   - `_degraded_findings` → `state.degraded_findings`
   - `plan_action_called` → `state.plan_action_called`
   - `_last_blocked_tool` → `state.last_blocked_tool`
   - `_working_memory` → `state.working_memory`
   - `_budget_nudge_fired` → `state.budget_nudge_fired`
   - `_hallucination_block_fired` → `state.hallucination_block_fired`
   - `_halluc_guard_attempts` → `state.halluc_guard_attempts`
   - `_halluc_guard_max` → `state.halluc_guard_max`
   - `_fabrication_min_cites` → `state.fabrication_min_cites`
   - `_fabrication_score_threshold` → `state.fabrication_score_threshold`
   - `_fabrication_detected_once` → `state.fabrication_detected_once`
   - `_render_tool_calls` → `state.render_tool_calls`
   - `_trace_prev_msg_count` → `state.trace_prev_msg_count`
   - `_trace_step_index` → `state.trace_step_index`
   - `_trace_is_subagent` → `state.trace_is_subagent`
   - `_trace_parent_op_id` → `state.trace_parent_op_id`
   - `_zero_streaks` → `state.zero_streaks`
   - `_nonzero_seen` → `state.nonzero_seen`
   - `_zero_pivot_fired` → `state.zero_pivot_fired`
   - `_run_facts` → `state.run_facts`
   - `last_reasoning` → `state.last_reasoning`
   - `_empty_completion_synth_done` → `state.empty_completion_synth_done`
   - `final_status` → `state.final_status`

5. Update the `_maybe_force_empty_synthesis` inner function:
   Replace `nonlocal _empty_completion_synth_done, last_reasoning, _trace_step_index`
   with just reading/writing `state.*` directly (no nonlocal needed since state
   is a mutable object in the enclosing scope).

6. At end of function, before `return`, set:
   ```python
   state.steps_taken = step
   ```
   Then replace the `return { ... }` dict with:
   ```python
   return state.to_result_dict()
   ```

---

## Verification

CC must run after the edit:

```bash
cd /d/claude_code/ai-local-agent-tools
python -c "from api.routers.agent import _run_single_agent_step; print('import ok')"
python -m pytest tests/ -x -q 2>&1 | tail -20
```

Both must pass before committing.

---

## Version bump

Update `VERSION` file: `2.40.4` → `2.41.0`

---

## Commit

```
git add -A
git commit -m "refactor(agents): v2.41.0 StepState dataclass — consolidate _run_single_agent_step accumulators"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
