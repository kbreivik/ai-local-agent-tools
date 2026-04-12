# CC PROMPT — v2.10.0 — Lightweight Coordinator Pattern Between Agent Steps

## What this does

Replaces the static keyword-based `build_step_plan()` orchestrator with a lightweight
coordinator that runs between steps and decides what to do next based on actual results.

The coordinator is a tiny LLM call (no tools, max 200 tokens, 4k context) that receives:
- The original task
- A structured summary of what the last step found
- A set of available next actions

It returns structured JSON: `{"next": "done|continue|query|escalate", "reason": "...", "context": "..."}`

This makes multi-step tasks **adaptive** rather than pre-planned, and the context passed
between steps is compact structured data rather than prose summaries.

Version bump: 2.9.1 → 2.10.0 (major architectural change to the agent loop, x.1.x bump)

---

## Change 1 — api/agents/orchestrator.py — add coordinator function

Add to orchestrator.py (keep existing functions — they're used for single-step tasks):

```python
# ── Coordinator ───────────────────────────────────────────────────────────────

_COORDINATOR_SYSTEM = """You are a task coordinator for an infrastructure AI system.

Given a task and the result of the last step, decide what to do next.
Respond ONLY with valid JSON — no prose, no markdown, no explanation outside the JSON.

Available next values:
  "done"      — task is fully answered, no more steps needed
  "continue"  — run another tool/step (specify which in context)
  "query"     — need more data before deciding (specify what in context)
  "escalate"  — something went wrong or needs human review

Response format (strict JSON):
{
  "next": "done|continue|query|escalate",
  "reason": "one sentence, max 80 chars",
  "context": "what to tell the next agent step (max 150 chars)",
  "tool_hint": "optional: name of tool the next step should try first"
}"""


def run_coordinator(
    task: str,
    step_summary: str,
    step_verdict: str,
    available_tools: list[str],
    client,
    model: str,
) -> dict:
    """Run a lightweight coordinator to decide the next action.

    Args:
        task:           Original user task
        step_summary:   Compact summary of what the last step found (≤200 chars)
        step_verdict:   GO | ASK | HALT from verdict_from_text()
        available_tools: Names of tools available to the next step
        client:         OpenAI-compat client (LM Studio)
        model:          Model name string

    Returns coordinator decision dict with keys: next, reason, context, tool_hint
    Falls back to {"next": "done", "reason": "coordinator unavailable", ...} on error.
    """
    import json as _json

    # If verdict is already HALT, don't even call the coordinator
    if step_verdict == "HALT":
        return {"next": "escalate", "reason": "step returned HALT",
                "context": step_summary[:150], "tool_hint": ""}

    tools_str = ", ".join(available_tools[:15]) if available_tools else "none"

    user_msg = (
        f"Task: {task[:200]}\n"
        f"Last step result: {step_summary[:200]}\n"
        f"Verdict: {step_verdict}\n"
        f"Available tools: {tools_str}\n\n"
        "What should happen next?"
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _COORDINATOR_SYSTEM},
                {"role": "user",   "content": user_msg + "\n/no_think"},
            ],
            tools=None,
            temperature=0.1,
            max_tokens=200,
        )
        text = response.choices[0].message.content or ""
        # Strip any markdown fences
        text = text.strip().strip("```json").strip("```").strip()
        decision = _json.loads(text)
        # Validate required keys
        if "next" not in decision:
            raise ValueError("missing 'next' key")
        return decision
    except Exception as e:
        import logging as _log
        _log.getLogger(__name__).debug("coordinator failed: %s", e)
        # Safe fallback: if verdict was GO, continue; otherwise done
        return {
            "next": "continue" if step_verdict == "GO" else "done",
            "reason": f"coordinator unavailable ({type(e).__name__})",
            "context": step_summary[:150],
            "tool_hint": "",
        }


def should_use_coordinator(steps: list[dict]) -> bool:
    """Return True if this task warrants coordinator-guided multi-step execution.

    Single-step tasks skip the coordinator (no overhead needed).
    Multi-step tasks or tasks with check/cleanup words use coordinator.
    """
    return len(steps) > 1
```

---

## Change 2 — api/routers/agent.py — integrate coordinator into _stream_agent

### 2a — Import coordinator

```python
from api.agents.orchestrator import (
    build_step_plan, format_step_header, verdict_from_text,
    extract_structured_verdict, run_coordinator, should_use_coordinator,
)
```

### 2b — Coordinator loop in _stream_agent

Replace the current `for step_info in steps:` loop with a coordinator-aware version.

The key change: after each step completes, if `should_use_coordinator(steps)` is True,
call `run_coordinator()` instead of using `verdict_from_text()` alone.

```python
    use_coordinator = should_use_coordinator(steps)
    coordinator_step = 0
    MAX_COORDINATOR_STEPS = 5   # prevent coordinator from looping forever

    for step_info in steps:
        step_intent = step_info["intent"]
        step_domain = step_info.get("domain")
        step_task   = step_info["task"]
        step_num    = step_info["step"]
        total_steps = len(steps)

        if total_steps > 1:
            header = format_step_header(step_num, total_steps, step_intent, step_domain)
            await manager.send_line("agent", header, session_id=session_id)

        step_agent_type = step_intent
        if step_agent_type == "ambiguous":
            step_agent_type = "execute"

        # ... existing step_system_prompt building ...

        step_result = await _run_single_agent_step(
            step_task, session_id, operation_id, owner_user,
            system_prompt=step_system_prompt,
            tools_spec=step_tools,
            agent_type=step_agent_type,
            client=client,
            is_final_step=(step_num == total_steps and not use_coordinator),
        )

        all_tools_used.extend(step_result["tools_used"])
        agg_positive += step_result["positive_signals"]
        agg_negative += step_result["negative_signals"]
        agg_steps    += step_result["steps_taken"]
        agg_prompt_tokens     += step_result.get("prompt_tokens", 0)
        agg_completion_tokens += step_result.get("completion_tokens", 0)
        final_status  = step_result["final_status"]

        # ── Coordinator decision ───────────────────────────────────────────────
        prior_verdict = extract_structured_verdict(step_result["output"], step_info)

        if use_coordinator and coordinator_step < MAX_COORDINATOR_STEPS:
            coordinator_step += 1
            available_tool_names = [t["function"]["name"] for t in step_tools]

            decision = run_coordinator(
                task=task,
                step_summary=prior_verdict.get("summary", "")[:200],
                step_verdict=prior_verdict["verdict"],
                available_tools=available_tool_names,
                client=client,
                model=_lm_model(),
            )

            await manager.send_line(
                "step",
                f"[coordinator] next={decision['next']} — {decision.get('reason', '')}",
                status="ok", session_id=session_id,
            )

            if decision["next"] == "done":
                # Coordinator says we're done — broadcast and exit
                await manager.broadcast({
                    "type": "done", "session_id": session_id,
                    "agent_type": first_intent,
                    "content": step_result["output"] or "Task complete.",
                    "status": "ok", "choices": [],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                break

            elif decision["next"] == "escalate":
                halted_early = True
                final_status = "escalated"
                break

            elif decision["next"] in ("continue", "query"):
                # Build next step dynamically from coordinator decision
                context_for_next = decision.get("context", "")
                tool_hint = decision.get("tool_hint", "")
                next_task = (
                    f"{task}"
                    + (f"\n[Context from previous step: {context_for_next}]" if context_for_next else "")
                    + (f"\n[Suggested next tool: {tool_hint}]" if tool_hint else "")
                )
                # Inject coordinator context as next step
                # (re-uses same step_info structure, increments step_num)
                next_step_info = {
                    "step":   step_num + 1,
                    "intent": step_intent,
                    "domain": step_domain,
                    "task":   next_task,
                }
                steps.append(next_step_info)  # dynamic step addition
                total_steps = len(steps)
                prior_verdict = {"verdict": "GO", "summary": context_for_next}
                continue

        else:
            # No coordinator — use static verdict (existing behavior)
            if prior_verdict["verdict"] == "HALT" and step_num < total_steps:
                await manager.send_line(
                    "agent",
                    f"⛔ Step {step_num} returned HALT — stopping. "
                    f"Reason: {prior_verdict['summary'][:200]}",
                    session_id=session_id,
                )
                halted_early = True
                break
```

Note: The dynamic `steps.append()` allows the coordinator to extend the plan at runtime.
Cap at `MAX_COORDINATOR_STEPS` additions to prevent infinite loops.

---

## Change 3 — Add coordinator token tracking

In the coordinator call, track tokens the same way as the main loop:

```python
            # Track coordinator tokens (small but nonzero)
            if hasattr(response, 'usage') and response.usage:
                agg_prompt_tokens     += getattr(response.usage, 'prompt_tokens', 0) or 0
                agg_completion_tokens += getattr(response.usage, 'completion_tokens', 0) or 0
```

---

## Change 4 — STATUS_PROMPT update

Add to STATUS_PROMPT in api/agents/router.py, before STOPPING RULES:

```
COORDINATOR CONTEXT:
You may receive a [Context from previous step: ...] note in your task.
This contains structured facts found by the prior step. Use it to avoid
re-fetching data you already have. Only call tools for information not
yet in the context.

You may also receive [Suggested next tool: ...] — call that tool first
unless you have a clear reason not to.
```

---

## Version bump

Update VERSION: `2.9.1` → `2.10.0`

---

## Commit

```bash
git add -A
git commit -m "feat(agent): v2.10.0 lightweight coordinator pattern for multi-step tasks

- run_coordinator(): tiny LLM call (no tools, 200 tokens) between steps
- Decides: done | continue | query | escalate with structured JSON
- Dynamic step extension: coordinator can append new steps at runtime
- should_use_coordinator(): skips coordinator for single-step tasks
- Context passing: compact structured facts replace prose summaries
- MAX_COORDINATOR_STEPS=5 guard prevents infinite extension
- /no_think injected into coordinator prompt for fast response
- Coordinator tokens accumulated in session total"
git push origin main
```
