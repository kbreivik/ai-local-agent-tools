"""POST /api/agent/run — execute agent task, stream output via WebSocket."""
import asyncio
import json
import logging
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone

log = logging.getLogger(__name__)

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

from api.websocket import manager
import api.logger as logger_mod

router = APIRouter(prefix="/api/agent", tags=["agent"])

def _lm_base():  return os.environ.get("LM_STUDIO_BASE_URL", "http://localhost:1234/v1")
def _lm_model(): return os.environ.get("LM_STUDIO_MODEL", "lmstudio-community/qwen3-coder-30b-a3b-instruct")
def _lm_key():   return os.environ.get("LM_STUDIO_API_KEY", "lm-studio")

# Ensure project root importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from api.tool_registry import get_registry, invoke_tool


def _build_tools_spec() -> list[dict]:
    registry = get_registry()
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["schema"],
            },
        }
        for t in registry
    ]


DESTRUCTIVE_TOOLS = frozenset({
    "service_upgrade", "service_rollback", "node_drain",
    "checkpoint_restore", "kafka_rolling_restart_safe",
})

_CHOICE_SIGNAL = re.compile(
    r'(would you like|what would you like|what.*next|next step|next action'
    r'|suggest|option|choose|shall i|should i|do you want|how would you|'
    r'here are.*option|here are.*choice|here are.*action|here are.*step'
    r'|please (choose|select|let me know)|you (can|could|may))',
    re.IGNORECASE,
)

# Past-tense verbs that indicate a summary, not a suggestion
_PAST_TENSE = re.compile(
    r'^(performed|verified|saved|upgraded|downgraded|confirmed|checked|'
    r'completed|executed|applied|deployed|restarted|rolled|logged|fetched|'
    r'collected|inspected|reviewed)',
    re.IGNORECASE,
)


def _extract_choices(text: str) -> list[str] | None:
    """
    Extract numbered list items only when the agent is explicitly offering
    options/next steps — not when summarising past actions.

    Guards:
    1. Text must contain a forward-looking signal phrase.
    2. Extracted items must NOT start with a past-tense action verb.
    Returns None if fewer than 2 valid choices found.
    """
    if not _CHOICE_SIGNAL.search(text):
        print("[DEBUG choices] no signal phrase — skipping extraction")
        return None

    choices = []
    for line in text.split('\n'):
        m = re.match(r'^\s*\d+[.)]\s+(.+)', line)
        if m:
            val = re.sub(r'\*+|_+|`+', '', m.group(1))
            val = val.strip().rstrip(':').strip()
            if val and not _PAST_TENSE.match(val):
                choices.append(val)

    result = choices[:5] if len(choices) >= 2 else None
    print(f"[DEBUG choices] extracted: {result}")
    return result


class RunRequest(BaseModel):
    task: str = "Perform a full infrastructure health check and report status."
    session_id: str = ""


class RunResponse(BaseModel):
    session_id: str
    operation_id: str
    message: str


_AGENT_LABEL = {
    'status':   'Status',
    'action':   'Action',
    'research': 'Research',
    'ambiguous': 'Action',
}

_AGENT_BADGE_COLOR = {
    'status':   'blue',
    'action':   'orange',
    'research': 'purple',
    'ambiguous': 'orange',
}


