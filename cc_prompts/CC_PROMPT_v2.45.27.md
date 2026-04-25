# CC PROMPT — v2.45.27 — fix(agent): elastic loop guard — sliding-window zero-ratio detector

## What this does
Closes the last 2 test failures from the v2.45.17 A/B baseline:
- `research-elastic-search-01` (with-memory) — loops `elastic_search_logs` 4× → timeout
- `orch-correlate-01` (with-memory) — same loop pattern

Root cause: the existing zero-pivot guard in `api/agents/step_facts.py` uses a
strict consecutive-count of zero results. A single non-zero call resets the
counter, so patterns like `[10, 0, 0, 0, 5, 0, 0, 0]` never trip the
3-in-a-row threshold even though 6 of 8 calls returned nothing.

Fix: add a sliding-window zero-ratio detector that fires when the last N calls
are mostly zeros. The existing strict consecutive guard stays — both are
useful in different shapes.

Version bump: 2.45.26 → 2.45.27

---

## Context

Current logic in `api/agents/step_facts.py:process_tool_result`:

```python
    if _count is not None:
        if _count == 0:
            state.zero_streaks[fn_name] = state.zero_streaks.get(fn_name, 0) + 1
        else:
            state.zero_streaks[fn_name] = 0   # ← single non-zero resets counter
            state.nonzero_seen[fn_name] = max(state.nonzero_seen.get(fn_name, 0), _count)
```

And further down, the guard fires only when `state.zero_streaks[fn_name] >= 3`
or `>= 4`.

We need a parallel signal: track the last 6 results in a deque, fire when
`zeros / window_size >= 0.66` (i.e. 4-of-6 zeros), once per tool per run.

---

## Change 1 — `api/agents/step_state.py` — add sliding-window field

CC: open `api/agents/step_state.py`. Find the `StepState` dataclass and the
existing zero-tracking fields (`zero_streaks`, `nonzero_seen`,
`zero_pivot_fired`). Add a new field next to them:

```python
    zero_window: dict = field(default_factory=dict)  # v2.45.27 — fn_name → deque of last N _count values
```

If the existing dict fields use a different `field(...)` import style or
a custom factory, match it. Add `from collections import deque` near the top
of the file if it is not already imported (the `deque` is created lazily
inside step_facts.py, so the import there is fine — step_state.py only needs
the `dict` type).

---

## Change 2 — `api/agents/step_facts.py` — track window + fire ratio guard

In `process_tool_result`, find the existing zero-tracking block:

```python
    if _count is not None:
        if _count == 0:
            state.zero_streaks[fn_name] = state.zero_streaks.get(fn_name, 0) + 1
        else:
            state.zero_streaks[fn_name] = 0
            state.nonzero_seen[fn_name] = max(state.nonzero_seen.get(fn_name, 0), _count)
```

Right AFTER this block, BEFORE the existing zero-pivot nudge logic, insert:

