# CC PROMPT — v2.45.13 — fix(agent): clarifying_question→plan_action structural injection

## Root cause

After `clarifying_question()` returns any non-cancel answer, the model calls
`audit_log()` instead of `plan_action()`. Prompt rules (v2.45.7, v2.45.9) are
ignored consistently across all 4 action tests.

Root: the tool result message for `clarifying_question` just says
`"User answered: {answer}"`. The LLM reads this and then picks the next tool
based on its priors — which is `audit_log` as a "task complete" signal.

Fix: inject a hard directive INTO the tool result content itself, so the LLM
sees it in the immediate tool-call context (not just the system prompt):

```python
result = {
    "status": "ok",
    "answer": answer,
    "message": f"User answered: {answer}. NOW call plan_action() immediately as your next tool.",
    ...
}
```

Additionally, append a harness system message into the conversation messages
list AFTER the clarification result (same pattern used for plan dedup), forcing
the directive into the assistant's visible context before the next LLM step.

Version bump: 2.45.12 → 2.45.13.

---

## Change — `api/agents/step_tools.py`

Find the clarifying_question result block (the entire block after
`answer = await wait_for_clarification(session_id)`):

```python
                answer = await wait_for_clarification(session_id)
                result = {
                    "status":  "ok",
                    "answer":  answer,
                    "message": f"User answered: {answer}",
                    "data":    {"question": question, "answer": answer},
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
```

Replace with:

```python
                answer = await wait_for_clarification(session_id)
                _is_cancel = answer.lower() in ("cancel", "timeout — proceed with best guess", "")
                _directive = (
                    "" if _is_cancel
                    else " Your NEXT tool call MUST be plan_action(). Do NOT call audit_log."
                )
                result = {
                    "status":  "ok",
                    "answer":  answer,
                    "message": f"User answered: {answer}.{_directive}",
                    "data":    {"question": question, "answer": answer},
                    "next_required_tool": None if _is_cancel else "plan_action",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                # Inject harness system message so the directive appears in
                # conversation context before the next LLM step
                if not _is_cancel:
                    messages.append({
                        "type": "harness",
                        "content": (
                            f"[SYSTEM] Clarification received: '{answer}'. "
                            "You now have all information needed. "
                            "Call plan_action() as your next tool immediately. "
                            "Do NOT call audit_log. Do NOT ask another question."
                        ),
                        "session_id": session_id,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
```

CC: The `messages` list in this context is the WS broadcast list, NOT the LLM
conversation. Do NOT append to the LLM messages here. The key fix is the
`result["message"]` directive which IS included in the tool result the LLM sees.
The WS broadcast of the harness message is informational only.

---

## Version bump

Update `VERSION`: `2.45.12` → `2.45.13`

---

## Commit

```
git add -A
git commit -m "fix(agent): v2.45.13 clarifying_question result injects plan_action directive"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
