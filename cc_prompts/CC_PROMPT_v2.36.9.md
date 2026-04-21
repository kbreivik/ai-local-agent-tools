# CC PROMPT — v2.36.9 — fix: render-tool clobber race + verify dispatch + polish

## What this does

Fixes the three critical defects found in the v2.36.8 code audit before
the feature can be trusted for smoke testing, plus four polish items
from the same audit.

The critical bugs are:

1. **Clobber race (data loss).** Mid-run `result_render_table` appends
   a table to `operations.final_answer` via the new
   `set_operation_final_answer_append` helper. End-of-run `_stream_agent`
   cleanup then calls `set_operation_final_answer(last_reasoning)` —
   which is a **wholesale overwrite** via `q.set_operation_final_answer`,
   not an append. The agent's natural caption clobbers the table. Fix
   requires ordering-preserving composition: caption ABOVE table.

2. **Harness dispatch unverified.** Head(1500) + tail(2000) reads of
   `api/routers/agent.py` (257KB / ~5000 lines) found no
   `render_markdown` or `set_operation_final_answer_append` references.
   Middle ~1500 lines unread. Either the dispatch is there (silent in
   those ranges) or it never shipped. If missing, the entire v2.36.8
   feature is broken — tool runs, markdown never reaches DB.

3. **Rescue threshold too generous.** v2.36.8 shipped the rescue guard
   with `>= 500` chars as the "render wrote substantive content" cutoff
   in `_maybe_force_empty_synthesis`. 500 chars is below the length of
   a legitimate LLM prose answer that's otherwise preamble-shaped and
   SHOULD be rescued — the render guard false-suppresses. Bump to
   `>= 1500`.

Polish items:

4. `caption` kwarg on `result_render_table` is accepted but ignored
   (docstring even says "reserved for future use"). The LLM sees this
   parameter in v2.34.9's injected tool signatures and may pass it
   expecting it to work. Remove the arg entirely — caption is the
   agent's own `final_answer`, not a tool parameter.

5. Truncation footer when `where` is applied shows "of 42" where 42 is
   the **pre-filter** ref total, not the filtered match count. Mislead.

6. Dead code: `result_cols = qr.get("columns") or []` in the
   `query_result` branch is immediately overridden by `chosen_cols`.

7. Two DB round-trips per render in the query_result path (extra
   `fetch_result(ref, offset=0, limit=1)` just to read `total`).
   Optimise to one call.

Version bump: 2.36.8 → 2.36.9 (`.x.N` — fix pass on new feature).

Feature remains behind the `renderToolPromptEnabled=False` dark-launch
flag. No change to the promotion story — Kent flips when ready, now
for a correct implementation instead of a broken one.

---

## Change 0 — REQUIRED FIRST: verify dispatch state + report

Before touching any file, CC runs these greps and pastes the output
into the commit message body:

```bash
grep -n 'render_markdown' api/routers/agent.py
grep -n 'set_operation_final_answer_append' api/routers/agent.py
grep -n 'result_render_table' api/routers/agent.py
grep -n 'tool_name.*render' api/routers/agent.py
```

Three possible outcomes, each triggers a different branch of Change 2:

- **Dispatch present at a single seam** (all three greps hit the same
  line range): proceed to Change 2 option A (tighten existing).
- **Dispatch absent** (greps 1, 2 return zero hits; grep 3 may hit the
  allowlist registration in a different file): proceed to Change 2
  option B (wire it up).
- **Dispatch partially present** (e.g. one grep hits but not the others):
  proceed to Change 2 option B and REMOVE the partial scaffolding.

CC records which branch was taken in the commit message.

---

## Change 1 — fix clobber race (data loss)

The fix preserves ordering: caption ABOVE table, regardless of which
writes to DB first.

### 1a — new `api/logger.py` helper `set_operation_final_answer_prepend`

Add after the existing `set_operation_final_answer_append`:

