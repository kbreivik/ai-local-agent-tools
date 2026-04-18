# CC PROMPT — v2.34.16 — feat(ui): trace viewer + gates-fired digest + propose_subtask idempotency + service_placement signature

## Evidence

v2.34.15 deployed cleanly. The `/trace` endpoint let us verify all four
changes on live traffic in operation `00379abc` (commit `793248a`, build 612).
Three more findings emerged from that run — worth folding into v2.34.16
rather than spinning a new version each time.

### Summary of v2.34.15 verification

| Change | Result | Evidence |
|---|---|---|
| 1. Signature rendering | ✅ Works for kafka_consumer_lag | Char 9818: `kafka_consumer_lag(group='<group>')`. Step 0 call: `{"group":"logstash"}` first shot. `tool_signature_errors{kafka_consumer_lag}` unchanged from pre-deploy |
| 2. Prompt snapshot CI | ✅ Shipped | Counter declared, 0 divergence at startup |
| 3. Sanitizer scope | ✅ Works | `/api/health` returns `"version":"2.34.15"` clean; sanitizer fired 1× with `pattern="length_cap"` (narrow, not false positive) |
| 4. Budget truncate | ✅ Shipped | Counter declared; run stayed within budget (14/16) so truncate path not exercised. `subagent_spawns{outcome="rejected_budget"} 2.0` confirms budget-aware dispatch |

### Finding 1 — service_placement has the same signature regression

Parent run logged `tool_signature_errors_total{service_placement} 2.0`.
Prompt grep of `/trace`:

- Position 9313: `service_placement(kafka_broker-N)` — positional arg with no quotes, not a kwarg. Agent likely calls `service_placement(kafka_broker-N)` (unquoted → identifier error) or `service_placement()` (missing required arg).
- Position 20085: `Tier 1: kafka_broker_status → service_placement → swarm_node_status` — bare name without parens in a tool-chain arrow notation. Arguably fine because it's a conceptual chain, not a call example.
- Position 28667: TOOL SIGNATURES section, correct: `service_placement(service_name: str)`.

Same pattern as kafka_consumer_lag — TRIAGE example overrides reference section. Fix: route position 9313 through `render_call_example("service_placement", hint_args={"service_name": "'kafka_broker-N'"})`.

Expand the v2.34.15 scan-and-fix pass to cover ALL prescriptive examples, not just kafka_consumer_lag. Known candidates:

- `service_placement(service_name)` — at char 9313
- `kafka_exec(broker_label, command)` — check in KAFKA TRIAGE for bare-call usage
- `vm_exec(host, command)` — check in OVERLAY-LAYER DIAGNOSIS
- `container_discover_by_service(service_name)` — check in same block
- `container_tcp_probe(host, container_id, target_host, target_port)` — check
- `proxmox_vm_power(vm_label, action)` — ACTION_PROMPT
- `plan_action(...)` — too complex for render_call_example; leave for now

### Finding 2 — propose_subtask loops without idempotency

Parent trace (op 00379abc) shows FOUR `propose_subtask` calls with IDENTICAL args
across steps 4, 5, 6, 6 (two in step 6). Task body in every case:
`{"task":"Reschedule Logstash to fix Kafka broker 3 connectivity", "executable_steps":["docker service update --force logstash_logstash"], "manual_steps":[...]}`

Prometheus shows `subagent_spawns{outcome="spawned"} 2.0` and `{outcome="rejected_budget"} 2.0` — two accepted, two rejected.

Problem: parent doesn't know the first proposal is in flight or has been rejected, so it keeps asking. No harness message tells it "you already proposed this; wait for result or move on."

Two sub-issues:

- **No dedup on (task, executable_steps, manual_steps) within the parent's run.** Identical proposals should be rejected at the harness, not burn spawn budget.
- **No immediate harness feedback when a sub-agent terminates.** Parent doesn't see `sub_agent_done` until a later step, so in between it assumes its proposal is pending and keeps reproposing "to get a result."

### Finding 3 — parent correctly ignored fabricated sub-agent output

This is a WIN for v2.34.14, worth documenting here:

- Sub-agent c32d2fe2 (child of 00379abc) emitted `broker 3 (IP: 10.0.4.17) port 9092` — fabricated.
- Fabrication detector fired (`fabrication_detected{} 1.0`).
- `subagent_distrust_injected{reason="fabrication_detected"} 1.0`.
- Parent's final_answer uses its OWN step 1-4 evidence (overlay hairpin NAT on 192.168.199.33:9094) and does NOT pull in the fabrication.

