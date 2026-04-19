# CC PROMPT — v2.35.16 — Multi-direction strategy memo + recommended change

## TL;DR — recommended direction: **D (fix at source: last-step final_answer assignment)**

After v2.35.10→v2.35.15 (six consecutive prompts on drift / fallback / rescue
machinery), the structural invariant `status=completed ⇒ substantive
final_answer` is met. Further patches on rescue triggers have
diminishing returns. The next-highest-leverage change is to **fix the
root cause of the preamble/near-empty bug in the orchestrator**,
turning v2.35.14+15 rescues into a safety net rather than the primary
path. Concrete change in §Direction D below.

Kent: pick the direction you want. Everything after §Direction A is
optional context for that decision. Tests + commit + deploy sequence
appears at the end, scoped to whichever direction you choose.

---

## Verification results (completed before this prompt was written)

v2.35.15 deployed at commit `3ca8409` / build 631, 2026-04-19.

| Test | fa_len | status | notes |
|---|---|---|---|
| UniFi device status (op `62dfc5dd`) | 397 | completed | `STATUS: HEALTHY / FINDINGS:` — real synthesis, no rescue needed |
| PBS datastore health (op `9d289a6c`) | 301 | completed | **tool `status=ok`** (was `error` pre-v2.35.15) — Change 3 verified |
| Agent success rate audit (op `ed22215c`) | 1175 | completed | `empty_completion` rescue fired, LLM produced clean text via forced path |

Metrics at closeout:
```
deathstar_forced_synthesis_total{agent_type="status",reason="empty_completion"} 1.0
deathstar_forced_synthesis_fallback_total  (empty — LLM synthesis succeeded)
```

v2.35.15 acceptance criteria all met. Structural invariant holds.

---

## Direction A — Do nothing more on this area; ship v2.36.x elsewhere

**Thesis:** six drift/rescue prompts are enough. The invariant is met.
Further prompts on this problem are marginal.

**Cost:** 0 prompts. Frees budget for other concerns.

**Risk:** Some failure modes may still be lurking but unseen.

**Good fit if:** you want to broaden the investigation instead of
deepening it.

---

## Direction B — Close template coverage gaps

**Thesis:** the templates catalogue is partly tested. Run every
non-destructive template, categorize outcomes, document which work
cleanly vs rescue-dependent vs broken.

**Changes:** no code — testing + documentation only. Produces a
`docs/TEMPLATE_CATALOG_STATUS.md` artifact showing per-template
behaviour + follow-up work items.

**Cost:** ~0.5 prompts (testing + doc write, no engineering).

**Risk:** none (read-only).

**Good fit if:** you want a comprehensive health-check before
committing to any further engineering.

---

## Direction C — Drill into the 30.9% agent success rate

**Thesis:** `agent_performance_summary` reported **55 runs, 30.9%
success rate** in the past 24h. Over two-thirds of agent runs aren't
completing cleanly. Use the new tool to categorize failures and
identify the single most impactful fix.

**Process:**
1. Call `agent_performance_summary(hours_back=168)` for a larger sample.
2. For each of the top-10 failing task labels, pull 2-3 example
   `operation_id`s + their `/trace` digests.
3. Categorize root causes: hallucination_guard_exhausted, preamble-
   rescued (would have been empty without v2.35.14/15), drift-capped,
   SSH auth errors (the worker-host failures from op `b5328859`),
   other.
4. Pick the single highest-volume root cause and draft a targeted
   fix for it.

**Cost:** 1-2 prompts. Phase 1 = analysis doc, Phase 2 = the fix.

**Risk:** may reveal a problem outside agent-loop scope
(infrastructure, credentials, SSH profiles) that requires a
non-code fix.

**Good fit if:** you want to attack the highest-impact remaining
failure mode quantitatively.

---

## Direction D — **RECOMMENDED** — fix at source: last-step final_answer assignment