```python
async def set_operation_final_answer_prepend(session_id: str, prefix: str) -> None:
    """v2.36.9 — prepend text ABOVE the existing final_answer.

    Used by the end-of-run cleanup path when the render tool appended
    a table mid-run. The cleanup needs to place the agent's caption
    ABOVE the table, not below it, for correct reading order.

    Mirrors set_operation_final_answer_append: direct write, two-newline
    separator between prefix and existing content, no-op when prefix is
    empty, no-op when the operation row doesn't exist yet.
    """
    if not prefix or not prefix.strip():
        return
    try:
        from sqlalchemy import text as _t
        async with get_engine().begin() as conn:
            existing = await conn.execute(
                _t(
                    "SELECT final_answer FROM operations "
                    "WHERE session_id = :sid "
                    "ORDER BY started_at DESC LIMIT 1"
                ),
                {"sid": session_id},
            )
            row = existing.fetchone()
            if not row:
                return
            current = (row[0] or "").lstrip()
            sep = "\n\n" if current else ""
            new_val = prefix.rstrip() + sep + current
            await conn.execute(
                _t(
                    "UPDATE operations SET final_answer = :val "
                    "WHERE session_id = :sid"
                ),
                {"val": new_val, "sid": session_id},
            )
    except Exception as e:
        log.error("set_operation_final_answer_prepend failed: %s", e)
```

### 1b — agent-loop-scope flag + branched cleanup

In `api/routers/agent.py::_stream_agent`, locate the existing cleanup
block that writes the final answer. It looks like:

```python
        if last_reasoning:
            try:
                await logger_mod.set_operation_final_answer(session_id, last_reasoning)
            except Exception as _sfa_e:
                log.debug("set_operation_final_answer failed: %s", _sfa_e)
```

Agents aggregate steps via `_run_single_agent_step` + coordinator loop,
so the flag needs to be tracked across coordinator iterations. The
cleanest seam is: track render events inside `_run_single_agent_step`
via `step_result`, then aggregate at the outer loop into
`_any_render_fired`.

**In `_run_single_agent_step`**: add a counter initialised with the
other per-run accumulators:

```python
    _render_tool_calls = 0          # v2.36.9
```

When the render-dispatch branch fires (see Change 2), bump the counter:

```python
                    _render_tool_calls += 1
```

At the end of the function, add the counter to the returned dict:

```python
    return {
        "output":                 last_reasoning,
        "tools_used":             tools_used_names,
        "substantive_tool_calls": substantive_tool_calls,
        "tool_history":           tool_history,
        "final_status":           final_status,
        "positive_signals":       positive_signals,
        "negative_signals":       negative_signals,
        "steps_taken":            step,
        "prompt_tokens":          total_prompt_tokens,
        "completion_tokens":      total_completion_tokens,
        "run_facts":              _run_facts,
        "fabrication_detected":   bool(_fabrication_detected_once),
        "render_tool_calls":      _render_tool_calls,   # v2.36.9
    }
```

**In `_stream_agent` outer loop**: initialise the aggregate before the
coordinator loop:

```python
    _any_render_fired = False   # v2.36.9
```

Inside the per-step aggregation block (near where `all_tools_used.extend
(step_result["tools_used"])` is called), add:

```python
        if step_result.get("render_tool_calls", 0) > 0:
            _any_render_fired = True
```

Replace the cleanup's `set_operation_final_answer` call with branched logic:

```python
        if last_reasoning:
            try:
                if _any_render_fired:
                    # v2.36.9 — render tool appended table mid-run; prepend
                    # the agent's caption ABOVE the table so ordering is
                    # caption-then-table, not table-then-clobbered-by-caption.
                    await logger_mod.set_operation_final_answer_prepend(
                        session_id, last_reasoning,
                    )
                else:
                    await logger_mod.set_operation_final_answer(
                        session_id, last_reasoning,
                    )
            except Exception as _sfa_e:
                log.debug("final_answer write failed: %s", _sfa_e)
```

---

## Change 2 — verify / wire the harness dispatch