The distrust plumbing works end-to-end on a real fabrication. No code change
needed here — just a celebratory paragraph in the CHANGELOG.

Version bump: 2.34.15 → 2.34.16 (UI-visible change + propose_subtask
semantics change — architectural).

---

## Change 1 — trace viewer in Logs UI

Add a new "Trace" subtab under the existing Logs view, selected operation
drives it.

### UI shape

```
Logs
├── Operations  (existing)
├── Sessions    (existing, if present)
├── Audit       (existing)
└── Trace       (NEW)
```

Trace tab layout (two-pane, responsive):

```
┌─────────────────┬──────────────────────────────────────────┐
│ STEPS           │ SELECTED STEP                            │
│                 │                                          │
│ #  tools  fin   │ ┌─ Assistant ──────────────────────────┐ │
│ 0  4      tc    │ │ "I'll investigate why Logstash..."   │ │
│ 1  3      tc    │ │                                      │ │
│ 2  2      tc    │ └──────────────────────────────────────┘ │
│ 3  2      tc    │                                          │
│ 4  2      tc  🚩│ ┌─ Tool calls ─────────────────────────┐ │
│ 5  2      tc    │ │ • kafka_broker_status()              │ │
│ 6  2      tc    │ │ • kafka_consumer_lag(group="logstash")│ │
│                 │ │ • elastic_cluster_health()           │ │
│ ─────────────   │ └──────────────────────────────────────┘ │
│ GATES FIRED     │                                          │
│ ✓ halluc_guard  │ ┌─ Tool results ───────────────────────┐ │
│ ✓ fabrication   │ │ [structured, collapsible per-call]   │ │
│ ✓ distrust inj  │ └──────────────────────────────────────┘ │
│ ─────────────   │                                          │
│ [Copy sys prompt│ ┌─ Harness injections ─────────────────┐ │
│  Download JSON] │ │ [system / user messages inserted     │ │
│                 │ │  by the harness in this step's delta]│ │
│                 │ └──────────────────────────────────────┘ │
└─────────────────┴──────────────────────────────────────────┘
```

### Component structure

New file `gui/src/components/TraceView.jsx`:

```jsx
export function TraceView({ operationId }) {
  const [trace, setTrace] = useState(null);
  const [selectedStep, setSelectedStep] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!operationId) return;
    setLoading(true);
    fetch(`/api/logs/operations/${operationId}/trace`, { credentials: 'include' })
      .then(r => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then(d => { setTrace(d); setError(null); })
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [operationId]);

  if (loading) return <div className="skeleton">Loading trace...</div>;
  if (error) return <div className="error">Failed to load trace: {error}</div>;
  if (!trace) return <div className="muted">Select an operation</div>;

  return (
    <div className="trace-view">
      <div className="trace-steps">
        <StepList steps={trace.steps}
                  selected={selectedStep}
                  onSelect={setSelectedStep} />
        <GatesFired steps={trace.steps} />
        <TraceActions systemPrompt={trace.system_prompt}
                      operationId={operationId} />
      </div>
      <div className="trace-detail">
        <StepDetail step={trace.steps[selectedStep]} />
      </div>
    </div>
  );
}
```

Sub-components:

- `StepList` — renders each step as a row: step_index, tools_count badge, finish_reason chip, small 🚩 marker if the step has any "gate fired" signal (detected via `messages_delta` containing `[harness]` or by tool result names).
- `GatesFired` — scans all steps for known guard signals and displays a summary section: hallucination_guard_attempts, fabrication_detected, subagent_distrust_injected, budget_truncate, sanitizer_blocks, budget_nudges. Each with count per type.
- `StepDetail` — renders selected step's assistant content, tool_calls (parsed JSON args), tool_results (collapsible per call), and any `messages_delta` items with role=system/user that were injected.
- `TraceActions` — two buttons: "Copy system prompt" (writes to clipboard) and "Download full JSON" (triggers blob download of the full trace object).

Styling follows v2.34.x's existing Logs tab — same borders, same monospace for technical text, same chip patterns.

### Routing

Add to `gui/src/App.jsx` (or wherever the Logs tab layout is defined):

```jsx
<TabPanel label="Trace" value="trace">
  <OperationPicker selected={selectedOpId} onChange={setSelectedOpId} />
  <TraceView operationId={selectedOpId} />
</TabPanel>
```

