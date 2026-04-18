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
"""
from __future__ import annotations

import logging
from typing import Iterable

log = logging.getLogger(__name__)


_REASON_LABELS = {
    "budget_cap":        "tool-call budget-cap",
    "wall_clock":        "wall-clock cap",
    "token_cap":         "token cap",
    "destructive_cap":   "destructive-call cap",
    "tool_failures":     "consecutive-tool-failure cap",
}


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
        f"Cite only tools that actually ran. Do NOT fabricate."
    )


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

    - ``synthesis_text`` — the model's output, prefixed with a DRAFT warning
      if the fabrication detector fired.
    - ``harness_message`` — the ``[harness] ...`` string injected into the
      conversation (caller uses this when persisting to the trace).
    - ``raw_response_dict`` — ``model_dump()`` of the completion if available,
      else ``None`` (caller persists this as the trace step's response_raw).

    Never raises — on API failure returns an empty synthesis and ``None`` raw
    response. The caller decides whether to still mark the run as capped.
    """
    from api.metrics import (
        FORCED_SYNTHESIS_COUNTER,
        FORCED_SYNTHESIS_FABRICATED_COUNTER,
    )

    harness_msg = build_harness_message(reason, tool_count, budget)
    synthesis_msgs = messages + [{"role": "system", "content": harness_msg}]

    try:
        FORCED_SYNTHESIS_COUNTER.labels(
            reason=reason, agent_type=agent_type
        ).inc()
    except Exception:
        pass

    try:
        # Intentionally NO ``tools=`` — the model has no way to call anything.
        forced = client.chat.completions.create(
            model=model,
            messages=synthesis_msgs,
            temperature=0.3,
            max_tokens=max_tokens,
        )
    except Exception as e:
        log.warning("forced_synthesis: LLM call failed (%s): %s", reason, e)
        return "", harness_msg, None

    try:
        synthesis_text = (forced.choices[0].message.content or "").strip()
    except Exception:
        synthesis_text = ""

    # Fabrication detector — if the forced output cites uncalled tools,
    # prefix with a DRAFT warning but still return the text (an imperfect
    # synthesis is better than a silent null).
    if synthesis_text:
        try:
            from api.agents.fabrication_detector import is_fabrication
            fired, _detail = is_fabrication(
                synthesis_text,
                actual_tool_names=list(actual_tool_names or []),
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

    raw: dict | None
    try:
        raw = forced.model_dump() if hasattr(forced, "model_dump") else dict(forced)
    except Exception:
        raw = None

    return synthesis_text, harness_msg, raw