### Branch A (Change 0 grep shows dispatch present)

Locate the existing dispatch. Confirm it:
- Detects `tool_name == "result_render_table"` on successful result
- Extracts `data.render_markdown` safely (type checks)
- Calls `await logger_mod.set_operation_final_answer_append(session_id, _md)`
- Increments the per-step `_render_tool_calls` counter added in Change 1b
- Increments `RENDER_TOOL_CALLS` Prometheus counter with an `outcome` label

If any of those points is missing, tighten the dispatch to match. If
the counter bump from Change 1b isn't present, add it. Paste the
final dispatch block into the commit message body.

### Branch B (Change 0 grep shows dispatch absent)

Wire the dispatch. Locate the tool-result processing branch in
`_run_single_agent_step` — the section where successful tool results
emit the `⚙ [tool] → ok | message` visual feed line and `log_tool_call`
runs. Use the same section; the render dispatch must share the canonical
`(tool_name, result)` pair with those.

Add within the successful-result branch, after `log_tool_call` but
before the next step dispatches:

```python
            # v2.36.8-dispatch (wired in v2.36.9) — render tool: append
            # rendered markdown to operations.final_answer so the operator
            # sees the table in the Operations view. LLM context stays
            # small (only the short ack message), the operator-facing
            # field gets the full rendered output.
            if tool_name == "result_render_table" and isinstance(result, dict):
                _data = result.get("data") or {}
                _md = _data.get("render_markdown") if isinstance(_data, dict) else None
                if isinstance(_md, str) and _md.strip():
                    try:
                        await logger_mod.set_operation_final_answer_append(
                            session_id, _md,
                        )
                        _render_tool_calls += 1   # v2.36.9 — seen by cleanup
                        try:
                            from api.metrics import RENDER_TOOL_CALLS
                            _outcome = "truncated" if _data.get("truncated") else "ok"
                            if _data.get("row_count", 0) == 0:
                                _outcome = "no_rows"
                            RENDER_TOOL_CALLS.labels(outcome=_outcome).inc()
                        except Exception:
                            pass
                    except Exception as _re_e:
                        log.debug(
                            "render tool append failed (session=%s): %s",
                            session_id, _re_e,
                        )
```

Exact variable names (`tool_name`, `result`, `session_id`) must match
the surrounding code. If the enclosing loop uses different names,
adapt accordingly.

If any partial scaffolding exists (e.g. an import of
`set_operation_final_answer_append` but no call site, or a half-written
`if` block), REMOVE the partial scaffolding first, then add this block
cleanly.

---

## Change 3 — rescue threshold 500 → 1500

In `api/routers/agent.py::_maybe_force_empty_synthesis`, locate:

```python
                if _row and _row[0] and len(_row[0]) >= 500:
                    _render_wrote_substantive = True
```

Replace with:

```python
                # v2.36.9 — raised from 500 to 1500. A full caption + even
                # a small 10-row table exceeds 1500 chars; a normal LLM
                # prose answer staying in the 500-1000 range should remain
                # eligible for too_short / preamble_only rescue so we don't
                # false-suppress a legitimate rescue when the render tool
                # wrote a trivially small table.
                if _row and _row[0] and len(_row[0]) >= 1500:
                    _render_wrote_substantive = True
```

Keep the surrounding log line so operators can see which threshold
path fired.

---

## Change 4 — remove `caption` kwarg from `result_render_table`

In `mcp_server/tools/render_tools.py`, remove the `caption: str = ""`
parameter and the docstring section describing it. Don't leave a
"reserved" note — the LLM will see it in the injected signatures and
try to use it.

Before:

```python
def result_render_table(
    ref: str,
    columns: str = "",
    where: str = "",
    order_by: str = "",
    caption: str = "",
    limit: int = _DEFAULT_LIMIT,
) -> dict:
```

After:

```python
def result_render_table(
    ref: str,
    columns: str = "",
    where: str = "",
    order_by: str = "",
    limit: int = _DEFAULT_LIMIT,
) -> dict:
```