### Gate detection heuristics

The `GatesFired` component walks the trace and categorises each step:

```js
function detectGates(steps) {
  const gates = {
    halluc_guard: { count: 0, details: [] },
    fabrication: { count: 0, details: [] },
    distrust: { count: 0, details: [] },
    budget_truncate: { count: 0, details: [] },
    budget_nudge: { count: 0, details: [] },
    sanitizer: { count: 0, details: [] },
  };

  steps.forEach((s, i) => {
    (s.messages_delta || []).forEach(m => {
      const c = m.content || '';
      if (c.includes('[harness]') && c.includes('substantive tool call')) {
        gates.halluc_guard.count++;
        gates.halluc_guard.details.push({ step: i, snippet: c.slice(0, 120) });
      }
      if (c.includes('[harness]') && c.includes('flagged') && c.includes('fabrication')) {
        gates.distrust.count++;
        gates.distrust.details.push({ step: i, snippet: c.slice(0, 120) });
      }
      if (c.includes('[harness]') && c.includes('Tool budget')) {
        gates.budget_truncate.count++;
        gates.budget_truncate.details.push({ step: i, snippet: c.slice(0, 120) });
      }
      if (c.includes('HARNESS NUDGE') && c.includes('propose_subtask')) {
        gates.budget_nudge.count++;
        gates.budget_nudge.details.push({ step: i, snippet: c.slice(0, 120) });
      }
      if (c.includes('[REDACTED]')) {
        gates.sanitizer.count++;
      }
    });
  });
  return gates;
}
```

Render as compact list in the left sidebar; clicking a detail jumps to that step.

### No-trace fallback

Some older operations (pre-v2.34.14) have no trace data. Endpoint returns
404 in that case. Show friendly message:

```jsx
<div className="muted">
  No trace data for this operation.
  Trace persistence was added in v2.34.14 (retention: 7 days).
</div>
```

## Change 2 — `format=digest` gets a "Gates fired" section

Update the `_render_digest` function in the trace endpoint handler to
include a top-of-output gates summary, matching the UI.

```python
def _render_digest(sp_row, step_rows) -> str:
    lines = []
    if sp_row:
        lines.append(f"# System prompt: {sp_row['prompt_chars']} chars, "
                     f"{sp_row['tools_count']} tools exposed")
        lines.append("")

    # NEW: gates-fired summary
    gates = _detect_gates_from_steps(step_rows)
    if any(g["count"] > 0 for g in gates.values()):
        lines.append("## Gates fired")
        for name, info in gates.items():
            if info["count"] > 0:
                lines.append(f"- **{name}**: {info['count']}× "
                             f"(steps: {', '.join(str(d['step']) for d in info['details'][:5])})")
        lines.append("")

    # Existing step rendering
    for r in step_rows:
        ...
    return "\n".join(lines)
```

Where `_detect_gates_from_steps` mirrors the JS logic above in Python. Put
both in a shared module `api/agents/gate_detection.py` so the UI can fetch
a pre-computed summary via `/trace?format=gates` if needed later.

## Change 3 — propose_subtask idempotency within a parent run

### Dedup key

In `api/routers/agent.py` (or wherever propose_subtask is handled in the
in-band spawn path), compute a canonical key per proposal:

```python
import hashlib
import json

def _subtask_dedup_key(proposed_args: dict) -> str:
    """Stable hash of the proposal shape, for within-run dedup."""
    canonical = {
        "task": (proposed_args.get("task") or proposed_args.get("objective") or "").strip(),
        "executable_steps": proposed_args.get("executable_steps") or [],
        "manual_steps": proposed_args.get("manual_steps") or [],
    }
    blob = json.dumps(canonical, sort_keys=True, separators=(',', ':'))
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]
```

### Track in parent run state

Keep a `set` on the parent's run context:

```python
# At start of parent run
state.proposed_subtask_keys = set()
state.proposed_subtask_map = {}   # key -> {status, sub_op_id, proposed_at_step}
```

### On each propose_subtask

