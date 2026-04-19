"""Forced-synthesis step for agent runs that hit a hard cap (v2.34.17).

When the loop exits because of budget / wall-clock / token-cap / consecutive
failures, the model never gets a chance to produce a ``final_answer`` from
the evidence it has already collected. Without this step, the operator sees
``status=capped, final_answer=null`` and the run is effectively lost even
though the smoking gun may have been found on tool-call 7 of 16.

This module builds a synthesis-only message, calls the LLM with ``tools=None``
(so the model physically cannot make another tool call), runs the fabrication
detector on the output, and returns the text so the caller can persist it as
``final_answer``. Counters are incremented in ``api.metrics``.

The harness message starts with ``[harness]`` and contains the literal
string ``budget-cap`` (or ``wall-clock`` / ``token-cap`` etc.) so the
gate-fired detector can count it alongside the other harness gates.

v2.35.10 adds an XML-drift defense layer: Qwen3-Coder-Next occasionally
emits tool calls as XML text (<tool_call><function=...>...) even when no
tools are available. Outputs are screened; a retry is made with cleaned
history, and if that also drifts, a programmatic fallback built from the
tool-call history is returned.
"""
from __future__ import annotations

import logging
import re as _re
from typing import Iterable

log = logging.getLogger(__name__)


_REASON_LABELS = {
    "budget_cap":        "tool-call budget-cap",
    "wall_clock":        "wall-clock cap",
    "token_cap":         "token cap",
    "destructive_cap":   "destructive-call cap",
    "tool_failures":     "consecutive-tool-failure cap",
}


# XML-drift detection: model emits tool calls as <tool_call>... or
# <function=...>... or raw ```json fences around JSON args. Any of these
# in the first 200 chars of output means synthesis failed.
_DRIFT_PREFIX_RE = _re.compile(
    r"^\s*(?:<tool_call>|<function[=\s]|<parameter[=\s]|```json\b)",
    _re.IGNORECASE,
)


# Module-level constant — used by both _strip_xml_drift_from_messages
# and _is_drift so the placeholder can never be echoed back as valid
# synthesis output.
_DRIFT_STRIPPED_PLACEHOLDER = "[__FORCED_SYNTHESIS_STRIPPED_DRIFT_PLACEHOLDER__]"


def _xml_density(text: str) -> float:
    """Fraction of characters inside balanced ``<...>`` tag pairs.

    >0.30 means the text is mostly markup, not prose. Only balanced pairs
    are counted so a stray ``<`` in prose (e.g. ``ISR was < expected``)
    doesn't get treated as an unclosed tag running to end-of-string.
    """
    if not text:
        return 0.0
    total = len(text)
    in_tag = 0
    depth = 0
    open_start = -1
    for i, ch in enumerate(text):
        if ch == "<":
            if depth == 0:
                open_start = i
            depth += 1
        elif ch == ">" and depth > 0:
            depth -= 1
            if depth == 0 and open_start >= 0:
                in_tag += (i - open_start + 1)
                open_start = -1
    return in_tag / total if total else 0.0


def _is_drift(text: str, *, density_threshold: float = 0.30) -> tuple[bool, str]:
    """Return (is_drift, reason) for a synthesis candidate."""
    if not text:
        return True, "empty"

    # v2.35.11: defend against the model echoing the stripped-drift
    # placeholder from cleaned retry context. If the output IS the
    # placeholder or substantially contains it (>50% of output), treat
    # as drift so the programmatic fallback fires.
    stripped = text.strip()
    if stripped == _DRIFT_STRIPPED_PLACEHOLDER:
        return True, "placeholder_echo"
    if (_DRIFT_STRIPPED_PLACEHOLDER in text
            and len(_DRIFT_STRIPPED_PLACEHOLDER) / max(len(text), 1) > 0.5):
        return True, "placeholder_echo"

    if _DRIFT_PREFIX_RE.match(text):
        return True, "tool_call_prefix"
    if _xml_density(text) > density_threshold:
        return True, f"xml_density>{density_threshold:.2f}"
    # Also catch "<parameter=host>" anywhere in the first 500 chars
    if "<parameter=" in text[:500] or "<function=" in text[:500]:
        return True, "parameter_tag_in_head"
    return False, ""


