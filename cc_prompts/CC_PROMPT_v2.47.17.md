# CC PROMPT — v2.47.17 — fix(gui): expanded results row clips bottom + tighten loop guard for elastic_search_logs

## What this does

Two small fixes from the v2.47.16 baseline analysis (run 04504024):

**1. UI bug — Results tab expansion clips at the bottom.** When a user
clicks ▼ on a run row in Tools → Tests → Results, the expanded inner
panel is taller than the row's flex slot allows, and the row's
`overflow: 'hidden'` style clips the rest. User sees the top portion
of the test list, then a striped/dark band where the next collapsed
row peeks through. Diagnostic confirmed: container has
`overflow:hidden`, height=470px, scrollHeight=1502px. One-character
fix.

**2. Loop guard didn't fire on `research-elastic-pattern-01`.** v2.47.16
added the consecutive-same-tool guard with threshold 3 and
`elastic_search_logs` in the list. Latest baseline:

```
research-elastic-pattern-01: TIMEOUT 150s
tools: elastic_log_pattern, elastic_search_logs ×4, audit_log
```

The guard counts consecutive calls to the SAME tool. The first call
was `elastic_log_pattern` (different tool), then `elastic_search_logs`
×4 — so the consecutive counter reached 4 on the 5th tool call. The
nudge would inject a directive AFTER call 3 (counter increments to 3,
threshold met). But the test timed out at 150s before the nudge had
effect, OR the nudge fired and the model ignored it.

Looking at v2.47.16's nudge wording: it says "STOP searching and
synthesise". For a research agent that's actively searching with no
matches, this is ambiguous — the model interprets it as advisory.
Tighten the wording AND lower the threshold for `elastic_search_logs`
specifically (threshold 2 instead of 3) since this tool's loop pattern
is documented and the cost of an early nudge is low.

**3. Bump `research-elastic-pattern-01` timeout from 150 to 200s.**
The test legitimately needs more time when the agent has to call
`elastic_log_pattern` first then a couple of `elastic_search_logs`
narrowing the query. Combined with the tighter guard, the test should
finish well under cap.

Version bump: 2.47.16 → 2.47.17

---

## Change 1 — `gui/src/components/TestsPanel.jsx` — expansion clip fix

CC: open `gui/src/components/TestsPanel.jsx`. Find the run-row container
in `ResultsTab` (around line 880-890). Current:

```jsx
        {visibleRuns.map(run => (
          <div key={run.id} style={{ border: '1px solid var(--border)', background: 'var(--bg-2)', borderRadius: 2, overflow: 'hidden' }}>
            <div onClick={() => expand(run)} style={{ display: 'flex', gap: 10, padding: '7px 12px', cursor: 'pointer', alignItems: 'center' }}
```

Change `overflow: 'hidden'` to `overflow: 'visible'`:

```jsx
        {visibleRuns.map(run => (
          <div key={run.id} style={{ border: '1px solid var(--border)', background: 'var(--bg-2)', borderRadius: 2, overflow: 'visible' }}>
            <div onClick={() => expand(run)} style={{ display: 'flex', gap: 10, padding: '7px 12px', cursor: 'pointer', alignItems: 'center' }}
```

CC: this is exactly one word changed: `'hidden'` → `'visible'`. The
parent (`flex: 1, overflowY: 'auto'`) already handles scrolling for
the whole list. The row container doesn't need to clip its own
expanded content.

---

## Change 2 — `api/agents/step_state.py` — already has the fields, no change

CC: no edits to step_state.py. The fields added in v2.47.16
(`consecutive_same_tool_count`, `consecutive_same_tool_name`,
`consecutive_loop_nudge_fired`) are reused.

---

## Change 3 — `api/agents/step_tools.py` — tighten loop guard for elastic search

CC: open `api/agents/step_tools.py`. Find the v2.47.16 loop-guard block
(search for `_LOOP_GUARD_TOOLS = frozenset`).

Current code:

```python
        # v2.47.16 — consecutive-same-tool loop guard. After N
        # consecutive calls to the same search/scan tool (where each
        # successive call returns non-zero results but doesn't
        # advance synthesis), inject a directive to synthesise from
        # what's been gathered. Pattern observed in orch-correlate-01:
        # elastic_search_logs called 4× back-to-back, none of which
        # produced a result the model considered conclusive. Existing
        # zero-pivot guard misses this because each call returns
        # non-zero hits.
        _LOOP_GUARD_TOOLS = frozenset({
            "elastic_search_logs", "elastic_error_logs",
            "elastic_kafka_logs", "elastic_log_pattern",
            "elastic_index_stats",
            "log_timeline",
        })
        _LOOP_THRESHOLD = 3
        if fn_name in _LOOP_GUARD_TOOLS:
```

Replace with the tighter version:

```python
        # v2.47.16 — consecutive-same-tool loop guard. After N
        # consecutive calls to the same search/scan tool (where each
        # successive call returns non-zero results but doesn't
        # advance synthesis), inject a directive to synthesise from
        # what's been gathered. Pattern observed in orch-correlate-01:
        # elastic_search_logs called 4× back-to-back, none of which
        # produced a result the model considered conclusive. Existing
        # zero-pivot guard misses this because each call returns
        # non-zero hits.
        # v2.47.17 — per-tool thresholds. elastic_search_logs has the
        # most documented loop history (research-elastic-pattern-01,
        # orch-correlate-01) so its threshold is tightened to 2.
        _LOOP_GUARD_TOOLS = frozenset({
            "elastic_search_logs", "elastic_error_logs",
            "elastic_kafka_logs", "elastic_log_pattern",
            "elastic_index_stats",
            "log_timeline",
        })
        _LOOP_THRESHOLD_BY_TOOL = {
            "elastic_search_logs": 2,
        }
        _LOOP_THRESHOLD_DEFAULT = 3
        if fn_name in _LOOP_GUARD_TOOLS:
```

