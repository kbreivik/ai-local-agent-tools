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
        6,
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
