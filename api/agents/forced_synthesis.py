"""Forced-synthesis step for agent runs that hit a hard cap.

v2.34.17 — original version: single-shot LLM call after budget cap.
v2.35.10 — added XML-drift defence (regex check on output) + one-shot
           retry with a sentinel-replaced history + programmatic
           fallback.
v2.35.11 — unique sentinel constant + placeholder_echo drift detection
           + attempt-1 uses cleaned history + strong anti-XML prompt
           from the start.
v2.35.12 — drop drifted messages from history entirely (instead of
           sentinel replacement) because the sentinel became an
           attractor the model would echo. Sentinel constant + echo
           detection retained for edge cases. Fallback enriched with
           per-tool result snippets.
v2.35.13 — DB-sourced fallback: _programmatic_fallback now optionally
           takes an operation_id and queries tool_calls directly for
           canonical rows (tool_name/status/params/result dict).
           Removes caller-wiring fragility. Dedup keyed by
           (tool_name, first_arg_value) so vm_exec across multiple
           hosts each gets its own row. _best_snippet helper prefers
           result['message'] -> data.summary -> top-level data keys
           -> JSON dump.
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
    # v2.35.14 — natural exit with no assistant text emitted
    "empty_completion":  "natural completion with empty final_answer",
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


# Priority order for identifying a call's primary argument. Used for
# dedup keying so calls to the same tool with different primary args
# (e.g. vm_exec across hosts) each get their own fallback row.
_FIRST_ARG_KEYS_PRIORITY = (
    "host", "service_name", "entity_id", "container_id",
    "vm_name", "node", "broker_id", "pool", "datastore",
    "topic", "group", "key", "name", "label",
)


def _first_arg_value(params: dict) -> str:
    """Return a short stable representation of the call's primary arg.

    Used for dedup keying: calls to the same tool with different primary
    args should NOT be collapsed into a single fallback row. For example,
    vm_exec(host='worker-01', command='df -h') and
    vm_exec(host='worker-02', command='df -h') must produce two rows.

    Falls back to empty string (= no distinction) when no recognised
    primary arg key is present and no leaf value can be extracted.
    """
    if not isinstance(params, dict) or not params:
        return ""
    for k in _FIRST_ARG_KEYS_PRIORITY:
        v = params.get(k)
        if v is not None:
            s = str(v).strip()
            if s:
                return s[:40]
    for k, v in params.items():
        if isinstance(v, (str, int, float)) and str(v).strip():
            return str(v).strip()[:40]
    return ""


def _best_snippet(result, max_chars: int = 120) -> str:
    """Extract a useful short snippet from a tool's result.

    Tool results have a canonical shape:
      {"status": "ok"|"error", "message": "<short>", "data": {...}}

    Preference order:
      1. `message` field (short, author-written)
      2. First line of `data.summary`
      3. Top-level keys of `data` (for structured tool returns)
      4. JSON dump of `data` (truncated)
      5. str(result) truncated
    """
    def _truncate(s: str) -> str:
        s = s.strip().replace("\n", " ")
        return s[:max_chars - 3] + "..." if len(s) > max_chars else s

    if result is None:
        return ""
    if not isinstance(result, dict):
        return _truncate(str(result))

    msg = result.get("message")
    if isinstance(msg, str) and msg.strip():
        return _truncate(msg)

    data = result.get("data")

    if isinstance(data, dict):
        summ = data.get("summary")
        if isinstance(summ, str) and summ.strip():
            first_line = summ.strip().split("\n", 1)[0].strip()
            return _truncate(first_line)

    if isinstance(data, dict) and data:
        pairs = []
        for k, v in list(data.items())[:6]:
            if isinstance(v, (str, int, float, bool)):
                pairs.append(f"{k}={v}")
            elif isinstance(v, list):
                pairs.append(f"{k}=[{len(v)} items]")
            elif isinstance(v, dict):
                pairs.append(f"{k}={{{len(v)} keys}}")
        if pairs:
            return _truncate(", ".join(pairs))
    elif isinstance(data, list) and data:
        return f"[{len(data)} items]"

    try:
        import json as _json
        return _truncate(_json.dumps(result, default=str))
    except Exception:
        return _truncate(str(result))


def _load_tool_calls_for_op(operation_id: str) -> list[dict]:
    """Load canonical tool_calls rows from the DB for a given operation.

    Returns [] on any DB error (logged at debug). Never raises — the
    fallback must work even if the DB is flaky.

    Rows have the canonical shape:
      {tool_name, status, params (dict), result (dict),
       duration_ms, timestamp}
    """
    try:
        from sqlalchemy import text
        from api.db.base import get_sync_engine
        eng = get_sync_engine()
        with eng.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT tool_name, status, params, result, "
                    "duration_ms, timestamp "
                    "FROM tool_calls WHERE operation_id = :op "
                    "ORDER BY timestamp ASC"
                ),
                {"op": operation_id},
            ).mappings().all()
        return [dict(r) for r in rows]
    except Exception as e:
        log.debug("fallback DB load error op=%s: %s", operation_id, e)
        return []


def _programmatic_fallback(
    *,
    reason: str,
    tool_count: int,
    budget: int,
    operation_id: str | None = None,       # v2.35.13 preferred source
    actual_tool_calls: list[dict] | None = None,
    actual_tool_names: list[str] | None = None,  # backward compat
) -> str:
    """Build a final_answer from tool history alone.

    Source preference (first non-empty wins):
      1. operation_id -> DB query for canonical tool_calls rows
         (v2.35.13 preferred — removes caller-wiring fragility).
      2. actual_tool_calls -> any shape with name/tool_name + status +
         result/params keys (v2.35.12 path).
      3. actual_tool_names -> names-only (v2.35.10 legacy path).

    Dedup v2.35.13: groups by (tool_name, first_arg_value) so vm_exec
    calls across different hosts each get their own row. When a second
    call has the same (tool, first_arg) as an existing row, the success
    replaces an error.
    """
    label = _REASON_LABELS.get(reason, reason)

    calls: list[dict] = []
    source = "names_only"

    if operation_id:
        try:
            calls = _load_tool_calls_for_op(operation_id)
            source = "db"
        except Exception as e:
            log.debug("fallback DB load failed op=%s: %s", operation_id, e)
            calls = []

    if not calls and actual_tool_calls:
        calls = list(actual_tool_calls)
        source = "caller_calls"

    if not calls and actual_tool_names:
        calls = [{"tool_name": n} for n in actual_tool_names]
        source = "names_only"

    log.info(
        "forced_synthesis fallback source=%s calls=%d reason=%s",
        source, len(calls), reason,
    )

    unique_rows: list[dict] = []
    seen_keys: set[tuple[str, str]] = set()
    for call in calls:
        name = (call.get("tool_name") or call.get("name") or "").strip()
        if not name:
            continue
        first_arg = _first_arg_value(call.get("params") or {})
        key = (name, first_arg)
        if key in seen_keys:
            existing_idx = next(
                (i for i, r in enumerate(unique_rows)
                 if (r.get("tool_name") or r.get("name")) == name
                 and _first_arg_value(r.get("params") or {}) == first_arg),
                None,
            )
            if existing_idx is not None:
                existing = unique_rows[existing_idx]
                if (call.get("status") == "ok"
                        and existing.get("status") != "ok"):
                    unique_rows[existing_idx] = call
            continue
        seen_keys.add(key)
        unique_rows.append(call)

    lines = [
        f"[HARNESS FALLBACK] Agent reached {label} "
        f"({tool_count}/{budget} tool calls). The model failed to produce "
        "a clean synthesis; this summary was built from tool history alone.",
        "",
        "EVIDENCE:",
    ]

    if unique_rows:
        for row in unique_rows:
            name = row.get("tool_name") or row.get("name") or "?"
            first_arg = _first_arg_value(row.get("params") or {})
            status = row.get("status") or "?"
            # Prefer structured result dict via _best_snippet; fall back
            # to the legacy `content` field for callers still using v1
            # shape.
            raw_result = row.get("result")
            if raw_result is None:
                raw_result = row.get("content")
            snippet = _best_snippet(raw_result)
            arg_label = f"({first_arg})" if first_arg else "()"
            if snippet:
                lines.append(f"- {name}{arg_label} status={status}: {snippet}")
            else:
                lines.append(f"- {name}{arg_label} status={status}")
        lines.append("- See the Trace viewer (Logs \u2192 Trace) "
                     "for full tool results.")
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
        "entity or a single question), or ask a follow-up that "
        "references a specific tool result to continue from that "
        "evidence.",
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
    """Return a copy of messages with XML-drift assistant turns REMOVED.

    v2.35.12 change: messages whose content matches `_is_drift()` are
    dropped from the history entirely (not replaced with a sentinel).
    The previous sentinel-replacement approach created an attractor
    pattern — the model in the synthesis call would sometimes echo the
    sentinel verbatim as 'prose', treating it as a safe plain-text
    fallback. Dropping entirely avoids this.

    Related tool-response messages for the dropped assistant turns are
    also dropped, because the pairing is broken once the parent
    assistant message is gone. This is safe: drifted assistant messages
    never had real `tool_calls` (they had text-embedded XML), so the
    tool responses below them were produced by different flow branches
    and aren't referenced by `tool_call_id` anywhere upstream.
    """
    cleaned = []
    skip_next_tool_block = False
    for m in messages:
        role = m.get("role")

        # A tool response immediately following a dropped assistant turn
        # is orphaned — drop it too.
        if role == "tool" and skip_next_tool_block:
            continue
        # First non-tool message clears the skip flag
        if role != "tool":
            skip_next_tool_block = False

        # Check for drift on text-only assistant content
        if role == "assistant" and isinstance(m.get("content"), str):
            drift, _ = _is_drift(m["content"])
            if drift:
                skip_next_tool_block = True
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
    operation_id: str | None = None,               # NEW v2.35.13
    actual_tool_calls: list[dict] | None = None,   # NEW v2.35.12
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
            reason=reason,
            tool_count=tool_count,
            budget=budget,
            operation_id=operation_id,             # v2.35.13
            actual_tool_calls=actual_tool_calls,
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
