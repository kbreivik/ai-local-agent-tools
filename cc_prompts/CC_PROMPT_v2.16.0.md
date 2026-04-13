# CC PROMPT — v2.16.0 — Agent: investigate-on-degraded + halt synthesis

## What this does

When running "Find out why the kafka_cluster is degraded", the agent immediately halts
with no findings. Three bugs: (1) research/investigate agents halt on `degraded` instead
of continuing to gather root cause; (2) a noisy auto-escalate fires and fails silently
but still streams "Escalating failed" to the GUI; (3) on halt there is zero actionable
output — no root cause, no fix steps.

This makes research/investigate agents treat `degraded` as a finding and continue
investigating. It adds a synthesis LLM call on halt (and on completion with degraded
findings) that outputs: root cause in one sentence + numbered fix steps + which steps
the agent can run automatically.

Version bump: 2.15.10 → 2.16.0

---

## Change 1 — api/routers/agent.py

### 1a — Add `_degraded_findings` tracker

In `_run_single_agent_step`, near the top of the function alongside `_audit_logged = False`
and similar flags, add:

```python
_degraded_findings: list[str] = []  # research agents: degraded results are findings, not halts
```

### 1b — Replace the halt-on-degraded block

Find this entire block (inside the `for tc in msg.tool_calls` loop, after the tool result
status is known and `send_line("tool", ...)` has fired):

```python
                if result_status in ("degraded", "failed", "escalated") or (fn_name == "escalate" and result_status != "blocked"):
                    negative_signals += 1
                    from api.memory.feedback import record_feedback_signal as _rfs2
                    asyncio.create_task(_rfs2(
                        task, "escalation", f"{fn_name} returned {result_status}: {result_msg[:80]}"
                    ))
                    await manager.send_line(
                        "halt",
                        f"HALT: {fn_name} returned {result_status} — escalating",
                        tool=fn_name, status="escalated", session_id=session_id,
                    )
                    # Auto-escalate — enrich reason with relevant memory context
                    try:
                        from api.memory.client import get_client as _get_mem
                        esc_context = await _get_mem().activate(
                            [fn_name, result_status, result_msg[:80]], max_results=2
                        )
                        esc_mem_hint = ""
                        if esc_context:
                            esc_mem_hint = " | Memory: " + "; ".join(
                                a.get("concept", "") for a in esc_context
                            )
                        esc = await asyncio.get_event_loop().run_in_executor(
                            None,
                            lambda: invoke_tool(
                                "escalate",
                                {"reason": f"Tool '{fn_name}' returned {result_status}: {result_msg}{esc_mem_hint}"},
                            ),
                        )
                        await logger_mod.log_tool_call(
                            operation_id, "escalate",
                            {"reason": f"{fn_name} → {result_status}"}, esc,
                            _lm_model(), 0,
                        )
                    except Exception:
                        pass
                    # Record in persistent escalation table for dashboard visibility
                    try:
                        from api.routers.escalations import record_escalation
                        esc_reason = f"{fn_name} returned {result_status}: {result_msg[:200]}"
                        if fn_name == "escalate" and result_status != "blocked":
                            esc_reason = result_msg or fn_args.get("reason", "Agent escalated")
                        record_escalation(
                            session_id=session_id,
                            reason=esc_reason[:500],
                            operation_id=operation_id,
                            severity="critical" if result_status == "failed" else "warning",
                        )
                        await manager.broadcast({
                            "type": "escalation_recorded",
                            "session_id": session_id,
                            "reason": esc_reason[:200],
                            "severity": "critical" if result_status == "failed" else "warning",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        })
                    except Exception as _re:
                        log.debug("record_escalation failed: %s", _re)
                    halt = True
                    final_status = "escalated"
                    break
```

Replace with:

```python
                _is_hard_failure = result_status in ("failed", "escalated") or (fn_name == "escalate" and result_status != "blocked")
                _is_degraded = result_status == "degraded"
                _is_investigate = agent_type in ("research", "investigate", "status", "observe")

                if _is_degraded and _is_investigate:
                    # Research/investigate/observe agents: degraded is a FINDING, not a halt.
                    # Accumulate and keep going — synthesis fires at end of run.
                    negative_signals += 1
                    _degraded_findings.append(f"{fn_name}: {result_msg[:120]}")
                    await manager.send_line(
                        "step",
                        f"[degraded] {fn_name} reported degraded — continuing investigation",
                        tool=fn_name, status="warning", session_id=session_id,
                    )

                elif _is_hard_failure or (_is_degraded and not _is_investigate):
                    negative_signals += 1
                    from api.memory.feedback import record_feedback_signal as _rfs2
                    asyncio.create_task(_rfs2(
                        task, "escalation", f"{fn_name} returned {result_status}: {result_msg[:80]}"
                    ))
                    await manager.send_line(
                        "halt",
                        f"HALT: {fn_name} returned {result_status}",
                        tool=fn_name, status="escalated", session_id=session_id,
                    )
                    # Record in persistent escalation table
                    try:
                        from api.routers.escalations import record_escalation
                        esc_reason = f"{fn_name} returned {result_status}: {result_msg[:200]}"
                        if fn_name == "escalate" and result_status != "blocked":
                            esc_reason = result_msg or fn_args.get("reason", "Agent escalated")
                        record_escalation(
                            session_id=session_id,
                            reason=esc_reason[:500],
                            operation_id=operation_id,
                            severity="critical" if result_status == "failed" else "warning",
                        )
                        await manager.broadcast({
                            "type": "escalation_recorded",
                            "session_id": session_id,
                            "reason": esc_reason[:200],
                            "severity": "critical" if result_status == "failed" else "warning",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        })
                    except Exception as _re:
                        log.debug("record_escalation failed: %s", _re)
                    # Synthesis: explain root cause + steps before halting
                    try:
                        _synth_ctx = "\n".join(
                            [f"- {f}" for f in _degraded_findings]
                            or [f"- {fn_name} returned {result_status}: {result_msg[:120]}"]
                        )
                        _synth_resp = client.chat.completions.create(
                            model=_lm_model(),
                            messages=[
                                {
                                    "role": "system",
                                    "content": (
                                        "You are a concise infrastructure ops assistant. "
                                        "Based on the findings, provide:\n"
                                        "1. Root cause in one sentence\n"
                                        "2. Numbered fix steps (specific commands or UI actions)\n"
                                        "3. Which steps the agent can run automatically "
                                        "if re-run with an action task\n"
                                        "Plain text only. No markdown headers."
                                    ),
                                },
                                {
                                    "role": "user",
                                    "content": (
                                        f"Task: {task}\n\nFindings:\n{_synth_ctx}\n\n"
                                        "Explain root cause and provide remediation steps."
                                    ),
                                },
                            ],
                            tools=None,
                            temperature=0.3,
                            max_tokens=400,
                        )
                        _synth_text = _synth_resp.choices[0].message.content or ""
                        if _synth_text.strip():
                            last_reasoning = _synth_text.strip()
                            await manager.send_line("reasoning", _synth_text, session_id=session_id)
                    except Exception as _se:
                        log.debug("Halt synthesis failed: %s", _se)
                    halt = True
                    final_status = "escalated"
                    break
```

