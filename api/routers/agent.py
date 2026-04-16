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

from fastapi import APIRouter, BackgroundTasks, Depends, Query, HTTPException
from pydantic import BaseModel, Field

from api.websocket import manager
from api.auth import get_current_user
import api.logger as logger_mod
from api.constants import DEFAULT_LM_STUDIO_URL, DEFAULT_LM_STUDIO_MODEL, DEFAULT_LM_STUDIO_KEY

router = APIRouter(prefix="/api/agent", tags=["agent"])

def _lm_base():  return os.environ.get("LM_STUDIO_BASE_URL", DEFAULT_LM_STUDIO_URL)
def _lm_model(): return os.environ.get("LM_STUDIO_MODEL",    DEFAULT_LM_STUDIO_MODEL)
def _lm_key():   return os.environ.get("LM_STUDIO_API_KEY",  DEFAULT_LM_STUDIO_KEY)


def _step_temperature(agent_type: str, has_tool_calls: bool, is_force_summary: bool = False) -> float:
    """Return appropriate temperature for this step type.

    Tool-call steps need low temperature for deterministic JSON argument formatting.
    Text-only steps (final summary, force summary) benefit from slightly higher
    temperature for more natural, readable prose.
    """
    if is_force_summary:
        return 0.3
    if not has_tool_calls:
        # Text-only response (final step)
        return 0.3
    # Tool-call step — deterministic
    return 0.1


def _should_disable_thinking(tool_names_this_step: list[str], step: int, max_steps: int) -> bool:
    """Return True if we should append /no_think to suppress the <think> block.

    Qwen3 supports /no_think suffix to skip chain-of-thought reasoning.
    Use this for steps where structured output matters more than reasoning:
    - audit_log-only steps (model is just recording, not deciding)

    Do NOT use for planning steps, multi-tool steps, or first steps of complex tasks.
    """
    if tool_names_this_step == ["audit_log"]:
        return True
    return False


# Ensure project root importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from api.tool_registry import get_registry, invoke_tool
from api.lock import plan_lock


def _build_tools_spec() -> list[dict]:
    from api.tool_registry import build_tools_spec
    spec = build_tools_spec()
    log.info("Sending %d tools to LLM: %s", len(spec), [t["function"]["name"] for t in spec])
    return spec


DESTRUCTIVE_TOOLS = frozenset({
    "service_upgrade", "service_rollback", "node_drain",
    "checkpoint_restore", "kafka_rolling_restart_safe",
    "docker_engine_update", "docker_prune",
    # Skill write-tools — modify persistent state (modules on disk + DB)
    "skill_create", "skill_regenerate", "skill_disable", "skill_enable", "skill_import",
    # Swarm recovery + Proxmox power — require plan_action approval
    "swarm_service_force_update", "proxmox_vm_power",
})

# ─── Hard caps on agent runs (v2.31.8) ───────────────────────────────────────
# All env-configurable so an operator can tighten them without a redeploy.
_AGENT_MAX_WALL_CLOCK_S   = int(os.environ.get("AGENT_MAX_WALL_CLOCK_S",   "600"))   # 10 min
_AGENT_MAX_TOTAL_TOKENS   = int(os.environ.get("AGENT_MAX_TOTAL_TOKENS",   "120000"))
_AGENT_MAX_DESTRUCTIVE    = int(os.environ.get("AGENT_MAX_DESTRUCTIVE",    "3"))
_AGENT_MAX_TOOL_FAILURES  = int(os.environ.get("AGENT_MAX_TOOL_FAILURES",  "8"))


def _cap_exceeded(
    *,
    started_monotonic: float,
    total_tokens: int,
    destructive_calls: int,
    tool_failures: int,
) -> tuple[bool, str]:
    """Return (exceeded, reason). reason is human-readable or empty."""
    import time as _t
    elapsed = _t.monotonic() - started_monotonic
    if elapsed > _AGENT_MAX_WALL_CLOCK_S:
        return True, (f"wall-clock cap exceeded ({int(elapsed)}s > "
                      f"{_AGENT_MAX_WALL_CLOCK_S}s)")
    if total_tokens > _AGENT_MAX_TOTAL_TOKENS:
        return True, (f"token cap exceeded ({total_tokens} > "
                      f"{_AGENT_MAX_TOTAL_TOKENS})")
    if destructive_calls > _AGENT_MAX_DESTRUCTIVE:
        return True, (f"destructive-call cap exceeded ({destructive_calls} > "
                      f"{_AGENT_MAX_DESTRUCTIVE})")
    if tool_failures > _AGENT_MAX_TOOL_FAILURES:
        return True, (f"tool-failure cap exceeded ({tool_failures} > "
                      f"{_AGENT_MAX_TOOL_FAILURES})")
    return False, ""


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


_MAX_TOOL_RESULT_TOKENS = 800
_LARGE_RESULT_BYTES = 3000

_LIST_KEYS = frozenset({
    "clients", "devices", "hosts", "images", "volumes", "vms",
    "entities", "pairs", "containers", "services", "nodes",
    "entries", "results", "items", "alerts", "snapshots",
    "backups", "pools", "disks", "capabilities",
})


