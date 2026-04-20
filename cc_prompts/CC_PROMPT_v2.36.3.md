# CC PROMPT — v2.36.3 — External AI client + REPLACE mode wiring

## What this does

Actually calls Claude/OpenAI/Grok. Implements the REPLACE output mode
(external AI synthesises `final_answer` from evidence already gathered;
local agent does not continue after escalation). Wires v2.36.1 router +
v2.36.2 confirmation gate into the agent loop body.

Reuses wire-format shape from v2.35.21's `POST /test-external-ai`
endpoint — Claude uses `/v1/messages` with `x-api-key`; OpenAI and Grok
use `/v1/chat/completions` with Bearer. Adapter layer translates the
internal OpenAI-shape `messages[]` + `tool_calls[]` trace into each
provider's preferred format (Claude's tool format differs).

Writes `external_ai_calls` on every call. All existing gates (fabrication
detector, hallucination guard, forced_synthesis drift defence,
too_short/preamble_only rescue) fire on external output. On
rejected_by_gate: discard the external synthesis, run local
forced_synthesis instead, log the external row with
`outcome=rejected_by_gate`.

On external-AI failure (auth, network, timeout): halt with
`status=escalation_failed` + escalation banner. Silent fallback is
rejected by design (we want the product-degradation signal visible).

Version bump: 2.36.2 → 2.36.3.

**This is the largest prompt in the phase — plan to spend 30-60 minutes
on it. Work incrementally; commit after Change 1 passes tests before
continuing to Change 2.**

---

## Change 1 — `api/agents/external_ai_client.py` — new module

The provider-agnostic client. Given a RouterState-like context + the
existing OpenAI-shape `messages` + `tool_calls` history, produce a
synthesis string plus billing fields.