def build_harness_message(reason: str, tool_count: int, budget: int) -> str:
    """Build the synthesis-only harness message for a given loop-exit reason."""
    label = _REASON_LABELS.get(reason, reason)
    return (
        f"[harness] You have hit the {label} "
        f"({tool_count}/{budget} tools used). No more tool calls allowed. "
        f"Produce your final_answer right now from the evidence you have "
        f"already gathered. Format: EVIDENCE: (bullets citing actual tool "
        f"results) / ROOT CAUSE: (if you can conclude) or UNRESOLVED: "
        f"(what would unblock you) / NEXT STEPS: (what a human should do). "
        f"Cite only tools that actually ran. Do NOT fabricate.\n\n"
        f"CRITICAL FORMAT RULE: Output PLAIN TEXT ONLY. Do NOT use any of "
        f"these syntaxes: <tool_call>, <function=...>, <parameter=...>, "
        f"```json ... ```, or any XML/JSON tool-call format. If you find "
        f"yourself wanting to call a tool, write '[UNRESOLVED: would have "
        f"called <tool>(<args>) next]' instead."
    )


def _programmatic_fallback(
    *,
    reason: str,
    tool_count: int,
    budget: int,
    actual_tool_names: list[str],
) -> str:
    """Build a final_answer from tool history alone when the LLM fails
    to produce a clean synthesis. This is the last line of defence —
    the operator will ALWAYS get readable output, even if the model
    emits pure XML drift multiple times.
    """
    seen = set()
    unique_tools: list[str] = []
    for t in actual_tool_names:
        if t not in seen:
            seen.add(t)
            unique_tools.append(t)

    label = _REASON_LABELS.get(reason, reason)

    lines = [
        f"[HARNESS FALLBACK] Agent reached {label} ({tool_count}/{budget} "
        "tool calls). The model failed to produce a clean synthesis; this "
        "summary was built from tool history alone.",
        "",
        "EVIDENCE:",
    ]
    if unique_tools:
        lines.append(
            f"- {tool_count} tool calls made across "
            f"{len(unique_tools)} distinct tools: {', '.join(unique_tools)}"
        )
        lines.append(
            "- See the Trace viewer (Logs \u2192 Trace) for full tool results."
        )
    else:
        lines.append("- No tool calls were recorded for this run.")

    lines += [
        "",
        "UNRESOLVED: The agent did not converge on a conclusion within "
        "the budget. The evidence above may still be useful.",
        "",
        "NEXT STEPS:",
        "1. Open the Trace viewer for this operation to inspect the "
        "full tool results.",
        "2. Consider re-running with a narrower task (scope to a single "
        "entity or a single question), or ask a follow-up that references "
        "a specific tool result to continue from that evidence.",
    ]
    return "\n".join(lines)


def _call_synthesis(client, model, msgs, max_tokens):
    """One tools-free completion. Returns (text, raw_response_dict_or_None)."""
    try:
        forced = client.chat.completions.create(
            model=model, messages=msgs,
            temperature=0.3, max_tokens=max_tokens,
        )
    except Exception as e:
        log.warning("forced_synthesis: LLM call failed: %s", e)
        return "", None

    try:
        text = (forced.choices[0].message.content or "").strip()
    except Exception:
        text = ""

    try:
        raw = forced.model_dump() if hasattr(forced, "model_dump") else dict(forced)
    except Exception:
        raw = None

    return text, raw


def _strip_xml_drift_from_messages(messages: list) -> list:
    """Return a copy of messages with XML-drift removed from assistant text.

    Keeps message order and roles; replaces text-only assistant messages
    whose content is XML-drift with a short placeholder. Real tool_calls
    messages are unchanged. Prevents the drift pattern from being 'primed'
    in the retry call.
    """
    cleaned = []
    for m in messages:
        if m.get("role") == "assistant" and isinstance(m.get("content"), str):
            drift, _ = _is_drift(m["content"])
            if drift:
                cleaned.append({
                    "role": "assistant",
                    "content": _DRIFT_STRIPPED_PLACEHOLDER,
                })
                continue
        cleaned.append(m)
    return cleaned


