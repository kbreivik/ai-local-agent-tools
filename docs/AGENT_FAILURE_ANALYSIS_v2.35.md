# Agent Failure Analysis — v2.35.18

Two-phase drill on the 30.9% success-rate baseline captured during
v2.35.13 `agent_performance_summary` first run. Phase 1 here is
analysis-only; Phase 2 (landed in the same commit) is the single
targeted fix the analysis recommends.

---

## Aggregate state

Pulled via `agent_performance_summary` on deployed v2.35.17
(2026-04-19):

| Window | Total | Completed | Success | Delta from baseline |
|---|---|---|---|---|
| 168h | 143 | 84 | **58.7%** | +27.8 pts vs 30.9% |
| 24h  | 69  | 28 | **40.6%** | mix of pre- and post-v2.35.17 |

The 168h window is the reliable signal — it spans the bulk of
v2.35.10-17 rollout. Success rate has nearly doubled from the
baseline, which confirms the synthesis-rescue work (v2.35.10
programmatic fallback → v2.35.17 preamble leak fix) closed most of
the empty-completion failures that dominated the baseline. The
residual ~41% non-completed runs are a different population than
the original 69%.

### Per-(agent_type, status) breakdown (168h)

| agent_type | completed | capped | failed | error | escalated | other | success% |
|---|---|---|---|---|---|---|---|
| status     | 26 | **19** | 5 | 1 |  -  |  -  | 51%  |
| research   |  3 |  2 |  -  | 2 |  -  |  -  | 43%  |
| action     |  1 |  -  |  -  |  -  | 2 |  -  | 33%  |
| unknown    | 54 |  2 |  -  | 9 | 9 | 1 cancelled, 4 ok, 3 running | 66% |

"unknown" agent_type = WebSocket/free-form tasks where the router's
classifier doesn't run (or pre-routed batches). The classified
agents tell the real story: **status.capped = 19 runs, the single
largest failure bucket by a factor of 4×**.

### Top failing task labels (168h, count ≥ 2)

Every one of these failed with status=capped unless otherwise
noted:

1. VM-hosts health summary — 3× capped
2. PBS datastore health — 3× **failed** (hallucination_guard_exhausted)
3. DNS resolver chain health — 3× capped
4. Logstash/Elasticsearch correlation investigation — 2× capped
5. kafka_broker-3 + logstash status — 2× error (worker-03 is Down)
6. Disk usage across VM hosts — 2× capped
7. SSL certificate expiry audit — 2× capped
8. Container restart-loop detection — 2× capped
9. kafka_cluster degraded root-cause — 2× escalated (infra)

---

## Sampled traces

### Sample 1 — `dcb4c364` (PBS datastore health, failed)

- agent_type: status
- status_reason: `hallucination_guard_exhausted`
- 3 steps, **0 tool calls across all 3**
- Each step: `finish=stop tools=0 toks~6500`
- final_answer: fabricated from preflight facts
  (`PBS-Backup, 1006.9 GB, 2.5%`), while admitting GC status and
  task-success-rate are not collected
- v2.34.8 guard fired and rejected the run. **Working as designed.**

### Sample 2 — `b5328859` (VM-hosts health summary, capped)

This is the smoking gun. Verbatim trace:

```
Step 0 — finish=tool_calls tools=5 toks=6414
  vm_exec(hp1-ai-agent-lab,       "df -h && free -m && uptime && whoami")
  vm_exec(ds-docker-worker-01,    "df -h && free -m && uptime && whoami")
  vm_exec(ds-docker-worker-02,    "df -h && free -m && uptime && whoami")
  vm_exec(ds-docker-worker-03,    "df -h && free -m && uptime && whoami")
  vm_exec(ds-docker-manager-01,   "df -h && free -m && uptime && whoami")

Step 1 — 5× tool_result:
  {"status":"error","message":"Maximum two boolean chain operators
   allowed (got 3 in 'df -h && free -m && uptime && whoami')"}

  Agent re-plans, issues 3 split calls for hp1-ai-agent-lab only.

Step 2 — finish=stop tools=0 (Qwen emitted text-form <tool_call>
  blocks instead of proper tool_calls — not parsed).

→ budget cap 8/8 reached, programmatic_fallback fires,
  final_answer = [HARNESS FALLBACK] ...
```

The agent had the right plan (`1 call per host` — minimal,
correct). The command validator rejected it, forcing a 4× fan-out
that burns through the 8-call status budget before the fifth host
is even reached.

### Sample 3 — other capped ops

Spot-checked 9 further capped op finals: every single one starts
`[HARNESS FALLBACK] Agent reached tool-call budget-cap (8/8 tool
calls). The model failed to produce a clean synthesis ...`

The pattern is uniform across VM-health, DNS, disk-usage, cert
expiry, restart-loop, swarm-overlay, and storage-overview tasks.
All of them need ≥1 vm_exec per registered host. All of them
currently need ≥3 vm_exec per host because of the chain cap.

---

## Bucket categorisation

Sampled 12 non-completed ops across top-5 failing labels (5 PBS
failed, 5 VM-health capped, 1 restart-loop capped, 1 DNS capped).