```python
"""External AI client — provider-agnostic wrapper for v2.36.3 REPLACE mode.

Calls Claude / OpenAI / Grok with a synthesis-only prompt (no tools, no
continuation). Returns the response text plus billing metadata.

Wire format reference: api/routers/settings.py::test_external_ai (v2.35.21).
Same URLs, same auth headers, same response-shape normalisation.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

log = logging.getLogger(__name__)


# ── Per-call price estimates (USD per 1M tokens) ─────────────────────────────
# Rough reference prices current as of spec time — operator should
# double-check their provider invoice. Stored here (not in Settings) because
# these are provider-announced prices, not operator preferences.
_TOKEN_PRICES: dict[tuple[str, str], tuple[float, float]] = {
    # (provider, model_prefix) → (input_per_1M, output_per_1M)
    ("claude", "claude-sonnet-4-6"):      (3.00, 15.00),
    ("claude", "claude-sonnet"):          (3.00, 15.00),
    ("claude", "claude-opus"):            (15.00, 75.00),
    ("claude", "claude-haiku"):           (0.80,  4.00),
    ("openai", "gpt-4o"):                 (5.00, 15.00),
    ("openai", "gpt-4"):                  (30.00, 60.00),
    ("openai", "gpt-4.1"):                (3.00, 12.00),
    ("openai", "o1"):                     (15.00, 60.00),
    ("grok",   "grok-2"):                 (2.00, 10.00),
    ("grok",   "grok-4"):                 (5.00, 15.00),
}


def _estimate_cost(
    provider: str, model: str,
    input_tokens: int | None, output_tokens: int | None,
) -> float | None:
    """Best-effort USD cost estimate. Returns None if model is unknown."""
    if input_tokens is None or output_tokens is None:
        return None
    # Match on longest prefix — claude-sonnet-4-6 > claude-sonnet > claude
    best_match = None
    best_len = 0
    for (p, prefix), price in _TOKEN_PRICES.items():
        if p != provider:
            continue
        if model.startswith(prefix) and len(prefix) > best_len:
            best_match = price
            best_len = len(prefix)
    if best_match is None:
        return None
    in_rate, out_rate = best_match
    return round(
        (input_tokens * in_rate + output_tokens * out_rate) / 1_000_000.0,
        4,
    )


# ── Error taxonomy ────────────────────────────────────────────────────────────
class ExternalAIError(Exception):
    """Base for all external-AI failures — caller pattern-matches on subclass."""
    outcome: str = "network_error"


class ExternalAIAuthError(ExternalAIError):
    outcome = "auth_error"


class ExternalAINetworkError(ExternalAIError):
    outcome = "network_error"


class ExternalAITimeoutError(ExternalAIError):
    outcome = "timeout"


@dataclass
class ExternalAIResponse:
    """Return shape of call_external_ai."""
    text: str
    provider: str
    model: str
    input_tokens: int | None
    output_tokens: int | None
    est_cost_usd: float | None
    latency_ms: int


# ── Message adapter ───────────────────────────────────────────────────────────
# The agent loop stores messages in OpenAI chat-completions shape:
#   [{role: system|user|assistant|tool, content: str, tool_calls?, tool_call_id?}]
#
# OpenAI and Grok accept this shape directly. Claude's /v1/messages endpoint
# uses a subtly different shape for multi-turn tool use:
#   [{role: user|assistant, content: str | list[block]}] where each block is
#   {type: text|tool_use|tool_result, ...}
#
# For REPLACE mode we never ask the external model to CALL tools — we only ask
# it to synthesise from tool results the local agent has already produced.
# That simplifies the adapter: we flatten everything into text.

def _flatten_openai_messages_to_text(
    messages: list[dict], max_chars: int = 12000,
) -> str:
    """Convert OpenAI-shape history into a single prose block for synthesis."""
    parts: list[str] = []
    for m in messages:
        role = (m.get("role") or "").lower()
        content = m.get("content") or ""
        if role == "system":
            parts.append(f"[SYSTEM]\n{content}")
        elif role == "user":
            parts.append(f"[USER]\n{content}")
        elif role == "assistant":
            if content:
                parts.append(f"[ASSISTANT]\n{content}")
            # Surface any tool calls as structured text
            tool_calls = m.get("tool_calls") or []
            for tc in tool_calls:
                fn = (tc.get("function") or {}) if isinstance(tc, dict) else {}
                name = fn.get("name") or "?"
                args = fn.get("arguments") or "{}"
                if isinstance(args, str) and len(args) > 400:
                    args = args[:400] + "..."
                parts.append(f"[TOOL CALL] {name}({args})")
        elif role == "tool":
            if isinstance(content, str) and len(content) > 1200:
                content = content[:1200] + "..."
            parts.append(f"[TOOL RESULT]\n{content}")

    text = "\n\n".join(parts)
    if len(text) > max_chars:
        # Keep the tail (most recent context) — truncate from the front.
        text = "[... history truncated ...]\n\n" + text[-max_chars:]
    return text


def _build_synthesis_prompt(
    task: str, agent_type: str, context_text: str, digest: str | None,
) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) for the synthesis-only call."""
    system = (
        "You are a senior infrastructure operator synthesising a FINAL ANSWER "
        "from evidence gathered by a less-capable local agent. Your output "
        "WILL be shown to the operator as-is — no follow-up, no tool calls, "
        "no questions.\n\n"
        "Produce output in this EXACT structure (plain text, no markdown "
        "headers, no code fences):\n\n"
        "STATUS: (HEALTHY | DEGRADED | CRITICAL | UNRESOLVED)\n\n"
        "EVIDENCE:\n"
        "- (bullet per concrete finding: tool → observed value)\n\n"
        "ROOT CAUSE: (one specific sentence)\n\n"
        "NEXT STEPS:\n"
        "1. (specific actionable step)\n"
        "2. ...\n\n"
        "Use only the evidence in the CONTEXT below. DO NOT invent container "
        "IDs, IPs, hostnames, or tool output. If the evidence is insufficient "
        "to reach a root cause, state UNRESOLVED and list what's missing."
    )
    user_parts = [
        f"TASK: {task}\n",
        f"AGENT TYPE: {agent_type}\n",
    ]
    if digest:
        user_parts.append(f"\nRUN DIGEST:\n{digest}\n")
    user_parts.append(f"\nCONTEXT (local agent's message history):\n{context_text}")
    return system, "\n".join(user_parts)


# ── Provider dispatch ─────────────────────────────────────────────────────────

async def _call_claude(
    api_key: str, model: str, system: str, user: str, timeout_s: float,
) -> ExternalAIResponse:
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": 1500,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as c:
            r = await c.post(url, json=payload, headers=headers)
    except httpx.TimeoutException as e:
        raise ExternalAITimeoutError(f"Claude timed out after {timeout_s}s") from e
    except httpx.HTTPError as e:
        raise ExternalAINetworkError(f"Claude network error: {e!s}") from e
    latency_ms = int((time.monotonic() - t0) * 1000)

    if r.status_code in (401, 403):
        raise ExternalAIAuthError(f"Claude auth failed (HTTP {r.status_code})")
    if r.status_code >= 400:
        msg = f"Claude HTTP {r.status_code}"
        try:
            err = r.json().get("error")
            if isinstance(err, dict):
                msg = err.get("message", msg)
        except Exception:
            pass
        raise ExternalAINetworkError(msg)

    try:
        data = r.json()
    except Exception as e:
        raise ExternalAINetworkError(f"Claude returned non-JSON: {e!s}") from e

    # Claude shape: {content: [{type:'text', text:'...'}], usage: {...}}
    text = ""
    for block in data.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            text += block.get("text", "")
    usage = data.get("usage") or {}
    in_tok = usage.get("input_tokens")
    out_tok = usage.get("output_tokens")
    served_model = data.get("model") or model

    return ExternalAIResponse(
        text=text.strip(),
        provider="claude",
        model=served_model,
        input_tokens=in_tok,
        output_tokens=out_tok,
        est_cost_usd=_estimate_cost("claude", served_model, in_tok, out_tok),
        latency_ms=latency_ms,
    )


async def _call_openai_compatible(
    provider: str, base_url: str, api_key: str, model: str,
    system: str, user: str, timeout_s: float,
) -> ExternalAIResponse:
    """Shared Bearer-auth /v1/chat/completions handler for OpenAI + Grok."""
    url = f"{base_url}/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": 1500,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.3,
    }
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as c:
            r = await c.post(url, json=payload, headers=headers)
    except httpx.TimeoutException as e:
        raise ExternalAITimeoutError(f"{provider} timed out after {timeout_s}s") from e
    except httpx.HTTPError as e:
        raise ExternalAINetworkError(f"{provider} network error: {e!s}") from e
    latency_ms = int((time.monotonic() - t0) * 1000)

    if r.status_code in (401, 403):
        raise ExternalAIAuthError(f"{provider} auth failed (HTTP {r.status_code})")
    if r.status_code >= 400:
        msg = f"{provider} HTTP {r.status_code}"
        try:
            err = r.json().get("error")
            if isinstance(err, dict):
                msg = err.get("message", msg)
            elif isinstance(err, str):
                msg = err
        except Exception:
            pass
        raise ExternalAINetworkError(msg)

    try:
        data = r.json()
    except Exception as e:
        raise ExternalAINetworkError(f"{provider} returned non-JSON: {e!s}") from e

    text = ""
    try:
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
    except Exception:
        text = ""
    usage = data.get("usage") or {}
    in_tok = usage.get("prompt_tokens")
    out_tok = usage.get("completion_tokens")
    served_model = data.get("model") or model

    return ExternalAIResponse(
        text=text.strip(),
        provider=provider,
        model=served_model,
        input_tokens=in_tok,
        output_tokens=out_tok,
        est_cost_usd=_estimate_cost(provider, served_model, in_tok, out_tok),
        latency_ms=latency_ms,
    )


async def call_external_ai(
    *,
    provider: str,
    api_key: str,
    model: str,
    system: str,
    user: str,
    timeout_s: float = 45.0,
) -> ExternalAIResponse:
    """Single-shot synthesis call. Raises ExternalAI* on failure.

    Caller is responsible for reading Settings + handing the right api_key.
    """
    provider = (provider or "").strip().lower()
    if provider == "claude":
        return await _call_claude(api_key, model, system, user, timeout_s)
    elif provider == "openai":
        return await _call_openai_compatible(
            "openai", "https://api.openai.com", api_key, model,
            system, user, timeout_s,
        )
    elif provider == "grok":
        return await _call_openai_compatible(
            "grok", "https://api.x.ai", api_key, model,
            system, user, timeout_s,
        )
    else:
        raise ExternalAIAuthError(f"Unknown provider: {provider!r}")


# ── Public entry-point used by the agent loop ─────────────────────────────────

async def synthesize_replace(
    *,
    task: str,
    agent_type: str,
    messages: list[dict],
    digest: str | None = None,
    context_max_chars: int = 12000,
    timeout_s: float = 45.0,
) -> ExternalAIResponse:
    """High-level helper: reads Settings, builds prompt, calls provider.

    Raises ExternalAI* on failure. Caller wraps this in try/except to
    produce the halt-on-failure behaviour.
    """
    from mcp_server.tools.skills.storage import get_backend
    backend = get_backend()

    provider = (backend.get_setting("externalProvider") or "claude").strip().lower()
    api_key = (backend.get_setting("externalApiKey") or "").strip()
    model = (backend.get_setting("externalModel") or "").strip()

    if not api_key:
        raise ExternalAIAuthError("externalApiKey is not set")
    if not model:
        raise ExternalAIAuthError("externalModel is not set")

    context_text = _flatten_openai_messages_to_text(messages, max_chars=context_max_chars)
    system, user = _build_synthesis_prompt(task, agent_type, context_text, digest)

    result = await call_external_ai(
        provider=provider, api_key=api_key, model=model,
        system=system, user=user, timeout_s=timeout_s,
    )

    # Token metrics
    try:
        from api.metrics import (
            EXTERNAL_AI_TOKENS, EXTERNAL_AI_LATENCY,
        )
        if result.input_tokens:
            EXTERNAL_AI_TOKENS.labels(
                provider=result.provider, direction="input",
            ).inc(result.input_tokens)
        if result.output_tokens:
            EXTERNAL_AI_TOKENS.labels(
                provider=result.provider, direction="output",
            ).inc(result.output_tokens)
        EXTERNAL_AI_LATENCY.labels(
            provider=result.provider,
        ).observe(result.latency_ms / 1000.0)
    except Exception:
        pass

    return result
```

