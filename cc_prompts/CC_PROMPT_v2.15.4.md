# CC PROMPT — v2.15.4 — Agent loop quality fixes

## What this does

Four bugs found during docker prune testing:

1. **result_query SQL type error** — temp table columns are TEXT but agent passes
   bare boolean literals (`WHERE dangling = true`). Postgres rejects `text = boolean`.
2. **Double plan_action** — after first approval, model re-calls plan_action for
   follow-on sub-operations. Should only need approval once per task.
3. **Approval UI colour** — plan_pending dialog shows neutral green regardless of
   risk_level/reversible. High-risk or irreversible plans should show amber/red.
4. **Incomplete final_answer** — loop breaks on audit_log step, last reasoning
   (mid-sentence) becomes the final_answer. Should force a summary if truncated.

Version bump: 2.15.3 → 2.15.4 (bug fixes, x.x.1)

---

## Fix 1 — api/db/result_store.py — auto-coerce booleans in WHERE clause

In `query_result()`, find this block after `safe = where.replace(";", "").strip()`:

```python
safe = where.replace(";", "").strip()
for kw in ("DROP", "DELETE", "INSERT", "UPDATE", "CREATE", "ALTER"):
    if kw.upper() in safe.upper():
        ...
```

Add boolean coercion BEFORE the keyword check:

```python
safe = where.replace(";", "").strip()

# All temp table columns are TEXT. Coerce bare boolean literals to quoted strings
# so the agent can write: WHERE dangling = true  (not: WHERE dangling = 'true')
import re as _re
safe = _re.sub(
    r'=\s*(true|false)\b',
    lambda m: f"= '{m.group(1)}'",
    safe,
    flags=_re.IGNORECASE,
)
# Also handle IS TRUE / IS FALSE
safe = _re.sub(r'\bIS\s+TRUE\b',  "= 'true'",  safe, flags=_re.IGNORECASE)
safe = _re.sub(r'\bIS\s+FALSE\b', "= 'false'", safe, flags=_re.IGNORECASE)

for kw in ("DROP", "DELETE", "INSERT", "UPDATE", "CREATE", "ALTER"):
    ...
```

---

## Fix 2 — api/routers/agent.py — prevent redundant plan_action re-approval

The issue: `plan_action_called` is local to `_run_single_agent_step()`, so if the
coordinator loops back and calls `_run_single_agent_step()` again, `plan_action_called`
resets to False. The model then voluntarily calls plan_action a second time.

### Fix 2a — Pass plan_approved through to system prompt

In `_run_single_agent_step()`, add a `plan_already_approved: bool = False` parameter:

```python
async def _run_single_agent_step(
    task: str,
    session_id: str,
    operation_id: str,
    owner_user: str,
    *,
    system_prompt: str,
    tools_spec: list,
    agent_type: str,
    client,
    is_final_step: bool = True,
    plan_already_approved: bool = False,   # NEW
) -> dict:
```

At the top of the function, if `plan_already_approved`, inject into system_prompt:

```python
if plan_already_approved:
    system_prompt = (
        "[PLAN APPROVED] The user has already approved the plan for this task. "
        "You do NOT need to call plan_action() again. "
        "Proceed directly with execution steps.\n\n"
    ) + system_prompt
    plan_action_called = True  # pre-set so vm_exec(write) pre-flight check passes
```

### Fix 2b — Track approval across coordinator loop iterations

In `_stream_agent()`, add a session-level flag:

```python
plan_approved_this_session = False
```

In the coordinator loop, after `step_result = await _run_single_agent_step(...)`:
- Check if `"plan_action" in step_result["tools_used"]` — if yes, set `plan_approved_this_session = True`

Pass the flag to subsequent calls:

```python
step_result = await _run_single_agent_step(
    step_task, session_id, operation_id, owner_user,
    system_prompt=step_system_prompt,
    tools_spec=step_tools,
    agent_type=step_agent_type,
    client=client,
    is_final_step=(step_num == total_steps and not use_coordinator),
    plan_already_approved=plan_approved_this_session,   # NEW
)

# After the call:
if "plan_action" in step_result["tools_used"]:
    plan_approved_this_session = True
```

---

## Fix 3 — GUI — plan approval dialog colour based on risk_level

Find the component that handles `plan_pending` WebSocket events and renders
the approval dialog (likely in `App.jsx` or `OutputPanel.jsx`).

The `plan_pending` payload has:
```json
{
  "type": "plan_pending",
  "plan": {
    "summary": "...",
    "steps": [...],
    "risk_level": "low|medium|high",
    "reversible": true|false
  },
  "session_id": "..."
}
```