```python
def handle_propose_subtask(args, state, step_index):
    key = _subtask_dedup_key(args)

    if key in state.proposed_subtask_keys:
        prior = state.proposed_subtask_map[key]
        increment_metric(PROPOSE_DUPLICATE_COUNTER, {"prior_status": prior["status"]})

        inject_harness_message(
            f"[harness] You already proposed this exact subtask at step "
            f"{prior['proposed_at_step']} (sub_op_id={prior.get('sub_op_id','<pending>')}, "
            f"status={prior['status']}). Do NOT re-propose. Your options: "
            f"(a) wait for the prior sub-agent result in your next turn, "
            f"(b) propose a DIFFERENT subtask with different steps, "
            f"(c) synthesise your own final_answer from evidence gathered so far, "
            f"(d) call escalate() if you cannot make progress.",
            role="system",
        )
        return {"status": "duplicate_proposal", "key": key, "prior": prior}

    state.proposed_subtask_keys.add(key)
    state.proposed_subtask_map[key] = {
        "status": "pending",
        "sub_op_id": None,
        "proposed_at_step": step_index,
    }

    # ... continue with existing spawn logic, update status to "spawned" / "rejected_budget"
```

### On sub-agent terminal state

When sub-agent finishes (completed/escalated/failed), update the map entry:

```python
def on_subagent_terminal(sub_op_id, terminal_status, state, dedup_key):
    if dedup_key in state.proposed_subtask_map:
        state.proposed_subtask_map[dedup_key]["status"] = terminal_status
        state.proposed_subtask_map[dedup_key]["sub_op_id"] = sub_op_id
```

### Metric

```python
PROPOSE_DUPLICATE_COUNTER = Counter(
    "deathstar_propose_subtask_duplicate_total",
    "propose_subtask calls rejected as duplicates of an earlier proposal in the same parent run",
    ["prior_status"],  # pending | spawned | rejected_budget | completed | escalated | failed
)
```

### Test

`tests/test_propose_dedup.py`:

```python
def test_identical_proposal_rejected_on_second_call():
    state = make_parent_state()
    args = {
        "task": "Reschedule X",
        "executable_steps": ["docker service update --force X"],
        "manual_steps": [],
    }
    r1 = handle_propose_subtask(args, state, step_index=4)
    assert r1["status"] != "duplicate_proposal"

    r2 = handle_propose_subtask(args, state, step_index=5)
    assert r2["status"] == "duplicate_proposal"
    assert r2["key"] == r1["key"]

def test_different_task_not_duplicate():
    state = make_parent_state()
    handle_propose_subtask({"task": "A", "executable_steps": []}, state, 4)
    r2 = handle_propose_subtask({"task": "B", "executable_steps": []}, state, 5)
    assert r2["status"] != "duplicate_proposal"

def test_dedup_key_stable_across_arg_order():
    args_a = {"task": "X", "executable_steps": ["a", "b"], "manual_steps": []}
    args_b = {"manual_steps": [], "executable_steps": ["a", "b"], "task": "X"}
    assert _subtask_dedup_key(args_a) == _subtask_dedup_key(args_b)
```

## Change 4 — immediate harness feedback on sub-agent terminal state

Currently, when a sub-agent terminates, the parent doesn't see the result
until harness feeds `sub_agent_done` as a tool_result in a subsequent step.
Between sub-agent termination and that tool_result landing, the parent can
repropose or drift.

### Fix

When a sub-agent reaches terminal state, queue a harness system message to
be delivered BEFORE the parent's next completion call (alongside the
`sub_agent_done` tool_result, not after). Shape:

```python
def on_subagent_terminal(sub_op_id, terminal_status, final_answer, fabrication_detail,
                          halluc_guard_detail, state, dedup_key):
    # update dedup map (from Change 3)
    if dedup_key in state.proposed_subtask_map:
        state.proposed_subtask_map[dedup_key]["status"] = terminal_status

    # Decide what to inject
    warnings = []
    if halluc_guard_detail and halluc_guard_detail["fired"]:
        warnings.append(
            f"Sub-agent's hallucination guard fired {halluc_guard_detail['attempts']}× "
            f"before terminating."
        )
    if fabrication_detail and fabrication_detail["score"] > 0.5:
        warnings.append(
            f"Sub-agent output cited {len(fabrication_detail['fabricated'])} tools "
            f"that did not run: {', '.join(fabrication_detail['fabricated'][:5])}. "
            f"Do NOT treat its EVIDENCE block as factual."
        )

    if terminal_status == "escalated":
        warnings.append(
            f"Sub-agent ESCALATED (did not execute). Your proposed action "
            f"was not performed; operator must decide."
        )
    elif terminal_status == "failed":
        warnings.append(
            f"Sub-agent FAILED. Consider a different approach or escalate yourself."
        )

    if warnings:
        state.queued_harness_messages.append(
            f"[harness] Sub-agent {sub_op_id[:8]} returned status={terminal_status}. "
            + " ".join(warnings)
            + " Do NOT repeat the same propose_subtask. Review your evidence and "
            + "either synthesise a final_answer or take a different action."
        )
```