---

## Change 2 — `api/routers/agent.py` — wire router + confirmation + client into loop

This is the invasive one. Add a helper `_maybe_route_to_external_ai`
that's called at the two seams we already identified:

- **Pre-run (step 0)**: before the main while loop starts, check if
  `complexity_prefilter` fires.
- **Terminal happy/cap path**: after gates fire or after budget cap, check
  if `budget_exhaustion` / `gate_failure` / `consecutive_failures` /
  `prior_attempts` fires.

Add this helper just above `_run_single_agent_step`:

```python
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
) -> str | None:
    """Run the v2.36.1 router. If it fires, gate on v2.36.2 confirmation and
    call the v2.36.3 external AI. Return the synthesis text on success,
    None on no-op, or raise a sentinel-failure string via ExternalAIError.

    Caller treats a non-None return as the final_answer (REPLACE mode).
    """
    from api.agents.external_router import (
        should_escalate_to_external_ai, record_decision, RouterState,
    )
    from mcp_server.tools.skills.storage import get_backend

    try:
        _cap = int(get_backend().get_setting("routeMaxExternalCallsPerOp") or 3)
    except Exception:
        _cap = 3

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

    # v2.36.3 only implements REPLACE. Other modes deferred to v2.36.5+.
    if output_mode != "replace":
        await manager.send_line(
            "step",
            f"[external-ai] output mode {output_mode!r} not implemented — "
            f"falling back to 'replace'",
            status="warning", session_id=session_id,
        )
        output_mode = "replace"

    # Confirmation gate
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
            messages=messages, digest=digest_text,
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
```

