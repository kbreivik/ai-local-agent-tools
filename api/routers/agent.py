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
from api.metrics import AGENT_TASKS, AGENT_TOOL_CALLS, AGENT_WALL_SECONDS
from api.agents import META_TOOLS, MIN_SUBSTANTIVE_BY_TYPE
from api.agents.gates import (
    _is_preamble_only,
    _classify_terminal_final_answer,
    compute_final_answer,
    _result_count,
    _should_disable_thinking,
)
from api.agents.context import (
    _build_prerun_external_context,
    _extract_working_memory,
    _build_subagent_context,
)
from api.agents.step_llm import call_llm_step, LlmStepResult
from api.agents.step_guard import run_stop_path_guards, GuardOutcome
from api.agents.step_facts import process_tool_result
from api.agents.step_synth import maybe_force_empty_synthesis
from api.agents.step_tools import dispatch_tool_calls, ToolLoopAction

router = APIRouter(prefix="/api/agent", tags=["agent"])

def _lm_base():  return os.environ.get("LM_STUDIO_BASE_URL", DEFAULT_LM_STUDIO_URL)
def _lm_model(): return os.environ.get("LM_STUDIO_MODEL",    DEFAULT_LM_STUDIO_MODEL)
def _lm_key():   return os.environ.get("LM_STUDIO_API_KEY",  DEFAULT_LM_STUDIO_KEY)


def _extract_response_model(response, fallback: str = "") -> str:
    """Return the model string actually served by the API for this response.

    OpenAI SDK exposes this as `response.model`. Fall back to the provided
    default (typically `_lm_model()`) when unavailable — never crashes.
    """
    try:
        m = getattr(response, "model", None)
        if m:
            return str(m)
    except Exception:
        pass
    try:
        if isinstance(response, dict):
            m = response.get("model")
            if m:
                return str(m)
    except Exception:
        pass
    return fallback or ""


# ─── Per-agent-type tool call budgets (v2.36.5) ───────────────────────────────
# Runtime-Settings driven so operators can tune without redeploy. Falls back
# to the pre-v2.36.5 hardcoded values when Settings are unavailable or a
# key returns a malformed value.

_TOOL_BUDGET_DEFAULTS: dict[str, int] = {
    "observe":     8,
    "investigate": 16,
    "execute":     14,
    "build":       12,
}

# Agent-type aliases → canonical type. status / research / action are
# historical names that still appear in task classifications; they share
# the canonical type's budget.
_TOOL_BUDGET_ALIASES: dict[str, str] = {
    "status":      "observe",
    "research":    "investigate",
    "action":      "execute",
    "ambiguous":   "observe",   # ambiguous classifier routes to observe
}

# Accept anything from 4 (below which the agent has no room to work) to 100
# (above which wall-clock / token caps will trip first anyway). Misconfigured
# values get clamped and a warning is logged.
_TOOL_BUDGET_MIN = 4
_TOOL_BUDGET_MAX = 100


def _tool_budget_for(agent_type: str) -> int:
    """Return the tool call budget for `agent_type`, read fresh from Settings.

    Aliases resolved first (status→observe, research→investigate, action→execute).
    Unknown types fall back to the investigate budget (the most permissive of the
    four canonical types). Misconfigured values (None, non-int, <=0, >100) log
    a warning and fall back to the hardcoded default.
    """
    canonical = _TOOL_BUDGET_ALIASES.get(agent_type, agent_type)
    default = _TOOL_BUDGET_DEFAULTS.get(canonical, _TOOL_BUDGET_DEFAULTS["investigate"])
    key = f"agentToolBudget_{canonical}"

    try:
        from mcp_server.tools.skills.storage import get_backend
        raw = get_backend().get_setting(key)
    except Exception as e:
        log.debug("tool budget settings read failed for %s: %s", key, e)
        return default

    if raw is None or raw == "":
        return default

    try:
        value = int(raw)
    except (TypeError, ValueError):
        log.warning(
            "tool budget setting %s has non-int value %r; using default %d",
            key, raw, default,
        )
        return default

    if value <= 0:
        # Operator explicitly set 0 → fall back to default (documented behaviour).
        return default

    if value < _TOOL_BUDGET_MIN or value > _TOOL_BUDGET_MAX:
        log.warning(
            "tool budget setting %s=%d outside safe range [%d..%d]; "
            "clamping to default %d",
            key, value, _TOOL_BUDGET_MIN, _TOOL_BUDGET_MAX, default,
        )
        return default

    return value


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

# ─── Post-action verification map (v2.32.2) ──────────────────────────────────
# Maps destructive tool → (verify_tool_name, args_builder_function)
# args_builder receives the original tool's fn_args and returns verify tool args.
# Only tools where state verification is meaningful are included.

def _verify_spec(tool_name: str, fn_args: dict) -> tuple[str, dict] | None:
    """Return (verify_tool, verify_args) for a destructive tool, or None if no verify needed."""
    if tool_name == "swarm_service_force_update":
        svc = fn_args.get("service_name", "")
        if svc:
            return ("service_health", {"service_name": svc})
    elif tool_name == "proxmox_vm_power":
        # After rebooting a VM, check if Swarm nodes recovered
        return ("swarm_node_status", {})
    elif tool_name == "service_upgrade":
        svc = fn_args.get("service_name", "")
        if svc:
            return ("post_upgrade_verify", {"service_name": svc})
    elif tool_name == "service_rollback":
        svc = fn_args.get("service_name", "")
        if svc:
            return ("service_health", {"service_name": svc})
    elif tool_name == "node_drain":
        return ("swarm_node_status", {})
    elif tool_name == "node_activate":
        return ("swarm_node_status", {})
    # docker_prune already returns before/after data — no separate verify needed
    # skill tools don't need infra verification
    return None


async def _auto_verify(
    tool_name: str,
    fn_args: dict,
    session_id: str,
    operation_id: str,
) -> dict | None:
    """Run post-action verification. Returns verify result dict or None if skipped.

    Called by the agent loop after a destructive tool returns status=ok.
    The verification is harness-driven — the model doesn't decide to verify,
    the harness does it automatically.
    """
    spec = _verify_spec(tool_name, fn_args)
    if spec is None:
        return None

    verify_name, verify_args = spec

    await manager.send_line(
        "step",
        f"[verify] Auto-verifying via {verify_name}...",
        status="ok", session_id=session_id,
    )

    try:
        verify_result = await asyncio.get_event_loop().run_in_executor(
            None, lambda vn=verify_name, va=verify_args: invoke_tool(vn, va)
        )
    except Exception as e:
        log.debug("Auto-verify %s failed: %s", verify_name, e)
        await manager.send_line(
            "step",
            f"[verify] {verify_name} failed: {str(e)[:100]}",
            status="warning", session_id=session_id,
        )
        return None

    v_status = verify_result.get("status", "error") if isinstance(verify_result, dict) else "error"
    v_message = verify_result.get("message", "") if isinstance(verify_result, dict) else str(verify_result)

    # Log the verify call
    await logger_mod.log_tool_call(
        operation_id, verify_name, verify_args, verify_result,
        _lm_model(), 0, status="ok",
    )

    # Determine if verification passed
    passed = v_status in ("ok", "healthy")
    icon = "✓" if passed else "⚠"

    await manager.send_line(
        "step",
        f"[verify] {icon} {verify_name} → {v_status} | {v_message[:120]}",
        tool=verify_name, status="ok" if passed else "warning",
        session_id=session_id,
    )

    return {
        "verify_tool": verify_name,
        "verify_status": v_status,
        "verify_message": v_message[:200],
        "passed": passed,
    }


# ─── Hard caps on agent runs (v2.31.8) ───────────────────────────────────────
# All env-configurable so an operator can tighten them without a redeploy.
_AGENT_MAX_WALL_CLOCK_S   = int(os.environ.get("AGENT_MAX_WALL_CLOCK_S",   "600"))   # 10 min
_AGENT_MAX_TOTAL_TOKENS   = int(os.environ.get("AGENT_MAX_TOTAL_TOKENS",   "120000"))
_AGENT_MAX_DESTRUCTIVE    = int(os.environ.get("AGENT_MAX_DESTRUCTIVE",    "3"))
_AGENT_MAX_TOOL_FAILURES  = int(os.environ.get("AGENT_MAX_TOOL_FAILURES",  "8"))

# ─── Sub-agent runtime caps (v2.34.0) ─────────────────────────────────────────
# Configurable via env var — operator-tunable without a redeploy.
_SUBAGENT_MAX_DEPTH             = int(os.environ.get("SUBAGENT_MAX_DEPTH",          "2"))
_SUBAGENT_MIN_PARENT_RESERVE    = int(os.environ.get("SUBAGENT_MIN_PARENT_RESERVE", "2"))
_SUBAGENT_TREE_WALL_CLOCK_S     = int(os.environ.get("SUBAGENT_TREE_WALL_CLOCK_S",  "1800"))
# v2.34.5: budget-nudge threshold (fraction of tool budget). Floor of 0.40,
# ceiling of 0.90 enforced by _resolve_nudge_threshold. Dropped from 0.70 to
# 0.60 so propose_subtask math is still reachable when it fires.
_SUBAGENT_NUDGE_THRESHOLD       = os.environ.get("SUBAGENT_NUDGE_THRESHOLD", "0.60")


def _agent_settings() -> dict:
    """Build the settings dict consumed by orchestrator helpers."""
    return {
        "subagentNudgeThreshold":   _SUBAGENT_NUDGE_THRESHOLD,
        "subagentMinParentReserve": _SUBAGENT_MIN_PARENT_RESERVE,
    }


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


class RunRequest(BaseModel):
    task: str = Field(
        default="Perform a full infrastructure health check and report status.",
        max_length=4096,
    )
    session_id: str = Field(default="", max_length=128)
    force_external: bool = Field(
        default=False,
        description="Skip local agent loop and route directly to external AI. "
                    "Bypasses router decision and confirmation modal.",
    )


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