Update the dialog to apply colour based on risk:

```jsx
// Compute risk colour
const riskColor = (() => {
  if (!plan.reversible) return 'var(--red)'
  if (plan.risk_level === 'high') return 'var(--red)'
  if (plan.risk_level === 'medium') return 'var(--amber)'
  return 'var(--green)'
})()

const riskLabel = !plan.reversible
  ? '⚠ IRREVERSIBLE'
  : plan.risk_level === 'high'
  ? '⚠ HIGH RISK'
  : plan.risk_level === 'medium'
  ? '△ MEDIUM RISK'
  : '✓ LOW RISK'
```

Apply to the dialog header/border:

```jsx
<div style={{
  border: `1px solid ${riskColor}`,
  background: `${riskColor}18`,   // 10% opacity fill
  borderRadius: 2,
  padding: '10px 14px',
}}>
  <div style={{ color: riskColor, fontFamily: 'var(--font-mono)', fontSize: 10, marginBottom: 6 }}>
    {riskLabel}
  </div>
  <div style={{ color: 'var(--text-1)', fontSize: 12, fontWeight: 500, marginBottom: 8 }}>
    {plan.summary}
  </div>
  {plan.steps?.length > 0 && (
    <ol style={{ margin: '0 0 8px 16px', padding: 0, fontSize: 11, color: 'var(--text-2)' }}>
      {plan.steps.map((s, i) => <li key={i} style={{ marginBottom: 2 }}>{s}</li>)}
    </ol>
  )}
  <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
    <button
      onClick={() => onApprove()}
      style={{
        background: riskColor, color: '#fff',
        border: 'none', borderRadius: 2,
        padding: '4px 14px', fontSize: 11, cursor: 'pointer',
        fontFamily: 'var(--font-mono)',
      }}
    >
      APPROVE
    </button>
    <button onClick={() => onReject()} style={{ ... }}>CANCEL</button>
  </div>
</div>
```

The Approve button now uses `riskColor` — red for irreversible/high, amber for
medium, green for low. This makes it visually clear what kind of action is being approved.

---

## Fix 4 — api/routers/agent.py — prevent truncated final_answer

In `_stream_agent()`, in the cleanup block where `set_operation_final_answer` is called:

```python
last_reasoning = prior_verdict["summary"] if prior_verdict else ""
if last_reasoning:
    try:
        await logger_mod.set_operation_final_answer(session_id, last_reasoning)
    except Exception as _sfa_e:
        log.debug("set_operation_final_answer failed: %s", _sfa_e)
```

Add a truncation check — if the last reasoning ends mid-sentence, force a summary call:

```python
last_reasoning = prior_verdict["summary"] if prior_verdict else ""

# Detect truncated reasoning: ends without sentence-ending punctuation
# and is shorter than a full summary would be
_is_truncated = (
    last_reasoning
    and len(last_reasoning) < 200
    and not last_reasoning.rstrip().endswith(('.', '!', '?', ':'))
    and final_status == "completed"
)

if _is_truncated:
    # Force a clean summary from the model
    try:
        _sum_messages = [
            {"role": "system", "content": "You are a concise infrastructure ops assistant. Write a 2-3 sentence summary only."},
            {"role": "user", "content": f"Task completed: '{task}'. Write a brief summary of what was done and the outcome. Plain text, no markdown."},
        ]
        _sum_resp = client.chat.completions.create(
            model=_lm_model(),
            messages=_sum_messages,
            tools=None,
            temperature=0.3,
            max_tokens=200,
        )
        _sum_text = _sum_resp.choices[0].message.content or ""
        if _sum_text.strip():
            last_reasoning = _sum_text.strip()
    except Exception as _se:
        log.debug("Force summary for truncated answer failed: %s", _se)

if last_reasoning:
    try:
        await logger_mod.set_operation_final_answer(session_id, last_reasoning)
    except Exception as _sfa_e:
        log.debug("set_operation_final_answer failed: %s", _sfa_e)
```

---

## Version bump

Update VERSION: `2.15.3` → `2.15.4`

---

## Commit

```bash
git add -A
git commit -m "fix(agent): v2.15.4 four agent loop quality fixes

- result_query: auto-coerce WHERE dangling=true → WHERE dangling='true' (TEXT cols)
- plan_action: plan_already_approved flag prevents redundant re-approval across steps
- plan approval dialog: red border/button for irreversible/high-risk, amber for medium
- final_answer: detect truncated reasoning, force summary call before completing"
git push origin main
```