**Call site 1 — step 0 complexity_prefilter in `_stream_agent`:**

Find `client = OpenAI(base_url=base_url, api_key=api_key)` in `_stream_agent`.
Immediately AFTER that line, add (within the `try` block guarding the loop):

```python
    # v2.36.3 — complexity_prefilter: step 0, before any tool calls
    try:
        # Count prior failed attempts for this entity (v2.32.3 table)
        _prior_failed = 0
        try:
            from api.db.agent_attempts import count_recent_failures_for_entity
            _scope_entity = ""
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

        _prerun_synth = await _maybe_route_to_external_ai(
            session_id=session_id, operation_id=operation_id,
            task=task, agent_type=first_intent,
            messages=[{"role": "system", "content": system_prompt},
                      {"role": "user", "content": task}],
            tool_calls_made=0, tool_budget=16, diagnosis_emitted=False,
            consecutive_tool_failures=0,
            halluc_guard_exhausted=False, fabrication_detected_count=0,
            external_calls_this_op=0,
            scope_entity=_scope_entity if '_scope_entity' in dir() else "",
            is_prerun=True,
            prior_failed_attempts_7d=_prior_failed,
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
            final_status = "completed"
            # Jump straight to the finally-cleanup
            raise _PrerunShortCircuit()
    except _PrerunShortCircuit:
        pass
    except Exception as _pre:
        log.debug("prerun external route check failed: %s", _pre)
```

