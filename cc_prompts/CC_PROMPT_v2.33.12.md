# CC PROMPT — v2.33.12 — feat(agents): zero-result pivot detection

## What this does
From the 2026-04-17 09:39 trace: after `elastic_search_logs` returned 90 hits
at step 3, the agent issued 7 more calls (steps 5–11) all returning 0 hits,
never pivoting. Wasted 7/16 of its tool budget chasing a broken filter
variant instead of synthesizing from the working call.

Add harness-level detection: when any single tool returns 0 results on 3+
consecutive calls within the same task, inject a nudge instructing the
agent to broaden the query, try a different tool, or synthesize from
prior non-zero results.

Version bump: 2.33.11 → 2.33.12

## Change 1 — api/routers/agent.py — zero-result tracking

Inside the agent loop (same location as the v2.33.3 budget nudge), add
tracking state at the start of the task:

```python
# Track consecutive zero-result calls per tool + whether tool has EVER returned > 0 in this task
_zero_streaks: dict[str, int] = {}       # tool_name -> consecutive zero count
_nonzero_seen: dict[str, int] = {}       # tool_name -> best non-zero count seen
_zero_pivot_fired: set[str] = set()      # tools we've already nudged about
```

After each tool call completes, inspect the result:

```python
def _result_count(tool_result: dict) -> int | None:
    """Heuristic: extract a 'count of items returned' from common tool response shapes."""
    if not isinstance(tool_result, dict):
        return None
    # Direct count fields
    for key in ("total", "count", "hit_count", "num_results"):
        v = tool_result.get(key)
        if isinstance(v, int):
            return v
    # Array fields
    for key in ("hits", "results", "items", "entries", "logs"):
        arr = tool_result.get(key)
        if isinstance(arr, list):
            return len(arr)
    # Stringly-typed "Found N ..." summary fallback
    summary = tool_result.get("summary") or tool_result.get("message") or ""
    import re
    m = re.search(r"[Ff]ound\s+(\d+)", str(summary))
    if m:
        return int(m.group(1))
    return None

# ... after a tool call ...
count = _result_count(tool_result)
if count is not None:
    if count == 0:
        _zero_streaks[tool_name] = _zero_streaks.get(tool_name, 0) + 1
    else:
        _zero_streaks[tool_name] = 0
        _nonzero_seen[tool_name] = max(_nonzero_seen.get(tool_name, 0), count)

# Nudge condition: 3 consecutive zeros with same tool, have prior non-zero, not yet nudged
if (
    _zero_streaks.get(tool_name, 0) >= 3
    and _nonzero_seen.get(tool_name, 0) > 0
    and tool_name not in _zero_pivot_fired
):
    _zero_pivot_fired.add(tool_name)
    prior_n = _nonzero_seen[tool_name]
    messages.append({
        "role": "system",
        "content": (
            f"HARNESS NUDGE: Your last 3 calls to {tool_name} returned 0 results. "
            f"Earlier in this task, {tool_name} returned {prior_n} result(s). "
            "Your filter is likely too narrow. Your next step must either "
            "(a) synthesize from the non-zero call's output, "
            "(b) broaden the filter (drop level/service/host constraints), or "
            "(c) switch to a different tool. "
            "Do NOT repeat the same narrow-filter pattern."
        ),
    })
    await ws.send_json({
        "event": "zero_result_pivot",
        "tool": tool_name,
        "consecutive_zeros": _zero_streaks[tool_name],
        "prior_nonzero": prior_n,
    })

# Also nudge on 4 zeros even without prior non-zero (likely wrong tool entirely)
elif (
    _zero_streaks.get(tool_name, 0) >= 4
    and tool_name not in _zero_pivot_fired
):
    _zero_pivot_fired.add(tool_name)
    messages.append({
        "role": "system",
        "content": (
            f"HARNESS NUDGE: {tool_name} has returned 0 results for 4 consecutive calls "
            "in this task and has never returned any data. It may not be the right tool "
            "for this question. Switch to a different approach or call propose_subtask."
        ),
    })
    await ws.send_json({
        "event": "zero_result_pivot",
        "tool": tool_name,
        "consecutive_zeros": _zero_streaks[tool_name],
        "prior_nonzero": 0,
    })
```

## Change 2 — RESEARCH_PROMPT — add explicit rule

In `api/agents/router.py` find the investigate CONSTRAINTS section and add:

```
N. ZERO-RESULT PIVOT RULE: If the same tool returns 0 results 3 times in a row,
   STOP using that filter pattern. Either (a) broaden by dropping fields,
   (b) reuse data from an earlier non-zero call of the same tool, or
   (c) switch tools / propose_subtask. Never exceed 3 consecutive zero-result
   calls to the same tool.
```

## Change 3 — GUI: optional indicator

In `gui/src/components/OutputPanel.jsx`, handle the `zero_result_pivot` WS
event with an inline amber banner:

```jsx
{zeroPivot && (
  <div className="mono" style={{
    margin: '6px 0', padding: '6px 10px',
    background: 'var(--amber-dim)', color: 'var(--amber)',
    border: '1px solid var(--amber)', borderRadius: 2,
    fontSize: 10, letterSpacing: '0.1em',
  }}>
    ⚠ PIVOT NUDGE — {zeroPivot.tool} returned 0 · {zeroPivot.consecutive_zeros}× in a row
    {zeroPivot.prior_nonzero > 0 && <> (earlier: {zeroPivot.prior_nonzero})</>}
  </div>
)}
```

Add a listener for `event: "zero_result_pivot"` that sets this state.

## Change 4 — tests

`tests/test_zero_result_pivot.py`:

```python
def test_result_count_from_hits_array():
    from api.routers.agent import _result_count
    assert _result_count({"hits": [1, 2, 3]}) == 3
    assert _result_count({"hits": []}) == 0

def test_result_count_from_summary_text():
    from api.routers.agent import _result_count
    assert _result_count({"summary": "Found 90 log entries"}) == 90
    assert _result_count({"message": "Found 0 log entries"}) == 0

def test_result_count_from_total_field():
    from api.routers.agent import _result_count
    assert _result_count({"total": 42}) == 42

def test_result_count_none_for_unrecognised():
    from api.routers.agent import _result_count
    assert _result_count({"status": "ok"}) is None
```

## Version bump
Update `VERSION`: 2.33.11 → 2.33.12

## Commit
```
git add -A
git commit -m "feat(agents): v2.33.12 zero-result pivot detection — 3-in-a-row nudge"
git push origin main
```

## How to test after push
1. Redeploy.
2. Investigate: "Search Elasticsearch for error-level log entries in the last 1 hour" (same prompt that surfaced the bug).
3. Expect: if any tool returns 0 results 3 times in a row after having returned non-zero, a `zero_result_pivot` WS event fires and the OutputPanel shows an amber PIVOT NUDGE banner.
4. Agent's next step should be a substantially different query (broader filter) or a `propose_subtask` call.
5. Budget efficiency: total tool calls to reach a conclusion should drop (previously 12, expected ≤8).
