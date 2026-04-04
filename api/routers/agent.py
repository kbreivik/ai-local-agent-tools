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

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, Field

from api.websocket import manager
from api.auth import get_current_user
import api.logger as logger_mod
from api.constants import DEFAULT_LM_STUDIO_URL, DEFAULT_LM_STUDIO_MODEL, DEFAULT_LM_STUDIO_KEY

router = APIRouter(prefix="/api/agent", tags=["agent"])

def _lm_base():  return os.environ.get("LM_STUDIO_BASE_URL", DEFAULT_LM_STUDIO_URL)
def _lm_model(): return os.environ.get("LM_STUDIO_MODEL",    DEFAULT_LM_STUDIO_MODEL)
def _lm_key():   return os.environ.get("LM_STUDIO_API_KEY",  DEFAULT_LM_STUDIO_KEY)

# Ensure project root importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from api.tool_registry import get_registry, invoke_tool
from api.lock import plan_lock


def _build_tools_spec() -> list[dict]:
    registry = get_registry()
    spec = [
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
    log.info("Sending %d tools to LLM: %s", len(spec), [t["function"]["name"] for t in spec])
    return spec


DESTRUCTIVE_TOOLS = frozenset({
    "service_upgrade", "service_rollback", "node_drain",
    "checkpoint_restore", "kafka_rolling_restart_safe",
    "docker_engine_update",
    # Skill write-tools — modify persistent state (modules on disk + DB)
    "skill_create", "skill_regenerate", "skill_disable", "skill_enable", "skill_import",
})

# Per-session cancellation flags — set by POST /api/agent/stop
# Values are (flag: bool, inserted_at: float) where inserted_at is time.monotonic().
# Entries older than _CANCEL_FLAG_TTL_SECONDS are pruned by _cleanup_stale_cancel_flags().
_CANCEL_FLAG_TTL_SECONDS = 300  # 5 minutes
_cancel_flags: dict[str, tuple[bool, float]] = {}


def _cleanup_stale_cancel_flags() -> None:
    """Remove cancel flag entries that were inserted more than _CANCEL_FLAG_TTL_SECONDS ago."""
    cutoff = time.monotonic() - _CANCEL_FLAG_TTL_SECONDS
    stale = [k for k, (_, ts) in _cancel_flags.items() if ts < cutoff]
    for k in stale:
        _cancel_flags.pop(k, None)

# Trigger phrases that must appear before a numbered list for it to be choices.
# Choices are only valid when the agent explicitly labels them as options/actions.
_CHOICE_TRIGGERS = [
    r'suggested next actions?:',
    r'available actions?:',
    r'next steps?:',
    r'you can:',
    r'options?:',
    r'would you like(?: to)?:',
    r'please (choose|select):',
    r'here are.*(?:option|action|step|choice)',
    r'what would you like',
    r'shall i',
    r'should i',
]
_CHOICE_TRIGGER_RE = re.compile(
    '|'.join(_CHOICE_TRIGGERS),
    re.IGNORECASE,
)


def _extract_choices(text: str) -> list[str] | None:
    """
    Extract numbered list items ONLY from after an explicit trigger phrase.

    Valid triggers: 'Suggested next actions:', 'You can:', 'Options:',
    'Next steps:', 'Would you like to:', 'Available actions:', etc.

    Numbered lists that appear as section headers (e.g. '1. **Swarm Status**:')
    or as summary paragraphs are NOT extracted as choices.
    Returns None if no trigger found or fewer than 2 valid choices found.
    """
    m = _CHOICE_TRIGGER_RE.search(text)
    if not m:
        return None

    # Only extract items from AFTER the trigger phrase
    relevant = text[m.end():]
    choices = []
    for line in relevant.split('\n'):
        item_m = re.match(r'^\s*\d+[.)]\s+(.+)', line)
        if item_m:
            val = re.sub(r'\*+|_+|`+', '', item_m.group(1))
            val = val.strip().rstrip(':').strip()
            if val and len(val) > 3:
                choices.append(val)
        elif line.strip() and not line.strip().startswith('-') and choices:
            # Stop at the first non-list line after we've started collecting
            # (avoids grabbing unrelated numbered lists further down)
            break

    return choices[:5] if len(choices) >= 2 else None


class RunRequest(BaseModel):
    task: str = Field(
        default="Perform a full infrastructure health check and report status.",
        max_length=4096,
    )
    session_id: str = Field(default="", max_length=128)


class RunResponse(BaseModel):
    session_id: str
    operation_id: str
    message: str


_AGENT_LABEL = {
    'status':      'Observe',
    'observe':     'Observe',
    'action':      'Execute',
    'execute':     'Execute',
    'research':    'Investigate',
    'investigate': 'Investigate',
    'build':       'Build',
    'ambiguous':   'Execute',
}

_AGENT_BADGE_COLOR = {
    'status':      'blue',
    'observe':     'blue',
    'action':      'orange',
    'execute':     'orange',
    'research':    'purple',
    'investigate': 'purple',
    'build':       'yellow',
    'ambiguous':   'orange',
}


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
) -> dict:
    """Run one agent loop iteration. Returns dict with output and feedback stats.

    Contains the existing while-loop body from _stream_agent — moved verbatim
    except that agent_type, system_prompt, tools_spec, and client come from
    parameters instead of being computed inside.
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": task},
    ]

    # ── Per-run feedback accumulators ─────────────────────────────────────────
    tools_used_names: list = []
    positive_signals = 0
    negative_signals = 0
    _audit_logged = False        # allow at most one audit_log call per run
    plan_action_called = False   # track if plan_action was called this run
    _last_blocked_tool = None    # name of most recently blocked tool

    step = 0
    _MAX_STEPS_BY_TYPE = {"status": 8, "observe": 8, "research": 12, "investigate": 12, "action": 20, "execute": 20, "build": 15}
    max_steps = _MAX_STEPS_BY_TYPE.get(agent_type, 20)
    final_status = "completed"
    last_reasoning = ""

    try:
        _cleanup_stale_cancel_flags()
        while step < max_steps:
            # Check cancellation flag before each step
            if _cancel_flags.pop(session_id, (False, 0.0))[0]:
                await manager.broadcast({
                    "type":       "error",
                    "session_id": session_id,
                    "content":    "Stopped by user.",
                    "status":     "cancelled",
                    "timestamp":  datetime.now(timezone.utc).isoformat(),
                })
                final_status = "cancelled"
                break

            step += 1
            await manager.send_line("step", f"── Step {step} ──", session_id=session_id)

            try:
                response = client.chat.completions.create(
                    model=_lm_model(),
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

                if (agent_type in ("action", "execute") and _has_destructive_intent
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
                if is_final_step:
                    payload = {
                        "type":       "done",
                        "session_id": session_id,
                        "agent_type": agent_type,
                        "content":    f"Agent finished after {step} steps.",
                        "status":     "ok",
                        "choices":    choices or [],
                        "timestamp":  datetime.now(timezone.utc).isoformat(),
                    }
                    log.debug("agent done choices=%s", choices)
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

            # Also block if global lock is held by a different session
            if _destructive_req and plan_lock.is_locked_by_other(session_id):
                lock_info = plan_lock.get_info()
                block_msg = (
                    f"STOP. Destructive tool(s) {sorted(_destructive_req)} blocked — "
                    f"global plan lock held by {lock_info['owner_user']}. "
                    "Wait for the other operation to complete."
                )
                await manager.send_line("step", f"[lock] Blocked by global lock (owner: {lock_info['owner_user']})", status="ok", session_id=session_id)
                for _btc in msg.tool_calls:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": _btc.id,
                        "content": json.dumps({"status": "locked", "message": block_msg}),
                    })
                messages.append({"role": "user", "content": block_msg})
                continue

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
                # Block duplicate audit_log calls — the model tends to loop on it.
                # One audit_log per session is sufficient.
                if fn_name == "audit_log" and _audit_logged:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps({
                            "status": "ok",
                            "message": "Audit already recorded for this session.",
                        }),
                    })
                    await manager.send_line(
                        "step", "[audit_log] skipped — already logged once this run",
                        status="ok", session_id=session_id,
                    )
                    continue
                if fn_name == "audit_log":
                    _audit_logged = True

                try:
                    if fn_name == "plan_action":
                        plan_action_called = True
                        # Try to acquire the global destructive lock
                        lock_ok = await plan_lock.acquire(session_id, owner_user)
                        if not lock_ok:
                            lock_info = plan_lock.get_info()
                            result = {
                                "status": "locked",
                                "approved": False,
                                "message": f"System locked by {lock_info['owner_user']} (session {lock_info['session_id'][:8]}). Wait for their plan to complete.",
                                "data": {"approved": False},
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            }
                            await manager.send_line("step", f"[lock] Destructive lock held by {lock_info['owner_user']} — plan blocked", status="ok", session_id=session_id)
                        else:
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
                            await plan_lock.release(session_id)

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
                    elif fn_name == "escalate" and agent_type in ("action", "execute") and not plan_action_called:
                        # Fix 2: Block premature escalation — agent must plan first
                        _last_blocked_tool = "escalate"
                        result = {
                            "status": "blocked",
                            "message": (
                                "escalate() blocked. You MUST call plan_action() next. "
                                "Do not call audit_log. Do not stop. "
                                "Call plan_action() with your proposed upgrade steps NOW. "
                                "plan_action() is the required next step."
                            ),
                            "data": None,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                        await manager.send_line(
                            "step",
                            "[safety] escalate() blocked — plan_action() must be called next",
                            status="ok", session_id=session_id,
                        )
                    else:
                        _last_blocked_tool = None   # successful tool call clears blocked state
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
                    _lm_model(), duration_ms
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
                    halt = True
                    final_status = "escalated"
                    break

            if halt:
                await manager.send_line("halt", "Agent halted — human review required.",
                                        status="escalated", session_id=session_id)
                break

            # Fix 1C: if entire step was only audit_log calls, the agent is done
            # Exception: if escalate was just blocked, the model may call audit_log
            # as a confused "done" signal — don't treat it as completion; let loop continue.
            _step_names = [tc.function.name for tc in msg.tool_calls]
            if (_step_names and all(n == "audit_log" for n in _step_names)
                    and _last_blocked_tool != "escalate"):
                choices = _extract_choices(last_reasoning) if last_reasoning else None
                if is_final_step:
                    await manager.broadcast({
                        "type": "done", "session_id": session_id, "agent_type": agent_type,
                        "content": f"Agent finished after {step} steps.",
                        "status": "ok", "choices": choices or [],
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                break

        else:
            if is_final_step:
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

    return {
        "output":           last_reasoning,
        "tools_used":       tools_used_names,
        "final_status":     final_status,
        "positive_signals": positive_signals,
        "negative_signals": negative_signals,
        "steps_taken":      step,
    }


async def _stream_agent(task: str, session_id: str, operation_id: str, owner_user: str = "admin"):
    """Run the full agent loop, streaming every step to WebSocket clients."""
    from openai import OpenAI
    from api.agents.router import classify_task, filter_tools, get_prompt
    from api.agents.orchestrator import build_step_plan, format_step_header, verdict_from_text

    base_url = _lm_base()
    api_key  = _lm_key()

    # Classify task using first step intent for memory injection
    first_intent = classify_task(task)
    if first_intent == "ambiguous":
        first_intent = "action"

    system_prompt = get_prompt(first_intent)

    # ── Inject past outcomes + relevant doc chunks into system prompt ─────────
    try:
        from api.memory.feedback import get_past_outcomes, build_outcome_prompt_section
        from api.memory.client import get_client as _get_mem_client

        injected_sections: list = []
        doc_chunks: list = []

        # Past outcomes (all agent types)
        past_outcomes = await get_past_outcomes(task, max_results=4)
        outcome_section = build_outcome_prompt_section(past_outcomes)
        if outcome_section:
            injected_sections.append(outcome_section)

        # Doc chunks (research/investigate agent — activate on task keywords + component names)
        if first_intent in ("research", "investigate"):
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
                    body = re.sub(r'^\[source:[^\]]+\]\n\n', '', content).strip()
                    src_m = re.search(r'source:\s*([^|]+)', content)
                    src = src_m.group(1).strip() if src_m else "docs"
                    doc_lines.append(f"[{src}]\n{body[:500]}")
                injected_sections.append("\n\n".join(doc_lines))

        if injected_sections:
            injection = "\n\n".join(injected_sections) + "\n\n"
            system_prompt = injection + system_prompt
            total_injected = len(past_outcomes) + (len(doc_chunks) if first_intent in ("research", "investigate") else 0)
            await manager.send_line(
                "memory",
                f"[memory] {total_injected} context item(s) injected into prompt",
                status="ok", session_id=session_id,
            )
    except Exception:
        pass

    client = OpenAI(base_url=base_url, api_key=api_key)

    # Build orchestrator step plan
    steps = build_step_plan(task)
    prior_verdict = None

    # Broadcast agent start (using first step's intent for badge)
    await manager.broadcast({
        "type":       "agent_start",
        "agent_type": first_intent,
        "session_id": session_id,
        "timestamp":  datetime.now(timezone.utc).isoformat(),
    })

    await manager.send_line("step", f"Agent started — task: {task}", status="ok", session_id=session_id)
    await manager.send_line("step", f"Model: {_lm_model()} | Agent: {_AGENT_LABEL.get(first_intent, 'Execute')}", status="ok", session_id=session_id)

    # Aggregate feedback across all steps
    all_tools_used: list = []
    agg_positive = 0
    agg_negative = 0
    agg_steps = 0
    final_status = "completed"
    halted_early = False
    all_tools = _build_tools_spec()

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

        step_system_prompt = get_prompt(step_agent_type)

        # Prepend prior step verdict as context (minimal — no prose)
        if prior_verdict:
            context_line = (
                f"[Prior step verdict: {prior_verdict['verdict']} — "
                f"{prior_verdict['summary'][:200]}]\n\n"
            )
            step_system_prompt = context_line + step_system_prompt
        else:
            # First step: use the already-injected memory prompt
            step_system_prompt = system_prompt

        step_tools = filter_tools(all_tools, step_agent_type, domain=step_domain or "general")
        log.info(
            "Agent=%s domain=%s filtered manifest: %d tools — %s",
            step_agent_type, step_domain, len(step_tools),
            [t["function"]["name"] for t in step_tools],
        )

        step_result = await _run_single_agent_step(
            step_task, session_id, operation_id, owner_user,
            system_prompt=step_system_prompt,
            tools_spec=step_tools,
            agent_type=step_agent_type,
            client=client,
            is_final_step=(step_num == total_steps),
        )

        all_tools_used.extend(step_result["tools_used"])
        agg_positive += step_result["positive_signals"]
        agg_negative += step_result["negative_signals"]
        agg_steps    += step_result["steps_taken"]
        final_status  = step_result["final_status"]

        prior_verdict = verdict_from_text(step_result["output"])

        # If step halted and there are more steps, stop the plan
        if prior_verdict["verdict"] == "HALT" and step_num < total_steps:
            await manager.send_line(
                "agent",
                f"⛔ Step {step_num} returned HALT — stopping plan. "
                f"Reason: {prior_verdict['summary'][:200]}",
                session_id=session_id,
            )
            halted_early = True
            break

    if halted_early:
        await manager.broadcast({
            "type": "done", "session_id": session_id,
            "agent_type": first_intent,
            "content": "Plan halted — pre-conditions not met.",
            "status": "ok", "choices": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    # ── Cleanup: always runs regardless of how the agent loop exited ─────────
    try:
        # Record outcome for feedback loop
        try:
            from api.memory.feedback import record_outcome
            await record_outcome(
                session_id=session_id,
                task=task,
                agent_type=first_intent,
                tools_used=all_tools_used,
                status=final_status,
                steps=agg_steps,
                positive_signals=agg_positive,
                negative_signals=agg_negative,
            )
        except Exception as _oe:
            log.debug("record_outcome error: %s", _oe)

        last_reasoning = prior_verdict["summary"] if prior_verdict else ""
        if last_reasoning:
            try:
                await logger_mod.set_operation_final_answer(session_id, last_reasoning)
            except Exception as _sfa_e:
                log.debug("set_operation_final_answer failed: %s", _sfa_e)
    finally:
        _cleanup_stale_cancel_flags()
        # Release plan lock and mark operation complete — both guaranteed to run
        await plan_lock.release(session_id)
        log.info("COMPLETING operation_id=%r status=%r", operation_id, final_status)
        try:
            # Flush any queued writes (e.g. final_answer) before marking complete
            await logger_mod.flush_now()
            await logger_mod.complete_operation(operation_id, final_status)
        except Exception as _comp_e:
            log.error("complete_operation failed for %s: %s", operation_id, _comp_e)


@router.post("/run", response_model=RunResponse)
async def run_agent(req: RunRequest, background_tasks: BackgroundTasks,
                    user: str = Depends(get_current_user)):
    """Start an agent task. Streams output to ws://host:8000/ws/output."""
    session_id = req.session_id or str(uuid.uuid4())
    operation_id = await logger_mod.log_operation(session_id, req.task, owner_user=user)
    background_tasks.add_task(_stream_agent, req.task, session_id, operation_id, user)
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
async def confirm_plan(req: ConfirmRequest, user: str = Depends(get_current_user)):
    """Resolve a pending plan_action() call in the agent loop."""
    from api.confirmation import resolve_confirmation
    # Any authenticated user can confirm (ownership enforced by GUI; backend trusts auth)
    ok = resolve_confirmation(req.session_id, req.approved)
    if not ok:
        return {"status": "error", "message": f"No pending plan for session '{req.session_id}'"}
    action = "approved" if req.approved else "cancelled"
    return {"status": "ok", "message": f"Plan {action}"}