Declare the sentinel at module level:

```python
class _PrerunShortCircuit(Exception):
    pass
```

And `count_recent_failures_for_entity` needs adding to
`api/db/agent_attempts.py`. Add at the bottom of that file:

```python
def count_recent_failures_for_entity(entity_id: str, days: int = 7) -> int:
    """Count agent_attempts rows for this entity with outcome != 'completed'
    in the last `days` days. Used by v2.36.3 complexity_prefilter router rule.
    Returns 0 on any error (never raises)."""
    if not entity_id:
        return 0
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            """SELECT COUNT(*) FROM agent_attempts
               WHERE entity_id = %s
               AND outcome <> 'completed'
               AND created_at > NOW() - INTERVAL '%s days'""",
            (entity_id, int(days)),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        return int(row[0] or 0) if row else 0
    except Exception:
        return 0
```

**Call site 2 — terminal path in `_run_single_agent_step`:**

Find the block where `final_status = "capped"` is set (after the
`if len(tools_used_names) >= _tool_budget:` check). AFTER the existing
`run_forced_synthesis` call but BEFORE `if is_final_step:`, add:

```python
                # v2.36.3 — budget_exhaustion rule check
                try:
                    _router_synth = await _maybe_route_to_external_ai(
                        session_id=session_id,
                        operation_id=operation_id,
                        task=task,
                        agent_type=agent_type,
                        messages=messages,
                        tool_calls_made=len(tools_used_names),
                        tool_budget=_tool_budget,
                        diagnosis_emitted="DIAGNOSIS:" in (last_reasoning or ""),
                        consecutive_tool_failures=_tool_failures,
                        halluc_guard_exhausted=(_halluc_guard_attempts >= _halluc_guard_max),
                        fabrication_detected_count=(1 if _fabrication_detected_once else 0),
                        external_calls_this_op=0,
                        scope_entity=parent_session_id or "",
                        is_prerun=False,
                        prior_failed_attempts_7d=0,
                    )
                    if _router_synth:
                        last_reasoning = _router_synth
                except Exception as _re:
                    # Halt-on-failure: mark status and fall through
                    log.warning("external AI routing failed: %s", _re)
                    final_status = "escalation_failed"
```

**Call site 3 — gate_failure (hallucination/fabrication exhausted):**

Find the `HALLUC_GUARD_EXHAUSTED_COUNTER` label increment block. Both
branches (hallucination and fabrication exhaustion) set `final_status =
"failed"` before the `break`. Before each `break`, add the same router
check — but with `halluc_guard_exhausted=True` and the appropriate
`fabrication_detected_count`. If the router returns a synthesis, REPLACE
`last_reasoning` before the `break`.

This is the pattern (apply to both HALLUC_GUARD_EXHAUSTED branches):

