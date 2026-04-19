# CC PROMPT — v2.35.12 — Drop drifted messages entirely + enrich programmatic fallback with tool-result snippets

## What this does

v2.35.11 verification confirmed all three defence layers work, but
surfaced a side-effect: **100% fallback rate across 3 capped runs.**
Before v2.35.11, ~50% of capped runs produced real LLM synthesis
(DNS test op `e442810b`, Docker overlay op `234e828e`). After v2.35.11,
every attempt drifts — either echoing the sentinel placeholder or
emitting high-XML-density content.

Two targeted fixes address the regression without undoing v2.35.11:

1. **Drop drifted assistant messages entirely instead of replacing with
   the sentinel.** The sentinel string is too visually distinctive —
   when the model sees `[__FORCED_SYNTHESIS_STRIPPED_DRIFT_PLACEHOLDER__]`
   repeated in recent context, it becomes an attractor ("just echo this
   plain text and you're safe"). Removing the messages entirely makes
   the synthesis context cleaner and lets the model focus on real tool
   results.

2. **Enrich `_programmatic_fallback()` with per-tool result snippets.**
   Current output lists tool NAMES only — operator has to open the
   Trace viewer to see what happened. Adding a first-line snippet per
   unique tool gives a glance-level understanding directly in
   `final_answer`.

Version bump: 2.35.11 → 2.35.12.

---

## Evidence gathered before this prompt was written

Three v2.35.11 verification runs (2026-04-19 against commit `c780daf`):

| op | template | attempt 1 | attempt 2 | final_answer |
|---|---|---|---|---|
| 69cc4d87 | VM host overview | placeholder_echo | placeholder_echo | HARNESS FALLBACK |
| a1a1e36f | DNS resolver | xml_density | xml_density | HARNESS FALLBACK |
| a18e3047 | Container restart loop | (at least one attempt drifted) | | HARNESS FALLBACK |

Cumulative metrics at closeout:
```
deathstar_forced_synthesis_total{agent_type="status",reason="budget_cap"} = 3.0
deathstar_forced_synthesis_fallback_total{reason="budget_cap"} = 3.0
deathstar_forced_synthesis_drift_total{attempt="1",reason="placeholder_echo"} = 1.0
deathstar_forced_synthesis_drift_total{attempt="2",reason="placeholder_echo"} = 2.0
deathstar_forced_synthesis_drift_total{attempt="1",reason="xml_density>0.30"} = 2.0
deathstar_forced_synthesis_drift_total{attempt="2",reason="xml_density>0.30"} = 1.0
deathstar_forced_synthesis_drift_total{reason="tool_call_prefix"} = 0   # v2.35.11 win preserved
deathstar_forced_synthesis_fabricated_total = 0                         # v2.35.11 win preserved
```

The v2.35.11 wins (no `tool_call_prefix` drift, no fabrication false
positives) must be preserved by any v2.35.12 change. The goal is ONLY
to restore LLM synthesis success on well-behaved runs.

---

## Change 1 — `api/agents/forced_synthesis.py` — drop drifted messages entirely

Replace `_strip_xml_drift_from_messages()` to REMOVE drifted assistant
messages rather than substitute the sentinel:

```python
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
```

The existing `_DRIFT_STRIPPED_PLACEHOLDER` constant stays for backward
compatibility and for the placeholder-echo drift detection (which still
catches the rare case where the model types out the sentinel from
memory). But the module stops INSERTING the sentinel into cleaned
messages, eliminating the attractor.

Also update the module docstring note on v2.35.11 → v2.35.12 history:

```python
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
"""
```

---

## Change 2 — `api/agents/forced_synthesis.py` — enrich programmatic fallback

The programmatic fallback currently lists only tool NAMES. For an
8-tool run it's hard to tell which tool found what. Add a snippet of
the first result per unique tool, truncated to ~120 chars.

Rewrite `_programmatic_fallback()` to accept tool-call history (not
just names) and produce richer output. The caller will change
accordingly.

```python
def _programmatic_fallback(
    *,
    reason: str,
    tool_count: int,
    budget: int,
    actual_tool_calls: list[dict] | None = None,
    actual_tool_names: list[str] | None = None,  # backward compat
) -> str:
    """Build a final_answer from tool history alone.

    Accepts either:
      - `actual_tool_calls`: list of {name, params?, result?, status?}
        dicts for rich snippets (v2.35.12 preferred)
      - `actual_tool_names`: list of tool name strings (v2.35.10
        fallback — retained so existing callers and tests keep working)

    When `actual_tool_calls` is provided, the output includes a per-tool
    snippet line with the first 120 chars of each unique tool's first
    successful result. This gives operators actionable insight inline
    without opening the Trace viewer.
    """
    label = _REASON_LABELS.get(reason, reason)

    # Normalise inputs — prefer rich calls over names
    if actual_tool_calls:
        calls = actual_tool_calls
    elif actual_tool_names:
        calls = [{"name": n} for n in actual_tool_names]
    else:
        calls = []

    # Deduplicate by tool name, keep first success per tool (fall back to
    # first error if no success). This gives each unique tool at most one
    # snippet row.
    seen_names: set[str] = set()
    unique_rows: list[dict] = []
    for call in calls:
        name = call.get("name") or call.get("tool_name")
        if not name or name in seen_names:
            continue
        # Find best call for this name across the full history
        candidates = [c for c in calls
                      if (c.get("name") or c.get("tool_name")) == name]
        success = next((c for c in candidates
                        if c.get("status") in ("ok", None, "")), None)
        chosen = success or candidates[0] if candidates else {"name": name}
        seen_names.add(name)
        unique_rows.append(chosen)

    lines = [
        f"[HARNESS FALLBACK] Agent reached {label} "
        f"({tool_count}/{budget} tool calls). The model failed to produce "
        "a clean synthesis; this summary was built from tool history alone.",
        "",
        "EVIDENCE:",
    ]

    if unique_rows:
        for row in unique_rows:
            name = row.get("name") or row.get("tool_name") or "?"
            status = row.get("status", "?")
            result = row.get("result") or row.get("content") or ""
            if isinstance(result, dict):
                try:
                    import json as _json
                    result = _json.dumps(result, default=str)
                except Exception:
                    result = str(result)
            result = str(result).strip().replace("\n", " ")
            if len(result) > 120:
                result = result[:117] + "..."
            if result:
                lines.append(f"- {name}() status={status}: {result}")
            else:
                lines.append(f"- {name}() status={status}")
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
```

---

## Change 3 — update `run_forced_synthesis` to pass rich tool history

In `run_forced_synthesis`, change the signature to accept `actual_tool_calls`
(optional, backward-compatible with `actual_tool_names`):

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
    actual_tool_calls: list[dict] | None = None,   # NEW v2.35.12
    max_tokens: int = 1500,
) -> tuple[str, str, dict | None]:
```

At the fallback trigger site, pass both:

```python
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
        actual_tool_calls=actual_tool_calls,
        actual_tool_names=actual_list,
    )
