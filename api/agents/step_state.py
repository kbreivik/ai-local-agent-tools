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
    # Identity (immutable after init)
    session_id: str
    operation_id: str
    agent_type: str
    task: str
    parent_session_id: str = ""

    # Tool tracking
    tools_used_names: list = field(default_factory=list)
    tool_history: list = field(default_factory=list)       # v2.33.13: for contradiction detection
    substantive_tool_calls: int = 0                        # v2.34.8: hallucination guard counter

    # Signal counters
    positive_signals: int = 0
    negative_signals: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0

    # Execution flags
    audit_logged: bool = False                             # at most one audit_log per run
    degraded_findings: list = field(default_factory=list)  # research agents: degraded = findings
    plan_action_called: bool = False
    last_blocked_tool: str | None = None
    working_memory: str = ""                               # compact facts from <think> blocks
    budget_nudge_fired: bool = False                       # v2.33.3: 70% nudge fires at most once

    # Hallucination guard
    hallucination_block_fired: bool = False                # v2.34.8: legacy flag
    halluc_guard_attempts: int = 0                         # v2.34.14: retry counter
    halluc_guard_max: int = 3                              # from env AGENT_HALLUC_GUARD_MAX_ATTEMPTS

    # Fabrication detector
    fabrication_min_cites: int = 3                         # from env AGENT_FABRICATION_MIN_CITES
    fabrication_score_threshold: float = 0.5               # from env AGENT_FABRICATION_SCORE_THRESHOLD
    fabrication_detected_once: bool = False

    # Synthesis
    last_reasoning: str = ""
    empty_completion_synth_done: bool = False              # v2.35.14/15: idempotency guard
    render_tool_calls: int = 0                             # v2.36.9

    # Loop status
    final_status: str = "completed"
    steps_taken: int = 0

    # LLM trace
    trace_prev_msg_count: int = 0                          # v2.34.14: delta-index for trace writes
    trace_step_index: int = 0
    trace_is_subagent: bool = False
    trace_parent_op_id: str | None = None

    # Zero-result pivot
    zero_streaks: dict = field(default_factory=dict)       # tool_name -> consecutive zero count
    nonzero_seen: dict = field(default_factory=dict)       # tool_name -> best non-zero count seen
    zero_pivot_fired: set = field(default_factory=set)     # tools already nudged

    # In-run fact tracking
    run_facts: dict = field(default_factory=dict)          # v2.35.2: key -> {value, step, tool, ...}
    run_facts_persisted: bool = False                      # v2.45.25 — drain to known_facts_current

    # Propose dedup
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
            "steps_taken":            self.steps_taken,
            "prompt_tokens":          self.total_prompt_tokens,
            "completion_tokens":      self.total_completion_tokens,
            "run_facts":              self.run_facts,
            "fabrication_detected":   bool(self.fabrication_detected_once),
            "render_tool_calls":      self.render_tool_calls,
        }