def _summarize_tool_result(tool_name, result, status, message,
                           *, operation_id="", session_id=""):
    """Summarize large tool results for LLM context.
    Small results: pass through. Large with lists: store in result_store,
    return compact reference. Large without lists: keep scalars, truncate nested.
    """
    if not isinstance(result, dict):
        return str(result)[:_MAX_TOOL_RESULT_TOKENS * 4]

    if status in ("error", "blocked", "locked"):
        return json.dumps({"status": status, "message": message[:200]})

    full = json.dumps(result, default=str)
    if len(full) <= _LARGE_RESULT_BYTES:
        from api.security.prompt_sanitiser import sanitise
        cleaned, _ = sanitise(full, max_chars=4000, source_hint=f"tool_result:{tool_name}")
        return cleaned

    data = result.get("data")
    list_data = None
    list_key = None

    if isinstance(data, dict):
        for k in _LIST_KEYS:
            if k in data and isinstance(data[k], list) and len(data[k]) > 5:
                list_data = data[k]; list_key = k; break
    elif isinstance(data, list) and len(data) > 5:
        list_data = data; list_key = "items"

    if list_data is not None:
        try:
            from api.db.result_store import store_result
            ref_summary = store_result(tool_name, list_data,
                                       operation_id=operation_id, session_id=session_id)
            out_json = json.dumps({
                "status": status, "message": message[:200],
                "data": {
                    **{k: v for k, v in (data.items() if isinstance(data, dict) else {}.items())
                       if not isinstance(v, list)},
                    list_key: ref_summary,
                },
            }, default=str)
            from api.security.prompt_sanitiser import sanitise
            cleaned, _ = sanitise(out_json, max_chars=4000, source_hint=f"tool_result:{tool_name}")
            return cleaned
        except Exception:
            out_json = json.dumps({
                "status": status, "message": message[:200],
                "data": {list_key: list_data[:10], f"{list_key}_total": len(list_data),
                         f"{list_key}_truncated": True},
            }, default=str)
            from api.security.prompt_sanitiser import sanitise
            cleaned, _ = sanitise(out_json, max_chars=4000, source_hint=f"tool_result:{tool_name}")
            return cleaned

    summary = {"status": status, "message": message[:200]}
    if isinstance(data, dict):
        compact = {}
        for k, v in data.items():
            if isinstance(v, (str, int, float, bool, type(None))): compact[k] = v
            elif isinstance(v, list): compact[k] = f"[{len(v)} items]"
            elif isinstance(v, dict): compact[k] = f"{{{len(v)} keys}}"
        summary["data"] = compact
    elif isinstance(data, list):
        summary["data"] = f"[{len(data)} items]"
    out_json = json.dumps(summary, default=str)
    from api.security.prompt_sanitiser import sanitise
    cleaned, _ = sanitise(out_json, max_chars=4000, source_hint=f"tool_result:{tool_name}")
    return cleaned


def _extract_working_memory(think_text: str, step: int) -> str:
    """Extract key facts from a model <think> block for inter-step continuity.

    Parses numbers, hostnames, ref tokens, status words, and tool plans
    from the model's reasoning. Returns a compact string (≤120 chars)
    suitable for prepending to the next step's user message.

    Returns empty string if nothing useful found.
    """
    if not think_text or len(think_text) < 20:
        return ""

    facts = []

    # Result store refs
    refs = re.findall(r'rs-[a-f0-9]{8,}', think_text)
    if refs:
        facts.append(f"ref={refs[0]}")

    # Numbers with units (disk, memory, counts)
    nums = re.findall(
        r'(\d+(?:\.\d+)?)\s*(GB|MB|TB|%|clients?|devices?|images?|containers?)',
        think_text, re.IGNORECASE
    )
    for val, unit in nums[:3]:
        facts.append(f"{val}{unit.lower()}")

    # Hostnames / labels in quotes or after "on "
    hosts = re.findall(r'(?:on|host|label)\s+["\']?([\w-]{3,30})["\']?', think_text, re.IGNORECASE)
    if hosts:
        facts.append(f"host={hosts[0]}")

    # Status findings
    statuses = re.findall(
        r'\b(healthy|degraded|critical|error|ok|success|failed|stopped|running)\b',
        think_text, re.IGNORECASE
    )
    if statuses:
        facts.append(f"status={statuses[0].lower()}")

    if not facts:
        return ""

    return f"[Step {step} found: {', '.join(facts[:5])}]"


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
    'ambiguous':   'Observe',   # gather info first, then user can re-run with intent
}