```python
    # ── v2.45.27: sliding-window zero-ratio guard ────────────────────────────
    # The strict consecutive-zero guard misses patterns where a single nonzero
    # result resets the streak (e.g. [10, 0, 0, 0, 5, 0, 0, 0] — 6/8 zeros).
    # Track the last 6 _count values per tool; when 4-of-6 are zero AND there
    # is at least one nonzero in the window AND we have not fired this signal
    # for this tool yet, inject a harness nudge.
    from collections import deque as _deque
    _ZW_SIZE = 6
    _ZW_TRIGGER = 4   # zeros in window required to fire
    if _count is not None:
        win = state.zero_window.get(fn_name)
        if win is None:
            win = _deque(maxlen=_ZW_SIZE)
            state.zero_window[fn_name] = win
        win.append(_count)
        _zeros_in_win = sum(1 for v in win if v == 0)
        _nonzeros_in_win = sum(1 for v in win if v and v > 0)
        if (
            len(win) >= _ZW_SIZE
            and _zeros_in_win >= _ZW_TRIGGER
            and _nonzeros_in_win >= 1
            and fn_name not in state.zero_pivot_fired
        ):
            state.zero_pivot_fired.add(fn_name)
            _max_seen = state.nonzero_seen.get(fn_name, 0)
            messages.append({
                "role": "system",
                "content": (
                    f"HARNESS NUDGE: In your last {_ZW_SIZE} calls to {fn_name}, "
                    f"{_zeros_in_win} returned 0 results (only {_nonzeros_in_win} "
                    f"returned data; max seen: {_max_seen}). The query shape is "
                    "mostly missing — flapping or filter-too-narrow. Stop "
                    "repeating the same pattern. Your next step must either "
                    "(a) synthesize from the calls that DID return data, "
                    "(b) broaden the filter (drop level/service/host constraints), or "
                    "(c) switch to a different tool. "
                    "Do NOT call this tool again with the same shape."
                ),
            })
            await manager.broadcast({
                "type":              "zero_result_pivot",
                "session_id":        session_id,
                "tool":              fn_name,
                "consecutive_zeros": state.zero_streaks.get(fn_name, 0),
                "prior_nonzero":     _max_seen,
                "window_size":       _ZW_SIZE,
                "window_zeros":      _zeros_in_win,
                "trigger":           "sliding_window_ratio",
                "timestamp":         datetime.now(timezone.utc).isoformat(),
            })
            await manager.send_line(
                "step",
                f"[pivot:window] {fn_name} returned 0 in {_zeros_in_win}/{_ZW_SIZE} "
                f"recent calls — nudging agent to broaden or switch",
                status="warning", session_id=session_id,
            )
            try:
                from api.metrics import ZERO_PIVOT_WINDOW_COUNTER
                ZERO_PIVOT_WINDOW_COUNTER.labels(tool=fn_name).inc()
            except Exception:
                pass
```

CC: `datetime`, `manager`, `session_id`, `messages`, `state`, `_count`,
`fn_name` are all already in scope at this point in the function. The
`from collections import deque as _deque` import inside the block is
intentional — keeps the change local. If you prefer module-level, add
`from collections import deque` at the top of `step_facts.py` and drop the
`_deque` alias.

---

## Change 3 — `api/metrics.py` — register the new counter

CC: open `api/metrics.py`. Find the existing pivot counter (search for
`ZERO_PIVOT` or `zero_pivot`). If `ZERO_PIVOT_COUNTER` exists for the strict
guard, add a sibling for the window guard right next to it:

```python
ZERO_PIVOT_WINDOW_COUNTER = Counter(
    "deathstar_zero_pivot_window_total",
    "Sliding-window zero-ratio pivot guard fired (4-of-6 zeros)",
    labelnames=["tool"],
)
```

If the file uses `prometheus_client.Counter` or a registry-register pattern,
match the existing style.

If the existing strict-pivot counter does not exist either, add both — but
the strict counter is just for parity and is optional; the window counter is
the one this prompt requires.

---

## Verify

```bash
python -m py_compile api/agents/step_state.py api/agents/step_facts.py api/metrics.py
grep -n "zero_window\|sliding_window_ratio" api/agents/step_state.py api/agents/step_facts.py
```

Expected: zero_window dict field present in StepState; the new harness nudge
text appears in step_facts.py.

After deploy, run `research-elastic-search-01` manually. Expect the agent to
trip the sliding-window guard on the 4th-6th `elastic_search_logs` call, get
the nudge, and pivot — instead of looping until timeout.

---

## Version bump

Update `VERSION`: `2.45.26` → `2.45.27`

---

## Commit

```
git add -A
git commit -m "fix(agent): v2.45.27 sliding-window zero-ratio guard — catches loop patterns the consecutive guard misses"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```

Re-run the full A/B baseline. Expect both `research-elastic-search-01` and
`orch-correlate-01` to flip from FAIL to PASS in the with-memory variant.