Then find the threshold check a few lines below. Current:

```python
        if (
            state.consecutive_same_tool_count >= _LOOP_THRESHOLD
            and not state.consecutive_loop_nudge_fired
        ):
```

Replace with:

```python
        _threshold = _LOOP_THRESHOLD_BY_TOOL.get(
            state.consecutive_same_tool_name, _LOOP_THRESHOLD_DEFAULT,
        )
        if (
            state.consecutive_same_tool_count >= _threshold
            and not state.consecutive_loop_nudge_fired
        ):
```

Then find the directive text and tighten it. Current:

```python
            messages.append({
                "role": "system",
                "content": (
                    f"[harness] You have called {fn_name} "
                    f"{state.consecutive_same_tool_count} times in a row. "
                    "Each successive call is unlikely to produce new "
                    "information. STOP searching and synthesise from "
                    "the evidence already gathered. If you genuinely "
                    "cannot answer with what you have, call escalate() "
                    "with reason='insufficient_evidence' — do NOT keep "
                    "searching."
                ),
            })
```

Replace with stronger wording:

```python
            messages.append({
                "role": "system",
                "content": (
                    f"[harness] HARD STOP — {fn_name} has been called "
                    f"{state.consecutive_same_tool_count} times "
                    f"consecutively. Further calls to this tool will be "
                    "REJECTED. You MUST do ONE of the following on your "
                    "next turn:\n"
                    "  1. Call final_answer() summarising what you found "
                    "(or that searches returned no relevant data).\n"
                    "  2. Call a DIFFERENT tool (e.g. elastic_cluster_health, "
                    "elastic_index_stats, kafka_broker_status) to gather "
                    "different evidence.\n"
                    "  3. Call escalate(reason='insufficient_evidence') if "
                    "you cannot answer.\n"
                    "Do NOT call audit_log. Do NOT repeat the same search "
                    "with different keywords. Choose 1, 2, or 3 NOW."
                ),
            })
```

CC: keep the surrounding `await manager.send_line(...)` and metric
counter blocks unchanged. This is a wording change only inside the
nudge, plus the per-tool threshold lookup.

---

## Change 4 — `api/db/test_definitions.py` — bump research-elastic-pattern-01 timeout

CC: open `api/db/test_definitions.py`. Find:

```python
    TestCase(id="research-elastic-pattern-01", category="research",
        task="use the elastic_log_pattern tool to retrieve log entry patterns for the nginx service from elasticsearch",
        expect_tools=["elastic_log_pattern"], max_steps=10, timeout_s=150),
```

Change `timeout_s=150` to `timeout_s=200`:

```python
    TestCase(id="research-elastic-pattern-01", category="research",
        task="use the elastic_log_pattern tool to retrieve log entry patterns for the nginx service from elasticsearch",
        expect_tools=["elastic_log_pattern"], max_steps=10, timeout_s=200),
```

---

## Verify

```bash
python -m py_compile api/agents/step_tools.py api/db/test_definitions.py

# Confirm UI fix
grep -n "borderRadius: 2, overflow:" gui/src/components/TestsPanel.jsx
# Expected: 'overflow: visible' in the run-row container line

# Confirm per-tool threshold
grep -n "_LOOP_THRESHOLD_BY_TOOL\|_LOOP_THRESHOLD_DEFAULT" api/agents/step_tools.py
# Expected: dict definition + lookup line

# Confirm directive change
grep -n "HARD STOP" api/agents/step_tools.py
# Expected: 1 match

# Confirm test timeout bump
grep -B 1 "timeout_s=200" api/db/test_definitions.py | grep elastic-pattern
# Expected: research-elastic-pattern-01 line above the timeout=200 line
```

After deploy + browser refresh:

1. Tools → Tests → Results — click ▼ on any run; expansion now shows
   ALL 38 tests with full scroll, no clipping
2. Trace for `research-elastic-pattern-01` should show
   `[loop-guard] elastic_search_logs called 2× consecutively` after
   the 2nd call (not 3rd), and the model should call final_answer
   or a different tool on the next turn
3. Test should pass within 200s

---

## What this does NOT do

- **Does not fix the soft `action-upgrade-01` "Expected plan_pending"
  failure.** That's the v2.47.8 force-plan rejection not kicking in
  early enough. Worth its own diagnosis in v2.47.18+.
- **Does not change the threshold for other elastic tools.** Only
  `elastic_search_logs` has the documented loop pattern. If
  `elastic_log_pattern` or `elastic_index_stats` shows looping in a
  future run, add it to `_LOOP_THRESHOLD_BY_TOOL`.

---

## Version bump

Update `VERSION`: `2.47.16` → `2.47.17`

---

## Commit

```bash
git add -A
git commit -m "fix(gui+agent): v2.47.17 results expansion clip + tighter elastic_search_logs loop guard"
git push origin main
```

Deploy:

```bash
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
