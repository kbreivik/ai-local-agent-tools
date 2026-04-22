# CC PROMPT — v2.40.3 — refactor(agents): extract gate/synthesis helpers into api/agents/gates.py

## What this does

api/routers/agent.py is 5523 lines. The hallucination guard, forced synthesis,
preamble detection, final answer classification, and related pure helpers are
all co-located with the agent loop making it hard to reason about gate ordering
and test gates in isolation.

Extract the following pure/near-pure functions from agent.py into a new module
`api/agents/gates.py`, then import them back into agent.py. No behaviour change.

Functions to move:
- `_is_preamble_only()`         (line ~158)
- `_classify_terminal_final_answer()`  (line ~192)
- `compute_final_answer()`      (line ~212)
- `_result_count()`             (line ~250)
- `_should_disable_thinking()`  (line ~276)

Constants used by these functions that should also move:
- `_PREAMBLE_STARTERS` (list — used by _is_preamble_only)
- `_VERDICT_MARKERS`   (list — used by _is_preamble_only / _classify_terminal)

Version bump: 2.40.2 → 2.40.3.

---

## Change 1 — create `api/agents/gates.py`

Create new file `api/agents/gates.py` with the following content (copy the
functions verbatim from agent.py, preserving all docstrings and comments):

```python
"""Agent harness gate helpers — v2.40.3.

Extracted from api/routers/agent.py to make gate logic independently
testable and to reduce agent.py line count.

Imported back into agent.py:
    from api.agents.gates import (
        _is_preamble_only, _classify_terminal_final_answer,
        compute_final_answer, _result_count, _should_disable_thinking,
    )
"""
from __future__ import annotations

# ── Preamble / synthesis classification ──────────────────────────────────────

_PREAMBLE_STARTERS = [
    "i'll ", "i will ", "let me ", "let's ", "sure", "okay",
    "first", "i'm going to ", "to answer", "to check",
    "going to ", "i need to ",
]

_VERDICT_MARKERS = [
    "STATUS:", "FINDINGS:", "ROOT CAUSE:", "EVIDENCE:",
    "CONCLUSION:", "SUMMARY:", "UNRESOLVED:", "NEXT STEPS:",
    "DIAGNOSIS:",
]
```

Then copy verbatim from agent.py (preserving all docstrings):
- `_is_preamble_only(text: str) -> bool`
- `_classify_terminal_final_answer(text: str) -> str | None`
- `compute_final_answer(steps: list[dict]) -> str`
- `_result_count(tool_result: dict) -> int | None`
- `_should_disable_thinking(tool_names_this_step: list[str], step: int, max_steps: int) -> bool`

---

## Change 2 — `api/routers/agent.py` — replace definitions with imports

CC: first grep for `_PREAMBLE_STARTERS` and `_VERDICT_MARKERS` in agent.py to
find their exact current definitions. Then:

1. Delete the `_PREAMBLE_STARTERS`, `_VERDICT_MARKERS` constants and all five
   function definitions from agent.py.

2. At the top of agent.py, after the existing imports block (near line 20-25),
   add:

```python
from api.agents.gates import (
    _is_preamble_only,
    _classify_terminal_final_answer,
    compute_final_answer,
    _result_count,
    _should_disable_thinking,
)
```

---

## Change 3 — verify no broken references

CC must grep agent.py after the edit to confirm:
- `_is_preamble_only` appears only in imports + call sites (not definition)
- `_classify_terminal_final_answer` same
- `compute_final_answer` same
- `_result_count` same
- `_should_disable_thinking` same

If any of these functions are also imported/used by OTHER files (check with
grep -r across api/), add them to the `__all__` list in gates.py and ensure
the import in agent.py covers them.

---

## Version bump

Update `VERSION` file: `2.40.2` → `2.40.3`

---

## Commit

```
git add -A
git commit -m "refactor(agents): v2.40.3 extract gate helpers into api/agents/gates.py"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
