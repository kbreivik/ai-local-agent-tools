# SPEC MEMO — v2.36.8 — `result_render_table` and the render-and-caption grammar

**Status:** draft for Kent's review • 2026-04-20
**Author:** Claude Desktop (architect side)
**Targets:** v2.36.8 (tool + wiring) — will split if scope grows

---

## 1 · Problem

Large-list observe tasks thrash. Canonical trace: UniFi clients task
2026-04-20 21:49:59, 12 substantive tool calls, `status=completed` via
empty-completion rescue. Tool sequence:

| Step | Tool              | Ref                  | Row count   |
|------|-------------------|----------------------|-------------|
| 1    | unifi_network_status | rs-fae20305249f    | 42          |
| 2    | result_fetch      | rs-fae20305249f      | 42 of 42    |
| 3    | result_fetch      | rs-be6bea558ed1      | 42 of 42    |
| 4    | result_query      | rs-fae20305249f      | 42          |
| 5    | result_fetch      | rs-bd8393a382df      | 42 of 42    |
| 6    | result_fetch      | rs-9a3591179b31      | 42 of 42    |
| 7    | result_query      | rs-fae20305249f      | 42          |
| 8    | result_fetch      | rs-2f09c69d4739      | 42 of 42    |
| 9    | result_query      | rs-fae20305249f      | 42          |
| 10   | result_fetch      | rs-fae20305249f      | 42 of 42    |
| 11   | result_fetch      | rs-fb9effe4e975      | 37 of 42    |
| 12   | result_fetch      | rs-fb9effe4e975      | 32 of 42    |

Agent never transitions to synthesis. v2.35.14 `empty_completion` rescue
fires. Budget didn't save it (12/24 used). Doubling the budget would
just extend thrashing.

The pattern isn't UniFi-specific. Any task of shape **"list all X
with attributes Y"** where the count is >15 and the row payload is
non-trivial hits the same failure. The LLM has the data (via fetched
refs), but the act of writing the 42-row enumeration as prose is
expensive token-wise and the model keeps picking another fetch as an
easier next action.

## 2 · Why existing primitives don't close the loop

`result_store` (DB) + `result_fetch` + `result_query` already provide
the DB-as-memory substrate Kent described:

- Tool produces large result → stored with ref token
- Agent calls `result_fetch(ref)` → raw items come back as JSON
- Agent calls `result_query(ref, where=…)` → filtered items come back as JSON