| Bucket | Count | Share of sampled | Notes |
|---|---|---|---|
| `budget_cap_with_fallback` | 7 | 58% | ALL capped ops sampled |
| `hallucination_guard_exhausted` | 3 | 25% | PBS — collector gap, guard works |
| `hallucination_guard_exhausted` (PBS cluster) | 2 | 17% | same task, different sessions |
| `tool_auth_ssh` | 0 | 0% | no 93-char auth errors seen |
| `tool_signature` | 0 | 0% (direct); driver of `budget_cap_with_fallback` | |
| `tool_missing` | 0 | 0% | |
| `fabrication_detected_and_rejected` | 0 | 0% | |
| `subagent_spawn_failed` | 0 | 0% | |
| `infra_not_found` | (adjacent) | — | kafka_broker-3 errors are worker-03 Down, not code |
| `classifier_wrong` | 0 | 0% | |

`budget_cap_with_fallback` dominates at **58% of sampled
failures** and is the cause of every `status=capped` run. The
underlying trigger for nearly all capped runs is the same narrow
code artefact: **`_validate_command` in `mcp_server/tools/vm.py`
limits boolean chains to 2 operators (3 segments)**.

`hallucination_guard_exhausted` is real but a different population
(tasks referencing metrics the PBS collector doesn't yet surface)
and not code-addressable without collector work.

---

## Recommended Phase 2

### Selected bucket: `budget_cap_with_fallback` (via `tool_signature`/chain cap)

### Justification

- Highest-volume single bucket (58% of sampled, 19 capped ops in 168h).
- Narrowest, most targeted code change of any candidate —
  changing one integer in one validator plus one test.
- Safety model unchanged: each chain segment still validates
  independently against the allowlist and metachar set. Read-only
  operands, no exfiltration risk.
- Directly closes the dominant waste pattern in the sampled
  traces (4×-inflated tool call count on multi-host health tasks).

### File(s)

- `mcp_server/tools/vm.py` — `_validate_command` chain cap and
  the accompanying comment.
- `tests/test_vm_exec_hardening.py` — existing
  `test_validate_command_chain_depth_cap` currently asserts 4
  segments are rejected; update to reflect new cap and add a
  regression test for the exact failing pattern from Sample 2.

### Behaviour change

Chain-segment cap raised from 3 → 5 (max 4 boolean operators per
command). `df -h && free -m && uptime && whoami` — the literal
command in the failing traces — becomes accepted.

### LOC estimate

≤5 lines of production code, ≤15 lines of test code.

### Expected effect on the 30.9% baseline

For a 5-host VM health task, the chain cap forced roughly 3 calls
per host (split `df`, `free`, `uptime/whoami`). A 5-host budget-8
run hits the cap after 2-3 hosts. Raising the cap lets the agent
complete 5 hosts in 5 calls, well inside budget.

If half of the 19 status.capped runs are attributable to this
pattern (conservative), recovering them lifts the 168h success
rate from 58.7% to roughly 65% without touching any other path.

### Regression test

`test_vm_exec_hardening.py::test_validate_command_chain_depth_cap`
currently asserts a 4-segment command (`df -h && uptime && free
-m && uname -a`) is rejected. That exact command is the pattern
agents repeatedly emit. Update the test:

- 4-segment (3-operator) command → now accepted
- 6-segment (5-operator) command → still rejected with the
  "boolean chain operators" message

### Prometheus

No new counters — existing `VM_EXEC_CHAIN_COUNTER` already tracks
chain usage by operator. The `forced_synthesis_total{reason=...}`
and `agent_final_status_total` already surface cap-fallback.

---

## Phase 2 (as landed in this commit) — `budget_cap_with_fallback` fix

### Evidence

Sample 2 trace (`b5328859`) shows the agent issuing
`vm_exec("df -h && free -m && uptime && whoami")` on 5 hosts in
one batch — correct minimal plan — and being rejected by the 2-op
chain cap. All 10 sampled capped ops end in `[HARNESS FALLBACK]
... budget-cap (8/8 tool calls)`.

### Change 1 — `mcp_server/tools/vm.py`

Raise `chain_segments > 3` to `chain_segments > 5` in
`_validate_command`. Update the accompanying comment and error
message text to match. No other logic change — per-segment
validation, recursion depth, metachar blocking, and allowlist
enforcement are unchanged. `VM_EXEC_CHAIN_COUNTER` keeps working.

### Change 2 — `tests/test_vm_exec_hardening.py`

Update `test_validate_command_chain_depth_cap`:
- 4-segment command (`df -h && uptime && free -m && uname -a`)
  → asserted accepted (was: rejected)
- 6-segment command → asserted rejected with the "chain"/"boolean"
  error message.

Add `test_validate_command_four_chain_segments_the_vm_health_pattern`
pinning the exact observed command `df -h && free -m && uptime
&& whoami`.

### Prometheus

No new counters.

---

## Scope note

Did not touch any synthesis or rescue code (v2.35.10 / .13 / .14 /
.15 / .17). The invariant `status=completed ⇒ substantive
final_answer` is unchanged. `hallucination_guard_exhausted` on PBS
is a collector gap, not a code bug — deferred to a future
`pbs_gc_status` collector addition. `kafka_broker-3` errors are
infra (worker-03 is Down), not in scope.