**Thesis:** v2.35.15's UniFi regression (`"I'll check the UniFi
network device stat..."` as `final_answer`) happened because the
orchestrator assigned an *aggregate* of assistant text across all
steps (or step-1 text when later steps had none) to `final_answer`.
v2.35.14/15 rescues now catch this, but they rescue by running
another LLM round — an expensive workaround for what is likely a
one-line orchestrator bug.

The fix:
- Find where `final_answer` gets assigned in the terminal write path.
- Change it from "aggregate of assistant content" or "first non-empty
  content" to **"the assistant content from the LAST tool-less step,
  or empty if every step was tool_calls-only"**.
- v2.35.14 `empty_completion` rescue then catches the clean-empty
  case (when the LLM never emitted text at all) and produces the
  proper synthesis via `run_forced_synthesis`.
- v2.35.15 `too_short_completion` / `preamble_only_completion`
  rescues become near-obsolete — they were compensating for a bug
  that's now gone. Keep them as a belt-and-suspenders safety net
  (no code removal), but they should stop firing in practice.

**Changes:**
1. Trace endpoint investigation: `/api/logs/operations/07d326a1-*/trace`
   to confirm the aggregation hypothesis (done as first step of the
   fix, not separately).
2. In `_stream_agent` or wherever `final_answer` is computed from
   step history, swap the logic from `step[0].content` (or whatever
   aggregator is there) to `steps[-1].content if
   steps[-1].finish_reason == "stop" else ""`.
3. Regression test: when all steps have `finish_reason=tool_calls`,
   final_answer MUST be empty (so rescue fires); when the last step
   has `finish_reason=stop` with content, that content becomes
   final_answer.
4. Re-run the 3 v2.35.15 acceptance tests — all should still pass.

**Cost:** 1 prompt, ~50-100 LOC if my hypothesis is right.

**Risk:** if aggregation is intentional (e.g., the orchestrator
builds up narrative text across steps), this change breaks cases
where the model legitimately emits text on every step. Mitigation:
the first step of the prompt is to read the orchestrator code +
confirm the hypothesis via the trace endpoint. If aggregation IS
intentional, pivot to "preserve aggregation but skip step-1 preamble
when final step emitted no text" — still one prompt, just slightly
different patch.

**Good fit if:** you want the rescue machinery to be a safety net,
not the primary path.

**Why I recommend it:**
- Lowest-friction: one targeted code fix vs a testing sweep (B) or
  multi-phase analysis (C).
- Highest-leverage: eliminates an entire class of bug upstream rather
  than catching its symptoms downstream.
- Lowest risk: the v2.35.14/15 rescues act as backstop if the fix is
  incomplete. Regression surface is small.
- Directly addresses the most common failure mode from v2.35.14's
  data point (5 of 5 steps had `finish_reason=tool_calls`, zero
  content) — in hindsight that IS the bug being masked.

---

## Direction E — Enrich LLM synthesis output with per-tool footer

**Thesis:** when forced_synthesis succeeds, the LLM produces prose
with no per-tool evidence rows. The programmatic fallback has them
(v2.35.13 `- vm_exec(worker-01) status=ok: snippet`), but the LLM
path doesn't. Both paths should offer operators the same level of
detail.

**Change:** append a "Tool evidence:" footer (populated by the same
`_best_snippet` logic used by the fallback) to every `run_forced_synthesis`
output, regardless of whether the LLM synthesis succeeded or the
programmatic fallback fired.

**Cost:** 1 prompt.

**Risk:** footer could annoy users who prefer clean prose. Could be
gated by a setting (`forcedSynthesisIncludeEvidence=true` default).

**Good fit if:** you value uniformity of output above all.

---

## Direction F — UI: verify / complete Trace viewer's Gates Fired panel

**Thesis:** v2.35.14+15 both added `empty_completion_rescued`,
`too_short_completion_rescued`, `preamble_only_completion_rescued`
signals to `gate_detection.py`. Haven't visually confirmed the
Trace viewer renders them. If the JS mirror (`gateDetection.js`)
wasn't updated, operators see an incomplete Gates Fired panel.