Both tools return **data to the LLM's context**, which the LLM then has
to verbally describe. That verbal description step is where the run
dies. The agent ends up repeatedly testing the data ("is it really 42?
are all the columns there? let me fetch again with different cols…")
because fetching is cheap for it and writing is expensive.

## 3 · Proposed primitive

**`result_render_table(ref, columns?, where?, order_by?, caption?, limit?)`**

Renders a stored result as a markdown table and **writes it directly to
`operations.final_answer`** (or appends to it, optionally prefixed with
a caption). Returns to the agent a tiny acknowledgement — NOT the table
data.

```python
result_render_table(
    ref="rs-fae20305249f",
    columns="hostname,ip,mac,ap_name,signal",
    order_by="ap_name, hostname",
    caption="All 42 UniFi clients with their APs:",
)
# Returns to agent:
{
  "status": "ok",
  "message": "Rendered 42 rows to operation output (4823 chars, 7 columns).",
  "data": {
    "row_count": 42,
    "columns_used": ["hostname", "ip", "mac", "ap_name", "signal"],
    "output_length": 4823,
    "truncated": false,
  }
}
```

The LLM's context grows by ~100 chars (the message above) instead of
~8KB (42 rows × ~200 chars each). The user's view of `final_answer`
gets the full rendered table inline.

### Key design properties

1. **Render goes to DB's `operations.final_answer` field, not LLM
   context.** The existing final_answer write path (via
   `set_operation_final_answer`) gains a parallel append-path.
2. **Agent writes a caption, not the data.** New grammar: call the
   tool, optionally write a one-line wrapper sentence, done. No
   enumeration of rows in prose.
3. **Column choice is explicit.** Agent declares which columns to
   render (from the `columns` metadata already stored on result_store
   rows). Prevents "I'll just fetch everything and see". If `columns`
   is omitted, render tool picks up to 6 most-informative columns via
   a small heuristic (prefer name/id/ip/mac/status fields, skip
   very-wide text columns).
4. **Filtering inherited from `result_query`.** Same `where` and
   `order_by` clauses — no new query language.
5. **Hard row cap.** Default 50, max 200. If `where` yields more,
   render truncates and writes `(showing first 200 of N)` footer.
   Agent is prompted (harness-side) to use a more specific `where`.
6. **Idempotent.** Same ref + same args = same output. Agent can call
   it once per run per logical view.

## 4 · Output channel

Two options, pick one:

### Option A — append to `operations.final_answer`

On call, server reads current `operations.final_answer`, appends the
caption + rendered table, writes back. Agent's eventual own synthesis
can either be absent (render tool output IS the answer) or can be
prepended via a follow-up `set_operation_final_answer` call that
preserves the table.

**Pro:** simplest. Existing column, existing UI renders markdown in
the Operations view.
**Con:** agent and harness both writing to the same field. Needs clear
rules about order and concatenation.

### Option B — new `operations.rendered_output` column

Separate column. UI concatenates `final_answer` (caption prose) +
`rendered_output` (table) for display. Trace viewer shows them as
separate sections.

**Pro:** clean separation of LLM-authored prose from tool-authored
data.
**Con:** schema change, UI change, migration.

**Recommendation: A for v2.36.8, B for v2.37.0 if the pattern proves
out.** Ship the tool behind a flag, validate the grammar, then upgrade
the schema when we know what we want.

## 5 · Agent-side grammar change

New section injected into `STATUS_PROMPT` (and `RESEARCH_PROMPT` for
data-heavy investigate tasks), positioned AFTER `CONTAINER INTROSPECT
FIRST` and BEFORE the domain-specific branches. Draft content:

```
═══ LARGE-LIST RENDERING ═══

When a tool returns result_ref and the task asks you to "list",
"show", "report", or "audit" those items for the user — DO NOT
loop on result_fetch / result_query trying to describe the data in
prose. Instead:

1. ONE result_fetch with limit=5 to confirm the shape / pick columns.
2. Call result_render_table(ref, columns=...) with the columns the
   user asked about. This writes the full formatted table to the
   operation output directly.
3. Write ONE summary line as your final_answer (e.g. "All 42 UniFi
   clients with their APs and signal strengths (table below)").

You do NOT need to describe each row. The table is already visible
to the operator.
```

Crucially: the prompt also gets a concrete example for each observe
domain (UniFi, kafka, containers, swarm) that shows the
three-call pattern. Matches the v2.34.13 lesson — prescriptive
examples win against abstract instructions.

## 6 · DB-as-memory threshold

Kent's threshold question: "use db as memory and collect info when
total info exceeds thresholds". This is already live via
`result_store`'s `_LARGE_RESULT_BYTES` threshold in `api/db/result_store.py`.
Current behaviour: when a tool returns >8KB (tunable), data is stored
with ref, only a 5-item preview + ref goes to the LLM. So the
infrastructure is in place.

What v2.36.8 adds on top: the render tool that reads the stored data
**server-side** (never loaded into LLM context at render time) and
emits directly to the operator-visible output. That's the "collect
info when thresholds exceed" loop closed.

No threshold changes needed for v2.36.8 — existing thresholds already
trigger result_store for payloads big enough to matter.

## 7 · Interaction with existing gates

| Gate                          | Behaviour under render tool                                    |
|-------------------------------|----------------------------------------------------------------|
| Hallucination guard           | Counts `result_render_table` as substantive (writes user output). |
| Fabrication detector          | Operates on caption prose only, ignores rendered table section. |
| `empty_completion` rescue     | **Must not fire** if render tool wrote ≥500 chars to `final_answer`. Check `final_answer` length, not just agent-side prose buffer. |
| `too_short_completion` rescue | Same logic — render-written content counts toward length. |
| `preamble_only_completion`    | Caption "here's the table" is preamble-shaped but has the table following it. Detector needs a "content after me?" check. |
| Budget cap                    | Unchanged. Tool counts as 1. |
| Contradiction detector (v2.35.2) | Ignores rendered-table content — scans only the caption prose. |

The `empty_completion` and `too_short_completion` rescues are the
trickiest — they currently check agent-side `final_answer` buffer
length. They need to check DB `operations.final_answer` length instead,
which includes render tool writes. This is a small but real change in
the v2.35.14 / v2.35.15 logic.

## 8 · Migration strategy

Two-phase rollout via Settings flag:

**Phase 1 — Dark launch (v2.36.8):**
- Tool ships, registered in observe + investigate allowlists.
- Prompt section added behind `renderToolPromptEnabled=False` (default).
- Existing v2.35.14/15 rescues work as today; `final_answer` reads
  from DB so they correctly see render-tool writes if the tool fires.
- New Prometheus counter `deathstar_render_tool_calls_total{outcome}`.
- Manual testing: flip flag on, run UniFi task, compare trace.

**Phase 2 — Promotion (v2.36.9 or later):**
- Flip `renderToolPromptEnabled=True` default.
- Move prompt section to always-on.
- Add gate-detection row `render_used` to Trace viewer sidebar.
- If needed, add caption-length minimum to prompt (≥20 chars).

## 9 · Open questions — NEED KENT'S CALL

**Q1 · UI rendering of markdown tables in Operations view.**
Current Operations-view `final_answer` renders as pre-wrap text (no
markdown). A markdown table would render as pipe-delimited lines, not
as a visual table. Options:
- (a) Ship as-is, table renders as monospace pipes (readable but
  ugly), upgrade to real markdown render in v2.37.
- (b) v2.36.8 includes a minimal markdown-to-HTML pass in the
  Operations view for tables + code blocks only.
- (c) Render tool emits HTML directly (rejected — breaks if anyone
  pastes `final_answer` elsewhere).

**My lean:** (a) for v2.36.8, (b) for v2.37.0. Gets the grammar win
first without blocking on UI work.

**Q2 · Where does the render tool dispatch the write?**
- (a) Synchronous write inside the MCP tool via
  `set_operation_final_answer` / an append variant. Simple but
  couples MCP tool code to the DB layer.
- (b) Tool returns the markdown in its result envelope, harness
  detects `data.render_markdown` and dispatches the write. Clean
  separation but more moving parts.

**My lean:** (b). Keeps MCP tools as pure data transforms; harness
handles I/O. Also means rendered content flows through trace
persistence cleanly.

**Q3 · What does the agent's final_answer prose look like when the
render tool has written the table?**
- (a) Harness auto-composes: `[agent caption]\n\n[rendered table]`.
  Agent's synthesis step runs normally, its output prepended.
- (b) Render tool supplies the caption too (as `caption` arg), agent
  synthesis is suppressed when render fired.
- (c) Agent writes final_answer normally, render tool's output is
  appended underneath regardless of what agent said.

**My lean:** (a). Cleanest operator mental model — the caption you
see is LLM-authored, the table below is tool-authored. Agent still
gets to put its one-line framing in.

**Q4 · Observe vs investigate scope for v2.36.8.**
- (a) Observe only. Lists and status checks.
- (b) Observe + investigate. Also useful for "what containers are
  on worker-03" diagnostic steps.
- (c) All four agent types. Execute runs might want to render
  pre-action audit tables.

**My lean:** (b). Execute's grammar is different (plan + act), not
a render-fit. Investigate benefits when a diagnostic needs a
structured peek at current state.

**Q5 · Does the render tool respect the v2.35.3 fact-age rejection
gate?**
result_render_table reads straight from result_store — it doesn't
re-run a tool call. Data in result_store is a snapshot from whenever
the original tool fired. If minutes elapsed and a high-confidence
fact now contradicts the stored data, the rendered table could be
stale.

**My lean:** mark it exempt for v2.36.8 (tool is pulling from a
named, time-stamped ref — operator can see when the ref was
created). Revisit if we see false confidence problems in practice.

## 10 · Scope guard

v2.36.8 **does not**:
- Touch result_fetch / result_query behaviour.
- Change result_store TTL or thresholds.
- Add new UI views.
- Change existing prompt structure outside the new `LARGE-LIST
  RENDERING` section.
- Affect execute or build agent paths.
- Touch the fabrication detector or hallucination guard logic.

## 11 · What v2.36.8 ships (assuming Kent approves all leans above)

1. **`mcp_server/tools/render_tools.py`** — new file with
   `result_render_table(ref, columns?, where?, order_by?, caption?, limit?)`.
   Reads from `result_store`, renders markdown table, returns
   `{status, message, data: {render_markdown, row_count, columns_used, …}}`.
   The render goes in `data.render_markdown` — harness handles the
   DB write (Q2 lean (b)).

2. **`api/routers/agent.py`** — on-tool-result handler detects
   `data.render_markdown` on successful `result_render_table` calls
   and appends to `operations.final_answer` via
   `set_operation_final_answer_append` (new helper in
   `api/logger.py`).

3. **`api/logger.py`** — new `set_operation_final_answer_append`
   helper that appends instead of overwriting. Used by render tool
   dispatch.

4. **`api/agents/router.py`** — add `result_render_table` to observe
   + investigate allowlists. Add `LARGE-LIST RENDERING` prompt
   section behind `renderToolPromptEnabled` setting (default
   False — dark launch).

5. **`api/routers/settings.py`** — new `renderToolPromptEnabled`
   setting key under "Agent Budgets" group (or new
   "Rendering" group if growing).

6. **`gui/src/context/OptionsContext.jsx`** — add
   `renderToolPromptEnabled` to DEFAULTS + SERVER_KEYS (v2.36.6
   CI guard catches this if forgotten).

7. **`api/metrics.py`** — new
   `deathstar_render_tool_calls_total{outcome}` counter. Outcomes:
   `ok`, `ref_not_found`, `no_rows`, `truncated`, `error`.

8. **v2.35.14/15 rescue updates** — `empty_completion` and
   `too_short_completion` read DB `operations.final_answer` length,
   not agent-side buffer length. Prevents false-rescue firing when
   render tool wrote the answer.

9. **Tests** — `tests/test_render_tool.py` covering:
   - Basic render of 10-row result
   - Column auto-pick heuristic
   - `where` clause via shared result_query path
   - Truncation at limit=200
   - Ref-not-found error path
   - Harness DB-write dispatch (integration)
   - Rescue no-fire when render wrote >500 chars (integration)

10. **Prompt snapshot regeneration** — `LARGE-LIST RENDERING`
    section added to STATUS + RESEARCH snapshots.

Version bump: 2.36.7 → 2.36.8 (`.x.N` — new tool + prompt change, but
behind a flag so no behaviour change on default install).

## 12 · Estimated size

- MCP tool: ~100 lines
- Harness dispatch: ~40 lines
- Logger append helper: ~20 lines
- Prompt section: ~30 lines of English
- Settings key: ~10 lines
- Frontend Options entry: 2 lines
- Rescue updates: ~20 lines
- Tests: ~150 lines
- **Total:** ~400 lines, single file per subsystem, 1 CC prompt.

If Q3 is (a) — harness composition — the prompt section shrinks
because the agent just needs to write its caption; the composition
is harness business.

---

## Kent's review checklist

Please flag any of the following:

- ☐ Q1: markdown in Operations view — accept (a), or push for (b)?
- ☐ Q2: MCP tool vs harness does the DB write — confirm (b)?
- ☐ Q3: caption composition — confirm (a)?
- ☐ Q4: observe + investigate — confirm (b)?
- ☐ Q5: fact-age exemption for v2.36.8 — confirm?
- ☐ Any scope objections in §10?
- ☐ Estimated size reasonable, or should we split into 2 CC prompts?
- ☐ Anything missing from the ships-list in §11?

Once signed off, v2.36.8 CC prompt takes ~1 turn to write.