```python
                        # v2.36.3 — gate_failure router rule
                        try:
                            _router_synth = await _maybe_route_to_external_ai(
                                session_id=session_id,
                                operation_id=operation_id,
                                task=task,
                                agent_type=agent_type,
                                messages=messages,
                                tool_calls_made=len(tools_used_names),
                                tool_budget=_tool_budget,
                                diagnosis_emitted=False,
                                consecutive_tool_failures=_tool_failures,
                                halluc_guard_exhausted=True,
                                fabrication_detected_count=(2 if _fabrication_detected_once else 0),
                                external_calls_this_op=0,
                                scope_entity=parent_session_id or "",
                                is_prerun=False,
                            )
                            if _router_synth:
                                last_reasoning = _router_synth
                                final_status = "completed"
                        except Exception as _re:
                            log.warning("external AI routing on gate failure: %s", _re)
                            final_status = "escalation_failed"
```

---

## Change 3 — `tests/test_external_ai_client.py`

```python
"""v2.36.3 — External AI client tests. httpx mocked, no network."""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock


def _mk_resp(status: int, body: dict):
    r = MagicMock()
    r.status_code = status
    r.json = MagicMock(return_value=body)
    return r


@pytest.mark.asyncio
async def test_claude_success_normalises_tokens():
    from api.agents.external_ai_client import _call_claude
    with patch("httpx.AsyncClient") as MockClient:
        ctx = AsyncMock()
        ctx.post = AsyncMock(return_value=_mk_resp(200, {
            "model": "claude-sonnet-4-6",
            "content": [{"type": "text", "text": "STATUS: HEALTHY"}],
            "usage": {"input_tokens": 100, "output_tokens": 50},
        }))
        MockClient.return_value.__aenter__.return_value = ctx
        result = await _call_claude(
            "sk-x", "claude-sonnet-4-6",
            "system", "user", 10.0,
        )
    assert result.text == "STATUS: HEALTHY"
    assert result.provider == "claude"
    assert result.input_tokens == 100
    assert result.output_tokens == 50
    # cost: (100*3 + 50*15) / 1M = 1050/1M = 0.00105
    assert abs(result.est_cost_usd - 0.00105) < 1e-5


@pytest.mark.asyncio
async def test_claude_401_raises_auth_error():
    from api.agents.external_ai_client import _call_claude, ExternalAIAuthError
    with patch("httpx.AsyncClient") as MockClient:
        ctx = AsyncMock()
        ctx.post = AsyncMock(return_value=_mk_resp(401, {
            "error": {"message": "invalid x-api-key"},
        }))
        MockClient.return_value.__aenter__.return_value = ctx
        with pytest.raises(ExternalAIAuthError):
            await _call_claude("sk-bad", "claude-sonnet-4-6", "s", "u", 10.0)


@pytest.mark.asyncio
async def test_openai_uses_bearer():
    from api.agents.external_ai_client import _call_openai_compatible
    with patch("httpx.AsyncClient") as MockClient:
        ctx = AsyncMock()
        ctx.post = AsyncMock(return_value=_mk_resp(200, {
            "model": "gpt-4o",
            "choices": [{"message": {"content": "STATUS: HEALTHY"}}],
            "usage": {"prompt_tokens": 80, "completion_tokens": 40},
        }))
        MockClient.return_value.__aenter__.return_value = ctx
        result = await _call_openai_compatible(
            "openai", "https://api.openai.com", "sk-openai",
            "gpt-4o", "s", "u", 10.0,
        )
        assert ctx.post.call_args.kwargs["headers"]["Authorization"] == "Bearer sk-openai"
    assert result.provider == "openai"
    # OpenAI token-field names get normalised to input/output
    assert result.input_tokens == 80
    assert result.output_tokens == 40


@pytest.mark.asyncio
async def test_grok_hits_xai_base():
    from api.agents.external_ai_client import _call_openai_compatible
    with patch("httpx.AsyncClient") as MockClient:
        ctx = AsyncMock()
        ctx.post = AsyncMock(return_value=_mk_resp(200, {
            "model": "grok-2-latest", "choices": [{"message": {"content": "ok"}}],
        }))
        MockClient.return_value.__aenter__.return_value = ctx
        result = await _call_openai_compatible(
            "grok", "https://api.x.ai", "xai-key",
            "grok-2-latest", "s", "u", 10.0,
        )
        assert ctx.post.call_args.args[0] == "https://api.x.ai/v1/chat/completions"
    assert result.provider == "grok"


@pytest.mark.asyncio
async def test_timeout_raises_timeout_error():
    import httpx
    from api.agents.external_ai_client import _call_claude, ExternalAITimeoutError
    with patch("httpx.AsyncClient") as MockClient:
        ctx = AsyncMock()
        ctx.post = AsyncMock(side_effect=httpx.TimeoutException("slow"))
        MockClient.return_value.__aenter__.return_value = ctx
        with pytest.raises(ExternalAITimeoutError):
            await _call_claude("sk-x", "claude-sonnet-4-6", "s", "u", 1.0)


def test_flatten_messages_preserves_tool_calls():
    from api.agents.external_ai_client import _flatten_openai_messages_to_text
    messages = [
        {"role": "system", "content": "You are an agent"},
        {"role": "user", "content": "check broker-3"},
        {"role": "assistant", "content": "checking",
         "tool_calls": [{"function": {"name": "kafka_broker_status",
                                      "arguments": '{"broker":3}'}}]},
        {"role": "tool", "tool_call_id": "c1",
         "content": '{"status":"offline"}'},
    ]
    out = _flatten_openai_messages_to_text(messages)
    assert "[SYSTEM]" in out
    assert "[USER]" in out
    assert "[TOOL CALL] kafka_broker_status" in out
    assert "[TOOL RESULT]" in out
    assert '"status":"offline"' in out


def test_flatten_truncates_long_histories():
    from api.agents.external_ai_client import _flatten_openai_messages_to_text
    big = [{"role": "user", "content": "x" * 20000}]
    out = _flatten_openai_messages_to_text(big, max_chars=5000)
    assert len(out) < 6000
    assert "history truncated" in out


def test_cost_estimate_uses_longest_prefix_match():
    from api.agents.external_ai_client import _estimate_cost
    # claude-sonnet-4-6 should match (claude, claude-sonnet-4-6) not (claude, claude-sonnet)
    c = _estimate_cost("claude", "claude-sonnet-4-6", 1000, 500)
    # Both prefixes have the same rate so equal result — verifies no crash
    assert c is not None and c > 0


def test_cost_estimate_returns_none_for_unknown_model():
    from api.agents.external_ai_client import _estimate_cost
    assert _estimate_cost("claude", "mystery-model-xyz", 1000, 500) is None
```