@router.post("/clarify")
async def clarify_agent(req: ClarifyRequest, _: str = Depends(get_current_user)):
    """Resolve a pending clarifying_question() call in the agent loop."""
    from api.clarification import resolve_clarification
    ok = resolve_clarification(req.session_id, req.answer)
    if not ok:
        return {"status": "error", "message": f"No pending clarification for session '{req.session_id}'"}
    return {"status": "ok", "message": "Clarification received"}


class StopRequest(BaseModel):
    session_id: str


@router.post("/stop")
async def stop_agent(req: StopRequest, _: str = Depends(get_current_user)):
    """Signal the running agent loop for a session to cancel after its current step."""
    sid = req.session_id.strip()
    if not sid:
        return {"status": "error", "message": "session_id required"}
    if len(sid) > 128:
        return {"status": "error", "message": "session_id too long"}
    _cleanup_stale_cancel_flags()
    _cancel_flags[sid] = (True, time.monotonic())
    # Mark the operation as cancelled immediately in DB
    try:
        from api.db.base import get_engine
        from api.db import queries as q
        async with get_engine().begin() as conn:
            op = await q.get_operation_by_session(conn, sid)
            if op and op.get("status") == "running":
                await q.complete_operation(conn, op["id"], "cancelled")
    except Exception as _e:
        log.debug("stop_agent DB update failed: %s", _e)
    return {"status": "ok", "message": f"Cancel signal sent for session '{sid}'"}


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