async def _stream_agent(task: str, session_id: str, operation_id: str):
    """Run the full agent loop, streaming every step to WebSocket clients."""
    from openai import OpenAI
    from api.agents.router import classify_task, filter_tools, get_prompt

    base_url = _lm_base()
    model    = _lm_model()
    api_key  = _lm_key()

    # Classify task → select agent type, prompt, tool subset
    agent_type = classify_task(task)
    if agent_type == 'ambiguous':
        agent_type = 'action'   # default to action for ambiguous tasks

    system_prompt = get_prompt(agent_type)

    # ── Inject past outcomes + relevant doc chunks into system prompt ─────────
    try:
        from api.memory.feedback import get_past_outcomes, build_outcome_prompt_section
        from api.memory.client import get_client as _get_mem_client

        injected_sections: list[str] = []
        doc_chunks: list[dict] = []

        # Past outcomes (all agent types)
        past_outcomes = await get_past_outcomes(task, max_results=4)
        outcome_section = build_outcome_prompt_section(past_outcomes)
        if outcome_section:
            injected_sections.append(outcome_section)

        # Doc chunks (research agent — activate on task keywords + component names)
        if agent_type == "research":
            _mem = _get_mem_client()
            doc_context_terms = [w for w in task.lower().split() if len(w) > 3][:6] + ["documentation"]
            doc_activations = await _mem.activate(doc_context_terms, max_results=5)
            doc_chunks = [
                a for a in doc_activations
                if "documentation" in a.get("tags", []) or
                   a.get("concept", "").startswith("docs:")
            ]
            if doc_chunks:
                doc_lines = ["RELEVANT DOCUMENTATION:"]
                for dc in doc_chunks:
                    content = dc.get("content", "")
                    # Strip the metadata header line and show the content
                    body = re.sub(r'^\[source:[^\]]+\]\n\n', '', content).strip()
                    # Extract source name from header
                    src_m = re.search(r'source:\s*([^|]+)', content)
                    src = src_m.group(1).strip() if src_m else "docs"
                    doc_lines.append(f"[{src}]\n{body[:500]}")
                injected_sections.append("\n\n".join(doc_lines))

        if injected_sections:
            injection = "\n\n".join(injected_sections) + "\n\n"
            system_prompt = injection + system_prompt
            total_injected = len(past_outcomes) + (len(doc_chunks) if agent_type == "research" else 0)
            await manager.send_line(
                "memory",
                f"[memory] {total_injected} context item(s) injected into prompt",
                status="ok", session_id=session_id,
            )
    except Exception:
        pass

    client = OpenAI(base_url=base_url, api_key=api_key)
    all_tools_spec = _build_tools_spec()
    tools_spec = filter_tools(all_tools_spec, agent_type)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": task},
    ]

    # ── Per-run feedback accumulators ─────────────────────────────────────────
    tools_used_names: list[str] = []
    positive_signals = 0
    negative_signals = 0

    # Broadcast agent type so GUI can display badge
    await manager.broadcast({
        "type":       "agent_start",
        "agent_type": agent_type,
        "session_id": session_id,
        "timestamp":  datetime.now(timezone.utc).isoformat(),
    })

    await manager.send_line("step", f"Agent started — task: {task}", status="ok", session_id=session_id)
    await manager.send_line("step", f"Model: {model} | Agent: {_AGENT_LABEL[agent_type]}", status="ok", session_id=session_id)

    step = 0
    max_steps = 40
    final_status = "completed"
    last_reasoning = ""

    try:
        while step < max_steps:
            step += 1
            await manager.send_line("step", f"── Step {step} ──", session_id=session_id)

            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    tools=tools_spec,
                    tool_choice="auto",
                    temperature=0.1,
                    max_tokens=2048,
                )
            except Exception as e:
                await manager.broadcast({
                    "type": "error", "session_id": session_id,
                    "content": f"LM Studio error: {e}", "status": "error",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                final_status = "error"
                break

            msg = response.choices[0].message
            finish = response.choices[0].finish_reason

            if msg.content:
                last_reasoning = msg.content
                await manager.send_line("reasoning", msg.content, session_id=session_id)

            if finish == "stop" or not msg.tool_calls:
                # Safety guard: action agent with destructive task must call plan_action
                # before finishing. If model gave a text response instead, remind it.
                _DESTRUCTIVE_TASK_WORDS = frozenset({
                    "upgrade", "downgrade", "rollback", "restart", "drain", "restore",
                    "kafka_rolling_restart",
                })
                _task_words = set(re.findall(r'\b\w+\b', task.lower()))
                _has_destructive_intent = bool(_task_words & _DESTRUCTIVE_TASK_WORDS)
                _plan_called = "plan_action" in tools_used_names

                if (agent_type == "action" and _has_destructive_intent
                        and not _plan_called and step < max_steps - 2):
                    # Model forgot to call plan_action — inject a mandatory reminder
                    if msg.content:
                        messages.append({"role": "assistant", "content": msg.content})
                    messages.append({
                        "role": "user",
                        "content": (
                            "MANDATORY: You must call plan_action() as a TOOL before "
                            "executing any destructive action. Do NOT write the plan as text. "
                            "Call plan_action() now with: summary, steps (list), "
                            "risk_level (low/medium/high), reversible (true/false)."
                        ),
                    })
                    await manager.send_line(
                        "step",
                        "[safety] plan_action not yet called — reminding model",
                        status="ok", session_id=session_id,
                    )
                    continue  # Next iteration will call plan_action

                choices = _extract_choices(last_reasoning) if last_reasoning else None
                payload = {
                    "type":       "done",
                    "session_id": session_id,
                    "agent_type": agent_type,
                    "content":    f"Agent finished after {step} steps.",
                    "status":     "ok",
                    "choices":    choices or [],
                    "timestamp":  datetime.now(timezone.utc).isoformat(),
                }
                print(f"[DEBUG broadcast] agent done choices={choices}")
                await manager.broadcast(payload)
                break

            # Build assistant message for history
            messages.append({
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name,
                                     "arguments": tc.function.arguments},
                    }
                    for tc in msg.tool_calls
                ],
            })

            # Pre-flight safety check: if any destructive tool is requested in this
            # batch without plan_action already called, block it and inject a reminder.
            _req_tools = {tc.function.name for tc in msg.tool_calls}
            _destructive_req = _req_tools & DESTRUCTIVE_TOOLS
            if _destructive_req and "plan_action" not in tools_used_names:
                block_msg = (
                    "STOP. You requested destructive tool(s) "
                    f"{sorted(_destructive_req)} without calling plan_action() first. "
                    "You MUST call plan_action() before any destructive action. "
                    "Call plan_action() now."
                )
                await manager.send_line(
                    "step", f"[safety] Blocked {_destructive_req} — plan_action required first",
                    status="ok", session_id=session_id,
                )
                # Return a synthetic tool result for each blocked tool, then re-prompt
                for _btc in msg.tool_calls:
                    if _btc.function.name in _destructive_req:
                        messages.append({
                            "role": "tool",
                            "tool_call_id": _btc.id,
                            "content": json.dumps({
                                "status": "blocked",
                                "message": "plan_action() must be called before this tool.",
                            }),
                        })
                # Also append tool results for any non-destructive tools in same batch
                for _btc in msg.tool_calls:
                    if _btc.function.name not in _destructive_req:
                        messages.append({
                            "role": "tool",
                            "tool_call_id": _btc.id,
                            "content": json.dumps({"status": "blocked", "message": "Batch blocked"}),
                        })
                messages.append({"role": "user", "content": block_msg})
                continue  # Re-enter while loop to call plan_action

            halt = False
            for tc in msg.tool_calls:
                fn_name = tc.function.name
                tools_used_names.append(fn_name)
                try:
                    fn_args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    fn_args = {}

                # Retrieve memory context before executing
                from api.memory.hooks import before_tool_call, after_tool_call as _mem_after
                mem_context = await before_tool_call(fn_name, fn_args)
                if mem_context:
                    await manager.send_line(
                        "memory",
                        f"[memory] {len(mem_context)} relevant engram(s) activated",
                        tool=fn_name, status="ok", session_id=session_id,
                    )

                t0 = time.monotonic()
                try:
                    if fn_name == "plan_action":
                        # Intercept: broadcast plan to GUI, suspend until approved/rejected
                        plan = {
                            "summary":    fn_args.get("summary", ""),
                            "steps":      fn_args.get("steps") or [],
                            "risk_level": fn_args.get("risk_level", "medium"),
                            "reversible": fn_args.get("reversible", True),
                        }
                        await manager.broadcast({
                            "type":       "plan_pending",
                            "plan":       plan,
                            "session_id": session_id,
                            "timestamp":  datetime.now(timezone.utc).isoformat(),
                        })
                        await manager.send_line(
                            "step",
                            f"[plan] Waiting for user approval: {plan['summary']}",
                            status="ok", session_id=session_id,
                        )
                        from api.confirmation import wait_for_confirmation
                        from api.memory.feedback import record_feedback_signal as _rfs
                        approved = await wait_for_confirmation(session_id)
                        if approved:
                            positive_signals += 1
                            asyncio.create_task(_rfs(
                                task, "plan_approved", plan["summary"][:120]
                            ))
                            result = {
                                "status":   "ok",
                                "approved": True,
                                "message":  "User confirmed. Proceed with plan.",
                                "data":     {"approved": True},
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            }
                            await manager.send_line("step", "[plan] Approved — executing plan.", status="ok", session_id=session_id)
                        else:
                            negative_signals += 1
                            asyncio.create_task(_rfs(
                                task, "plan_cancelled", plan["summary"][:120]
                            ))
                            result = {
                                "status":   "ok",
                                "approved": False,
                                "message":  "User cancelled. Do not proceed.",
                                "data":     {"approved": False},
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            }
                            await manager.send_line("step", "[plan] Cancelled by user — stopping.", status="ok", session_id=session_id)

                    elif fn_name == "clarifying_question":
                        # Intercept: broadcast question to GUI, suspend until answered
                        question = fn_args.get("question", "")
                        options  = fn_args.get("options") or []
                        negative_signals += 1   # task was ambiguous — mild negative signal
                        from api.memory.feedback import record_feedback_signal as _rfs
                        asyncio.create_task(_rfs(
                            task, "clarification_needed", question[:120]
                        ))
                        await manager.broadcast({
                            "type":      "clarification_needed",
                            "question":  question,
                            "options":   options,
                            "session_id": session_id,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        })
                        await manager.send_line(
                            "step", f"[clarification] Waiting for user: {question}", status="ok", session_id=session_id,
                        )
                        from api.clarification import wait_for_clarification
                        answer = await wait_for_clarification(session_id)
                        result = {
                            "status":  "ok",
                            "answer":  answer,
                            "message": f"User answered: {answer}",
                            "data":    {"question": question, "answer": answer},
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    else:
                        result = await asyncio.get_event_loop().run_in_executor(
                            None, lambda n=fn_name, a=fn_args: invoke_tool(n, a)
                        )
                except Exception as e:
                    result = {"status": "error", "message": str(e), "data": None,
                              "timestamp": datetime.now(timezone.utc).isoformat()}
                    negative_signals += 1
                    from api.memory.feedback import record_feedback_signal as _rfs
                    asyncio.create_task(_rfs(task, "tool_error", f"{fn_name}: {str(e)[:80]}"))

                duration_ms = int((time.monotonic() - t0) * 1000)
                result_status = result.get("status", "error") if isinstance(result, dict) else "error"
                result_msg = result.get("message", "") if isinstance(result, dict) else str(result)

                # Store tool execution in memory (non-blocking)
                _mem_after(fn_name, fn_args, result, result_status, duration_ms)

                # Log to SQLite
                await logger_mod.log_tool_call(
                    operation_id, fn_name, fn_args, result,
                    model, duration_ms
                )

                # Stream to GUI
                await manager.send_line(
                    "tool",
                    f"[{fn_name}] → {result_status} | {result_msg}",
                    tool=fn_name, status=result_status, session_id=session_id,
                )

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result),
                })

                if result_status in ("degraded", "failed"):
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
                            model, 0,
                        )
                    except Exception:
                        pass
                    halt = True
                    final_status = "escalated"
                    break

            if halt:
                await manager.send_line("halt", "Agent halted — human review required.",
                                        status="escalated", session_id=session_id)
                break

        else:
            await manager.broadcast({
                "type": "done", "session_id": session_id, "agent_type": agent_type,
                "content": f"Agent reached max steps ({max_steps}).",
                "status": "ok", "choices": [],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

    except Exception as e:
        await manager.broadcast({
            "type": "error", "session_id": session_id,
            "content": f"Agent loop error: {e}", "status": "error",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        final_status = "error"

    # If the agent halted (escalated), the while loop broke without a done/error
    # broadcast — send one now so any waiting WebSocket clients can close.
    if final_status == "escalated":
        await manager.broadcast({
            "type": "error", "session_id": session_id,
            "agent_type": agent_type,
            "content": "Agent halted — escalated for human review.",
            "status": "escalated", "choices": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    # ── Record outcome for feedback loop ─────────────────────────────────────
    try:
        from api.memory.feedback import record_outcome
        await record_outcome(
            session_id=session_id,
            task=task,
            agent_type=agent_type,
            tools_used=tools_used_names,
            status=final_status,
            steps=step,
            positive_signals=positive_signals,
            negative_signals=negative_signals,
        )
    except Exception as _oe:
        log.debug("record_outcome error: %s", _oe)

    await logger_mod.complete_operation(operation_id, final_status)


@router.post("/run", response_model=RunResponse)
async def run_agent(req: RunRequest, background_tasks: BackgroundTasks):
    """Start an agent task. Streams output to ws://host:8000/ws/output."""
    session_id = req.session_id or str(uuid.uuid4())
    operation_id = await logger_mod.log_operation(session_id, req.task[:120])
    background_tasks.add_task(_stream_agent, req.task, session_id, operation_id)
    return RunResponse(
        session_id=session_id,
        operation_id=operation_id,
        message="Agent started — connect to ws://[host]:8000/ws/output for live output",
    )


class ClarifyRequest(BaseModel):
    session_id: str
    answer: str


class ConfirmRequest(BaseModel):
    session_id: str
    approved: bool


@router.post("/confirm")
async def confirm_plan(req: ConfirmRequest):
    """Resolve a pending plan_action() call in the agent loop."""
    from api.confirmation import resolve_confirmation
    ok = resolve_confirmation(req.session_id, req.approved)
    if not ok:
        return {"status": "error", "message": f"No pending plan for session '{req.session_id}'"}
    action = "approved" if req.approved else "cancelled"
    return {"status": "ok", "message": f"Plan {action}"}


@router.post("/clarify")
async def clarify_agent(req: ClarifyRequest):
    """Resolve a pending clarifying_question() call in the agent loop."""
    from api.clarification import resolve_clarification
    ok = resolve_clarification(req.session_id, req.answer)
    if not ok:
        return {"status": "error", "message": f"No pending clarification for session '{req.session_id}'"}
    return {"status": "ok", "message": "Clarification received"}


@router.get("/models")
async def list_models():
    """Probe LM Studio for loaded models."""
    try:
        from openai import OpenAI
        client = OpenAI(base_url=_lm_base(), api_key=_lm_key())
        models = client.models.list()
        return {"models": [m.id for m in models.data], "base_url": _lm_base()}
    except Exception as e:
        return {"models": [], "error": str(e), "base_url": _lm_base()}
