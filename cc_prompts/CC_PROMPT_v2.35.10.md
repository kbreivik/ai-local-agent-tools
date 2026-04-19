# CC PROMPT — v2.35.10 — Forced synthesis XML-drift defense

## What this does

v2.34.17 introduced `forced_synthesis` so that budget-cap / wall-clock /
token-cap exits produce a real `final_answer` instead of a silent null.
v2.35.8 template smoke tests reveal the mechanism fires but its output is
contaminated by the Qwen3-Coder-Next model's tendency to emit tool calls as
XML-formatted text (`<tool_call><function=...>...</function></tool_call>`)
when the prompt pattern has been established over many turns.

Observed on every single one of 4 consecutive `status=capped` runs
(2026-04-19 against commit `3cf80a2`, ops `7f1fb061`, `d6f52901`,
`27b5be44`, `7660a0de`) — `operations.final_answer` rows look like:

```
<tool_call>
<function=vm_exec>
<parameter=host>
ds-docker-worker-03
</parameter>
<parameter=command>
df -h
</parameter>
</function>
</tool_call>
```

That's not a synthesis — that's the model attempting another tool call in
text form. When persisted as `final_answer`, the operator sees raw XML and
has no idea what the investigation concluded.

This prompt:

1. Hardens the `run_forced_synthesis` harness message with an explicit
   prohibition on XML / tool-call syntax.
2. Adds an **output sanity check** after the LLM call: if the synthesis
   output starts with `<tool_call>` / `<function=` / contains >30% XML-tag
   density, reject it and run ONE retry with an even stronger prompt
   plus a regex-stripped-XML snapshot of prior messages.
3. If the retry also fails, fall back to a **programmatic summary** built
   from the actual tool call history (not the model) — structured
   EVIDENCE / UNRESOLVED / NEXT STEPS — so operators never see raw XML.
4. Surfaces the failure mode via new Prometheus counters so we can see
   in production how often the fallback is needed.

Version bump: 2.35.9 → 2.35.10.

---

## Evidence gathered before this prompt was written

Direct DB query via `/api/logs/operations?limit=10` (2026-04-19 21:xx UTC):

| op | template | status | final_answer head |
|---|---|---|---|
| 7f1fb061 | VM host overview | capped | `<tool_call>\n<function=vm_exec>\n<parameter=host>\nds-docker-worker-03\n...` |
| d6f52901 | Container restart loop diagnosis | capped | `<tool_call>\n<function=service_placement>\n<parameter=service_name>\nkafka_broker-2\n...` |
| 27b5be44 | Certificate expiry check | capped | `<tool_call>\n<function=vm_exec>\n<parameter=host>\nmanager-01\n...` |
| 7660a0de | DNS resolver consistency | capped | `Let me try with the correct hostname from the available VM hosts list:\n\n<tool_call>\n<function=vm_exec>\n...` |

All four have tool-call counts at or near budget (8/8 for observe). All
four had status="capped" — which means `run_forced_synthesis` WAS called
(the budget-cap branch in `_run_single_agent_step` always calls it). So
forced_synthesis ran but its output was XML-drift text. That text then
propagated via `last_reasoning` → `prior_verdict.full_output` → `_stream_agent`
top-level → `set_operation_final_answer`.

The relevant code path in `api/agents/forced_synthesis.py::run_forced_synthesis`:

```python
try:
    forced = client.chat.completions.create(
        model=model,
        messages=synthesis_msgs,
        temperature=0.3,
        max_tokens=max_tokens,
    )
except Exception as e:
    log.warning(...)
    return "", harness_msg, None

try:
    synthesis_text = (forced.choices[0].message.content or "").strip()
except Exception:
    synthesis_text = ""
```

No output validation. Whatever the model returns (including XML-drift) is
returned verbatim. The fabrication detector runs but doesn't fire on
XML-drift because it checks for *cited tool names* not tool-call syntax.

---

## Change 1 — `api/agents/forced_synthesis.py` — stronger prohibition + drift detection + retry + programmatic fallback

Rewrite the core of `run_forced_synthesis`. Key additions:

### 1a. Harness message addition — explicit XML/tool-call prohibition

In `build_harness_message()`, append:

```python
return (
    f"[harness] You have hit the {label} "
    f"({tool_count}/{budget} tools used). No more tool calls allowed. "
    f"Produce your final_answer right now from the evidence you have "
    f"already gathered. Format: EVIDENCE: (bullets citing actual tool "
    f"results) / ROOT CAUSE: (if you can conclude) or UNRESOLVED: "
    f"(what would unblock you) / NEXT STEPS: (what a human should do). "
    f"Cite only tools that actually ran. Do NOT fabricate.\n\n"
    f"CRITICAL FORMAT RULE: Output PLAIN TEXT ONLY. Do NOT use any of "  # NEW
    f"these syntaxes: <tool_call>, <function=...>, <parameter=...>, "   # NEW
    f"```json ... ```, or any XML/JSON tool-call format. If you find "   # NEW
    f"yourself wanting to call a tool, write '[UNRESOLVED: would have "  # NEW
    f"called <tool>(<args>) next]' instead."                              # NEW
)
```

### 1b. Drift detector — reject XML-style output, optional retry

Add these module-level helpers:

```python
import re as _re

# XML-drift detection: model emits tool calls as <tool_call>... or
# <function=...>... or raw ```json fences around JSON args. Any of these
# in the first 200 chars of output means synthesis failed.
_DRIFT_PREFIX_RE = _re.compile(
    r"^\s*(?:<tool_call>|<function[=\s]|<parameter[=\s]|```json\b)",
    _re.IGNORECASE,
)

# Overall XML-tag density — calibrated for natural-text outputs. >30%
# characters inside <...> tags = model is emitting structured markup
# instead of prose.
def _xml_density(text: str) -> float:
    if not text:
        return 0.0
    in_tag = 0
    total = len(text)
    depth = 0
    for ch in text:
        if ch == "<":
            depth += 1
        if depth > 0:
            in_tag += 1
        if ch == ">" and depth > 0:
            depth -= 1
    return in_tag / total if total else 0.0


def _is_drift(text: str, *, density_threshold: float = 0.30) -> tuple[bool, str]:
    """Return (is_drift, reason) for a synthesis candidate."""
    if not text:
        return True, "empty"
    if _DRIFT_PREFIX_RE.match(text):
        return True, "tool_call_prefix"
    if _xml_density(text) > density_threshold:
        return True, f"xml_density>{density_threshold:.2f}"
    # Also catch "<parameter=host>" anywhere in the first 500 chars
    if "<parameter=" in text[:500] or "<function=" in text[:500]:
        return True, "parameter_tag_in_head"
    return False, ""
```

### 1c. Programmatic fallback — built from actual tool history

Add a helper that produces a minimal but TRUE synthesis from just the tool
call names, reason, and agent type — no LLM involved:

```python
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
    # Dedup preserving order for readability
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
            "- See the Trace viewer (Logs → Trace) for full tool results."
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
```

### 1d. Rewritten `run_forced_synthesis` body

Replace the body of `run_forced_synthesis` with:

```python
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
    from api.metrics import (
        FORCED_SYNTHESIS_COUNTER,
        FORCED_SYNTHESIS_FABRICATED_COUNTER,
    )
    # v2.35.10 — new counters
    try:
        from api.metrics import (
            FORCED_SYNTHESIS_DRIFT_COUNTER,
            FORCED_SYNTHESIS_FALLBACK_COUNTER,
        )
    except Exception:
        FORCED_SYNTHESIS_DRIFT_COUNTER = None
        FORCED_SYNTHESIS_FALLBACK_COUNTER = None

    harness_msg = build_harness_message(reason, tool_count, budget)
    synthesis_msgs = messages + [{"role": "system", "content": harness_msg}]
    actual_list = list(actual_tool_names or [])

    try:
        FORCED_SYNTHESIS_COUNTER.labels(reason=reason, agent_type=agent_type).inc()
    except Exception:
        pass

    # Attempt 1
    synthesis_text, raw = _call_synthesis(client, model, synthesis_msgs, max_tokens)

    # Attempt 2 — drift retry
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
                "forced_synthesis: drift detected (%s) on attempt 1, retrying",
                drift_reason,
            )
            # Retry with an even stronger anti-XML prompt and a cleaner
            # messages list: strip prior XML-drift assistant messages so
            # the model isn't primed to continue the pattern.
            cleaned_msgs = _strip_xml_drift_from_messages(messages)
            retry_harness = (
                harness_msg
                + "\n\nSYSTEM: Your previous response was rejected because "
                "it contained <tool_call> / <function=...> XML syntax. "
                "You CANNOT make tool calls — no tools are available. "
                "Write plain natural-language prose ONLY. If your first "
                "response would have started with '<', start with 'EVIDENCE:' "
                "instead. Do not include ANY angle-bracket tags."
            )
            retry_msgs = cleaned_msgs + [{"role": "system", "content": retry_harness}]
            synthesis_text, raw = _call_synthesis(
                client, model, retry_msgs, max_tokens
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
            fired, _detail = is_fabrication(synthesis_text, actual_tool_names=actual_list)
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
```

Add the helpers used above:

```python
def _call_synthesis(client, model, msgs, max_tokens):
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
                    "content": "[prior step: tool call attempt, see tool_calls]",
                })
                continue
        cleaned.append(m)
    return cleaned