**Changes:** grep `gate_detection` in gui/src/, compare the Python
and JS versions, sync any missing entries. Add UI polish (colour
coding per rescue reason?).

**Cost:** 0.5-1 prompt.

**Risk:** none (frontend-only).

**Good fit if:** you want operator-facing polish as the next step.

---

## Direction G — Infrastructure round-trip (worker-03, Kafka, SSH auth)

**Thesis:** known-deferred items from project instructions are still
deferred. The SSH auth failures on VM host overview (most workers
returned `status=error` with a ~93-char error message) suggest a
credential-profile issue. Worker-03 was Down causing Kafka 2/3.
These aren't code fixes — they're infra ops.

**Changes:** no code. Use existing agent tools to investigate, then
manual fixes via Proxmox / Swarm.

**Cost:** 0 prompts (not code work).

**Risk:** reveals infra issues that may take real work.

**Good fit if:** you want to clear operational debt before coding further.

---

# Recommended: Direction D — implementation

If you agree with the recommendation, the rest of this prompt is
for CC to execute. If you want a different direction, ignore
everything below and tell me which one.

Version bump: 2.35.15 → 2.35.16.

## Step 1 — investigate (before any edit)

1. Read `api/routers/agent.py`. Find where `final_answer` is
   computed from the accumulated step history. Likely patterns:
   - `final_answer = "\n".join(s.content for s in steps if s.content)`
   - `final_answer = steps[0].content` when later steps lack content
   - `final_answer = last_non_empty_content`
2. Also pull the trace for op `07d326a1-*` (UniFi, fa_len=53) via
   `/api/logs/operations/{id}/trace?format=structured` and confirm:
   (a) step 0 had non-empty content that starts with `"I'll check"`,
   (b) steps 1..N had `content=""` and only `tool_calls`.
3. Confirm or refute the aggregation hypothesis.

## Step 2 — patch

Based on what step 1 reveals, apply ONE of:

**Patch A (aggregation confirmed):** change the final_answer
computation to:

```python
# v2.35.16: use LAST step's assistant content only, not aggregated.
# Earlier steps' text is typically "thinking preamble" before tool
# calls; aggregating it contaminates final_answer when the final
# LLM turn produced only tool_calls (no synthesis text). v2.35.14
# empty_completion rescue then correctly catches the empty case
# and runs run_forced_synthesis to produce a proper answer.
last_step = steps[-1] if steps else None
if last_step and last_step.get("finish_reason") == "stop":
    final_answer = (last_step.get("content") or "").strip()
else:
    # Last step was tool_calls-only or missing — let rescue handle it
    final_answer = ""
```

**Patch B (step-0-only used; aggregation NOT the issue):** different
patch. The preamble case must have a different root cause. CC: describe
what you found, stop, and ask Claude-Desktop for guidance.

**Patch C (steps use `finish_reason="length"` or other codes):** the
test `finish_reason == "stop"` may be too narrow. Consider
`finish_reason in ("stop", "length")` or inspect for content length
instead. CC: document the observed finish_reasons in a log comment.

## Step 3 — test

Extend the integration test from v2.35.14 (if one exists) OR create
`tests/test_final_answer_assignment.py`:

```python
"""v2.35.16 — regression test for final_answer assignment from step history.

Before v2.35.16: final_answer was aggregated from all steps' content,
so step-0 preamble ('I'll check...') leaked into final_answer even
when the final step emitted only tool_calls.

After v2.35.16: final_answer is the LAST step's content when that
step finished with 'stop', else empty (rescue handles empty).
"""

def test_all_tool_calls_yields_empty_final_answer():
    """When every step has finish_reason=tool_calls, final_answer is
    empty so the empty_completion rescue can fire."""
    steps = [
        {"content": "I'll check the UniFi status",
         "finish_reason": "tool_calls",
         "tool_calls": [{"id": "1", "function": {"name": "unifi_network_status"}}]},
        {"content": "",
         "finish_reason": "tool_calls",
         "tool_calls": [{"id": "2", "function": {"name": "result_fetch"}}]},
        {"content": "",
         "finish_reason": "tool_calls",
         "tool_calls": [{"id": "3", "function": {"name": "audit_log"}}]},
    ]
    # CC: adapt this call to whatever helper computes final_answer
    # in api/routers/agent.py. If no reusable helper exists, extract
    # the logic into one before asserting.
    result = compute_final_answer(steps)
    assert result == "" or result is None


def test_last_step_stop_content_becomes_final_answer():
    """When the last step has finish_reason=stop with content, that
    content is final_answer (no preamble leakage)."""
    steps = [
        {"content": "I'll check the UniFi status",
         "finish_reason": "tool_calls",
         "tool_calls": [{"id": "1", "function": {"name": "unifi_network_status"}}]},
        {"content": "STATUS: HEALTHY. 39 clients connected, all APs online.",
         "finish_reason": "stop",
         "tool_calls": []},
    ]
    result = compute_final_answer(steps)
    assert result == "STATUS: HEALTHY. 39 clients connected, all APs online."
    assert "I'll check" not in result  # no preamble leakage


def test_middle_step_content_not_aggregated():
    """Text from middle steps must not leak into final_answer."""
    steps = [
        {"content": "Let me gather the data first",
         "finish_reason": "tool_calls", "tool_calls": [{"id": "1"}]},
        {"content": "Now I have the results",
         "finish_reason": "tool_calls", "tool_calls": [{"id": "2"}]},
        {"content": "Summary: all green.",
         "finish_reason": "stop", "tool_calls": []},
    ]
    result = compute_final_answer(steps)
    assert result == "Summary: all green."
    assert "Let me gather" not in result
    assert "Now I have" not in result
```

## Step 4 — verify the existing test corpus still passes

Re-run the full test suite focused on forced_synthesis + rescue paths:

```bash
pytest tests/test_forced_synthesis_drift.py -v
pytest tests/test_empty_completion_path.py -v
pytest tests/test_preamble_detection.py -v
pytest tests/test_final_answer_assignment.py -v
pytest tests/ -v -k "synthesis or rescue or preamble or final_answer"
```

## Step 5 — `VERSION`

```
2.35.16
```

## Step 6 — commit

```bash
git add -A
git commit -m "fix(agents): v2.35.16 last-step final_answer assignment (kills preamble bug at source)

Root-cause fix for the preamble-only final_answer class of bug that
v2.35.14 (empty_completion) and v2.35.15 (too_short_completion,
preamble_only_completion) rescue machinery was catching. The
orchestrator was aggregating step-0 thinking text as final_answer
when later steps emitted only tool_calls — leaking preamble into
what operators saw.

New rule: final_answer is the LAST step's content when that step
finished with 'stop', else empty (rescue handles empty). Earlier
steps' text is treated as internal thinking, never persisted.

v2.35.14 empty_completion rescue now fires for the common case where
the LLM kept choosing tool_calls until budget-like exit. v2.35.15
rescues (too_short, preamble_only) should drop to near-zero fire
rate once this is deployed — they're retained as belt-and-suspenders
but the primary path no longer needs them.

3 new tests lock in the new behaviour: all-tool_calls→empty,
last-step-stop→stop-content, middle-step-text→excluded."
git push origin main
```

## Step 7 — deploy

```bash
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```

## Step 8 — post-deploy smoke

Run the 3 v2.35.15 acceptance tests again + verify:
- **UniFi:** either status=completed with real synthesis, OR
  status=completed with rescue fired (`empty_completion`, NOT
  `too_short`/`preamble_only`).
- **PBS datastore health:** unchanged behaviour (already works post-v2.35.15).
- **Agent success rate audit:** unchanged (already works via
  `empty_completion` rescue).

Metric goal: **no new `too_short_completion` or
`preamble_only_completion` firings after v2.35.16** over a sample of
10+ runs. If either does fire, the root cause was more subtle than
aggregation and we need to revisit.