def run_forced_synthesis(
    *,
    client,
    model: str,
    messages: list,
    agent_type: str,
    reason: str,
    tool_count: int,
    budget: int,
    actual_tool_names: Iterable[str],
    max_tokens: int = 1500,
) -> tuple[str, str, dict | None]:
    """Run one tools-free completion to synthesise a final_answer.

    Returns ``(synthesis_text, harness_message, raw_response_dict)``.

    v2.35.10: drift detector + retry + programmatic fallback mean
    ``synthesis_text`` is never empty and never raw XML drift; operators
    always get a readable EVIDENCE/UNRESOLVED/NEXT STEPS block.
    """
    from api.metrics import (
        FORCED_SYNTHESIS_COUNTER,
        FORCED_SYNTHESIS_FABRICATED_COUNTER,
    )
    try:
        from api.metrics import (
            FORCED_SYNTHESIS_DRIFT_COUNTER,
            FORCED_SYNTHESIS_FALLBACK_COUNTER,
        )
    except Exception:
        FORCED_SYNTHESIS_DRIFT_COUNTER = None
        FORCED_SYNTHESIS_FALLBACK_COUNTER = None

    harness_msg = build_harness_message(reason, tool_count, budget)
    actual_list = list(actual_tool_names or [])

    try:
        FORCED_SYNTHESIS_COUNTER.labels(reason=reason, agent_type=agent_type).inc()
    except Exception:
        pass

    # v2.35.11: both attempts use cleaned history + strong anti-drift prompt.
    # Historical context showed attempt 1 drifts 4/4 times on Qwen3-Coder-Next
    # when left to use raw message history — the cleaned/strong path is
    # strictly better, so we promote it to attempt 1 and retain attempt 2
    # as one last-chance retry with even stronger prompt.
    cleaned_msgs = _strip_xml_drift_from_messages(messages)

    def _synthesis_messages(attempt: int) -> list:
        if attempt == 1:
            synth_harness = (
                harness_msg
                + "\n\nIMPORTANT: No tools are available in this final "
                "synthesis step. Write PLAIN PROSE only — no <tool_call>, "
                "<function=...>, <parameter=...>, or ```json``` syntax. "
                "Start with 'EVIDENCE:' and synthesise only from real tool "
                "results already in this conversation."
            )
        else:  # attempt 2 — even stronger
            synth_harness = (
                harness_msg
                + "\n\nSYSTEM: Your previous response was rejected because "
                "it contained <tool_call> / <function=...> XML syntax OR "
                "echoed a context placeholder. You CANNOT make tool calls "
                "\u2014 no tools are available. Write plain natural-language "
                "prose ONLY. Do NOT copy any prior message from this "
                "conversation \u2014 write a FRESH synthesis in your own "
                "words. Start with the literal word 'EVIDENCE:' (not '<') "
                "and do not include ANY angle-bracket tags."
            )
        return cleaned_msgs + [{"role": "system", "content": synth_harness}]

    # Attempt 1 — cleaned history + strong anti-XML prompt from the start
    synthesis_text, raw = _call_synthesis(
        client, model, _synthesis_messages(1), max_tokens
    )

    # Attempt 2 — only if attempt 1 drifted
    if synthesis_text:
        drift, drift_reason = _is_drift(synthesis_text)
        if drift:
            if FORCED_SYNTHESIS_DRIFT_COUNTER is not None:
                try:
                    FORCED_SYNTHESIS_DRIFT_COUNTER.labels(
                        reason=drift_reason, attempt="1"
                    ).inc()
                except Exception:
                    pass
            log.warning(
                "forced_synthesis: drift on attempt 1 despite cleaned history "
                "(%s), retrying with stronger prompt", drift_reason,
            )
            synthesis_text, raw = _call_synthesis(
                client, model, _synthesis_messages(2), max_tokens
            )
            if synthesis_text:
                drift2, drift_reason2 = _is_drift(synthesis_text)
                if drift2:
                    if FORCED_SYNTHESIS_DRIFT_COUNTER is not None:
                        try:
                            FORCED_SYNTHESIS_DRIFT_COUNTER.labels(
                                reason=drift_reason2, attempt="2"
                            ).inc()
                        except Exception:
                            pass
                    log.warning(
                        "forced_synthesis: drift persisted (%s) on attempt 2, "
                        "using programmatic fallback", drift_reason2,
                    )
                    synthesis_text = ""   # trigger fallback

    # Programmatic fallback — never return empty/drift from this function
    if not synthesis_text:
        if FORCED_SYNTHESIS_FALLBACK_COUNTER is not None:
            try:
                FORCED_SYNTHESIS_FALLBACK_COUNTER.labels(reason=reason).inc()
            except Exception:
                pass
        synthesis_text = _programmatic_fallback(
            reason=reason, tool_count=tool_count, budget=budget,
            actual_tool_names=actual_list,
        )

    # Fabrication detector (from v2.34.17) — still applies to non-fallback text
    if synthesis_text and not synthesis_text.startswith("[HARNESS FALLBACK]"):
        try:
            from api.agents.fabrication_detector import is_fabrication
            fired, _detail = is_fabrication(
                synthesis_text, actual_tool_names=actual_list
            )
            if fired:
                try:
                    FORCED_SYNTHESIS_FABRICATED_COUNTER.labels(
                        agent_type=agent_type
                    ).inc()
                except Exception:
                    pass
                synthesis_text = (
                    "[HARNESS: this synthesis was generated after a hard cap "
                    "and cites tool calls that did not run. Treat as DRAFT.]\n\n"
                    + synthesis_text
                )
        except Exception as _fde:
            log.debug("forced_synthesis: fabrication detector raised: %s", _fde)

    return synthesis_text, harness_msg, raw