Docstring: delete the two-line `caption: ...` block in Args.

v2.34.9's signature injector picks up the new signature automatically
on next container restart — no separate prompt change needed.

---

## Change 5 — truncation footer should cite filtered totals

In `mcp_server/tools/render_tools.py::result_render_table`, the
query_result branch currently computes:

```python
            # query_result's count is post-filter; we also want the full ref
            # total for the truncation footer.
            total_in_ref = fetch_result(ref, offset=0, limit=1)
            total_available = (
                total_in_ref.get("total") if total_in_ref else len(items)
            )
```

When a `where` clause is applied and the result is truncated, footer
currently says `(showing first 50 of 200 — add a where clause to narrow)`
where `200` is the pre-filter count. That's misleading — operator
thinks their `where` clause isn't working.

Fix: distinguish pre-filter from post-filter. Pass both into the
renderer and compose the footer conditionally:

Replace the `total_available` computation in the `query_result` branch
with:

```python
            # query_result's count is post-filter. Separate out the
            # pre-filter total for the footer so operators can see both
            # "matched your filter" vs "exists in the ref at all".
            post_filter_total = qr.get("count")
            if post_filter_total is None:
                post_filter_total = len(items)
            # Pre-filter total via a bounded fetch (limit=1 is enough —
            # we only want the `total` scalar).
            _pre = fetch_result(ref, offset=0, limit=1)
            pre_filter_total = _pre.get("total") if _pre else post_filter_total
            total_available = post_filter_total   # for the legacy field
```

In the `else` branch (no filter applied), keep:

```python
            post_filter_total = fr.get("total") or len(items)
            pre_filter_total = post_filter_total
            total_available = post_filter_total
```

Thread both into `_render_markdown_table`:

```python
        markdown = _render_markdown_table(
            items=items,
            columns=render_cols,
            post_filter_total=int(post_filter_total),
            pre_filter_total=int(pre_filter_total),
            truncated=truncated,
        )
```

Update `_render_markdown_table` signature and footer:

```python
def _render_markdown_table(
    items: list[dict],
    columns: list[str],
    post_filter_total: int,
    pre_filter_total: int,
    truncated: bool,
) -> str:
    """Render items + columns as a GitHub-flavoured markdown table string.

    Footer distinguishes filtered from unfiltered totals so operators
    aren't misled when a `where` clause is in play.
    """
    if not items:
        if pre_filter_total > 0 and post_filter_total == 0:
            return (
                f"_(no rows matched your filter — {pre_filter_total} "
                f"total rows exist in the ref)_"
            )
        return f"_(no rows matched — {pre_filter_total} total in ref)_"
    if not columns:
        return "_(no columns to render)_"

    header = "| " + " | ".join(columns) + " |"
    divider = "|" + "|".join(["---"] * len(columns)) + "|"
    rows = []
    for item in items:
        cells = [_format_cell(item.get(c)) for c in columns]
        rows.append("| " + " | ".join(cells) + " |")

    table = "\n".join([header, divider, *rows])
    if truncated:
        filtered_note = ""
        if post_filter_total < pre_filter_total:
            filtered_note = (
                f" matching filter out of {pre_filter_total} in ref"
            )
        table += (
            f"\n\n_(showing first {len(items)} of {post_filter_total}"
            f"{filtered_note} — narrow further with a tighter `where` clause)_"
        )
    return table
```

Also update the return payload:

```python
        return _ok(
            {
                "render_markdown":   markdown,
                "row_count":         len(items),
                "columns_used":      render_cols,
                "output_length":     len(markdown),
                "truncated":         truncated,
                "post_filter_total": int(post_filter_total),
                "pre_filter_total":  int(pre_filter_total),
                # Legacy field retained for back-compat
                "total_in_ref":      int(pre_filter_total),
            },
            ...
        )
```

---

## Change 6 — remove dead `result_cols`