```

### Caller update in `api/routers/agent.py`

Find the existing call site (grep for `run_forced_synthesis(`) and add
the `actual_tool_calls` parameter. The caller already has a list of
tool-call dicts in scope (from the step loop). Typical shape in that
file is something like `tool_calls_record` or `recent_calls` —
pass whatever is available. Example:

```python
synthesis_text, harness_msg, raw_resp = run_forced_synthesis(
    client=client, model=_lm_model(), messages=messages,
    agent_type=agent_type, reason="budget_cap",
    tool_count=len(tools_used_names), budget=_tool_budget,
    actual_tool_names=tools_used_names,
    # v2.35.12 — pass rich history for enriched fallback
    actual_tool_calls=[
        {
            "name": tc.get("tool_name") or tc.get("name"),
            "status": tc.get("status"),
            "result": tc.get("result") or tc.get("content"),
        }
        for tc in state.get("tool_history", []) or []
    ],
)
```

**CC instructions:** grep `run_forced_synthesis(` in `api/routers/agent.py`
and adapt the parameter passing to the actual variable names used there.
If `state["tool_history"]` doesn't exist, use whatever list of prior
tool-call records is in scope. Required: each entry must have a `name`
(or `tool_name`) key; `status` and `result` are optional but strongly
preferred — they power the snippet enrichment.

---

## Change 4 — extend `tests/test_forced_synthesis_drift.py`

Replace `test_programmatic_fallback_produces_readable_output` with a
richer test that validates both the backward-compat path and the new
enriched path:

```python
def test_programmatic_fallback_names_only_backward_compat():
    """v2.35.10 callers passing only names still work."""
    from api.agents.forced_synthesis import _programmatic_fallback
    out = _programmatic_fallback(
        reason="budget_cap", tool_count=8, budget=8,
        actual_tool_names=["runbook_search", "vm_exec", "vm_exec",
                           "service_placement"],
    )
    assert "HARNESS FALLBACK" in out
    assert "EVIDENCE" in out
    assert "NEXT STEPS" in out
    assert "<tool_call" not in out
    assert "<function=" not in out
    # De-duplicated: 2 vm_exec -> 1 row
    assert out.count("vm_exec()") <= 1 or out.count("vm_exec(") == 1
    assert "runbook_search" in out
    assert "service_placement" in out


def test_programmatic_fallback_enriched_with_results():
    """v2.35.12 new: per-tool result snippet included when available."""
    from api.agents.forced_synthesis import _programmatic_fallback
    calls = [
        {"name": "swarm_node_status", "status": "ok",
         "result": "6 nodes Ready, leader manager-02"},
        {"name": "vm_exec", "status": "ok",
         "result": "/dev/sda1 42G used 120G avail"},
        {"name": "vm_exec", "status": "ok",
         "result": "/dev/sda1 second run same"},
        {"name": "service_placement", "status": "error",
         "result": "Unknown service: foo"},
    ]
    out = _programmatic_fallback(
        reason="budget_cap", tool_count=4, budget=8,
        actual_tool_calls=calls,
    )
    assert "swarm_node_status" in out
    assert "6 nodes Ready" in out  # snippet included
    assert "vm_exec" in out
    assert "42G used" in out
    # Deduplicated: only one vm_exec row
    assert out.count("vm_exec()") == 1 or out.count("vm_exec() status") == 1
    # Error row gets rendered too (best we have for a tool that only failed)
    assert "service_placement" in out
    assert "Unknown service" in out


def test_programmatic_fallback_snippet_truncation():
    """Results longer than 120 chars must be truncated with ellipsis."""
    from api.agents.forced_synthesis import _programmatic_fallback
    long_result = "X" * 500
    out = _programmatic_fallback(
        reason="budget_cap", tool_count=1, budget=8,
        actual_tool_calls=[{"name": "vm_exec", "status": "ok",
                            "result": long_result}],
    )
    # Must contain some X but not all 500 of them
    assert "XXX" in out
    assert "XXXXXXXXXX" * 50 not in out
    # Ellipsis marker
    assert "..." in out


def test_programmatic_fallback_dict_result_serialised():
    """Dict results should be JSON-stringified (not `{...object address...}`)."""
    from api.agents.forced_synthesis import _programmatic_fallback
    out = _programmatic_fallback(
        reason="budget_cap", tool_count=1, budget=8,
        actual_tool_calls=[{"name": "kafka_broker_status", "status": "ok",
                            "result": {"brokers": 3, "isr": "[1,2,3]"}}],
    )
    assert "kafka_broker_status" in out
    assert "brokers" in out
    assert "3" in out


def test_strip_xml_drift_from_messages_drops_drifted_entirely():
    """v2.35.12: drifted messages must be REMOVED, not sentinel-replaced."""
    from api.agents.forced_synthesis import (
        _strip_xml_drift_from_messages, _DRIFT_STRIPPED_PLACEHOLDER,
    )
    msgs = [
        {"role": "system", "content": "you are helpful"},
        {"role": "user", "content": "do something"},
        {"role": "assistant", "content": "Sure, I'll check."},
        {"role": "assistant", "content": "<tool_call>\n<function=foo>\n</tool_call>"},
        {"role": "tool", "tool_call_id": "x", "content": "{}"},
        {"role": "assistant", "content": "Results look good."},
    ]
    out = _strip_xml_drift_from_messages(msgs)
    # Drifted assistant PLUS its orphaned tool response are both gone
    assert len(out) == len(msgs) - 2
    assert all(_DRIFT_STRIPPED_PLACEHOLDER not in str(m.get("content", ""))
               for m in out)
    # Non-drift messages preserved
    assert out[0]["content"] == "you are helpful"
    assert out[2]["content"] == "Sure, I'll check."
    assert out[3]["content"] == "Results look good."


def test_strip_xml_drift_preserves_tool_responses_to_valid_calls():
    """Tool responses that follow a non-drift assistant must NOT be dropped."""
    from api.agents.forced_synthesis import _strip_xml_drift_from_messages
    msgs = [
        {"role": "user", "content": "query"},
        {"role": "assistant", "content": None,
         "tool_calls": [{"id": "1", "function": {"name": "foo"}}]},
        {"role": "tool", "tool_call_id": "1", "content": "result"},
        {"role": "assistant", "content": "done"},
    ]
    out = _strip_xml_drift_from_messages(msgs)
    # None of these drift — all preserved
    assert len(out) == len(msgs)
```

---

## Change 5 — `VERSION`

Replace with:

```
2.35.12
```

---

## Verify

```bash
pytest tests/test_forced_synthesis_drift.py -v
pytest tests/test_fabrication_detector_regex.py -v  # v2.35.11 suite still passes
```

All must pass.

---

## Commit

```bash
git add -A
git commit -m "fix(agents): v2.35.12 drop drifted messages entirely + enrich programmatic fallback

v2.35.11 verification (3 capped runs 2026-04-19) showed 100% fallback
rate — every attempt drifted via either placeholder_echo or
xml_density. Root cause: the _DRIFT_STRIPPED_PLACEHOLDER sentinel in
cleaned retry context became an attractor. Model, pressed to produce
'plain text only', echoed the sentinel verbatim as its output.

Two surgical changes:

1. _strip_xml_drift_from_messages now DROPS drifted assistant turns
   (and their orphaned tool responses) entirely, instead of
   substituting the sentinel. Cleaner context; no attractor pattern.
   Sentinel constant + placeholder_echo drift detection retained for
   edge cases where the model types out the sentinel from memory.

2. _programmatic_fallback enriched with per-tool result snippets
   (first success per unique tool, 120-char truncated). Operator
   no longer has to open Trace viewer to see what each tool found.
   Backward-compatible — existing callers passing actual_tool_names
   still work.

run_forced_synthesis gains an optional actual_tool_calls parameter
for rich history; api/routers/agent.py caller wired to pass it.

Preserves all v2.35.11 wins (no tool_call_prefix drift, no
fabrication false positives)."
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

1. Re-fire **VM host overview** — previously 100% fallback.
   Expected: `fallback_total` grows slowly or not at all; LLM synthesis
   sometimes succeeds. When fallback DOES fire, `final_answer` now
   contains per-tool result snippets like
   `- vm_exec() status=ok: /dev/sda1 42G used 120G avail`.

2. Re-fire **DNS resolver consistency** — previously 100% fallback.
   Expected: similar improvement. Verify no `[HARNESS: ... DRAFT]`
   fabrication prefix resurfaces.

3. `/metrics` check:
   - `deathstar_forced_synthesis_drift_total{reason="placeholder_echo"}`
     should grow MUCH slower (ideally 0).
   - `deathstar_forced_synthesis_fallback_total{reason="budget_cap"}`
     should grow slower than `forced_synthesis_total` (i.e. some runs
     produce real synthesis again).
   - `reason="tool_call_prefix"` MUST remain 0 (v2.35.11 win preserved).