### 1c — Add post-loop synthesis for investigate agents (max-steps path)

Inside the `else:` branch that handles max-steps exceeded, find:

```python
                if forced_text:
                    last_reasoning = forced_text
                    await manager.send_line("reasoning", forced_text, session_id=session_id)
```

After that block add:

```python
            # Investigate agent: if degraded findings accumulated but no synthesis yet, do it now
            if _degraded_findings and (not last_reasoning or len(last_reasoning) < 80):
                try:
                    _synth_ctx2 = "\n".join(f"- {f}" for f in _degraded_findings)
                    _synth_resp2 = client.chat.completions.create(
                        model=_lm_model(),
                        messages=[
                            {
                                "role": "system",
                                "content": (
                                    "You are a concise infrastructure ops assistant. "
                                    "Based on the findings, explain:\n"
                                    "1. Root cause in one sentence\n"
                                    "2. Numbered fix steps (specific)\n"
                                    "3. Which steps the agent can run automatically\n"
                                    "Plain text only."
                                ),
                            },
                            {
                                "role": "user",
                                "content": (
                                    f"Task: {task}\n\nFindings:\n{_synth_ctx2}\n\n"
                                    "Give root cause and remediation steps."
                                ),
                            },
                        ],
                        tools=None,
                        temperature=0.3,
                        max_tokens=400,
                    )
                    _synth_text2 = _synth_resp2.choices[0].message.content or ""
                    if _synth_text2.strip():
                        last_reasoning = _synth_text2.strip()
                        await manager.send_line("reasoning", _synth_text2, session_id=session_id)
                except Exception as _se2:
                    log.debug("Post-loop synthesis failed: %s", _se2)
```

---

## Change 2 — api/agents/router.py

### 2a — Update STATUS_PROMPT rule 4

Find in `STATUS_PROMPT`:
```
4. If a metric is degraded, note it clearly and call escalate() with the finding.
```

Replace with:
```
4. If a metric is degraded, note it clearly in your reasoning and CONTINUE checking
   other components. Degraded status is a finding, not a stop condition. Only call
   escalate() if a tool returns status=failed or the system is completely unreachable.
   After gathering all findings, synthesise: root cause (one sentence), exact fix steps
   (numbered), which steps you can run automatically vs which require manual action.
```

### 2b — Update RESEARCH_PROMPT rule 4

Find in `RESEARCH_PROMPT`:
```
4. Present findings clearly: what happened, when, likely cause, recommended fix.
```

Replace with:
```
4. Present findings clearly: what was degraded, root cause (one sentence), when it
   started if determinable. If you find a degraded component, check related components
   to chain findings (e.g. kafka degraded → check swarm_node_status to find the downed
   worker node). Always end with: "Root cause: [sentence]. Fix steps: 1. ... 2. ..."
```

---

## Do NOT touch

- Halt/escalate logic for action/execute agents — they still halt on degraded
- `api/routers/escalations.py`
- `EscalationBanner.jsx`
- Any collector, connector, or other router file

---

## Version bump

Update `VERSION`: `2.15.10` → `2.16.0`

---

## Commit

```bash
git add -A
git commit -m "fix(agent): v2.16.0 investigate agents continue on degraded; halt synthesises root cause + steps

- research/investigate/status/observe agents: degraded result = finding, not halt
- _degraded_findings list accumulates findings; loop continues instead of breaking
- action/execute agents: still halt on degraded (pre-check failure path preserved)
- on halt: fires synthesis LLM call returning root cause + numbered fix steps
- max-steps path: synthesis fires if degraded findings present and no summary yet
- removed noisy auto-escalate invoke_tool('escalate') that was failing silently
- STATUS_PROMPT rule 4: continue on degraded, synthesise root cause at end
- RESEARCH_PROMPT rule 4: chain findings, end with root cause + fix steps"
git push origin main
```