In the `query_result` branch of `result_render_table`:

```python
            items = qr.get("items") or []
            result_cols = qr.get("columns") or []      # ← DEAD
```

`result_cols` is immediately overridden by `render_cols = chosen_cols`
a few lines down because that branch only runs when `chosen_cols` is
non-empty. Remove the line.

---

## Change 7 — update tests

In `tests/test_render_tool.py`:

### 7a — signature change

Any test that passes `caption=...` must be updated to drop the kwarg.
If no test passes `caption`, no change needed here.

### 7b — new filtered-footer test

Add after the existing truncation tests:

```python
def test_render_table_where_clause_footer_cites_both_totals(fake_result_store):
    """v2.36.9 — footer must cite BOTH the filtered match count AND
    the pre-filter ref total so operators can see the filter worked."""
    # fake_query filters signal < -50 → subset of the 42-row ref
    out = result_render_table(
        ref="rs-unifi42",
        columns="hostname,signal",
        where="signal < -50",
        limit=5,   # force truncation
    )
    data = out["data"]
    assert out["status"] == "ok"
    assert data["pre_filter_total"] == 42
    assert data["post_filter_total"] <= 42
    md = data["render_markdown"]
    if data["truncated"]:
        # Footer must name both numbers when filtering and truncating
        assert "of 42" in md or "out of 42" in md
        assert "matching filter" in md
```

### 7c — prepend helper test

New test file `tests/test_logger_prepend.py`:

```python
"""v2.36.9 — set_operation_final_answer_prepend + clobber-race regression."""
import asyncio
import pytest

from api import logger as logger_mod


@pytest.mark.asyncio
async def test_prepend_above_existing_content(postgres_engine, monkeypatch):
    """Render tool writes table; cleanup prepends caption. Final order:
    caption first, then blank line, then table. NOT table-then-clobber."""
    session_id = "test-prepend-1"

    # Setup: create an operation row via existing API
    op_id = await logger_mod.log_operation_start(
        session_id, "render-and-caption test", triggered_by="test",
    )

    # Mid-run: render tool appends a pipe-delimited table
    await logger_mod.set_operation_final_answer_append(
        session_id, "| hostname | ip |\n|---|---|\n| h1 | 10.0.0.1 |",
    )

    # End-of-run: cleanup prepends caption
    await logger_mod.set_operation_final_answer_prepend(
        session_id, "All 42 clients (table below):",
    )

    # Verify order
    from sqlalchemy import text
    from api.db.base import get_engine
    async with get_engine().connect() as conn:
        r = await conn.execute(
            text("SELECT final_answer FROM operations WHERE id = :op"),
            {"op": op_id},
        )
        final = r.scalar_one()

    assert final.startswith("All 42 clients (table below):")
    assert "| hostname | ip |" in final
    # Caption must appear BEFORE table
    assert final.index("All 42 clients") < final.index("| hostname | ip |")


@pytest.mark.asyncio
async def test_prepend_noop_on_empty_prefix(postgres_engine):
    """Empty / whitespace prefix is a no-op, not an overwrite."""
    session_id = "test-prepend-2"
    await logger_mod.log_operation_start(session_id, "test", "test")
    await logger_mod.set_operation_final_answer_append(session_id, "original")

    await logger_mod.set_operation_final_answer_prepend(session_id, "")
    await logger_mod.set_operation_final_answer_prepend(session_id, "   \n  ")

    from sqlalchemy import text
    from api.db.base import get_engine
    async with get_engine().connect() as conn:
        r = await conn.execute(
            text("SELECT final_answer FROM operations WHERE session_id = :sid"),
            {"sid": session_id},
        )
        assert r.scalar_one() == "original"


@pytest.mark.asyncio
async def test_prepend_noop_when_operation_missing(postgres_engine):
    """No exception when the operation row doesn't exist."""
    await logger_mod.set_operation_final_answer_prepend(
        "nonexistent-session-id", "some caption",
    )
    # If we got here, the helper handled the missing-row case gracefully.
```