```

---

## Change 2 — `api/metrics.py` — new counters

Add alongside the existing FORCED_SYNTHESIS_* counters:

```python
FORCED_SYNTHESIS_DRIFT_COUNTER = Counter(
    "deathstar_forced_synthesis_drift_total",
    "Times a forced_synthesis output was rejected as XML/JSON drift.",
    ["reason", "attempt"],  # reason: tool_call_prefix/xml_density/parameter_tag_in_head/empty
)

FORCED_SYNTHESIS_FALLBACK_COUNTER = Counter(
    "deathstar_forced_synthesis_fallback_total",
    "Times the programmatic fallback was used (both LLM attempts drifted).",
    ["reason"],  # reason: the loop-exit reason (budget_cap/wall_clock/...)
)
```

---

## Change 3 — `tests/test_forced_synthesis_drift.py` (new file)

```python
"""v2.35.10 regression — forced_synthesis must never persist XML drift."""
from __future__ import annotations

import pytest


def test_drift_detector_catches_tool_call_prefix():
    from api.agents.forced_synthesis import _is_drift
    drift, reason = _is_drift(
        "<tool_call>\n<function=vm_exec>\n<parameter=host>\nfoo</parameter>"
    )
    assert drift
    assert "tool_call" in reason or "parameter" in reason


def test_drift_detector_catches_function_prefix():
    from api.agents.forced_synthesis import _is_drift
    drift, reason = _is_drift("<function=foo>\n<parameter=x>1</parameter>")
    assert drift


def test_drift_detector_catches_json_fence_prefix():
    from api.agents.forced_synthesis import _is_drift
    drift, reason = _is_drift('```json\n{"tool": "foo", "args": {}}\n```')
    assert drift


def test_drift_detector_accepts_clean_prose():
    from api.agents.forced_synthesis import _is_drift
    drift, reason = _is_drift(
        "EVIDENCE:\n- kafka_broker_status returned 3 brokers online\n"
        "- service_placement confirmed kafka_broker-3 on worker-03\n\n"
        "ROOT CAUSE: Broker 3 has ISR mismatch.\n\n"
        "NEXT STEPS:\n1. Reboot worker-03 via Proxmox."
    )
    assert not drift, f"clean prose should not trigger drift, reason={reason!r}"


def test_drift_detector_accepts_angle_bracket_lt_gt_comparisons():
    """Prose containing '>' or '<' as comparison operators must not trigger."""
    from api.agents.forced_synthesis import _is_drift
    drift, _ = _is_drift(
        "The partition count was > 3 for all topics. ISR was < expected on broker 2."
    )
    assert not drift


def test_programmatic_fallback_produces_readable_output():
    from api.agents.forced_synthesis import _programmatic_fallback
    out = _programmatic_fallback(
        reason="budget_cap", tool_count=8, budget=8,
        actual_tool_names=["runbook_search", "vm_exec", "vm_exec", "service_placement"],
    )
    assert "HARNESS FALLBACK" in out
    assert "EVIDENCE" in out
    assert "NEXT STEPS" in out
    assert "<tool_call" not in out
    assert "<function=" not in out
    # De-duplicated list of tools (2 vm_exec → 1 entry)
    assert "runbook_search" in out
    assert "vm_exec" in out
    assert "service_placement" in out