async def wait_for_external_ai_confirmation(
    *,
    session_id: str,
    operation_id: str,
    provider: str,
    model: str,
    rule_fired: str,
    reason: str,
    output_mode: str,
) -> str:
    """Gate the agent loop on operator approval before calling external AI.

    v2.36.2. Broadcasts `external_ai_confirm_pending` to the GUI with the
    router rationale + provider/model, flips operations.status, waits up
    to `externalConfirmTimeoutSeconds` for a /confirm-external call,
    returns one of 'approved'|'rejected'|'timeout'.

    If requireConfirmation is false, returns 'approved' without waiting.
    """
    from mcp_server.tools.skills.storage import get_backend
    try:
        require = get_backend().get_setting("requireConfirmation")
    except Exception:
        require = True
    if require is None:
        require = True
    # Normalise truthy forms from storage backend
    if isinstance(require, str):
        require = require.strip().lower() in ("1", "true", "yes", "on")

    if not require:
        return "approved"

    # Read timeout (operator-tunable)
    try:
        timeout_s = int(get_backend().get_setting("externalConfirmTimeoutSeconds") or 300)
    except Exception:
        timeout_s = 300

    # Flip DB status
    try:
        from api.db.base import get_engine as _ge
        from sqlalchemy import text as _t
        async with _ge().begin() as conn:
            await conn.execute(
                _t("UPDATE operations SET status='awaiting_external_ai_confirm' "
                   "WHERE session_id=:sid"),
                {"sid": session_id},
            )
    except Exception as e:
        log.debug("wait_for_external_ai_confirmation DB flip failed: %s", e)

    await manager.broadcast({
        "type": "external_ai_confirm_pending",
        "session_id": session_id,
        "operation_id": operation_id,
        "provider": provider,
        "model": model,
        "rule_fired": rule_fired,
        "reason": reason,
        "output_mode": output_mode,
        "timeout_s": timeout_s,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    await manager.send_line(
        "step",
        f"[external-ai] Awaiting operator approval — {provider}/{model}, "
        f"rule={rule_fired}, mode={output_mode} (timeout {timeout_s}s)",
        status="warning", session_id=session_id,
    )

    from api.agents.external_ai_confirmation import wait_for_confirmation
    decision = await wait_for_confirmation(session_id, timeout_s=timeout_s)

    if decision == "timeout":
        try:
            from api.metrics import EXTERNAL_AI_CONFIRM_OUTCOME
            EXTERNAL_AI_CONFIRM_OUTCOME.labels(outcome="timeout").inc()
        except Exception:
            pass
        try:
            from api.db.base import get_engine as _ge
            from sqlalchemy import text as _t
            async with _ge().begin() as conn:
                await conn.execute(
                    _t("UPDATE operations SET status='cancelled', "
                       "final_answer='External AI escalation timed out waiting for approval.' "
                       "WHERE session_id=:sid "
                       "AND status='awaiting_external_ai_confirm'"),
                    {"sid": session_id},
                )
        except Exception:
            pass
        await manager.send_line(
            "halt",
            f"[external-ai] Approval timed out after {timeout_s}s — cancelling",
            status="failed", session_id=session_id,
        )

    return decision


class _PrerunShortCircuit(Exception):
    """v2.36.3 — sentinel raised when complexity_prefilter replaces the local run."""
    pass


async def _maybe_route_to_external_ai(
    *,
    session_id: str,
    operation_id: str,
    task: str,
    agent_type: str,
    messages: list[dict],
    tool_calls_made: int,
    tool_budget: int,
    diagnosis_emitted: bool,
    consecutive_tool_failures: int,
    halluc_guard_exhausted: bool,
    fabrication_detected_count: int,
    external_calls_this_op: int,
    scope_entity: str,
    is_prerun: bool,
    prior_failed_attempts_7d: int = 0,
    force: bool = False,
    prerun_digest: str = "",
) -> str | None:
    """Run the v2.36.1 router. If it fires, gate on v2.36.2 confirmation and
    call the v2.36.3 external AI. Return the synthesis text on success,
    None on no-op, or raise a sentinel-failure string via ExternalAIError.

    Caller treats a non-None return as the final_answer (REPLACE mode).

    force=True (v2.38.6): skip router decision and confirmation modal entirely.
    prerun_digest (v2.38.7): infrastructure context injected into synthesize_replace
    digest param so external AI has evidence at prerun time (no tool history yet).
    """
    # v2.47.9 — skip external AI entirely during test runs. Tests should
    # measure the local agent loop in isolation; external AI rescue
    # confounds the signal (8s latency, eventual rejection by harness
    # gate, requireConfirmation popup blocking 300s waiting for an
    # operator click that may never come). The score regression analysis
    # at 2026-04-26 traced a popup-during-tests issue back to this.
    try:
        from api.routers.tests_api import test_run_active
        if test_run_active:
            await manager.send_line(
                "step",
                "[external-ai] skipped — test run in progress (v2.47.9)",
                status="ok", session_id=session_id,
            )
            return None
    except Exception:
        pass

    from api.agents.external_router import (
        should_escalate_to_external_ai, record_decision, RouterState, RouterDecision,
    )
    from mcp_server.tools.skills.storage import get_backend

    try:
        _cap = int(get_backend().get_setting("routeMaxExternalCallsPerOp") or 3)
    except Exception:
        _cap = 3

    if force:
        # v2.38.6 — operator explicitly chose external AI; skip router.
        # Still respect per-op cap as hard safety limit.
        if external_calls_this_op >= _cap:
            await manager.send_line(
                "step",
                f"[external-ai] force=True but per-op cap reached "
                f"({external_calls_this_op}/{_cap}) — not calling external AI",
                status="warning", session_id=session_id,
            )
            return None
        try:
            from api.metrics import EXTERNAL_ROUTING_DECISIONS
            EXTERNAL_ROUTING_DECISIONS.labels(
                decision="escalated", rule="force_external",
            ).inc()
        except Exception:
            pass
        # Synthetic decision so downstream code that reads decision.* still works
        decision = RouterDecision(
            escalate=True,
            rule_fired="force_external",
            reason="operator chose to send directly to external AI",
            mode="replace",
        )
    else:
        state = RouterState(
            agent_type=agent_type,
            task_text=task,
            scope_entity=scope_entity,
            tool_calls_made=tool_calls_made,
            tool_budget=tool_budget,
            diagnosis_emitted=diagnosis_emitted,
            consecutive_tool_failures=consecutive_tool_failures,
            halluc_guard_exhausted=halluc_guard_exhausted,
            fabrication_detected_count=fabrication_detected_count,
            external_calls_this_op=external_calls_this_op,
            external_calls_cap=_cap,
            prior_failed_attempts_7d=prior_failed_attempts_7d,
        )
        decision = should_escalate_to_external_ai(state, is_prerun=is_prerun)
        record_decision(decision)
        if not decision.escalate:
            return None

    # Read provider/model/output_mode
    try:
        provider = (get_backend().get_setting("externalProvider") or "claude").strip().lower()
        model = (get_backend().get_setting("externalModel") or "").strip()
        output_mode = (get_backend().get_setting("externalRoutingOutputMode") or "replace").strip().lower()
    except Exception:
        provider, model, output_mode = "claude", "", "replace"

    # v2.45.26 — Default is "replace" (matches what is implemented). Other
    # modes ("augment", "replace+shrink") are accepted by settings validation
    # but treated as "replace" at runtime. Real "augment" semantics is a
    # planned v2.46.x change once a base-prompt + runbook-prepend strategy
    # has been designed.
    if output_mode != "replace":
        await manager.send_line(
            "step",
            f"[external-ai] output mode {output_mode!r} not implemented — "
            f"falling back to 'replace'",
            status="warning", session_id=session_id,
        )
        output_mode = "replace"

    # Confirmation gate — skipped when force=True (operator already chose this)
    if force:
        confirm_decision = "approved"
        await manager.send_line(
            "step",
            f"[external-ai] force=True — bypassing confirmation gate "
            f"({provider}/{model or 'default'})",
            status="ok", session_id=session_id,
        )
    else:
        confirm_decision = await wait_for_external_ai_confirmation(
            session_id=session_id,
            operation_id=operation_id,
            provider=provider,
            model=model,
            rule_fired=decision.rule_fired,
            reason=decision.reason,
            output_mode=output_mode,
        )
    if confirm_decision != "approved":
        await manager.send_line(
            "step",
            f"[external-ai] Escalation {confirm_decision} — no external call made",
            status="ok", session_id=session_id,
        )
        try:
            from api.db.external_ai_calls import write_external_ai_call
            write_external_ai_call(
                operation_id=operation_id, step_index=None,
                provider=provider, model=model or "?",
                rule_fired=decision.rule_fired, output_mode=output_mode,
                latency_ms=None, input_tokens=None, output_tokens=None,
                est_cost_usd=None,
                outcome="cancelled_by_user" if confirm_decision == "rejected" else "cancelled_by_user",
                error_message=f"Confirmation {confirm_decision}",
            )
        except Exception:
            pass
        return None

    # Compute the trace digest for context handoff
    digest_text = None
    try:
        try:
            last_n = int(get_backend().get_setting("externalContextLastNToolResults") or 5)
        except Exception:
            last_n = 5
        from api.db.llm_traces import get_trace, render_digest
        trace = get_trace(operation_id)
        digest_text = render_digest(trace, operation_id=operation_id)
        # Truncate middle tool-result bodies to just the last N, keep digest intact
        # (render_digest already emits a compact form; last_n is advisory for now)
        if len(digest_text) > 6000:
            digest_text = digest_text[:2500] + "\n[...digest truncated...]\n" + digest_text[-2500:]
    except Exception as _de:
        log.debug("digest render failed: %s", _de)

    # Actually call the external AI
    from api.agents.external_ai_client import (
        synthesize_replace,
        ExternalAIError, ExternalAIAuthError,
        ExternalAINetworkError, ExternalAITimeoutError,
    )
    from api.db.external_ai_calls import write_external_ai_call

    await manager.broadcast({
        "type": "external_ai_call_start",
        "session_id": session_id, "operation_id": operation_id,
        "provider": provider, "model": model,
        "rule_fired": decision.rule_fired, "output_mode": output_mode,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    await manager.send_line(
        "step",
        f"[external-ai] calling {provider}/{model} (rule={decision.rule_fired})",
        status="ok", session_id=session_id,
    )

    try:
        result = await synthesize_replace(
            task=task, agent_type=agent_type,
            messages=messages, digest=(prerun_digest or digest_text),
            context_max_chars=12000, timeout_s=45.0,
        )
    except ExternalAIError as e:
        outcome = e.outcome
        await manager.send_line(
            "halt",
            f"[external-ai] {outcome}: {e!s}",
            status="failed", session_id=session_id,
        )
        try:
            from api.metrics import EXTERNAL_AI_CALLS
            EXTERNAL_AI_CALLS.labels(provider=provider, outcome=outcome).inc()
        except Exception:
            pass
        write_external_ai_call(
            operation_id=operation_id, step_index=None,
            provider=provider, model=model or "?",
            rule_fired=decision.rule_fired, output_mode=output_mode,
            latency_ms=None, input_tokens=None, output_tokens=None,
            est_cost_usd=None, outcome=outcome, error_message=str(e)[:500],
        )
        # Halt — raise so the caller can set status=escalation_failed
        try:
            from api.routers.escalations import record_escalation
            record_escalation(
                session_id=session_id,
                reason=f"External AI ({provider}) failed: {e!s}",
                operation_id=operation_id, severity="critical",
            )
        except Exception:
            pass
        raise

    # Success path — apply existing harness gates to the external synthesis
    synth_text = result.text or ""

    # Fabrication detector on external output (D in spec)
    fabrication_rejected = False
    try:
        from api.agents.fabrication_detector import is_fabrication
        # Extract local tool names from messages history for the detector
        local_tools = []
        for m in messages:
            if m.get("role") == "assistant" and m.get("tool_calls"):
                for tc in m.get("tool_calls") or []:
                    fn = (tc.get("function") or {}) if isinstance(tc, dict) else {}
                    if fn.get("name"):
                        local_tools.append(fn["name"])
        fab_fired, _fab_detail = is_fabrication(
            synth_text, local_tools, min_cites=3, score_threshold=0.5,
        )
        if fab_fired:
            fabrication_rejected = True
    except Exception as _fe:
        log.debug("fabrication check on external output failed: %s", _fe)

    # Too-short / preamble-only rescue check
    if not fabrication_rejected:
        rescue_reason = _classify_terminal_final_answer(synth_text)
        if rescue_reason is not None:
            log.warning(
                "external AI output rejected by %s rescue — synth_text too short/preamble",
                rescue_reason,
            )
            fabrication_rejected = True

    # Log per-call outcome
    outcome = "rejected_by_gate" if fabrication_rejected else "success"
    try:
        from api.metrics import EXTERNAL_AI_CALLS
        EXTERNAL_AI_CALLS.labels(provider=result.provider, outcome=outcome).inc()
    except Exception:
        pass
    write_external_ai_call(
        operation_id=operation_id, step_index=None,
        provider=result.provider, model=result.model,
        rule_fired=decision.rule_fired, output_mode=output_mode,
        latency_ms=result.latency_ms,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        est_cost_usd=result.est_cost_usd,
        outcome=outcome,
        error_message=None,
    )

    if fabrication_rejected:
        await manager.send_line(
            "step",
            f"[external-ai] output rejected by harness gate — discarding, "
            "falling back to local forced_synthesis",
            status="warning", session_id=session_id,
        )
        return None  # Caller runs forced_synthesis instead

    # Persist the external-synthesis as an llm_trace row so the Trace
    # viewer shows it with provider='claude' etc.
    try:
        from api.logger import log_llm_step
        await log_llm_step(
            operation_id=operation_id,
            step_index=99999,  # distinguish from local steps
            messages_delta=[
                {"role": "system", "content": "[external-ai synthesis (REPLACE mode)]"},
                {"role": "assistant", "content": synth_text},
            ],
            response_raw={
                "external_ai": True,
                "provider": result.provider,
                "model": result.model,
                "latency_ms": result.latency_ms,
                "usage": {
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "est_cost_usd": result.est_cost_usd,
                },
                "rule_fired": decision.rule_fired,
            },
            agent_type=agent_type,
            temperature=0.3,
            model=result.model,
            provider=result.provider,
        )
    except Exception as _te:
        log.debug("external_ai trace log failed: %s", _te)

    await manager.broadcast({
        "type": "external_ai_call_done",
        "session_id": session_id, "operation_id": operation_id,
        "provider": result.provider, "model": result.model,
        "latency_ms": result.latency_ms,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "est_cost_usd": result.est_cost_usd,
        "outcome": outcome,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    # Prepend provider tag for operator visibility
    tagged = f"[EXTERNAL: {result.provider}/{result.model}]\n\n{synth_text}"
    return tagged


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
    parent_session_id: str = "",
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

    # ── Per-run feedback accumulators (v2.41.0: consolidated into StepState) ──
    from api.agents.propose_dedup import ProposeState
    from api.agents.step_state import StepState
    state = StepState(
        session_id=session_id,
        operation_id=operation_id,
        agent_type=agent_type,
        task=task,
        parent_session_id=parent_session_id,
        plan_action_called=plan_already_approved,
        halluc_guard_max=int(os.environ.get("AGENT_HALLUC_GUARD_MAX_ATTEMPTS", "3")),
        fabrication_min_cites=int(os.environ.get("AGENT_FABRICATION_MIN_CITES", "3")),
        fabrication_score_threshold=float(os.environ.get("AGENT_FABRICATION_SCORE_THRESHOLD", "0.5")),
        trace_is_subagent=bool(parent_session_id),
        propose_state=ProposeState(),
    )
    if state.trace_is_subagent and parent_session_id:
        try:
            from api.db.base import get_engine as _get_eng_for_trace
            from api.db import queries as _q_for_trace
            async with _get_eng_for_trace().connect() as _c_for_trace:
                _parent_op = await _q_for_trace.get_operation_by_session(
                    _c_for_trace, parent_session_id
                )
                if _parent_op:
                    state.trace_parent_op_id = _parent_op.get("id")
        except Exception:
            state.trace_parent_op_id = None

    step = 0
    _MAX_STEPS_BY_TYPE = {"status": 12, "observe": 12, "research": 12, "investigate": 12, "action": 20, "execute": 20, "build": 15}
    max_steps = _MAX_STEPS_BY_TYPE.get(agent_type, 20)
    # ─── Tool call budgets per agent type (v2.32.5 → v2.36.5) ────────────────────
    # Unlike max_steps (LLM inference rounds), this counts actual tool invocations.
    # When exhausted, the harness forces a summary — no more tool calls allowed.
    # v2.36.5: budget now sourced from Settings via _tool_budget_for(agent_type).

    # v2.35.14 — fire forced_synthesis at most once on the natural-completion
    # path (state.last_reasoning empty + >=1 substantive tool call). Each terminal
    # happy-path branch consults this guard before broadcasting "done".
    # v2.35.15 — extended from single empty-check to three-way dispatch
    # (empty / too_short / preamble_only). Each reason rides the same
    # once-per-run guard and gets a distinct metric label.
    state.empty_completion_synth_done = False

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
                state.final_status = "cancelled"
                break

            step += 1

            exceeded, reason = _cap_exceeded(
                started_monotonic=_run_started,
                total_tokens=state.total_prompt_tokens + state.total_completion_tokens,
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

                # v2.34.17: run a tools-free forced synthesis so the operator
                # still gets an EVIDENCE / ROOT CAUSE / NEXT STEPS block from
                # whatever was already gathered, instead of a silent null.
                _cap_reason_key = {
                    "wall_clock":       "wall_clock",
                    "token_cap":        "token_cap",
                    "destructive_cap":  "destructive_cap",
                    "tool_failures":    "tool_failures",
                }.get(reason, reason or "wall_clock")
                _budget_cap = _tool_budget_for(agent_type)
                from api.agents.forced_synthesis import run_forced_synthesis
                synthesis_text, harness_msg, raw_resp = run_forced_synthesis(
                    client=client,
                    model=_lm_model(),
                    messages=messages,
                    agent_type=agent_type,
                    reason=_cap_reason_key,
                    tool_count=len(state.tools_used_names),
                    budget=_budget_cap,
                    actual_tool_names=state.tools_used_names,
                    # v2.35.13 — DB-sourced fallback via operation_id
                    operation_id=operation_id,
                    # v2.35.12 — pass rich history as backup source
                    actual_tool_calls=[
                        {
                            "name": tc.get("tool") or tc.get("tool_name") or tc.get("name"),
                            "status": tc.get("status"),
                            "result": tc.get("result") or tc.get("content"),
                        }
                        for tc in (state.tool_history or [])
                    ],
                )
                if synthesis_text:
                    state.last_reasoning = synthesis_text
                else:
                    state.last_reasoning = (
                        f"Task stopped — {reason}. Partial findings above may be "
                        f"useful; re-run with a narrower task if needed."
                    )
                await manager.send_line("reasoning", state.last_reasoning, session_id=session_id)

                try:
                    from api.logger import log_llm_step
                    await log_llm_step(
                        operation_id=operation_id,
                        step_index=state.trace_step_index,
                        messages_delta=[{"role": "system", "content": harness_msg}],
                        response_raw=raw_resp or {"forced_synthesis": {"reason": _cap_reason_key,
                                                                        "text": synthesis_text}},
                        agent_type=agent_type,
                        is_subagent=state.trace_is_subagent,
                        parent_op_id=state.trace_parent_op_id,
                        temperature=0.3,
                        model=_extract_response_model(raw_resp, fallback=_lm_model()),
                        provider="lm_studio",
                    )
                    state.trace_step_index += 1
                except Exception as _te:
                    log.debug("forced synthesis trace log failed: %s", _te)

                if is_final_step:
                    await manager.broadcast({
                        "type": "done", "session_id": session_id, "agent_type": agent_type,
                        "content": state.last_reasoning, "status": "ok", "choices": [],
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                state.final_status = "capped"
                break

            # v2.32.5: Tool call budget enforcement
            _tool_budget = _tool_budget_for(agent_type)

            # v2.33.3: Budget handoff nudge — fires when investigate agent has
            # not emitted DIAGNOSIS: and has not yet proposed a subtask.
            # v2.34.5: threshold dropped from 0.70 to 0.60 (configurable via
            # SUBAGENT_NUDGE_THRESHOLD env / subagentNudgeThreshold setting) so
            # the propose_subtask spawn math is actually reachable when it
            # fires. At budget=16, reserve=2, min_sub=2 we need used<=11; 0.60
            # gives us fire at used=10.
            if agent_type in ("research", "investigate"):
                from api.agents.orchestrator import _resolve_nudge_threshold
                _nudge_threshold = _resolve_nudge_threshold(_agent_settings())
                _budget_threshold = int(_nudge_threshold * _tool_budget)
                _tools_used_count = len(state.tools_used_names)
                _subtask_proposed = "propose_subtask" in state.tools_used_names
                _diagnosis_emitted = "DIAGNOSIS:" in (state.last_reasoning or "")
                if (_tools_used_count >= _budget_threshold
                        and not _subtask_proposed
                        and not _diagnosis_emitted
                        and not state.budget_nudge_fired):
                    messages.append({
                        "role": "user",
                        "content": (
                            f"HARNESS NUDGE: You have used {_tools_used_count}/{_tool_budget} "
                            "tool calls. No DIAGNOSIS: section emitted yet. Per BUDGET "
                            "HANDOFF RULE, your next action must be propose_subtask("
                            "task=..., executable_steps=[...], manual_steps=[...]) with "
                            "a tight, single-entity scope carrying forward what you have "
                            "found so far. Do NOT produce a shallow conclusion."
                        ),
                    })
                    await manager.broadcast({
                        "type":       "budget_nudge",
                        "session_id": session_id,
                        "tools_used": _tools_used_count,
                        "budget":     _tool_budget,
                        "threshold":  _nudge_threshold,
                        "timestamp":  datetime.now(timezone.utc).isoformat(),
                    })
                    await manager.send_line(
                        "step",
                        f"[budget] {int(_nudge_threshold*100)}% threshold reached "
                        f"({_tools_used_count}/{_tool_budget}) without DIAGNOSIS — "
                        f"nudging agent toward propose_subtask",
                        status="ok", session_id=session_id,
                    )
                    state.budget_nudge_fired = True

            if len(state.tools_used_names) >= _tool_budget:
                await manager.send_line(
                    "step",
                    f"[budget] Tool call budget reached ({len(state.tools_used_names)}/{_tool_budget}) "
                    f"— forcing synthesis",
                    status="ok", session_id=session_id,
                )
                state.final_status = "capped"
                from api.agents.forced_synthesis import run_forced_synthesis
                synthesis_text, harness_msg, raw_resp = run_forced_synthesis(
                    client=client,
                    model=_lm_model(),
                    messages=messages,
                    agent_type=agent_type,
                    reason="budget_cap",
                    tool_count=len(state.tools_used_names),
                    budget=_tool_budget,
                    actual_tool_names=state.tools_used_names,
                    # v2.35.13 — DB-sourced fallback via operation_id
                    operation_id=operation_id,
                    # v2.35.12 — pass rich history as backup source
                    actual_tool_calls=[
                        {
                            "name": tc.get("tool") or tc.get("tool_name") or tc.get("name"),
                            "status": tc.get("status"),
                            "result": tc.get("result") or tc.get("content"),
                        }
                        for tc in (state.tool_history or [])
                    ],
                )
                if synthesis_text:
                    state.last_reasoning = synthesis_text
                    await manager.send_line("reasoning", synthesis_text, session_id=session_id)

                # Persist the forced step to the LLM trace
                try:
                    from api.logger import log_llm_step
                    await log_llm_step(
                        operation_id=operation_id,
                        step_index=state.trace_step_index,
                        messages_delta=[{"role": "system", "content": harness_msg}],
                        response_raw=raw_resp or {"forced_synthesis": {"reason": "budget_cap",
                                                                        "text": synthesis_text}},
                        agent_type=agent_type,
                        is_subagent=state.trace_is_subagent,
                        parent_op_id=state.trace_parent_op_id,
                        temperature=0.3,
                        model=_extract_response_model(raw_resp, fallback=_lm_model()),
                        provider="lm_studio",
                    )
                    state.trace_step_index += 1
                except Exception as _te:
                    log.debug("forced synthesis trace log failed: %s", _te)

                # v2.36.3 — budget_exhaustion rule check
                _external_ai_route_error = ""  # v2.38.4 — surface escalation failures to UI
                try:
                    _router_synth = await _maybe_route_to_external_ai(
                        session_id=session_id,
                        operation_id=operation_id,
                        task=task,
                        agent_type=agent_type,
                        messages=messages,
                        tool_calls_made=len(state.tools_used_names),
                        tool_budget=_tool_budget,
                        diagnosis_emitted="DIAGNOSIS:" in (state.last_reasoning or ""),
                        consecutive_tool_failures=_tool_failures,
                        halluc_guard_exhausted=(state.halluc_guard_attempts >= state.halluc_guard_max),
                        fabrication_detected_count=(1 if state.fabrication_detected_once else 0),
                        external_calls_this_op=0,
                        scope_entity=parent_session_id or "",
                        is_prerun=False,
                        prior_failed_attempts_7d=0,
                    )
                    if _router_synth:
                        state.last_reasoning = _router_synth
                except Exception as _re:
                    # v2.38.4 — louder logging + UI surface. Previous code
                    # logged a single-line warning and fell through silently
                    # to a done/ok broadcast, which masked real failures
                    # (esp. auth 401s from the pre-v2.38.3 ciphertext bug).
                    log.warning(
                        "EXTERNAL_AI_ROUTE_FAIL rule=budget_exhaustion "
                        "session=%s operation=%s err_class=%s err=%s",
                        session_id, operation_id, type(_re).__name__, _re,
                    )
                    _external_ai_route_error = (
                        f"{type(_re).__name__}: {str(_re)[:240]}"
                    )
                    state.final_status = "escalation_failed"
                    try:
                        await manager.send_line(
                            "halt",
                            f"[external-ai] route failed — {_external_ai_route_error}",
                            status="failed", session_id=session_id,
                        )
                    except Exception:
                        pass

                if is_final_step:
                    choices = _extract_choices(state.last_reasoning) if state.last_reasoning else None
                    if _external_ai_route_error:
                        _done_status = "failed"
                        _done_content = (
                            f"[EXTERNAL AI ESCALATION FAILED: {_external_ai_route_error}]\n\n"
                            f"{state.last_reasoning or f'Agent reached tool budget ({_tool_budget}).'}"
                        )
                        _done_reason = "escalation_failed"
                    else:
                        _done_status = "ok"
                        _done_content = state.last_reasoning or f"Agent reached tool budget ({_tool_budget})."
                        _done_reason = None
                    _payload = {
                        "type": "done", "session_id": session_id, "agent_type": agent_type,
                        "content": _done_content,
                        "status": _done_status, "choices": choices or [],
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    if _done_reason:
                        _payload["reason"] = _done_reason
                    await manager.broadcast(_payload)
                break

            _llm = await call_llm_step(
                state, client, messages, tools_spec, step, max_steps, system_prompt,
                manager=manager, session_id=session_id, operation_id=operation_id,
                agent_type=agent_type, is_final_step=is_final_step,
            )
            if _llm.hard_error:
                state.final_status = "error"
                break
            response, finish, msg = _llm.response, _llm.finish, _llm.msg

            if finish == "stop" or not msg.tool_calls:
                _guard = await run_stop_path_guards(
                    state, msg, messages,
                    manager=manager, session_id=session_id,
                    operation_id=operation_id, agent_type=agent_type,
                    task=task, step=step, max_steps=max_steps,
                    client=client, tools_spec=tools_spec,
                    is_final_step=is_final_step,
                    parent_session_id=parent_session_id,
                )
                if _guard == GuardOutcome.RETRY:
                    continue
                if _guard in (GuardOutcome.FAIL, GuardOutcome.RESCUED):
                    break
                # GuardOutcome.PROCEED — fall through to degraded synthesis + done

                # v2.47.5 — clarify-then-text-exit rescue.
                # Pattern observed in action-drain-01, action-rollback-01,
                # action-upgrade-01 (mem-on baseline 2026-04-25): agent
                # called clarifying_question, received prearmed answer,
                # then exited via finish=="stop" with text instead of
                # calling plan_action(). The v2.45.18 system-message
                # injection in step_tools._handle_clarifying_question
                # told the model to call plan_action() next, but the
                # model produced text. This guard rejects the empty
                # completion and forces ONE more LLM turn with a hard
                # directive. Idempotent — re-uses the v2.47.3 nudge flag.
                if (
                    agent_type in ("action", "execute")
                    and not state.plan_action_called
                    and "clarifying_question" in state.tools_used_names
                    and not state.plan_force_nudge_fired
                ):
                    state.plan_force_nudge_fired = True
                    messages.append({
                        "role": "system",
                        "content": (
                            "[harness] You called clarifying_question() and "
                            "received an answer, then exited with text instead "
                            "of calling plan_action(). For an EXECUTE-type "
                            "task this is a protocol failure. Re-read the task "
                            "and the user's clarification answer above, then "
                            "your NEXT response MUST be a plan_action() tool "
                            "call (NOT text) with concrete summary + steps. "
                            "Do NOT respond with prose. Do NOT call audit_log. "
                            "Do NOT call escalate. Call plan_action() now."
                        ),
                    })
                    await manager.send_line(
                        "step",
                        "[harness] clarify-then-text-exit rescue — forcing one "
                        "more turn for plan_action()",
                        status="warning", session_id=session_id,
                    )
                    try:
                        from api.metrics import HARNESS_PLAN_NUDGES_COUNTER
                        HARNESS_PLAN_NUDGES_COUNTER.labels(
                            agent_type=agent_type,
                        ).inc()
                    except Exception:
                        pass
                    continue   # one more LLM turn

                # v2.47.6 — no-evidence rebuke. Pattern observed in
                # status-elastic-01, research-elastic-index-01: agent
                # exits via finish=="stop" on step 1 having called ZERO
                # substantive tools. The dense system prompt's KAFKA
                # TRIAGE / EXIT CODE / NETWORK QUERIES sections steer the
                # model toward "this isn't a kafka problem, must be done"
                # for elastic-only tasks. Reject the empty exit and force
                # one more turn with a concrete tool hint.
                if (
                    agent_type in ("observe", "status", "investigate", "research")
                    and state.substantive_tool_calls == 0
                    and not state.no_evidence_rebuke_fired
                    and step <= 2
                ):
                    state.no_evidence_rebuke_fired = True
                    # Detect named subsystem to give a concrete hint
                    _t_lower = (task or "").lower()
                    _hint = ""
                    if "elastic" in _t_lower or "elasticsearch" in _t_lower:
                        if "index" in _t_lower or "stat" in _t_lower:
                            _hint = " Call elastic_index_stats() now."
                        elif "health" in _t_lower or "cluster" in _t_lower:
                            _hint = " Call elastic_cluster_health() now."
                        elif "log" in _t_lower or "search" in _t_lower:
                            _hint = " Call elastic_search_logs() now."
                    elif "kafka" in _t_lower:
                        if "broker" in _t_lower:
                            _hint = " Call kafka_broker_status() now."
                        elif "lag" in _t_lower or "consumer" in _t_lower:
                            _hint = " Call kafka_consumer_lag() now."
                        elif "topic" in _t_lower:
                            _hint = " Call kafka_topic_health() now."
                    elif "swarm" in _t_lower or "service" in _t_lower:
                        if "node" in _t_lower:
                            _hint = " Call swarm_node_status() now."
                        else:
                            _hint = " Call service_list() or swarm_status() now."

                    messages.append({
                        "role": "system",
                        "content": (
                            "[harness] You exited without gathering any "
                            "evidence. The user's task names a specific "
                            "subsystem and expects you to query it before "
                            "concluding. Calling audit_log() or producing "
                            "a text-only answer with zero tool calls is a "
                            "protocol failure. Re-read the task, identify "
                            "the specific tool that answers the user's "
                            "question, and call it now." + _hint
                        ),
                    })
                    await manager.send_line(
                        "step",
                        f"[harness] no-evidence rebuke — forcing one more turn"
                        + (f" ({_hint.strip()})" if _hint else ""),
                        status="warning", session_id=session_id,
                    )
                    try:
                        from api.metrics import HARNESS_NO_EVIDENCE_REBUKE_COUNTER
                        HARNESS_NO_EVIDENCE_REBUKE_COUNTER.labels(
                            agent_type=agent_type,
                        ).inc()
                    except Exception:
                        pass
                    continue   # one more LLM turn

                # Synthesise degraded findings if present and summary is thin
                if state.degraded_findings and (not state.last_reasoning or len(state.last_reasoning) < 100):
                    try:
                        _synth_ctx = "\n".join(f"- {f}" for f in state.degraded_findings)
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
                            state.last_reasoning = _synth_text.strip()
                            await manager.send_line("reasoning", _synth_text, session_id=session_id)
                    except Exception as _se:
                        log.debug("Stop-path synthesis failed: %s", _se)
                # v2.35.14: empty-completion rescue on natural exit
                await maybe_force_empty_synthesis(
                    state, client, messages,
                    manager=manager, session_id=session_id,
                    operation_id=operation_id, agent_type=agent_type,
                    tool_budget=_tool_budget_for(agent_type),
                )
                choices = _extract_choices(state.last_reasoning) if state.last_reasoning else None
                if is_final_step:
                    payload = {
                        "type":       "done",
                        "session_id": session_id,
                        "agent_type": agent_type,
                        "content":    state.last_reasoning if state.last_reasoning else f"Agent finished after {step} steps.",
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

            _allowed_tools = frozenset(t['function']['name'] for t in tools_spec)
            _tr = await dispatch_tool_calls(
                state, msg, messages, tools_spec,
                manager=manager, session_id=session_id,
                operation_id=operation_id, agent_type=agent_type,
                task=task, step=step, client=client,
                owner_user=owner_user, parent_session_id=parent_session_id,
                is_final_step=is_final_step,
                allowed_tools=_allowed_tools,
                destructive_tools=DESTRUCTIVE_TOOLS,
                tool_budget=_tool_budget_for(agent_type),
            )
            _destructive_calls += _tr.destructive_calls_delta
            _tool_failures     += _tr.tool_failures_delta
            if _tr.action == ToolLoopAction.BREAK:
                break
            if _tr.action == ToolLoopAction.CONTINUE:
                continue

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

            # Fix 1C: if entire step was only audit_log calls, the agent is done
            # Exception: if escalate was just blocked, the model may call audit_log
            # as a confused "done" signal — don't treat it as completion; let loop continue.
            _step_names = [tc.function.name for tc in msg.tool_calls]

            # v2.47.5 — audit_log-only step on action/execute that already
            # clarified but never planned: same rescue path. The model
            # took clarification answer → wrote audit_log → would otherwise
            # exit. Force one more turn for plan_action().
            if (
                _step_names
                and all(n == "audit_log" for n in _step_names)
                and agent_type in ("action", "execute")
                and not state.plan_action_called
                and "clarifying_question" in state.tools_used_names
                and not state.plan_force_nudge_fired
            ):
                state.plan_force_nudge_fired = True
                messages.append({
                    "role": "system",
                    "content": (
                        "[harness] You called audit_log() after the "
                        "clarification but never called plan_action(). "
                        "audit_log() is for AFTER an action completes — "
                        "not as a substitute for plan_action(). Your NEXT "
                        "response MUST be plan_action() as a tool call "
                        "with concrete summary + steps. "
                        "Do NOT call audit_log() again. "
                        "Do NOT respond with text."
                    ),
                })
                await manager.send_line(
                    "step",
                    "[harness] audit_log-only after clarify rescue — "
                    "forcing plan_action()",
                    status="warning", session_id=session_id,
                )
                try:
                    from api.metrics import HARNESS_PLAN_NUDGES_COUNTER
                    HARNESS_PLAN_NUDGES_COUNTER.labels(
                        agent_type=agent_type,
                    ).inc()
                except Exception:
                    pass
                continue

            # v2.47.6 — audit_log-only step on observe/research/investigate
            # with ZERO substantive tool calls: agent called audit_log as
            # a "done" signal without gathering evidence. Same rebuke as
            # the natural-exit path. Idempotent.
            if (
                _step_names
                and all(n == "audit_log" for n in _step_names)
                and agent_type in ("observe", "status", "investigate", "research")
                and state.substantive_tool_calls == 0
                and not state.no_evidence_rebuke_fired
            ):
                state.no_evidence_rebuke_fired = True
                _t_lower = (task or "").lower()
                _hint = ""
                if "elastic" in _t_lower:
                    if "index" in _t_lower or "stat" in _t_lower:
                        _hint = " Call elastic_index_stats() now."
                    elif "health" in _t_lower or "cluster" in _t_lower:
                        _hint = " Call elastic_cluster_health() now."
                elif "kafka" in _t_lower:
                    if "broker" in _t_lower:
                        _hint = " Call kafka_broker_status() now."
                    elif "lag" in _t_lower:
                        _hint = " Call kafka_consumer_lag() now."

                messages.append({
                    "role": "system",
                    "content": (
                        "[harness] You called audit_log() without gathering "
                        "evidence first. audit_log() is for AFTER you have "
                        "called the read-only status tools the user's task "
                        "implies. Re-read the task and call the specific "
                        "tool that answers it now." + _hint
                    ),
                })
                await manager.send_line(
                    "step",
                    f"[harness] audit_log-only no-evidence rebuke"
                    + (f" — {_hint.strip()}" if _hint else ""),
                    status="warning", session_id=session_id,
                )
                try:
                    from api.metrics import HARNESS_NO_EVIDENCE_REBUKE_COUNTER
                    HARNESS_NO_EVIDENCE_REBUKE_COUNTER.labels(
                        agent_type=agent_type,
                    ).inc()
                except Exception:
                    pass
                continue

            if (_step_names and all(n == "audit_log" for n in _step_names)
                    and state.last_blocked_tool != "escalate"):
                # Synthesise degraded findings before broadcasting done
                if state.degraded_findings and (not state.last_reasoning or len(state.last_reasoning) < 100):
                    try:
                        _synth_ctx = "\n".join(f"- {f}" for f in state.degraded_findings)
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
                            state.last_reasoning = _synth_text.strip()
                            await manager.send_line("reasoning", _synth_text, session_id=session_id)
                    except Exception as _se:
                        log.debug("Audit-log completion synthesis failed: %s", _se)
                # v2.35.14: empty-completion rescue when an audit_log-only step
                # ends the run with no assistant text emitted (op 1ebb7047).
                await maybe_force_empty_synthesis(
                    state, client, messages,
                    manager=manager, session_id=session_id,
                    operation_id=operation_id, agent_type=agent_type,
                    tool_budget=_tool_budget_for(agent_type),
                )
                choices = _extract_choices(state.last_reasoning) if state.last_reasoning else None
                if is_final_step:
                    await manager.broadcast({
                        "type": "done", "session_id": session_id, "agent_type": agent_type,
                        "content": state.last_reasoning if state.last_reasoning else f"Agent finished after {step} steps.",
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
                    state.last_reasoning = forced_text
                    await manager.send_line("reasoning", forced_text, session_id=session_id)
            except Exception as _fe:
                log.debug("Force summary call failed: %s", _fe)

            # Investigate agent: if degraded findings accumulated but no synthesis yet, do it now
            if state.degraded_findings and (not state.last_reasoning or len(state.last_reasoning) < 80):
                try:
                    _synth_ctx2 = "\n".join(f"- {f}" for f in state.degraded_findings)
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
                        state.last_reasoning = _synth_text2.strip()
                        await manager.send_line("reasoning", _synth_text2, session_id=session_id)
                except Exception as _se2:
                    log.debug("Post-loop synthesis failed: %s", _se2)

            # v2.35.14: empty-completion rescue when the loop exhausted
            # max_steps and the post-loop force_summary call also produced
            # nothing useful (state.last_reasoning still empty).
            await maybe_force_empty_synthesis(
                state, client, messages,
                manager=manager, session_id=session_id,
                operation_id=operation_id, agent_type=agent_type,
                tool_budget=_tool_budget_for(agent_type),
            )
            if is_final_step:
                await manager.broadcast({
                    "type": "done", "session_id": session_id, "agent_type": agent_type,
                    "content": state.last_reasoning or f"Agent reached max steps ({max_steps}).",
                    "status": "ok", "choices": [],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

    except Exception as e:
        await manager.broadcast({
            "type": "error", "session_id": session_id,
            "content": f"Agent loop error: {e}", "status": "error",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        state.final_status = "error"

    # If the agent halted (escalated), the while loop broke without a done/error
    # broadcast — send one now so any waiting WebSocket clients can close.
    if state.final_status == "escalated":
        await manager.broadcast({
            "type": "error", "session_id": session_id,
            "agent_type": agent_type,
            "content": "Agent halted — escalated for human review.",
            "status": "escalated", "choices": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    if state.total_prompt_tokens or state.total_completion_tokens:
        await manager.send_line(
            "step",
            f"[tokens] prompt={state.total_prompt_tokens} completion={state.total_completion_tokens} "
            f"total={state.total_prompt_tokens + state.total_completion_tokens}",
            status="ok", session_id=session_id,
        )

    state.steps_taken = step

    # v2.45.25 — drain agent_observation facts to known_facts_current
    try:
        from api.agents.step_persist import persist_run_facts
        persist_run_facts(
            state,
            operation_id=operation_id,
            session_id=session_id,
            agent_type=agent_type,
            task=task,
        )
    except Exception as _ppe:
        log.debug("persist_run_facts failed: %s", _ppe)

    return state.to_result_dict()


async def _spawn_and_wait_subagent(
    *,
    parent_session_id: str,
    parent_operation_id: str,
    owner_user: str,
    objective: str,
    agent_type: str,
    scope_entity: str | None,
    budget_tools: int,
    allow_destructive: bool,
    parent_remaining_budget: int,
    parent_agent_type: str,
    parent_diagnosis: str = "",
    parent_budget_tools: int = 0,
    parent_tools_used: int = 0,
) -> dict:
    """Spawn a sub-agent in-band, block until it completes, return its result.

    Enforces: depth cap, budget reservation, destructive permission rules.
    Emits subagent_spawned / subagent_done WS events for GUI rendering.
    """
    import asyncio as _asyncio
    from api.db.subagent_runs import (
        record_spawn, record_completion, get_ancestry,
    )

    # ── Depth enforcement ─────────────────────────────────────────────────────
    ancestry = get_ancestry(parent_session_id)
    depth = len(ancestry) + 1
    if depth > _SUBAGENT_MAX_DEPTH:
        return {
            "ok": False,
            "error": (
                f"sub-agent depth cap reached ({depth} > {_SUBAGENT_MAX_DEPTH}). "
                "Complete this task yourself — no further delegation."
            ),
        }

    # ── Destructive permission ────────────────────────────────────────────────
    if allow_destructive and agent_type != "execute":
        return {"ok": False,
                "error": "allow_destructive requires agent_type=execute"}
    if allow_destructive and parent_agent_type not in ("execute", "action"):
        return {"ok": False,
                "error": "destructive sub-agents only when parent is execute-type"}
    if allow_destructive and depth > 1:
        return {"ok": False,
                "error": "destructive sub-agents only at depth 1"}

    # ── Budget reservation ────────────────────────────────────────────────────
    # v2.34.5: dynamic reserve — relax when parent has no DIAGNOSIS and is
    # late-game, since the reserve exists so parent can synthesise after the
    # sub-agent returns. If parent has nothing to synthesise, reserving is
    # counter-productive and blocks the spawn that would otherwise rescue the
    # run.
    from api.agents.orchestrator import _dynamic_reserve
    _settings = _agent_settings()
    default_reserve = int(_settings.get("subagentMinParentReserve", 2))
    _diagnosis_seen = bool(parent_diagnosis and parent_diagnosis.strip())
    reserve = _dynamic_reserve(
        tools_used=parent_tools_used or max(0, parent_budget_tools - parent_remaining_budget),
        budget_tools=parent_budget_tools or (parent_remaining_budget + default_reserve),
        diagnosis_seen=_diagnosis_seen,
        settings=_settings,
    )
    max_sub_budget = max(0, parent_remaining_budget - reserve)
    sub_budget = min(max(budget_tools, 2), max_sub_budget) if max_sub_budget > 0 else 0
    if sub_budget < 2:
        _relaxed = "relaxed" if reserve < default_reserve else "default"
        return {
            "ok": False,
            "error": (
                f"sub-agent insufficient budget: parent remaining={parent_remaining_budget}, "
                f"reserve={reserve} ({_relaxed}), max_sub={max_sub_budget}, min=2. "
                "Complete this task yourself — do not delegate."
            ),
        }

    # ── Allocate sub-agent identity ───────────────────────────────────────────
    sub_session_id = str(uuid.uuid4())
    try:
        sub_operation_id = await logger_mod.log_operation(
            sub_session_id, objective, owner_user=owner_user,
        )
    except Exception as _le:
        log.warning("sub-agent log_operation failed: %s", _le)
        sub_operation_id = ""

    record_spawn(
        parent_task_id=parent_session_id,
        sub_task_id=sub_session_id,
        depth=depth,
        objective=objective,
        agent_type=agent_type,
        scope_entity=scope_entity,
        budget_tools=sub_budget,
        allow_destructive=allow_destructive,
    )

    # ── Broadcast spawn so GUI can render sub-panel ───────────────────────────
    try:
        await manager.broadcast({
            "type":             "subagent_spawned",
            "session_id":       sub_session_id,
            "parent_session_id": parent_session_id,
            "parent_task_id":   parent_session_id,
            "sub_task_id":      sub_session_id,
            "depth":            depth,
            "objective":        objective,
            "agent_type":       agent_type,
            "scope_entity":     scope_entity or "",
            "budget_tools":     sub_budget,
            "timestamp":        datetime.now(timezone.utc).isoformat(),
        })
    except Exception as _be:
        log.debug("subagent_spawned broadcast failed: %s", _be)

    # ── Build isolated context + run the sub-agent to completion ─────────────
    sub_system_prefix = _build_subagent_context(
        parent_diagnosis=parent_diagnosis,
        scope_entity=scope_entity or "",
        parent_session_id=parent_session_id,
    )

    terminal_status = "done"
    err_msg: str | None = None
    try:
        await _asyncio.wait_for(
            _stream_agent(
                task=objective,
                session_id=sub_session_id,
                operation_id=sub_operation_id,
                owner_user=owner_user,
                parent_context=sub_system_prefix,
                parent_session_id=parent_session_id,
            ),
            timeout=_SUBAGENT_TREE_WALL_CLOCK_S,
        )
    except _asyncio.TimeoutError:
        terminal_status = "timeout"
        err_msg = f"sub-agent wall-clock cap {_SUBAGENT_TREE_WALL_CLOCK_S}s"
        log.warning("sub-agent %s timed out", sub_session_id)
    except Exception as _se:
        terminal_status = "failed"
        err_msg = str(_se)[:300]
        log.warning("sub-agent %s failed: %s", sub_session_id, _se)

    # ── Harvest sub-agent's final_answer + tool-call count ───────────────────
    sub_final_answer = ""
    sub_diagnosis = ""
    sub_tools_used = 0
    sub_substantive = 0  # v2.34.8
    try:
        from api.db.base import get_engine
        from api.db import queries as q
        async with get_engine().connect() as conn:
            op = await q.get_operation_by_session(conn, sub_session_id)
            if op:
                sub_final_answer = op.get("final_answer", "") or ""
                if "DIAGNOSIS:" in sub_final_answer:
                    sub_diagnosis = sub_final_answer.split(
                        "DIAGNOSIS:", 1)[1][:2000].strip()
                if op.get("status") in ("cancelled", "escalated", "capped"):
                    if terminal_status == "done":
                        terminal_status = op.get("status") or "cap_hit"
        try:
            async with get_engine().connect() as conn2:
                tcs = await q.get_tool_calls_for_operation(conn2, sub_operation_id)
                sub_tools_used = len(tcs or [])
                # v2.34.8: count substantive (non-META) tool calls for this sub
                for _tc in (tcs or []):
                    try:
                        _name = (_tc.get("tool_name") or "") if isinstance(_tc, dict) else ""
                    except Exception:
                        _name = ""
                    if _name and _name not in META_TOOLS:
                        sub_substantive += 1
        except Exception:
            sub_tools_used = 0
            sub_substantive = 0
    except Exception as _he:
        log.debug("sub-agent harvest failed: %s", _he)

    record_completion(
        sub_task_id=sub_session_id,
        terminal_status=terminal_status,
        final_answer=sub_final_answer,
        diagnosis=sub_diagnosis,
        tools_used=sub_tools_used,
        substantive_tool_calls=sub_substantive,
        error=err_msg,
    )

    # v2.34.14: compute harness guard signals for parent-side distrust check.
    # The parent harness will inject a distrust message on the next turn if
    # either the hallucination guard fired OR the fabrication detector fired.
    # Fabrication check runs here (post-hoc) against the sub-agent's actual
    # tool-call names.
    _actual_tool_names: list[str] = []
    try:
        from api.db.base import get_engine as _geng
        from api.db import queries as _q_tc
        async with _geng().connect() as _conn_tc:
            _tcs = await _q_tc.get_tool_calls_for_operation(_conn_tc, sub_operation_id)
        for _tc in (_tcs or []):
            _name = (_tc.get("tool_name") or "") if isinstance(_tc, dict) else ""
            if _name:
                _actual_tool_names.append(_name)
    except Exception:
        pass

    try:
        from api.agents.fabrication_detector import is_fabrication as _is_fab
        _min_cites = int(os.environ.get("AGENT_FABRICATION_MIN_CITES", "3"))
        _score_th = float(os.environ.get("AGENT_FABRICATION_SCORE_THRESHOLD", "0.5"))
        _fab_fired, _fab_detail = _is_fab(
            sub_final_answer or "",
            _actual_tool_names,
            min_cites=_min_cites,
            score_threshold=_score_th,
        )
    except Exception:
        _fab_fired, _fab_detail = False, {
            "score": 0.0, "cited": [], "actual": [], "fabricated": [],
        }

    _min_subst_req = MIN_SUBSTANTIVE_BY_TYPE.get(agent_type, 1)
    _halluc_guard_fired = sub_substantive < _min_subst_req

    try:
        await manager.broadcast({
            "type":            "subagent_done",
            "session_id":      sub_session_id,
            "parent_session_id": parent_session_id,
            "sub_task_id":     sub_session_id,
            "parent_task_id":  parent_session_id,
            "terminal_status": terminal_status,
            "final_answer":    sub_final_answer[:500],
            "tools_used":      sub_tools_used,
            "halluc_guard_fired":   _halluc_guard_fired,
            "fabrication_detected": bool(_fab_fired),
            "timestamp":       datetime.now(timezone.utc).isoformat(),
        })
    except Exception:
        pass

    return {
        "ok":              True,
        "sub_task_id":     sub_session_id,
        "terminal_status": terminal_status,
        "final_answer":    sub_final_answer,
        "diagnosis":       sub_diagnosis,
        "tools_used":      sub_tools_used,
        "error":           err_msg,
        "harness_guard":   {
            "halluc_guard_fired":   bool(_halluc_guard_fired),
            "halluc_guard_attempts": 0,  # not surfaced from sub loop yet
            "fabrication_detected": bool(_fab_fired),
            "fabrication_detail":   _fab_detail,
            "substantive_tool_calls": sub_substantive,
            "min_substantive_required": _min_subst_req,
        },
    }


async def _stream_agent(task: str, session_id: str, operation_id: str,
                        owner_user: str = "admin", parent_context: str = "",
                        parent_session_id: str = "",
                        force_external: bool = False):
    """Run the full agent loop, streaming every step to WebSocket clients."""
    from openai import OpenAI
    from api.agents.router import classify_task, filter_tools, get_prompt, detect_domain
    from api.agents.orchestrator import (
        build_step_plan, format_step_header, verdict_from_text,
        extract_structured_verdict, run_coordinator, should_use_coordinator,
    )
    from api.agents.pipeline import (
        build_system_prompt,
        run_preflight,
        broadcast_preflight,
        inject_tool_signatures,
        inject_capability_hint,
        inject_memory_history,
        inject_prior_attempts,
        inject_facts_block,
    )
    _t0 = time.monotonic()

    base_url = _lm_base()
    api_key  = _lm_key()

    # Classify task using first step intent for memory injection
    first_intent = classify_task(task)
    if first_intent == "ambiguous":
        first_intent = "action"

    # Base prompt + runbook injection (v2.35.4)
    system_prompt = build_system_prompt(task, first_intent)

    # v2.35.1 — preflight resolution (regex → keyword_db → optional LLM fallback).
    _preflight_result, _preflight_facts_block, _preflight_skills_block = (
        await run_preflight(task, first_intent, operation_id)
    )
    await broadcast_preflight(
        manager, session_id, operation_id,
        _preflight_result, _preflight_skills_block,
    )

    # v2.34.9: inject MCP tool signatures so the agent calls tools with exact kwargs
    system_prompt = inject_tool_signatures(
        system_prompt, first_intent, detect_domain(task),
    )

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

    # Domain-specific capability hint (e.g. available VM hosts for vm_exec)
    system_prompt = inject_capability_hint(system_prompt, task, first_intent)

    # Recent entity activity (changes + events) for known hosts in the task
    system_prompt = inject_memory_history(system_prompt, task, first_intent)

    # v2.32.3 / v2.34.1 — prior-attempt injection (investigate/execute only)
    system_prompt = inject_prior_attempts(system_prompt, task, first_intent)

    # Past outcomes + RAG + MuninnDB chunks + preflight facts (v2.35.1 / v2.42.3)
    system_prompt, boost_tools, _context_parts, _first_tool_hint = await inject_facts_block(
        system_prompt, task, first_intent,
        _preflight_facts_block, _preflight_skills_block,
    )
    if _first_tool_hint:
        await manager.send_line(
            "memory",
            f"[hint] first-tool suggestion: {_first_tool_hint}",
            status="ok", session_id=session_id,
        )
    if _context_parts:
        await manager.send_line(
            "memory",
            f"[context] {' + '.join(_context_parts)} injected into prompt",
            status="ok", session_id=session_id,
        )

    client = OpenAI(base_url=base_url, api_key=api_key)

    # v2.36.3 — complexity_prefilter: step 0, before any tool calls
    try:
        # Count prior failed attempts for this entity (v2.32.3 table)
        _prior_failed = 0
        _scope_entity = ""
        try:
            from api.db.agent_attempts import count_recent_failures_for_entity
            from api.db.infra_inventory import resolve_host
            for word in task.split():
                if len(word) < 4:
                    continue
                _entry = resolve_host(word)
                if _entry:
                    _scope_entity = _entry.get("label", word)
                    break
            if _scope_entity:
                _prior_failed = count_recent_failures_for_entity(_scope_entity, days=7)
        except Exception:
            pass

        # v2.38.7 — build context digest for force-external prerun so
        # Claude Sonnet has real infrastructure evidence to synthesise from.
        _prerun_ext_digest = ""
        if force_external:
            try:
                _prerun_ext_digest = _build_prerun_external_context(
                    task=task,
                    preflight_facts_block=_preflight_facts_block,
                )
            except Exception as _pec_e:
                log.debug("prerun external context build failed: %s", _pec_e)

        _prerun_synth = await _maybe_route_to_external_ai(
            session_id=session_id, operation_id=operation_id,
            task=task, agent_type=first_intent,
            messages=[{"role": "system", "content": system_prompt},
                      {"role": "user", "content": task}],
            tool_calls_made=0, tool_budget=16, diagnosis_emitted=False,
            consecutive_tool_failures=0,
            halluc_guard_exhausted=False, fabrication_detected_count=0,
            external_calls_this_op=0,
            scope_entity=_scope_entity,
            is_prerun=True,
            prior_failed_attempts_7d=_prior_failed,
            force=force_external,
            prerun_digest=_prerun_ext_digest,
        )
        if _prerun_synth:
            # REPLACE mode pre-run: skip the local agent entirely
            try:
                await logger_mod.set_operation_final_answer(session_id, _prerun_synth)
            except Exception:
                pass
            await manager.broadcast({
                "type": "done", "session_id": session_id,
                "agent_type": first_intent,
                "content": _prerun_synth, "status": "ok", "choices": [],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            # Jump straight to the finally-cleanup
            raise _PrerunShortCircuit()
    except _PrerunShortCircuit:
        return
    except Exception as _pre:
        log.debug("prerun external route check failed: %s", _pre)

    # Build orchestrator step plan
    steps = build_step_plan(task)
    prior_verdict = None

    # Broadcast agent start (using first step's intent for badge)
    await manager.broadcast({
        "type":         "agent_start",
        "agent_type":   first_intent,
        "session_id":   session_id,
        "operation_id": operation_id,
        "timestamp":    datetime.now(timezone.utc).isoformat(),
    })

    await manager.send_line("step", f"Agent started — task: {task}", status="ok", session_id=session_id)
    await manager.send_line("step", f"Model: {_lm_model()} | Agent: {_AGENT_LABEL.get(first_intent, 'Execute')}", status="ok", session_id=session_id)

    # Aggregate feedback across all steps
    all_tools_used: list = []
    all_tool_history: list = []  # v2.33.13: cross-step tool call log
    all_run_facts: dict = {}     # v2.35.2: in-run fact snapshot (across coordinator steps)
    any_fabrication_detected = False   # v2.35.2: any step fired fabrication detector
    _any_render_fired = False    # v2.36.9: any step called the render tool with output
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

        # v2.35.4 — runbook injection per step (honours runbookInjectionMode setting)
        try:
            from api.agents.router import maybe_inject_runbook as _mir_step
            step_system_prompt = _mir_step(step_system_prompt, step_task or task, step_agent_type)
        except Exception:
            pass

        # v2.34.9: inject MCP tool signatures for this step's allowlist
        try:
            from api.agents.router import allowlist_for as _aw, format_tool_signatures_section as _fsig
            _step_sig = _fsig(_aw(step_agent_type, step_domain or "general"))
            if _step_sig:
                step_system_prompt = step_system_prompt + "\n\n" + _step_sig + "\n"
        except Exception:
            pass

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
            parent_session_id=parent_session_id,
        )

        # Track plan approval across coordinator loop iterations
        if "plan_action" in step_result["tools_used"]:
            plan_approved_this_session = True

        all_tools_used.extend(step_result["tools_used"])
        all_tool_history.extend(step_result.get("tool_history", []))
        _step_run_facts = step_result.get("run_facts") or {}
        if isinstance(_step_run_facts, dict):
            all_run_facts.update(_step_run_facts)
        if step_result.get("fabrication_detected"):
            any_fabrication_detected = True
        if step_result.get("render_tool_calls", 0) > 0:
            _any_render_fired = True   # v2.36.9 — switch cleanup to prepend path
        agg_positive += step_result["positive_signals"]
        agg_negative += step_result["negative_signals"]
        agg_steps    += step_result["steps_taken"]
        agg_prompt_tokens     += step_result.get("prompt_tokens", 0)
        agg_completion_tokens += step_result.get("completion_tokens", 0)
        final_status  = step_result["final_status"]

        # ── Coordinator decision ───────────────────────────────────────────────
        prior_verdict = extract_structured_verdict(step_result["output"], step_info)
        prior_verdict["full_output"] = step_result.get("output", "")  # preserve for final_answer

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

        # Use the full step output for final_answer, not the 300-char verdict
        # summary. v2.45.33 — moved ABOVE record_attempt so the F821 NameError
        # in record_attempt's `if isinstance(last_reasoning, str): _summary =
        # last_reasoning[:500]` line stops being silently swallowed.
        last_reasoning = ""
        if prior_verdict:
            last_reasoning = prior_verdict.get("full_output") or prior_verdict.get("summary", "")

        # v2.32.3: Record attempt history for the detected entity
        try:
            from api.db.agent_attempts import record_attempt
            from api.db.infra_inventory import resolve_host
            from api.agents.router import detect_domain

            _rec_entity = None
            for word in task.split():
                if len(word) < 4:
                    continue
                entry = resolve_host(word)
                if entry:
                    _rec_entity = entry.get("label", word)
                    break
            if not _rec_entity:
                domain = detect_domain(task)
                if domain == "kafka":
                    _rec_entity = "kafka_cluster"
                elif domain == "swarm":
                    _rec_entity = "swarm_cluster"

            if _rec_entity:
                _seen = set()
                _dedup_tools = []
                for t in all_tools_used:
                    if t not in _seen:
                        _seen.add(t)
                        _dedup_tools.append(t)

                _summary = ""
                if isinstance(last_reasoning, str):
                    _summary = last_reasoning[:500]

                record_attempt(
                    entity_id=_rec_entity,
                    task_type=first_intent,
                    task_text=task[:500],
                    tools_used=_dedup_tools[:10],
                    outcome=final_status,
                    summary=_summary,
                    session_id=session_id,
                    operation_id=operation_id or "",
                )
        except Exception as _ae:
            log.debug("record_attempt failed: %s", _ae)

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

        # ── v2.33.13: contradiction detection ────────────────────────────────
        # Compare the draft final answer against the aggregated tool history.
        # If the agent is about to assert "nothing found" while a prior tool
        # call returned non-zero results, give it one more chance to reconcile.
        try:
            from api.agents.orchestrator import detect_contradictions
            contradictions = detect_contradictions(last_reasoning or "", all_tool_history)
        except Exception as _ce:
            log.debug("detect_contradictions failed: %s", _ce)
            contradictions = []

        if contradictions:
            _contra_summary = "\n".join(
                f"  - Step {c['step']}: {c['tool']}({c['args']}) returned "
                f"{c['nonzero_count']} results"
                for c in contradictions
            )
            try:
                await manager.broadcast({
                    "type":           "contradiction_detected",
                    "session_id":     session_id,
                    "contradictions": contradictions,
                    "timestamp":      datetime.now(timezone.utc).isoformat(),
                })
                await manager.send_line(
                    "step",
                    f"[contradiction] Draft conclusion negates "
                    f"{len(contradictions)} prior non-zero result(s) — reconciling",
                    status="warning", session_id=session_id,
                )
            except Exception as _be:
                log.debug("contradiction broadcast failed: %s", _be)

            # One reconciliation turn with the same LLM.
            _neg_snip = contradictions[0]["negative_claim_snippets"][0] \
                if contradictions[0].get("negative_claim_snippets") else ""
            _reconcile_messages = [
                {
                    "role": "system",
                    "content": (
                        "You are revising an infrastructure assistant's draft answer. "
                        "The draft contains a negative claim that contradicts earlier "
                        "tool results in the same task. Revise to match the evidence."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Original task: {task}\n\n"
                        f"Draft answer:\n{last_reasoning}\n\n"
                        f"HARNESS: Your draft claims '{_neg_snip}' but your tool "
                        f"history contradicts it:\n{_contra_summary}\n\n"
                        "Revise the answer. Either:\n"
                        "  (a) Acknowledge the earlier non-zero result and explain "
                        "why the final claim still holds (different window / filter).\n"
                        "  (b) Revise the conclusion to match the evidence.\n"
                        "Do not silently drop the earlier data. Plain text, "
                        "2-4 sentences."
                    ),
                },
            ]
            try:
                _rec_resp = client.chat.completions.create(
                    model=_lm_model(),
                    messages=_reconcile_messages,
                    tools=None,
                    temperature=0.3,
                    max_tokens=300,
                )
                _rec_text = (_rec_resp.choices[0].message.content or "").strip()
                if _rec_text:
                    last_reasoning = _rec_text
            except Exception as _re:
                log.debug("reconciliation synthesis failed: %s", _re)

            # Re-check after reconciliation; if unresolved, prepend a warning.
            try:
                contradictions_after = detect_contradictions(
                    last_reasoning or "", all_tool_history
                )
            except Exception:
                contradictions_after = []
            if contradictions_after:
                last_reasoning = (
                    f"[HARNESS WARNING: {len(contradictions_after)} unresolved "
                    "evidence contradiction(s). See step history.]\n\n"
                    + (last_reasoning or "")
                )

        if last_reasoning:
            try:
                if _any_render_fired:
                    # v2.36.9 — render tool appended table mid-run; prepend
                    # the agent's caption ABOVE the table so ordering is
                    # caption-then-table, not table-then-clobbered-by-caption.
                    await logger_mod.set_operation_final_answer_prepend(
                        session_id, last_reasoning,
                    )
                else:
                    await logger_mod.set_operation_final_answer(
                        session_id, last_reasoning,
                    )
            except Exception as _sfa_e:
                log.debug("final_answer write failed: %s", _sfa_e)

        # ── v2.35.2: agent_observation fact writer ───────────────────────────
        # Only successful + non-suspect runs are allowed to persist facts into
        # known_facts. Any failure mode (capped, escalated, failed, cancelled,
        # error, fabrication firing) is skipped and recorded on the metric.
        try:
            _facts_reason = None
            # v2.47.9 — skip agent_observation writes during test runs.
            # Tests must not poison known_facts_current; cross-test
            # contamination causes mem-on baseline drift over time.
            try:
                from api.routers.tests_api import test_run_active
                _is_test_run = test_run_active
            except Exception:
                _is_test_run = False

            if _is_test_run:
                _facts_reason = "skipped_test_run"
            elif final_status != "completed":
                _facts_reason = "skipped_nonterminal"
            elif any_fabrication_detected:
                _facts_reason = "skipped_fabrication"
            elif not all_run_facts:
                _facts_reason = None  # nothing to write — no metric

            if _facts_reason:
                try:
                    from api.metrics import AGENT_OBSERVATION_FACTS_WRITTEN_COUNTER
                    AGENT_OBSERVATION_FACTS_WRITTEN_COUNTER.labels(
                        wrote_or_skipped=_facts_reason,
                    ).inc()
                except Exception:
                    pass
            elif all_run_facts:
                try:
                    from mcp_server.tools.skills.storage import get_backend as _gb_fs
                    _max_rows = int(_gb_fs().get_setting("factInjectionMaxRows") or 40) * 2
                except Exception:
                    _max_rows = 80

                _facts_to_write: list[dict] = []
                for _fk, _info in all_run_facts.items():
                    if len(_facts_to_write) >= _max_rows:
                        break
                    _raw = _info.get("raw") or {}
                    _md = {
                        "operation_id": operation_id,
                        "via_tool":     _info.get("tool"),
                        "step":         _info.get("step"),
                    }
                    _raw_md = _raw.get("metadata") if isinstance(_raw, dict) else None
                    if isinstance(_raw_md, dict):
                        _md.update(_raw_md)
                    _facts_to_write.append({
                        "fact_key": _fk,
                        "source":   "agent_observation",
                        "value":    _info.get("value"),
                        "metadata": _md,
                    })

                _dropped = max(0, len(all_run_facts) - len(_facts_to_write))
                try:
                    from api.db.known_facts import batch_upsert_facts
                    _res = batch_upsert_facts(
                        _facts_to_write,
                        actor=f"agent:{(operation_id or '')[:8]}",
                    )
                    log.info(
                        "agent_observation facts: op=%s wrote=%s dropped=%d totals=%s",
                        (operation_id or "")[:8], len(_facts_to_write), _dropped, _res,
                    )
                    try:
                        from api.metrics import AGENT_OBSERVATION_FACTS_WRITTEN_COUNTER
                        AGENT_OBSERVATION_FACTS_WRITTEN_COUNTER.labels(
                            wrote_or_skipped="wrote",
                        ).inc(len(_facts_to_write))
                        if _dropped:
                            AGENT_OBSERVATION_FACTS_WRITTEN_COUNTER.labels(
                                wrote_or_skipped="skipped_cap",
                            ).inc(_dropped)
                    except Exception:
                        pass
                except Exception as _fw_e:
                    log.warning("agent_observation fact write failed: %s", _fw_e)
        except Exception as _af_e:
            log.debug("agent_observation writer top-level failed: %s", _af_e)
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
        # Emit Prometheus terminal-status + wall-time metrics
        try:
            _status_map = {
                "completed": "success",
                "escalated": "escalated",
                "capped": "budget_exhausted",
                "cancelled": "failed",
                "error": "failed",
                "failed": "failed",
            }
            _terminal = _status_map.get(final_status, "failed")
            AGENT_TASKS.labels(agent_type=first_intent, status=_terminal).inc()
            AGENT_WALL_SECONDS.labels(agent_type=first_intent).observe(time.monotonic() - _t0)
        except Exception:
            pass


@router.post("/run", response_model=RunResponse)
async def run_agent(req: RunRequest, background_tasks: BackgroundTasks,
                    user: str = Depends(get_current_user)):
    """Start an agent task. Streams output to ws://host:8000/ws/output."""
    session_id = req.session_id or str(uuid.uuid4())
    operation_id = await logger_mod.log_operation(
        session_id, req.task, owner_user=user, model_used=_lm_model(),
    )
    background_tasks.add_task(
        _stream_agent, req.task, session_id, operation_id, user,
        force_external=req.force_external,
    )
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


class PreflightClarifyRequest(BaseModel):
    session_id: str
    selected_entity_id: str | None = None
    refined_task: str | None = None


class PreflightCancelRequest(BaseModel):
    session_id: str


@router.post("/preflight/clarify")
async def preflight_clarify(req: PreflightClarifyRequest,
                             user: str = Depends(get_current_user)):
    """Resume an operation paused on preflight disambiguation.

    Body: {session_id, selected_entity_id?|refined_task?}.

    Echoes a `preflight_clarify` WS event the feed can react to and flips
    the operation status back to `running`. Counters are incremented via
    `record_disambiguation_outcome`.
    """
    if not req.selected_entity_id and not req.refined_task:
        raise HTTPException(400, "selected_entity_id or refined_task required")

    try:
        from api.db.base import get_engine as _pge
        from sqlalchemy import text as _pt
        async with _pge().begin() as _pconn:
            await _pconn.execute(
                _pt("UPDATE operations SET status='running' "
                    "WHERE session_id=:sid AND status='awaiting_clarification'"),
                {"sid": req.session_id},
            )
    except Exception as _e:
        log.debug("preflight_clarify op update failed: %s", _e)

    try:
        await manager.broadcast({
            "type": "preflight_clarify",
            "session_id": req.session_id,
            "selected_entity_id": req.selected_entity_id,
            "refined_task": req.refined_task,
            "actor": user,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    except Exception:
        pass

    try:
        from api.agents.preflight import record_disambiguation_outcome
        record_disambiguation_outcome("user_picked")
    except Exception:
        pass

    return {"status": "ok", "message": "Preflight clarified"}


@router.post("/preflight/cancel")
async def preflight_cancel(req: PreflightCancelRequest, user: str = Depends(get_current_user)):
    """Cancel an operation paused on preflight disambiguation."""
    try:
        from api.db.base import get_engine as _pge
        from sqlalchemy import text as _pt
        async with _pge().begin() as _pconn:
            await _pconn.execute(
                _pt("UPDATE operations SET status='cancelled', "
                    "final_answer='Preflight disambiguation cancelled by user' "
                    "WHERE session_id=:sid"),
                {"sid": req.session_id},
            )
    except Exception as _e:
        log.debug("preflight_cancel op update failed: %s", _e)
    try:
        from api.agents.preflight import record_disambiguation_outcome
        record_disambiguation_outcome("cancelled")
    except Exception:
        pass
    return {"status": "ok", "message": "Preflight cancelled"}


class ExternalConfirmRequest(BaseModel):
    session_id: str
    approved: bool


class ExternalConfirmCancelRequest(BaseModel):
    session_id: str


@router.post("/operations/{operation_id}/confirm-external")
async def confirm_external_ai(
    operation_id: str,
    req: ExternalConfirmRequest,
    user: str = Depends(get_current_user),
):
    """Resolve a pending external-AI confirmation prompt.

    v2.36.2 — operator approves or rejects the escalation. Router-decision
    rationale (rule_fired, reason) was broadcast to the GUI when the gate
    opened; this endpoint just closes it.
    """
    from api.agents.external_ai_confirmation import resolve_confirmation
    ok = resolve_confirmation(req.session_id, req.approved)
    if not ok:
        return {
            "status": "error",
            "message": f"No pending external-AI confirmation for session '{req.session_id}'",
        }

    # Flip DB status back to running / cancelled so the UI reflects reality
    # even before the agent loop writes its terminal row.
    try:
        from api.db.base import get_engine as _ge
        from sqlalchemy import text as _t
        new_status = "running" if req.approved else "cancelled"
        async with _ge().begin() as conn:
            await conn.execute(
                _t("UPDATE operations SET status=:st "
                   "WHERE session_id=:sid AND status='awaiting_external_ai_confirm'"),
                {"st": new_status, "sid": req.session_id},
            )
    except Exception as e:
        log.debug("confirm_external_ai DB update failed: %s", e)

    try:
        await manager.broadcast({
            "type": "external_ai_confirm_resolved",
            "session_id": req.session_id,
            "approved": req.approved,
            "actor": user,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    except Exception:
        pass

    try:
        from api.metrics import EXTERNAL_AI_CONFIRM_OUTCOME
        EXTERNAL_AI_CONFIRM_OUTCOME.labels(
            outcome="approved" if req.approved else "rejected",
        ).inc()
    except Exception:
        pass

    return {"status": "ok", "message": "approved" if req.approved else "rejected"}


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
    operation_id = await logger_mod.log_operation(
        session_id, req.task, owner_user=user, model_used=_lm_model(),
    )

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