---

## Change 4 — `VERSION`

```
2.36.3
```

---

## Verify

```bash
pytest tests/test_external_ai_client.py tests/test_external_router.py \
       tests/test_external_ai_confirmation.py -v
```

---

## Commit

```bash
git add -A
git commit -m "feat(agents): v2.36.3 External AI client + REPLACE mode wiring

The subsystem is live. Router decisions now actually result in Claude/OpenAI/
Grok calls when the operator approves. REPLACE mode only — external AI
synthesises final_answer from local evidence, local agent does not continue.

New module api/agents/external_ai_client.py:
- Provider dispatch: Claude via /v1/messages with x-api-key; OpenAI and Grok
  via /v1/chat/completions with Bearer (Grok against https://api.x.ai base).
- OpenAI-shape message history flattened to prose for the synthesis call.
  No tool-calling from external AI in REPLACE mode — it only synthesises.
- Per-provider error taxonomy: ExternalAIAuthError (401/403),
  ExternalAITimeoutError, ExternalAINetworkError (everything else).
- Token normalisation: Claude's {input_tokens, output_tokens} and OpenAI/Grok's
  {prompt_tokens, completion_tokens} collapse into the same response fields.
- Cost estimate: _TOKEN_PRICES table, longest-prefix match so
  claude-sonnet-4-6 > claude-sonnet > claude. Returns None for unknown models.

Agent loop wiring in api/routers/agent.py via new async helper
_maybe_route_to_external_ai:
- Step 0 (pre-run, is_prerun=True): complexity_prefilter only. If fires and
  REPLACE mode produces a synthesis, skip the local agent entirely via new
  _PrerunShortCircuit sentinel.
- Budget-cap path: budget_exhaustion rule check after run_forced_synthesis.
- Hallucination/fabrication exhaustion path: gate_failure rule check before
  the failed-status break.
- Each seam threads the full RouterState — tool_calls_made, tool_budget,
  halluc_guard_exhausted, fabrication_detected_count, etc.
- Confirmation gate (wait_for_external_ai_confirmation from v2.36.2) runs
  between router-decision and client-call. Timeout→cancelled.
- Halt-on-failure: ExternalAIError raised → final_status='escalation_failed',
  written to escalation banner via record_escalation. Silent fallback rejected.

Rejected-by-gate path (fabrication detector or too-short/preamble-only rescue
fires on external output): discard the external synthesis, log
outcome='rejected_by_gate' on external_ai_calls, return None so the caller
runs local forced_synthesis instead. Kent paid for the call whether it was
good or not; the DB reflects truth.

Successful synthesis gets [EXTERNAL: provider/model] prefix for operator
visibility and a step_index=99999 row in agent_llm_traces with provider set,
so the v2.36.4 Trace viewer can render it with provenance.

New api/db/agent_attempts.py helper count_recent_failures_for_entity powers
the complexity_prefilter rule (pre-run check uses 7-day window).

9 regression tests in tests/test_external_ai_client.py cover every provider,
auth error, timeout, message flattening, truncation, cost estimate, and
prefix-match behaviour. All tests use mocked httpx — no network, <1s."
git push origin main
```