def test_strip_xml_drift_from_messages_preserves_non_drift():
    from api.agents.forced_synthesis import _strip_xml_drift_from_messages
    msgs = [
        {"role": "system", "content": "you are helpful"},
        {"role": "user", "content": "do something"},
        {"role": "assistant", "content": "Sure, I'll check."},                       # keep
        {"role": "assistant", "content": "<tool_call>\n<function=foo>\n</tool_call>"}, # strip
        {"role": "tool", "tool_call_id": "x", "content": "{}"},                      # keep
    ]
    out = _strip_xml_drift_from_messages(msgs)
    assert len(out) == len(msgs)
    assert out[0] == msgs[0]
    assert out[1] == msgs[1]
    assert out[2] == msgs[2]
    assert out[3]["content"].startswith("[prior step")
    assert out[3]["content"] != msgs[3]["content"]
    assert out[4] == msgs[4]


def test_run_forced_synthesis_falls_back_on_drift(monkeypatch):
    """Integration: if the mock LLM returns XML drift both times, the
    programmatic fallback must be returned — never the raw drift."""
    from api.agents import forced_synthesis as fs

    class _FakeMsg:
        def __init__(self, content): self.content = content
    class _FakeChoice:
        def __init__(self, content): self.message = _FakeMsg(content)
    class _FakeResp:
        def __init__(self, content):
            self.choices = [_FakeChoice(content)]
        def model_dump(self):
            return {"choices": [{"message": {"content": self.choices[0].message.content}}]}

    class _FakeCompletions:
        def __init__(self):
            self.call_count = 0
        def create(self, **kw):
            self.call_count += 1
            return _FakeResp("<tool_call>\n<function=vm_exec>\n</tool_call>")

    class _FakeClient:
        def __init__(self):
            self.chat = type("X", (), {"completions": _FakeCompletions()})()

    client = _FakeClient()
    text, harness, raw = fs.run_forced_synthesis(
        client=client, model="fake", messages=[{"role": "user", "content": "x"}],
        agent_type="observe", reason="budget_cap",
        tool_count=8, budget=8,
        actual_tool_names=["vm_exec", "swarm_node_status"],
    )
    # Must be 2 attempts made
    assert client.chat.completions.call_count == 2
    # Must NOT contain XML drift
    assert "<tool_call>" not in text
    assert "<function=" not in text
    # Must be the programmatic fallback
    assert "HARNESS FALLBACK" in text
    assert "vm_exec" in text    # tool list preserved
```

---

## Change 4 — `VERSION`

Replace with:

```
2.35.10
```

---

## Verify

```bash
pytest tests/test_forced_synthesis_drift.py -v
```

All 8 tests must pass.

---

## Commit

```bash
git add -A
git commit -m "fix(agents): v2.35.10 forced_synthesis XML-drift defense

Observed on every v2.35.8 status=capped run (2026-04-19): operations.
final_answer contained raw <tool_call><function=...> XML markup instead
of structured synthesis. forced_synthesis (v2.34.17) was firing but
its output was the model drifting into tool-call-as-text mode. Persisted
as final_answer, leaving operators with no readable output.

Fix has three layers: (1) explicit XML/tool-call prohibition in the
harness message, (2) drift detector + one-shot retry with cleaned message
history (prior XML-drift assistant messages replaced with placeholders
so the model isn't primed to continue the pattern), (3) programmatic
fallback built from actual tool-call history when the LLM refuses to
emit clean prose — guarantees operator always sees structured
EVIDENCE/UNRESOLVED/NEXT STEPS output.

Two new Prometheus counters surface how often each layer fires:
deathstar_forced_synthesis_drift_total{reason,attempt}
deathstar_forced_synthesis_fallback_total{reason}

8 regression tests: drift detector positive/negative cases, fallback
readability, message-stripping integrity, and an end-to-end integration
test with a mock client that always drifts."
git push origin main
```

---

## Deploy

```bash
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```

---

## Smoke test (post-deploy)

Re-fire any v2.35.8 template that hits budget cap (VM host overview is
reliable at this — 10+ hosts × multiple commands × 8 budget). Expected:
- `final_answer` begins with `EVIDENCE:` OR `[HARNESS FALLBACK]` — NEVER
  with `<tool_call>` / `<function=`.
- `/metrics` shows either a successful synthesis (no drift counter
  increment) or drift_total{attempt="1"} increments followed by either
  a successful retry or fallback_total increment.
- The Trace viewer's Gates Fired sidebar shows `forced_synthesis` for
  the operation; the drift-retry/fallback events surface in the step log.