On the parent's next turn, inject all queued harness messages as `role=system`
entries AHEAD of any new tool_results. They appear in `messages_delta` so the
UI's GatesFired detector picks them up.

### Test

`tests/test_subagent_terminal_feedback.py`:

```python
def test_escalated_subagent_injects_harness_warning():
    parent_state = make_parent_state()
    # simulate subagent that escalated with a fabricated answer
    on_subagent_terminal(
        sub_op_id="sub-abc", terminal_status="escalated",
        final_answer="EVIDENCE: container_tcp_probe(...) → ok",
        fabrication_detail={"score": 0.9, "fabricated": ["container_tcp_probe"]},
        halluc_guard_detail=None,
        state=parent_state, dedup_key="key-xyz",
    )
    assert len(parent_state.queued_harness_messages) == 1
    msg = parent_state.queued_harness_messages[0]
    assert "escalated" in msg.lower()
    assert "container_tcp_probe" in msg
    assert "do NOT repeat" in msg.lower()
```

## Change 5 — service_placement + full scan-and-fix for TRIAGE examples

Extend v2.34.15's render_call_example pass to cover every prescriptive call
example in RESEARCH_PROMPT, STATUS_PROMPT, ACTION_PROMPT.

### Identify call sites

In `api/agents/router.py` (or wherever prompts are built), grep for any
`<tool_name>(` patterns that are inside the prompt body (not TOOL SIGNATURES
section) and verify they're either (a) correctly formatted with quoted args
or (b) rendered via render_call_example.

Known to fix from /trace analysis of op 00379abc:

Position 9313:
```
3. service_placement(kafka_broker-N) — map broker id to Swarm node.
```
→
```
3. {render_call_example("service_placement", hint_args={"service_name": "'kafka_broker-N'"})} — map broker id to Swarm node.
```

Position 20085 (Tier 1 chain):
```
Tier 1 (always): kafka_broker_status → service_placement → swarm_node_status
```
Leave as-is — it's a conceptual chain, not a call example. Model should know
from TOOL SIGNATURES that service_placement requires service_name.

### Complete scan procedure

Walk RESEARCH_PROMPT / STATUS_PROMPT / ACTION_PROMPT source (after rendering).
For each occurrence of `{tool_name}(` where tool_name is in our tool registry
and where the following chars match the bare-parens regex
`[a-z_]+\([^\w'"][^)]*\)` OR `[a-z_]+\(\)`:

1. Check if the tool has required args (via signature introspection).
2. If yes, replace with a rendered example using `render_call_example`.
3. If no, leave as-is — bare parens are correct for zero-arg tools.

### Acceptance

After deploy, re-run canonical Logstash task. Check `/trace`:
- Char position of `service_placement(kafka_broker-N)` should now be a proper
  quoted-arg call.
- Prometheus: `deathstar_tool_signature_errors_total` should NOT increment
  for service_placement on the re-run.

## Change 6 — Prometheus metrics

Add to `api/metrics.py`:

```python
PROPOSE_DUPLICATE_COUNTER = Counter(
    "deathstar_propose_subtask_duplicate_total",
    "propose_subtask calls rejected as duplicates of an earlier proposal in the same parent run",
    ["prior_status"],
)

SUBAGENT_TERMINAL_FEEDBACK_COUNTER = Counter(
    "deathstar_subagent_terminal_feedback_total",
    "Harness feedback messages injected into parent after a sub-agent terminated",
    ["terminal_status"],   # completed | escalated | failed
)
```

## Change 7 — CHANGELOG