The fixtures `postgres_engine` and the `pytest.mark.asyncio` marker
follow whatever pattern is used by `tests/test_operations_model_column.py`
(v2.36.7). Reuse that fixture. If no postgres fixture exists, skip
these tests with `pytest.importorskip("psycopg2")` or similar — the
logic paths in `set_operation_final_answer_prepend` are also exercised
via inspection of the written SQL.

### 7d — dispatch regression test

Add a test that asserts the dispatch wiring exists. This is a file-level
grep guard so future refactors can't silently drop the dispatch:

In `tests/test_render_tool.py`:

```python
def test_dispatch_wired_in_agent_loop():
    """v2.36.9 — regression guard: the render tool dispatch must be
    wired in api/routers/agent.py. If this test fails, the feature
    is shipping as a no-op for operators (tool runs, markdown lost)."""
    import pathlib
    agent_py = pathlib.Path(__file__).parent.parent / "api" / "routers" / "agent.py"
    src = agent_py.read_text(encoding="utf-8")
    assert "result_render_table" in src, (
        "dispatch check: 'result_render_table' missing from agent.py — "
        "v2.36.8 feature is unwired"
    )
    assert "set_operation_final_answer_append" in src, (
        "dispatch check: 'set_operation_final_answer_append' missing from "
        "agent.py — render tool output cannot reach DB"
    )
    assert "render_markdown" in src, (
        "dispatch check: 'render_markdown' field extraction missing from "
        "agent.py — dispatch is shaped wrong"
    )
```

---

## Change 8 — VERSION

```
2.36.9
```

---

## Verify

```bash
# Dispatch wiring present — all three must hit
grep -c 'render_markdown' api/routers/agent.py                       # >=1
grep -c 'set_operation_final_answer_append' api/routers/agent.py     # >=1
grep -c 'result_render_table' api/routers/agent.py                   # >=1

# Clobber fix present
grep -n '_any_render_fired' api/routers/agent.py                     # 2-3 hits
grep -n 'set_operation_final_answer_prepend' api/logger.py           # 1 def site

# Threshold bumped
grep -n '>= 1500' api/routers/agent.py                               # in _maybe_force_empty_synthesis
grep -cn '>= 500' api/routers/agent.py                               # should NOT include the render-substantive check

# caption kwarg removed
grep -n 'caption' mcp_server/tools/render_tools.py                   # 0 hits

# Dead line removed
grep -n 'result_cols = qr.get' mcp_server/tools/render_tools.py      # 0 hits

# Filtered-footer fields exposed
grep -n 'pre_filter_total\|post_filter_total' mcp_server/tools/render_tools.py   # multiple hits

# Test suite
pytest tests/test_render_tool.py -v
pytest tests/test_logger_prepend.py -v

# Existing suite sanity
pytest tests/test_options_context_server_keys.py tests/test_operations_model_column.py tests/test_tool_budget_settings.py -v
```

---

## Commit

