# CC PROMPT — v2.33.13 — feat(agents): contradiction detection in synthesis

## What this does
From the 2026-04-17 09:39 trace: agent concluded "No error-level log entries
were found" despite step 3 explicitly returning **90 log entries**. The final
answer ignored contradicting evidence from its own tool history.

Add a pre-synthesis check: compare the proposed final answer against the
tool-call history. If the answer asserts "zero" / "none" / "not found" about
a subject while some prior tool call in the same task returned non-zero
results for a related query, inject a reminder to either reconcile or
revise the conclusion.

Version bump: 2.33.12 → 2.33.13

## Change 1 — api/agents/orchestrator.py (or wherever verdict_from_text lives)

Find the synthesis / final-answer builder (v2.32.4 touched `verdict_from_text`
and `_stream_agent` in `api/routers/agent.py`). Add a helper function and
invoke it just before the final_answer is emitted.

```python
import re

_NEGATIVE_CLAIM_PATTERNS = [
    r"\bno\s+(?:error|warning|critical|log|entries?|events?|issues?|problems?)",
    r"\b(?:zero|0)\s+(?:error|warning|critical|log|entries?|events?|issues?)",
    r"\bnot?\s+found",
    r"\bno\s+\w+\s+(?:were|was)?\s*found",
    r"\bnothing\s+(?:found|detected|returned)",
    r"\bno\s+results?",
]

def detect_negative_claim(text: str) -> list[str]:
    """Return list of negative-claim phrases found in the text (case-insensitive)."""
    found = []
    low = text.lower()
    for pat in _NEGATIVE_CLAIM_PATTERNS:
        for m in re.finditer(pat, low):
            found.append(m.group(0))
    return found


def detect_contradictions(final_text: str, tool_history: list[dict]) -> list[dict]:
    """
    Check if final_text asserts 'nothing found' while tool_history shows > 0
    results from earlier calls. Returns list of contradictions found.
    
    tool_history entry shape (from agent loop):
      {"tool": "elastic_search_logs", "args": {...}, "result": {...}, "step": N}
    """
    negatives = detect_negative_claim(final_text)
    if not negatives:
        return []

    # Aggregate non-zero results per tool
    from api.routers.agent import _result_count   # if colocated
    nonzero_by_tool = {}
    for call in tool_history:
        count = _result_count(call.get("result"))
        if count and count > 0:
            prev = nonzero_by_tool.get(call["tool"])
            if not prev or count > prev["count"]:
                nonzero_by_tool[call["tool"]] = {
                    "count": count,
                    "step": call.get("step"),
                    "args": call.get("args", {}),
                }

    contradictions = []
    for tool, info in nonzero_by_tool.items():
        contradictions.append({
            "tool": tool,
            "step": info["step"],
            "nonzero_count": info["count"],
            "args": info["args"],
            "negative_claim_snippets": negatives[:2],
        })
    return contradictions
```

## Change 2 — wire into final_answer emission

In the agent loop (`_stream_agent` in `api/routers/agent.py`), BEFORE the
final_answer is sent to the client, insert a contradiction check. If
contradictions exist AND this is the agent's first synthesis attempt,
send the model one more synthesis round with a corrective system message.

```python
# Near the end of _stream_agent, after model produces final text but before emit:
contradictions = detect_contradictions(final_text, tool_history)
if contradictions and not _already_reconciled:
    _already_reconciled = True   # prevent infinite loop
    contradiction_summary = "\n".join(
        f"  - Step {c['step']}: {c['tool']}({c['args']}) returned {c['nonzero_count']} results"
        for c in contradictions
    )
    await ws.send_json({
        "event": "contradiction_detected",
        "contradictions": contradictions,
    })
    messages.append({
        "role": "system",
        "content": (
            "HARNESS: Your draft conclusion contains a negative claim "
            f"({', '.join(c['negative_claim_snippets'][0] for c in contradictions[:1])}) "
            "but your tool history contradicts it:\n"
            f"{contradiction_summary}\n"
            "Revise your final answer. Either:\n"
            "  (a) Acknowledge the earlier non-zero result and explain why "
            "the final claim still holds (e.g. different time window / filter).\n"
            "  (b) Revise the conclusion to match the evidence.\n"
            "Do not silently drop the earlier data."
        ),
    })
    # One more synthesis turn
    final_text = await _synthesize_once(messages, ...)  # reuse existing synth call
```

If `_already_reconciled` is True and contradictions still exist, emit the
answer but prepend a machine-readable warning:

```python
final_text = (
    f"[HARNESS WARNING: {len(contradictions)} unresolved evidence contradiction(s). "
    "See step history.]\n\n" + final_text
)
```

## Change 3 — GUI: contradiction banner in OutputPanel

Handle `contradiction_detected` WS event:

```jsx
{contradictions.length > 0 && (
  <div className="mono" style={{
    margin: '8px 0', padding: '8px 10px',
    background: 'var(--red-dim)', color: 'var(--red)',
    border: '1px solid var(--red)', borderRadius: 2, fontSize: 10,
  }}>
    <div style={{ letterSpacing: '0.15em', marginBottom: 4 }}>
      ⚠ EVIDENCE CONTRADICTION — AGENT RECONCILING
    </div>
    {contradictions.map((c, i) => (
      <div key={i} style={{ opacity: 0.9 }}>
        Step {c.step}: {c.tool} → {c.nonzero_count} results (ignored in draft conclusion)
      </div>
    ))}
  </div>
)}
```

## Change 4 — tests

`tests/test_contradiction_detection.py`:

```python
def test_detect_no_entries_claim():
    from api.agents.orchestrator import detect_negative_claim
    assert detect_negative_claim("No error-level log entries were found") != []
    assert detect_negative_claim("Zero errors detected in the last hour") != []
    assert detect_negative_claim("The system is healthy") == []

def test_contradiction_flags_nonzero_history():
    from api.agents.orchestrator import detect_contradictions
    history = [
        {"tool": "elastic_search_logs", "step": 3, "args": {}, "result": {"hits": [1]*90}},
        {"tool": "elastic_search_logs", "step": 5, "args": {"level": "error"}, "result": {"hits": []}},
    ]
    contra = detect_contradictions("No error entries were found.", history)
    assert len(contra) == 1
    assert contra[0]["tool"] == "elastic_search_logs"
    assert contra[0]["nonzero_count"] == 90

def test_no_contradiction_when_history_empty():
    from api.agents.orchestrator import detect_contradictions
    assert detect_contradictions("No errors found.", []) == []

def test_no_contradiction_when_claim_is_positive():
    from api.agents.orchestrator import detect_contradictions
    history = [{"tool": "foo", "step": 1, "args": {}, "result": {"hits": [1, 2]}}]
    assert detect_contradictions("Found 2 errors in worker-01.", history) == []
```

## Version bump
Update `VERSION`: 2.33.12 → 2.33.13

## Commit
```
git add -A
git commit -m "feat(agents): v2.33.13 contradiction detection — reject conclusions that ignore evidence"
git push origin main
```

## How to test after push
1. Redeploy.
2. Investigate: "Search Elasticsearch for error-level log entries in the last 1 hour across all services."
3. Even if the agent falls into the zero-result trap again, the harness catches the contradiction before synthesis.
4. Expect WS event `contradiction_detected` and a red banner in OutputPanel.
5. Expect the agent to reconcile: either mention the earlier 90-entry result, or revise "no entries" to a more accurate claim.
6. Regression: positive conclusions ("found N issues") do not trigger contradictions.