```markdown
## v2.34.16 — trace viewer + propose_subtask idempotency + service_placement signature fix

**UI:** New Trace subtab under Logs. Per-step view of the exact system prompt
and every LLM message that shipped during an agent run. Includes a
"Gates fired" summary that aggregates hallucination guard attempts,
fabrication-detector fires, parent-side distrust injections, budget nudges
and truncations, and sanitizer blocks. Closes the loop on v2.34.14's
trace-persistence work.

**Agent harness:** propose_subtask now deduplicates identical proposals
within a single parent run. Repeating the same {task, executable_steps,
manual_steps} tuple triggers a harness message explaining the situation
and offering four clear next steps. Sub-agent terminal states
(completed/escalated/failed) now surface to the parent immediately via a
harness system message, alongside any fabrication_detector or
hallucination_guard findings from the sub-agent. Parent can no longer
silently repropose a subtask while waiting for an in-flight sub-agent.

**Prompts:** Second Option-B pass caught service_placement examples with
bare-parens / positional-arg shorthand in KAFKA TRIAGE; all prescriptive
call examples now render from tool signatures.

**Celebration:** v2.34.14's fabrication detector + parent-side distrust
fired in production for the first time on op 00379abc. Sub-agent
c32d2fe2 emitted fabricated IP 10.0.4.17 and port 9092. Parent
correctly ignored it and synthesised from its own diagnostic evidence.
End-to-end working as designed.
```

## Version bump

Update `VERSION`: `2.34.15` → `2.34.16`.

## Commit

```
git add -A
git commit -m "feat(ui): v2.34.16 trace viewer + gates-fired digest + propose_subtask idempotency + service_placement signature"
git push origin main
```

## How to test after push

1. Redeploy `hp1_agent`. Confirm `/api/health` shows `2.34.16`.
2. Navigate to **Logs → Trace**. Select op `00379abc` (from prior run).
   - Step list renders with finish_reason chips
   - Click step 0 → see assistant text + 4 tool calls + 4 tool results
   - Click "Copy system prompt" → 29700 chars on clipboard
   - Click "Download full JSON" → .json file downloaded
   - "Gates fired" sidebar shows: fabrication_detected 1× (from sub-agent)
3. `pytest tests/test_propose_dedup.py -v` → passes.
4. `pytest tests/test_subagent_terminal_feedback.py -v` → passes.
5. Snapshot test: `pytest tests/test_prompt_snapshots.py --update-snapshots`
   then commit the diff (service_placement example change will surface
   there).
6. Re-run canonical Logstash investigate task. Pull /trace on the new
   operation:
   - No duplicate `propose_subtask` calls visible
   - `deathstar_tool_signature_errors_total{service_placement}` stays at
     its pre-run value (no new TypeError)
   - `deathstar_propose_subtask_duplicate_total` increments if the LLM
     tries to re-propose (shouldn't, but if it does, harness catches it)
   - `deathstar_subagent_terminal_feedback_total{escalated}` increments
     if a sub-agent escalates
7. Force the dedup path: craft a test task that triggers two identical
   propose_subtask calls (the LLM's behaviour from today's op is a fine
   fixture). Verify parent receives a `[harness]` distrust injection in
   the trace and stops reproposing.

## Non-goals / deferred to v2.34.17 / v2.35

- Trace viewer enhancements (keyboard nav, step filtering by gate type,
  side-by-side step diff) — iterate after real usage
- Dedup across separate parent runs of the same task — out of scope,
  different concern (would want task-level replay detection)
- Interactive "replay this trace with a different prompt" button — great
  feature, scope for v2.35+
- known_facts table with confidence scoring (v2.35 phase)
- Runbook-based TRIAGE extraction (v2.35 phase)
- Entity preflight against infra_inventory (v2.35 phase)

## Risk register

- The Gates Fired detector is based on string-matching `[harness]` markers
  in messages_delta. If a future harness message doesn't use that marker,
  the detector misses it. Mitigation: add a test that asserts every
  harness-injected system message contains `[harness]`. Put this in
  `tests/test_prompt_snapshots.py` at least as a style check.

- The trace viewer loads the entire trace JSON up front (~30KB system
  prompt + step data). For 50-step runs this could get heavy. Mitigation:
  `/trace?format=digest` for fast scan, full structured only on demand.
  Endpoint already supports this.

- `propose_subtask_duplicate_total{prior_status="pending"}` could spike
  if an LLM spams proposals while waiting. That's the feature working
  correctly — document in the metric HELP text.

- The dedup key is a SHA1 prefix (16 chars). Collision is astronomically
  unlikely within a single run's propose_subtask volume, but worth noting.

- UI-side gate detection duplicates server-side logic. Put both in
  `api/agents/gate_detection.py` + `gui/src/utils/gateDetection.js` and
  keep them in sync. A snapshot test on a known trace fixture should
  assert both sides detect the same gates.