_AGENT_BADGE_COLOR = {
    'status':      'blue',
    'observe':     'blue',
    'action':      'orange',
    'execute':     'orange',
    'research':    'purple',
    'investigate': 'purple',
    'build':       'yellow',
    'ambiguous':   'blue',     # same as observe
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
    plan_already_approved: bool = False,
) -> dict:
    """Run one agent loop iteration. Returns dict with output and feedback stats.

    Contains the existing while-loop body from _stream_agent — moved verbatim
    except that agent_type, system_prompt, tools_spec, and client come from
    parameters instead of being computed inside.
    """
    if plan_already_approved:
        system_prompt = (
            "[PLAN APPROVED] The user has already approved the plan for this task. "
            "You do NOT need to call plan_action() again. "
            "Proceed directly with execution steps.\n\n"
        ) + system_prompt

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": task},
    ]

    # ── Per-run feedback accumulators ─────────────────────────────────────────
    tools_used_names: list = []
    positive_signals = 0
    negative_signals = 0
    total_prompt_tokens = 0
    total_completion_tokens = 0
    _audit_logged = False        # allow at most one audit_log call per run
    _degraded_findings: list[str] = []  # research agents: degraded results are findings, not halts
    plan_action_called = plan_already_approved   # pre-set if already approved
    _last_blocked_tool = None    # name of most recently blocked tool
    _working_memory: str = ""    # compact facts from <think> blocks for inter-step continuity

    step = 0
    _MAX_STEPS_BY_TYPE = {"status": 12, "observe": 12, "research": 12, "investigate": 12, "action": 20, "execute": 20, "build": 15}
    max_steps = _MAX_STEPS_BY_TYPE.get(agent_type, 20)
    final_status = "completed"
    last_reasoning = ""

    try:
        import time as _time
        _run_started = _time.monotonic()
        _destructive_calls = 0
        _tool_failures = 0
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

            exceeded, reason = _cap_exceeded(
                started_monotonic=_run_started,
                total_tokens=total_prompt_tokens + total_completion_tokens,
                destructive_calls=_destructive_calls,
                tool_failures=_tool_failures,
            )
            if exceeded:
                await manager.send_line(
                    "halt", f"CAP: {reason}",
                    status="escalated", session_id=session_id,
                )
                # Persist to escalation table so it shows in the banner
                try:
                    from api.routers.escalations import record_escalation
                    record_escalation(
                        session_id=session_id,
                        reason=f"Agent halted by cap: {reason}",
                        operation_id=operation_id,
                        severity="warning",
                    )
                except Exception:
                    pass
                last_reasoning = (
                    f"Task stopped — {reason}. Partial findings above may be "
                    f"useful; re-run with a narrower task if needed."
                )
                await manager.send_line("reasoning", last_reasoning, session_id=session_id)
                if is_final_step:
                    await manager.broadcast({
                        "type": "done", "session_id": session_id, "agent_type": agent_type,
                        "content": last_reasoning, "status": "ok", "choices": [],
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                final_status = "capped"
                break

            # Inject working memory into context for step > 1
            if step > 1 and _working_memory and len(messages) >= 2:
                for i in range(len(messages) - 1, -1, -1):
                    if messages[i]["role"] == "user" and isinstance(messages[i].get("content"), str):
                        if not messages[i]["content"].startswith("[Step"):
                            messages[i] = {
                                **messages[i],
                                "content": f"{_working_memory}\n{messages[i]['content']}",
                            }
                        break

            await manager.send_line("step", f"── Step {step} ──", session_id=session_id)

            # For audit_log-only likely steps: hint to skip thinking
            _prior_step_tools = [tc.function.name for tc in (msg.tool_calls or [])] if step > 1 and 'msg' in dir() else []
            if _should_disable_thinking(_prior_step_tools, step, max_steps):
                for i in range(len(messages) - 1, -1, -1):
                    if messages[i]["role"] == "user":
                        content = messages[i]["content"]
                        if isinstance(content, str) and "/no_think" not in content:
                            messages[i] = {**messages[i], "content": content + "\n/no_think"}
                        break

            import time as _time
            _step_t0 = _time.monotonic()
            try:
                response = client.chat.completions.create(
                    model=_lm_model(),
                    messages=messages,
                    tools=tools_spec,
                    tool_choice="auto",
                    temperature=0.1,
                    max_tokens=2048,
                    extra_body={"min_p": 0.1},
                )
            except Exception as e:
                await manager.broadcast({
                    "type": "error", "session_id": session_id,
                    "content": f"LM Studio error: {e}", "status": "error",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
                final_status = "error"
                break

            if hasattr(response, 'usage') and response.usage:
                total_prompt_tokens     += getattr(response.usage, 'prompt_tokens', 0) or 0
                total_completion_tokens += getattr(response.usage, 'completion_tokens', 0) or 0

            msg = response.choices[0].message
            finish = response.choices[0].finish_reason

            # Opt-in full LLM exchange logging (LOG_LLM_EXCHANGES=1)
            if os.environ.get("LOG_LLM_EXCHANGES", "").lower() in ("1", "true", "yes"):
                from api.logger import log_llm_exchange
                await log_llm_exchange(
                    operation_id, step, messages,
                    response_text=msg.content or "",
                    tool_calls=[{"function": {"name": tc.function.name}} for tc in (msg.tool_calls or [])],
                    prompt_tokens=getattr(response.usage, 'prompt_tokens', 0) or 0 if hasattr(response, 'usage') and response.usage else 0,
                    completion_tokens=getattr(response.usage, 'completion_tokens', 0) or 0 if hasattr(response, 'usage') and response.usage else 0,
                    model=_lm_model(),
                    duration_ms=int((_time.monotonic() - _step_t0) * 1000),
                )

            if msg.content:
                last_reasoning = msg.content
                await manager.send_line("reasoning", msg.content, session_id=session_id)
                # Extract working memory from <think> content for inter-step continuity
                _wm = _extract_working_memory(msg.content, step)
                if _wm:
                    _working_memory = _wm

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

                # Synthesise degraded findings if present and summary is thin
                if _degraded_findings and (not last_reasoning or len(last_reasoning) < 100):
                    try:
                        _synth_ctx = "\n".join(f"- {f}" for f in _degraded_findings)
                        _synth_resp = client.chat.completions.create(
                            model=_lm_model(),
                            messages=[
                                {
                                    "role": "system",
                                    "content": (
                                        "You are a concise infrastructure ops assistant. "
                                        "Produce a 4-section investigation report in plain text:\n\n"
                                        "EVIDENCE:\n"
                                        "- (one bullet per finding: tool → result)\n\n"
                                        "ROOT CAUSE: (one specific sentence)\n\n"
                                        "FIX STEPS:\n"
                                        "1. (specific action with exact command if known)\n"
                                        "2. ...\n\n"
                                        "AUTOMATABLE (if re-run as action task):\n"
                                        "- (step N — tool that would execute it)\n\n"
                                        "No markdown headers. No padding. Be specific: use exact "
                                        "exit codes, IPs, container names, and timestamps from the findings."
                                    ),
                                },
                                {
                                    "role": "user",
                                    "content": (
                                        f"Task: {task}\n\nFindings:\n{_synth_ctx}\n\n"
                                        "Give root cause, what was checked, and remediation steps."
                                    ),
                                },
                            ],
                            tools=None,
                            temperature=0.3,
                            max_tokens=500,
                        )
                        _synth_text = _synth_resp.choices[0].message.content or ""
                        if _synth_text.strip():
                            last_reasoning = _synth_text.strip()
                            await manager.send_line("reasoning", _synth_text, session_id=session_id)
                    except Exception as _se:
                        log.debug("Stop-path synthesis failed: %s", _se)
                choices = _extract_choices(last_reasoning) if last_reasoning else None
                if is_final_step:
                    payload = {
                        "type":       "done",
                        "session_id": session_id,
                        "agent_type": agent_type,
                        "content":    last_reasoning if last_reasoning else f"Agent finished after {step} steps.",
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
            # Check vm_exec write commands (prune, autoremove, vacuum, etc.)
            _VM_WRITE_PATTERNS = ['prune', 'autoremove', 'vacuum', 'clean', 'purge', 'remove']
            for _btc in msg.tool_calls:
                if _btc.function.name == 'vm_exec':
                    try:
                        _vargs = json.loads(_btc.function.arguments)
                        _vcmd = _vargs.get('command', '').lower()
                        if any(p in _vcmd for p in _VM_WRITE_PATTERNS):
                            if 'plan_action' not in tools_used_names:
                                _destructive_req = _destructive_req | {'vm_exec(write)'}
                    except Exception:
                        pass
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
                        # v2.31.10 blackout gate
                        try:
                            from api.db.agent_blackouts import check_active_blackout
                            # Inspect the plan's proposed tool calls — we don't
                            # know them yet here (plan_action is the gate ITSELF),
                            # so check against any destructive action.
                            active_bo = check_active_blackout(tool_name="")
                        except Exception:
                            active_bo = None
                        if active_bo:
                            plan_action_called = True  # prevent re-trigger loop
                            result = {
                                "status":   "blocked",
                                "approved": False,
                                "message":  (f"Blocked by active blackout: "
                                             f"{active_bo.get('label','')} — "
                                             f"{active_bo.get('reason','')}"),
                                "data":     {"approved": False, "blackout": active_bo},
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            }
                            await manager.send_line(
                                "step",
                                f"[blackout] Plan blocked — {active_bo.get('label','')}",
                                status="warning", session_id=session_id,
                            )
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": json.dumps(result),
                            })
                            continue  # skip the real plan_action handling below

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

                            # v2.31.14 — reject empty plans before showing modal
                            _plan_summary = (plan["summary"] or "").strip()
                            _plan_steps   = [s for s in plan["steps"] if s]
                            if not _plan_summary or not _plan_steps:
                                # Don't broadcast plan_pending with empty content.
                                # Release the lock we just acquired, report error
                                # back to the model, keep plan_action_called=False
                                # so the safety gate will still trigger next time.
                                await plan_lock.release(session_id)
                                plan_action_called = False
                                negative_signals += 1
                                result = {
                                    "status":   "error",
                                    "approved": False,
                                    "message": (
                                        "plan_action() rejected: "
                                        f"{'empty summary' if not _plan_summary else 'empty steps list'}. "
                                        "Required: summary (non-empty prose describing the overall change) "
                                        "AND steps (list of 2-6 concrete actions, each a short sentence). "
                                        "Retry with BOTH fields populated. Example:\n"
                                        "plan_action(\n"
                                        "  summary=\"Prune unused Docker images on all Swarm nodes\",\n"
                                        "  steps=[\"Get docker system df before state on each host\",\n"
                                        "         \"Run docker image prune -a -f on each host\",\n"
                                        "         \"Get docker system df after state on each host\",\n"
                                        "         \"Report reclaimed bytes per host\"],\n"
                                        "  risk_level=\"medium\",\n"
                                        "  reversible=False,\n"
                                        ")"
                                    ),
                                    "data": {"approved": False, "reason": "empty_plan"},
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                }
                                await manager.send_line(
                                    "step",
                                    "[plan] Rejected — empty summary or steps; asking model to retry",
                                    status="warning", session_id=session_id,
                                )
                                # Skip the broadcast + confirmation wait. The tool
                                # result below ( `messages.append({role: tool, ...})`)
                                # will carry this error back to the model, which
                                # will re-plan on the next loop iteration.
                            else:
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
                    elif fn_name == "propose_subtask":
                        # Parse arguments
                        try:
                            _pst_args = json.loads(tc.function.arguments or "{}")
                        except Exception:
                            _pst_args = {}

                        _pst_task        = _pst_args.get("task", task)[:500]
                        _pst_exec_steps  = _pst_args.get("executable_steps", [])
                        _pst_manual_steps = _pst_args.get("manual_steps", []) or []
                        _proposal_id     = str(uuid.uuid4())

                        # Feasibility: check available connections
                        _confidence = "medium"
                        try:
                            from api.connections import list_connections
                            if list_connections("vm_host"):
                                _confidence = "high"
                        except Exception:
                            pass

                        # Save to DB
                        try:
                            from api.db.subtask_proposals import save_proposal
                            save_proposal(
                                proposal_id=_proposal_id,
                                parent_session_id=session_id,
                                parent_op_id=operation_id,
                                task=_pst_task,
                                executable_steps=_pst_exec_steps,
                                manual_steps=_pst_manual_steps,
                                confidence=_confidence,
                            )
                        except Exception as _spe:
                            log.debug("save_proposal failed: %s", _spe)

                        # Broadcast
                        await manager.broadcast({
                            "type": "subtask_proposed",
                            "session_id": session_id,
                            "proposal_id": _proposal_id,
                            "task": _pst_task,
                            "executable_steps": _pst_exec_steps,
                            "manual_steps": _pst_manual_steps,
                            "confidence": _confidence,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        })
                        await manager.send_line(
                            "step",
                            f"[subtask] Proposal recorded — '{_pst_task[:70]}' "
                            f"({_confidence} confidence). User notified.",
                            status="ok", session_id=session_id,
                        )

                        # Return result to model (no waiting — model can finish with summary)
                        _pst_result = {
                            "status": "proposed",
                            "proposal_id": _proposal_id,
                            "confidence": _confidence,
                            "message": (
                                "Proposal recorded. User will see an offer to run this as an automated "
                                "sub-agent or as a manual runbook checklist. "
                                "Please provide your final investigation summary now."
                            ),
                        }
                        messages.append({"role": "assistant", "content": None, "tool_calls": [tc]})
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps(_pst_result),
                        })
                        await logger_mod.log_tool_call(
                            operation_id=operation_id, tool_name="propose_subtask",
                            params=_pst_args, result=_pst_result, model_used=_lm_model(),
                            duration_ms=0, status="ok",
                        )
                        tools_used_names.append("propose_subtask")
                        continue  # let model write final answer

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
                        if fn_name in DESTRUCTIVE_TOOLS:
                            _destructive_calls += 1
                except Exception as e:
                    err_str = str(e)
                    result = {"status": "error", "message": err_str, "data": None,
                              "timestamp": datetime.now(timezone.utc).isoformat()}
                    if "401" in err_str or "403" in err_str or "Unauthorized" in err_str:
                        await manager.send_line(
                            "step",
                            f"[auth] Token may have expired — tool {fn_name!r} got auth error. "
                            "Try stopping and re-running the task.",
                            status="error", session_id=session_id,
                        )
                    log.debug("Tool %r raised exception:", fn_name, exc_info=True)
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

                # Immutable audit row for destructive / remote-exec tools (v2.31.2)
                try:
                    from api.db.agent_actions import write_action, is_audited
                    if is_audited(fn_name):
                        write_action(
                            session_id=session_id,
                            operation_id=operation_id,
                            task_id=session_id,           # no separate task_id today
                            tool_name=fn_name,
                            args=fn_args,
                            result_status=result_status,
                            result_summary=result_msg,
                            duration_ms=duration_ms,
                            owner_user=owner_user,
                            was_planned=plan_action_called,
                        )
                except Exception as _ae:
                    log.debug("agent_actions write failed: %s", _ae)

                # Stream to GUI
                await manager.send_line(
                    "tool",
                    f"[{fn_name}] → {result_status} | {result_msg}",
                    tool=fn_name, status=result_status, session_id=session_id,
                )

                # Summarize tool result for LLM context (full result in DB audit trail)
                tool_content = _summarize_tool_result(fn_name, result, result_status, result_msg,
                                                     operation_id=operation_id, session_id=session_id)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": tool_content,
                })

                _is_hard_failure = result_status in ("failed", "escalated") or (fn_name == "escalate" and result_status != "blocked")
                _is_degraded = result_status == "degraded"
                _is_investigate = agent_type in ("research", "investigate", "status", "observe")

                if _is_hard_failure or result_status == "error":
                    _tool_failures += 1

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
                                        "Produce a 4-section investigation report in plain text:\n\n"
                                        "EVIDENCE:\n"
                                        "- (one bullet per finding: tool → result)\n\n"
                                        "ROOT CAUSE: (one specific sentence)\n\n"
                                        "FIX STEPS:\n"
                                        "1. (specific action with exact command if known)\n"
                                        "2. ...\n\n"
                                        "AUTOMATABLE (if re-run as action task):\n"
                                        "- (step N — tool that would execute it)\n\n"
                                        "No markdown headers. No padding. Be specific: use exact "
                                        "exit codes, IPs, container names, and timestamps from the findings."
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

            # Trim message history to cap token growth
            def _trim_messages(msgs, keep_system=2, max_total=18):
                if len(msgs) <= max_total:
                    return msgs
                fixed = msgs[:keep_system]
                rolling = msgs[keep_system:]
                while len(fixed) + len(rolling) > max_total and len(rolling) >= 2:
                    rolling = rolling[2:]
                return fixed + rolling
            messages = _trim_messages(messages)

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
                # Synthesise degraded findings before broadcasting done
                if _degraded_findings and (not last_reasoning or len(last_reasoning) < 100):
                    try:
                        _synth_ctx = "\n".join(f"- {f}" for f in _degraded_findings)
                        _synth_resp = client.chat.completions.create(
                            model=_lm_model(),
                            messages=[
                                {
                                    "role": "system",
                                    "content": (
                                        "You are a concise infrastructure ops assistant. "
                                        "Produce a 4-section investigation report in plain text:\n\n"
                                        "EVIDENCE:\n"
                                        "- (one bullet per finding: tool → result)\n\n"
                                        "ROOT CAUSE: (one specific sentence)\n\n"
                                        "FIX STEPS:\n"
                                        "1. (specific action with exact command if known)\n"
                                        "2. ...\n\n"
                                        "AUTOMATABLE (if re-run as action task):\n"
                                        "- (step N — tool that would execute it)\n\n"
                                        "No markdown headers. No padding. Be specific: use exact "
                                        "exit codes, IPs, container names, and timestamps from the findings."
                                    ),
                                },
                                {
                                    "role": "user",
                                    "content": (
                                        f"Task: {task}\n\nFindings:\n{_synth_ctx}\n\n"
                                        "Give root cause, what was checked, and remediation steps."
                                    ),
                                },
                            ],
                            tools=None,
                            temperature=0.3,
                            max_tokens=500,
                        )
                        _synth_text = _synth_resp.choices[0].message.content or ""
                        if _synth_text.strip():
                            last_reasoning = _synth_text.strip()
                            await manager.send_line("reasoning", _synth_text, session_id=session_id)
                    except Exception as _se:
                        log.debug("Audit-log completion synthesis failed: %s", _se)
                choices = _extract_choices(last_reasoning) if last_reasoning else None
                if is_final_step:
                    await manager.broadcast({
                        "type": "done", "session_id": session_id, "agent_type": agent_type,
                        "content": last_reasoning if last_reasoning else f"Agent finished after {step} steps.",
                        "status": "ok", "choices": choices or [],
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                break

        else:
            # Max steps reached — force one final LLM call without tools
            try:
                messages.append({
                    "role": "user",
                    "content": (
                        "You have used all available tool call steps. "
                        "Write your final summary NOW as plain text — no more tool calls allowed. "
                        "Format: first line = most important finding, "
                        "then 3-5 bullet points of key data, "
                        "then one recommended action or 'no action needed'."
                    ),
                })
                force_response = client.chat.completions.create(
                    model=_lm_model(),
                    messages=messages,
                    tools=None,
                    tool_choice=None,
                    temperature=0.3,
                    max_tokens=600,
                    extra_body={"min_p": 0.1},
                )
                forced_text = force_response.choices[0].message.content or ""
                if forced_text:
                    last_reasoning = forced_text
                    await manager.send_line("reasoning", forced_text, session_id=session_id)
            except Exception as _fe:
                log.debug("Force summary call failed: %s", _fe)

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
                                    "Produce a 4-section investigation report in plain text:\n\n"
                                    "EVIDENCE:\n"
                                    "- (one bullet per finding: tool → result)\n\n"
                                    "ROOT CAUSE: (one specific sentence)\n\n"
                                    "FIX STEPS:\n"
                                    "1. (specific action with exact command if known)\n"
                                    "2. ...\n\n"
                                    "AUTOMATABLE (if re-run as action task):\n"
                                    "- (step N — tool that would execute it)\n\n"
                                    "No markdown headers. No padding. Be specific: use exact "
                                    "exit codes, IPs, container names, and timestamps from the findings."
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

            if is_final_step:
                await manager.broadcast({
                    "type": "done", "session_id": session_id, "agent_type": agent_type,
                    "content": last_reasoning or f"Agent reached max steps ({max_steps}).",
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

    if total_prompt_tokens or total_completion_tokens:
        await manager.send_line(
            "step",
            f"[tokens] prompt={total_prompt_tokens} completion={total_completion_tokens} "
            f"total={total_prompt_tokens + total_completion_tokens}",
            status="ok", session_id=session_id,
        )

    return {
        "output":              last_reasoning,
        "tools_used":          tools_used_names,
        "final_status":        final_status,
        "positive_signals":    positive_signals,
        "negative_signals":    negative_signals,
        "steps_taken":         step,
        "prompt_tokens":       total_prompt_tokens,
        "completion_tokens":   total_completion_tokens,
    }


async def _stream_agent(task: str, session_id: str, operation_id: str,
                        owner_user: str = "admin", parent_context: str = "",
                        parent_session_id: str = ""):
    """Run the full agent loop, streaming every step to WebSocket clients."""
    from openai import OpenAI
    from api.agents.router import classify_task, filter_tools, get_prompt, detect_domain
    from api.agents.orchestrator import (
        build_step_plan, format_step_header, verdict_from_text,
        extract_structured_verdict, run_coordinator, should_use_coordinator,
    )

    base_url = _lm_base()
    api_key  = _lm_key()

    # Classify task using first step intent for memory injection
    first_intent = classify_task(task)
    if first_intent == "ambiguous":
        first_intent = "action"

    system_prompt = get_prompt(first_intent)

    # Inject parent investigation context for sub-agent tasks
    if parent_context:
        _parent_prefix = (
            "═══ PARENT INVESTIGATION CONTEXT ═══\n"
            "The user has already investigated this issue. Key findings:\n"
            f"{parent_context[:1200]}\n"
            "═══════════════════════════════════\n"
            "Proceed DIRECTLY to remediation. Do NOT re-investigate what is already known.\n\n"
        )
        system_prompt = _parent_prefix + system_prompt

    # Store parent linkage in operations table for Tree view in Logs
    if parent_session_id:
        try:
            from api.db.base import get_engine as _lge
            from sqlalchemy import text as _lt
            async with _lge().begin() as _lconn:
                await _lconn.execute(
                    _lt("UPDATE operations SET parent_session_id=:psid WHERE id=:oid"),
                    {"psid": parent_session_id, "oid": operation_id},
                )
        except Exception as _ple:
            log.debug("parent_session_id update failed: %s", _ple)

    # ── Domain-specific capability injection (e.g. available VM hosts) ────────
    try:
        domain = detect_domain(task)
        if domain == "vm_host":
            from api.connections import get_all_connections_for_platform
            vms = get_all_connections_for_platform("vm_host")
            if vms:
                inv = {}
                try:
                    from api.db.infra_inventory import list_inventory
                    inv = {e["connection_id"]: e for e in list_inventory("vm_host")}
                except Exception:
                    pass
                lines = []
                for c in vms[:8]:
                    cid = str(c.get("id", ""))
                    label = c.get("label", c.get("host", "?"))
                    ip = c.get("host", "")
                    entry = inv.get(cid)
                    hostname = entry.get("hostname", "") if entry else ""
                    display = f"{label} (hostname: {hostname})" if hostname and hostname != label else f"{label} ({ip})"
                    lines.append(f"  - {display}")
                cap_hint = (
                    "AVAILABLE VM HOSTS (use vm_exec to query, infra_lookup to resolve names):\n"
                    + "\n".join(lines)
                    + "\n\nvm_exec commands: df -h, free -m, journalctl -n 50, "
                    + "find / -size +100M -type f, docker system df, "
                    + "docker volume ls | head -20, apt list --upgradable\n\n"
                )
                from api.security.prompt_sanitiser import sanitise
                cap_hint, _ = sanitise(cap_hint, max_chars=2000, source_hint="vm_host_capabilities")
                system_prompt = cap_hint + system_prompt
    except Exception:
        pass

    # ── Entity history context injection ──────────────────────────────────────
    # If task mentions a known entity, inject recent changes/events as context
    try:
        from api.db.entity_history import get_recent_changes_summary, get_events
        from api.db.infra_inventory import resolve_host

        _entity_hints = []
        task_words = task.split()
        for word in task_words:
            if len(word) < 4:
                continue
            entry = resolve_host(word)
            if entry:
                entity_id = entry.get("label", word)
                summary = get_recent_changes_summary(entity_id, hours=48)
                if summary:
                    _entity_hints.append(f"  {entity_id}: {summary}")
                recent_events = get_events(entity_id, hours=48, severity="warning", limit=3)
                critical_events = get_events(entity_id, hours=48, severity="critical", limit=3)
                all_events = critical_events + recent_events
                if all_events:
                    ev_str = "; ".join(e["description"][:80] for e in all_events[:3])
                    _entity_hints.append(f"  {entity_id} events: {ev_str}")
                break   # one entity per task is enough

        if _entity_hints:
            history_hint = "RECENT ENTITY ACTIVITY (last 48h):\n" + "\n".join(_entity_hints) + "\n\n"
            from api.security.prompt_sanitiser import sanitise
            history_hint, _ = sanitise(history_hint, max_chars=2000, source_hint="entity_history")
            system_prompt = history_hint + system_prompt
    except Exception:
        pass

    # ── Inject past outcomes + pgvector docs + MuninnDB chunks into prompt ───
    boost_tools: list[str] = []  # populated from successful past outcomes below
    try:
        from api.memory.feedback import get_past_outcomes, build_outcome_prompt_section
        from api.memory.client import get_client as _get_mem_client

        injected_sections: list = []
        doc_chunks: list = []
        rag_doc_count = 0

        # Past outcomes (all agent types — OPERATIONAL MEMORY)
        past_outcomes = await get_past_outcomes(task, max_results=4)
        outcome_section = build_outcome_prompt_section(past_outcomes)
        if outcome_section:
            injected_sections.append(outcome_section)

        # Extract tool boost list from successful past outcomes
        _boost_tools: list[str] = []
        for o in past_outcomes:
            content = o.get("content", "")
            _bt_m = re.search(r"Tools:\s*(.+)", content)
            if _bt_m and "completed" in content.lower():
                names = [n.strip() for n in _bt_m.group(1).split(",") if n.strip()]
                _boost_tools.extend(names[:4])
        # Deduplicate preserving order, cap at 8
        seen = set()
        boost_tools: list[str] = []
        for n in _boost_tools:
            if n not in seen:
                seen.add(n); boost_tools.append(n)
            if len(boost_tools) >= 8:
                break

        # pgvector documentation (tiered by agent type — DOCUMENTATION)
        _RAG_BUDGETS = {
            "research": (3000, None),           # full budget, all doc_types
            "investigate": (3000, None),
            "execute": (1500, ["api_reference", "cli_reference"]),
            "action": (1500, ["api_reference", "cli_reference"]),
        }
        rag_cfg = _RAG_BUDGETS.get(first_intent)
        if rag_cfg:
            try:
                from api.rag.doc_search import search_docs, format_doc_results
                rag_budget, rag_type_filter = rag_cfg
                rag_results = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: search_docs(
                        query=task,
                        doc_type_filter=rag_type_filter,
                        token_budget=rag_budget,
                    )
                )
                # Filter low-confidence results (RRF score < 0.02 means poor match)
                rag_results = [r for r in rag_results if r.get("rrf_score", 0) >= 0.02]
                if rag_results:
                    rag_section = format_doc_results(rag_results)
                    if rag_section:
                        injected_sections.insert(0, rag_section)
                        rag_doc_count = len(rag_results)
            except Exception as _rag_e:
                log.debug("RAG injection skipped: %s", _rag_e)

        # MuninnDB doc chunks (research/investigate — Hebbian activation)
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
                doc_lines = ["OPERATIONAL MEMORY:"]
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
            total_injected = rag_doc_count + len(past_outcomes) + len(doc_chunks)
            parts = []
            if rag_doc_count:
                parts.append(f"{rag_doc_count} doc(s)")
            if past_outcomes:
                parts.append(f"{len(past_outcomes)} outcome(s)")
            if doc_chunks:
                parts.append(f"{len(doc_chunks)} memory chunk(s)")
            await manager.send_line(
                "memory",
                f"[context] {' + '.join(parts)} injected into prompt",
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
    agg_prompt_tokens = 0
    agg_completion_tokens = 0
    final_status = "completed"
    halted_early = False
    plan_approved_this_session = False
    all_tools = _build_tools_spec()

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

        from api.agents.router import rank_tools_for_task
        step_tools_filtered = filter_tools(all_tools, step_agent_type, domain=step_domain or "general")
        step_tools = rank_tools_for_task(
            step_task,
            step_tools_filtered,
            top_n=10,           # leave room for always-include tools
            boost_names=boost_tools,
        )
        log.info(
            "Agent=%s ranked tools (%d→%d): %s",
            step_agent_type, len(step_tools_filtered), len(step_tools),
            [t["function"]["name"] for t in step_tools],
        )

        step_result = await _run_single_agent_step(
            step_task, session_id, operation_id, owner_user,
            system_prompt=step_system_prompt,
            tools_spec=step_tools,
            agent_type=step_agent_type,
            client=client,
            is_final_step=(step_num == total_steps and not use_coordinator),
            plan_already_approved=plan_approved_this_session,
        )

        # Track plan approval across coordinator loop iterations
        if "plan_action" in step_result["tools_used"]:
            plan_approved_this_session = True

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
                context_for_next = decision.get("context", "")
                tool_hint = decision.get("tool_hint", "")
                next_task = (
                    f"{task}"
                    + (f"\n[Context from previous step: {context_for_next}]" if context_for_next else "")
                    + (f"\n[Suggested next tool: {tool_hint}]" if tool_hint else "")
                )
                next_step_info = {
                    "step":   step_num + 1,
                    "intent": step_intent,
                    "domain": step_domain,
                    "task":   next_task,
                }
                steps.append(next_step_info)
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
        # Purge session-scoped allowlist entries for this session
        try:
            from api.db.vm_exec_allowlist import purge_session
            purge_session(session_id)
        except Exception as _al_e:
            log.debug("allowlist session purge failed: %s", _al_e)
        # Trim session log to max_lines setting
        try:
            from mcp_server.tools.skills.storage import get_backend as _gb2
            max_lines = int(_gb2().get_setting("opLogMaxLinesPerSession") or 500)
            from api.session_store import trim_session_log
            await trim_session_log(session_id, max_lines)
        except Exception as _tl_e:
            log.debug("session log trim failed: %s", _tl_e)


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


class AskRequest(BaseModel):
    question: str = Field(max_length=512)
    context: dict = Field(default_factory=dict)


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


class SubtaskRequest(BaseModel):
    proposal_id: str
    task: str
    parent_session_id: str = ""

@router.post("/subtask", response_model=RunResponse)
async def run_subtask(req: SubtaskRequest, background_tasks: BackgroundTasks,
                      user: str = Depends(get_current_user)):
    """Start an execute sub-agent from a proposal, injecting parent investigation context."""
    session_id   = str(uuid.uuid4())
    operation_id = await logger_mod.log_operation(session_id, req.task, owner_user=user)

    # Fetch parent final_answer for context injection
    parent_context = ""
    if req.parent_session_id:
        try:
            from api.db.base import get_engine
            from api.db import queries as q
            async with get_engine().connect() as conn:
                parent_op = await q.get_operation_by_session(conn, req.parent_session_id)
                if parent_op:
                    parent_context = parent_op.get("final_answer", "")
        except Exception as _pce:
            log.debug("parent context fetch failed: %s", _pce)

    # Update proposal status
    try:
        from api.db.subtask_proposals import update_proposal_status
        update_proposal_status(req.proposal_id, "accepted")
    except Exception:
        pass

    background_tasks.add_task(
        _stream_agent, req.task, session_id, operation_id, user,
        parent_context, req.parent_session_id,
    )
    return RunResponse(
        session_id=session_id,
        operation_id=operation_id,
        message="Sub-agent started",
    )


@router.get("/proposals")
async def list_proposals(
    status: str = Query("pending"),
    limit: int = Query(10, ge=1, le=50),
    _: str = Depends(get_current_user),
):
    """Return subtask proposals filtered by status."""
    from api.db.subtask_proposals import list_proposals as _lp
    return {"proposals": _lp(status=status, limit=limit)}


@router.get("/proposals/{proposal_id}")
async def get_proposal(proposal_id: str, _: str = Depends(get_current_user)):
    from api.db.subtask_proposals import get_proposal as _gp
    p = _gp(proposal_id)
    if not p:
        raise HTTPException(404, "Proposal not found")
    return p


@router.post("/proposals/{proposal_id}/dismiss")
async def dismiss_proposal(proposal_id: str, _: str = Depends(get_current_user)):
    from api.db.subtask_proposals import update_proposal_status
    update_proposal_status(proposal_id, "dismissed")
    return {"status": "ok"}


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


@router.post("/ask")
async def ask_agent(req: AskRequest, _: str = Depends(get_current_user)):
    """
    Lightweight single-turn LLM call with entity context. No tools, no planning.
    Streams response as Server-Sent Events (text/event-stream).
    """
    from starlette.responses import StreamingResponse
    from fastapi.responses import JSONResponse

    base_url = _lm_base()
    if not base_url:
        return JSONResponse({"error": "LM Studio not configured"}, status_code=503)

    question = req.question.strip()
    if not question:
        return JSONResponse({"error": "question is required"}, status_code=400)

    entity_ctx = req.context

    system_prompt = (
        "You are an infrastructure assistant for DEATHSTAR (Imperial Ops). "
        "Answer questions about the infrastructure entity provided in context. "
        "Be concise — 2-4 sentences max unless a longer answer is clearly needed. "
        "Use plain text. No markdown headers. No bullet lists unless listing items."
    )

    ctx_lines = []
    if entity_ctx:
        ctx_lines.append(f"Entity: {entity_ctx.get('label', '?')} ({entity_ctx.get('id', '?')})")
        ctx_lines.append(f"Status: {entity_ctx.get('status', 'unknown')}")
        ctx_lines.append(f"Platform: {entity_ctx.get('platform', '?')} / Section: {entity_ctx.get('section', '?')}")
        if entity_ctx.get('last_error'):
            ctx_lines.append(f"Last error: {entity_ctx['last_error']}")
        if entity_ctx.get('latency_ms') is not None:
            ctx_lines.append(f"Latency: {entity_ctx['latency_ms']}ms")
        meta = entity_ctx.get('metadata', {})
        if meta:
            meta_str = ', '.join(f"{k}={v}" for k, v in list(meta.items())[:6])
            ctx_lines.append(f"Metadata: {meta_str}")

    user_msg = "\n".join(ctx_lines) + f"\n\nQuestion: {question}"
    from api.security.prompt_sanitiser import sanitise
    user_msg, _ = sanitise(user_msg, max_chars=6000, source_hint="entity_ask_context")

    async def generate():
        try:
            from openai import OpenAI
            client = OpenAI(base_url=base_url, api_key=_lm_key())
            stream = client.chat.completions.create(
                model=_lm_model(),
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_msg},
                ],
                stream=True,
                max_tokens=600,
                temperature=0.3,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if delta:
                    yield f"data: {delta}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: [ERROR] {str(e)[:120]}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/ask/suggestions")
async def ask_suggestions(
    status: str = "",
    section: str = "",
    platform: str = "",
    entity_id: str = "",
    _: str = Depends(get_current_user),
):
    """Return suggested questions based on entity status, section, platform, and entity_id."""

    # Platform-specific suggestions take priority
    platform_suggestions: dict[str, list[str]] = {
        "proxmox": {
            "error": [
                "What would cause this VM or container to stop?",
                "Is there a snapshot I can restore from?",
                "How do I check if the host node is healthy?",
                "What Proxmox logs would show the stop reason?",
            ],
            "degraded": [
                "What thresholds trigger a degraded VM status?",
                "Is disk usage causing this?",
                "How do I check memory pressure on the host?",
            ],
            "healthy": [
                "What resources does this VM consume?",
                "When was the last snapshot taken?",
                "What services run inside this VM?",
            ],
        },
        "docker": {
            "error": [
                "What exit code did this container have?",
                "Is there an OOM kill in dmesg?",
                "What does the container log show on last exit?",
                "Is this a dependency failing at startup?",
            ],
            "degraded": [
                "Is the health check endpoint responding?",
                "Is this container on the latest image?",
                "What are the restart conditions?",
            ],
            "healthy": [
                "What image version is running?",
                "What volumes does this container use?",
                "What ports are exposed?",
            ],
        },
        "kafka": {
            "error": [
                "Is this broker missing from the ISR?",
                "Which Swarm worker node is this broker on?",
                "What does the broker log show on last crash?",
            ],
            "degraded": [
                "Which partitions are under-replicated?",
                "What is the current consumer lag?",
                "Is the broker registered in the cluster?",
            ],
            "healthy": [
                "How many partitions does this broker lead?",
                "What is the current replication factor?",
                "Is consumer lag within normal range?",
            ],
        },
        "unifi": {
            "error": [
                "When did this device disconnect?",
                "How many clients lost connectivity?",
                "Is the controller reachable from the device?",
            ],
            "degraded": [
                "How many clients are on this device?",
                "Is the firmware up to date?",
                "Are there interference or error rates?",
            ],
            "healthy": [
                "How many clients is this device serving?",
                "What firmware version is running?",
                "What is the uplink port/speed?",
            ],
        },
        "truenas": {
            "error": [
                "Which drive failed in this pool?",
                "Can the pool be repaired with a spare?",
                "Is there a recent scrub result?",
            ],
            "degraded": [
                "What is the current usage percentage?",
                "Are there any failed drives?",
                "When was the last scrub completed?",
            ],
            "healthy": [
                "How much free space remains?",
                "When is the next scrub scheduled?",
                "What datasets use this pool?",
            ],
        },
        "pbs": {
            "error": [
                "Which backup jobs are failing?",
                "Is the datastore full?",
                "What does the task log show?",
            ],
            "degraded": [
                "What percentage of space is used?",
                "Are there any failed backup tasks?",
                "When was garbage collection last run?",
            ],
            "healthy": [
                "How many snapshots are stored?",
                "When was the last successful backup?",
                "What is the retention policy?",
            ],
        },
        "fortigate": {
            "error": [
                "Which interface is down?",
                "Is this the WAN or LAN interface?",
                "Are there error counters on the port?",
            ],
            "degraded": [
                "How many errors are on this interface?",
                "Is this affecting routing?",
                "Is HA failover active?",
            ],
            "healthy": [
                "What traffic is passing through this interface?",
                "What VLANs are on this interface?",
                "Is this interface in an HA pair?",
            ],
        },
    }

    # Section-level fallbacks when no platform match
    section_suggestions: dict[str, dict[str, list[str]]] = {
        "STORAGE": {
            "error": ["Is this affecting backup jobs?", "What happens when storage is full?"],
            "degraded": ["What is the usage threshold for this storage?", "Is data at risk?"],
            "healthy": ["What services depend on this storage?", "What is the retention policy?"],
        },
        "COMPUTE": {
            "error": ["What services depend on this component?", "Is there a failover option?"],
            "degraded": ["Is resource exhaustion causing this?", "How does this affect other services?"],
            "healthy": ["What is the normal resource usage?", "When was this last restarted?"],
        },
        "NETWORK": {
            "error": ["What services are affected by this?", "Is there a redundant path?"],
            "degraded": ["What traffic is impacted?", "What services depend on this?"],
            "healthy": ["What services use this network path?", "What is the expected latency?"],
        },
        "SECURITY": {
            "error": ["Are there active threats detected?", "What logs should I check?"],
            "degraded": ["What alert thresholds are configured?", "Is monitoring coverage reduced?"],
            "healthy": ["What events are being monitored?", "What alert rules are active?"],
        },
        "PLATFORM": {
            "error": ["Is this blocking other services?", "What depends on this platform component?"],
            "degraded": ["Is response latency acceptable?", "What would cause further degradation?"],
            "healthy": ["What does this component do?", "What would cause this to degrade?"],
        },
    }

    # Pick suggestions: platform-specific → section fallback → generic
    plat = platform.lower() if platform else ""
    stat = status.lower() if status else "healthy"

    if plat in platform_suggestions and stat in platform_suggestions[plat]:
        suggestions = platform_suggestions[plat][stat]
    elif section in section_suggestions and stat in section_suggestions[section]:
        suggestions = section_suggestions[section][stat]
    elif stat == "error":
        suggestions = ["What caused this failure?", "What should I check first?", "Is there a recovery procedure?"]
    elif stat == "degraded":
        suggestions = ["What is causing this degradation?", "How serious is this?", "What are the fix steps?"]
    elif stat == "maintenance":
        suggestions = ["Why is this in maintenance?", "What work is being done?", "When will it be restored?"]
    else:
        suggestions = ["What does this component do?", "What would cause this to degrade?"]

    return {"suggestions": suggestions[:4]}