```bash
git add -A
git commit -m "fix(agents): v2.36.9 render-tool clobber race + dispatch verify + polish

Three critical fixes on the v2.36.8 render-and-caption feature found in
code audit before smoke test.

CLOBBER RACE (data loss): mid-run result_render_table appended the
rendered table to operations.final_answer, then end-of-run cleanup
called set_operation_final_answer(last_reasoning) which overwrites
the field wholesale — the agent's natural caption clobbered the
table. Fix: new set_operation_final_answer_prepend helper in
api/logger.py (direct write, mirrors _append, two-newline separator,
no-op on empty prefix / missing op). Agent loop tracks _render_tool_calls
counter per step (returned via _run_single_agent_step dict); outer
_stream_agent aggregates into _any_render_fired bool. Cleanup branches:
render fired → prepend caption above table; render NOT fired →
existing wholesale write. Final order preserved: caption first, table
below.

DISPATCH VERIFY: v2.36.8 shipped without a verifiable wiring of
result_render_table -> set_operation_final_answer_append. Change 0
greps report findings; Change 2 either tightens existing dispatch
(Branch A) or wires from scratch (Branch B). Regression test at
tests/test_render_tool.py asserts all three grep strings appear in
agent.py so future refactors can't silently drop the dispatch.
Branch taken: <FILL IN FROM GREP OUTPUT>

RESCUE THRESHOLD 500 -> 1500: v2.36.8's _maybe_force_empty_synthesis
guard treated a >=500-char DB final_answer as 'render wrote substantive
content, skip rescue'. 500 chars false-suppressed legitimate
too_short_completion / preamble_only_completion rescues when the LLM
wrote 500-1000 chars of preamble-shaped prose AND the render tool
wrote a tiny 10-row table. Bumped to >=1500 (full caption + real table
exceeds 1500; prose answers in 500-1000 remain rescue-eligible).

POLISH: (a) removed caption= kwarg from result_render_table — it was
accepted-but-ignored, and LLM picks up the signature via v2.34.9
injection and may try to use it. Caption is agent's own final_answer,
not a tool parameter. (b) Truncation footer now distinguishes
pre_filter_total from post_filter_total so 'of 42' isn't misleading
when a where-clause is active — footer reads 'showing first N of M
matching filter out of K in ref'. Return payload exposes both.
(c) Removed dead result_cols = qr.get('columns') line — immediately
overridden by chosen_cols.

Grep output from Change 0:
<PASTE GREP RESULTS HERE>

Dark-launch flag renderToolPromptEnabled=False still gates the
prompt section; tool is always registered and allowlisted. Kent
flips the flag after v2.36.9 deploys."
git push origin main
```

---

## Deploy + smoke

```bash
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```

With v2.36.9 live:

1. Flip `renderToolPromptEnabled=True` in Settings → Agent Budgets.
2. Run the canonical UniFi observe task: "Check UniFi list all clients,
   their hostnames, ip's and mac addresses, and where they are connected".
3. Expected shape:
   - ~4-5 tool calls (not 12)
   - Operations view `final_answer` structure:
     - Line 1: agent's caption ("All 42 UniFi clients ...")
     - Blank line
     - Pipe-delimited markdown table below
   - NO rescue gate fired (no HARNESS FALLBACK stub)
4. Spot-check DB:
   ```bash
   docker compose exec hp1_agent python -c "
   import asyncio
   from api.db.base import get_engine
   from sqlalchemy import text
   async def main():
       async with get_engine().connect() as c:
           r = await c.execute(text(
               'SELECT length(final_answer), substring(final_answer from 1 for 80), status '
               'FROM operations ORDER BY started_at DESC LIMIT 3'
           ))
           for row in r.fetchall():
               print(row)
   asyncio.run(main())
   "
   ```
   Top row (most recent run): length should be 1500-8000; first 80 chars
   should be the caption, not a table header.

5. Flip flag OFF, re-run same task, confirm old fetch-and-describe
   behaviour returns (tool still registered, just not advertised).

---

## Scope guard — do NOT touch

- `result_store` schema / `fetch_result` / `query_result` — unchanged.
- Fabrication detector, hallucination guard — unchanged.
- v2.34.9 signature injection — picks up the removed `caption` kwarg
  automatically on container restart; no helper changes needed.
- Trace viewer UI, Operations view markdown-to-HTML — still deferred
  to v2.37.
- External AI Router — unchanged.
- Settings registry — no new keys (renderToolPromptEnabled from v2.36.8
  stays).

---

## Post-deploy followups (not v2.36.9)

- v2.37.0: Operations view renders markdown tables as real HTML tables.
- v2.37.x: Trace viewer Gates Fired sidebar gains `render_used` row.
- TBD: Collapse two DB round-trips in query_result branch into one call
  (requires a new `query_result_with_totals()` result_store helper — not
  worth doing under the fix-pass umbrella).
- TBD: Column heuristic `_pick_columns` tuning from production data.