---

## Deploy + smoke

```bash
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```

End-to-end smoke (requires externalApiKey set to a real Claude key):

1. Set `externalRoutingMode=auto` in Settings via the UI's "Save settings"
   (no UI for this yet — v2.36.4; update via curl):
   ```bash
   curl -sS -X POST http://192.168.199.10:8000/api/settings \
     -H 'Content-Type: application/json' \
     -H "Cookie: hp1_auth_cookie=$(cat ~/.hp1_cookie)" \
     -d '{"key":"externalRoutingMode","value":"auto"}'
   ```
2. Start an investigate task you know loops to budget cap (e.g. an
   over-scoped "Investigate all Kafka brokers" template).
3. When the budget cap hits, the WebSocket should emit
   `external_ai_confirm_pending` with rule=budget_exhaustion. Until
   v2.36.4 lands, approve via:
   ```bash
   curl -sS -X POST \
     http://192.168.199.10:8000/api/agent/operations/{operation_id}/confirm-external \
     -H 'Content-Type: application/json' \
     -H "Cookie: hp1_auth_cookie=$(cat ~/.hp1_cookie)" \
     -d '{"session_id":"{session_id}","approved":true}'
   ```
4. Expect: `external_ai_call_start` → 30-60s delay → `external_ai_call_done`
   → final_answer prefixed `[EXTERNAL: claude/claude-sonnet-4-6]`.
5. Verify the row landed:
   ```bash
   psql -c "SELECT provider, model, rule_fired, outcome, latency_ms,
     input_tokens, output_tokens, est_cost_usd
     FROM external_ai_calls ORDER BY created_at DESC LIMIT 5;"
   ```
6. Verify the trace has provider set:
   ```bash
   psql -c "SELECT step_index, provider, model FROM agent_llm_traces
     WHERE operation_id = '{operation_id}' ORDER BY step_index;"
   ```
   Last row should be `step_index=99999, provider='claude'`.

Revert `externalRoutingMode=off` after smoke.

---

## Scope guard — do NOT touch

- Output modes other than REPLACE — ADVISE/TAKEOVER/ADVISE_THEN_TAKEOVER
  deferred to v2.36.5+. The helper falls back to REPLACE with a warning.
- `SETTINGS_KEYS` registry — all new keys shipped in v2.36.0.
- UI — the confirmation modal and Triggers subsection land in v2.36.4.
  Until v2.36.4 lands, operators use curl to approve (as documented above).
- `_TOKEN_PRICES` is a minimal reference table — not meant to be
  authoritative billing. v2.36.5+ can introduce a Settings-driven override.
- Sub-agent integration — sub-agents share the parent's router state today.
  Full sub-agent-isolated external routing is out of scope.
