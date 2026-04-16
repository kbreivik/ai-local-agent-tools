# CC PROMPT — v2.32.4 — Fix final_answer truncation at 300 chars

## What this does
Fixes a bug where `final_answer` stored in the operations table is always truncated
to 300 characters. The cause: `verdict_from_text()` in `orchestrator.py` truncates
the summary to `text[:300]`, and `_stream_agent()` in `agent.py` uses
`prior_verdict["summary"]` as `last_reasoning` which becomes the `final_answer`.

The fix: use `step_result["output"]` (the full model output) for `last_reasoning`
instead of the truncated verdict summary. The verdict summary remains short for
coordinator inter-step context injection (where it's truncated further to 200 chars),
but the final answer gets the full text.

Version bump: 2.32.3 → 2.32.4

## Change 1 — api/routers/agent.py — Use full output for last_reasoning

In the `_stream_agent` function, find the cleanup section after the step loop.
There's a line that reads:

```python
        last_reasoning = prior_verdict["summary"] if prior_verdict else ""
```

Replace it with:

```python
        # Use the full step output for final_answer, not the 300-char verdict summary
        last_reasoning = ""
        if prior_verdict:
            # Try to get the full output from the last step result first
            last_reasoning = prior_verdict.get("full_output") or prior_verdict.get("summary", "")
```

## Change 2 — api/routers/agent.py — Preserve full output in verdict

In the step loop in `_stream_agent`, find the line that extracts the verdict:

```python
        prior_verdict = extract_structured_verdict(step_result["output"], step_info)
```

Add one line right after it to preserve the full output:

```python
        prior_verdict = extract_structured_verdict(step_result["output"], step_info)
        prior_verdict["full_output"] = step_result.get("output", "")  # preserve for final_answer
```

## Change 3 — api/agents/orchestrator.py — Increase verdict summary to 1500 chars

The 300-char limit is also too aggressive for the verdict summary itself (coordinator
context, step headers, etc.). Increase to 1500 chars which still fits in the coordinator
prompt budget but preserves much more useful context.

In `verdict_from_text()`, find all instances of `text[:300]` and replace with `text[:1500]`:

```python
# There are 4 occurrences:
# Line: return {"verdict": "HALT", "summary": text[:300]}
# Line: return {"verdict": "HALT", "summary": text[:300]}  (the error one)
# Line: return {"verdict": "ASK", "summary": text[:300]}
# Line: result = {"verdict": "GO", "summary": text[:300]}
```

Replace each `text[:300]` with `text[:1500]`.

## Version bump

Update VERSION file: 2.32.3 → 2.32.4

## Commit

```bash
git add -A
git commit -m "fix(agents): v2.32.4 final_answer truncation at 300 chars

verdict_from_text() truncated summary to text[:300], and _stream_agent
used prior_verdict['summary'] as last_reasoning → final_answer was
always cut to 300 chars.

Fix: preserve full step output in verdict dict, use it for final_answer.
Also increase verdict summary from 300→1500 chars for better coordinator
context while staying within prompt budget."
git push origin main
```
