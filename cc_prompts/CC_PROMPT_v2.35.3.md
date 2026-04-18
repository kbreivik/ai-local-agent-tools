# CC PROMPT — v2.35.3 — feat(agents): fact-age rejection on tool results (Medium mode)

## What this does

When a tool result reports a value that disagrees with a high-confidence
recently-verified fact, the value is stripped from what the agent sees
(Medium aggression mode). The original value is preserved in a
`_rejected_by_fact_age` field for transparency. A harness message
instructs the agent to re-verify if it believes the fact is stale.

Settings-controlled aggression: `off`, `soft` (advisory only), `medium`
(default — strip value), `hard` (fail tool call).

Version bump: 2.35.2 → 2.35.3 (new subsystem in agent hot path, multi-file).

Design ref: `cc_prompts/PHASE_v2.35_SPEC.md` → "Fact-age rejection — Medium mode".

---

## Change 1 — age-rejection engine

New file `api/agents/fact_age_rejection.py`.

```python
"""
Fact-age rejection:
When a tool result reports a value for a fact key that contradicts a
high-confidence recently-verified known_fact, the tool result is
filtered per the configured aggression mode.

Modes:
  off     — no rejection (pass-through)
  soft    — advisory harness message only, tool result untouched
  medium  — strip the conflicting value, add _rejected_by_fact_age,
            inject harness message
  hard    — mark the tool call failed, require re-run
"""

from api.db.known_facts import get_fact
from api.facts.tool_extractors import extract_facts_from_tool_result


def check_and_apply_rejection(
    tool_name: str,
    args: dict,
    result: dict,
    settings: dict,
) -> tuple[dict, list, str | None]:
    """
    Returns (possibly-modified result, harness_messages_to_inject, failure_reason).

    If mode is 'hard' and rejection fires, returns a failure sentinel
    in place of result so the caller can mark the tool call failed.
    """
    mode = settings.get('factAgeRejectionMode', 'medium')
    if mode == 'off':
        return result, [], None

    max_age_min = settings.get('factAgeRejectionMaxAgeMin', 5)
    min_conf = settings.get('factAgeRejectionMinConfidence', 0.85)

    # Extract what this tool thinks the facts are
    proposed = extract_facts_from_tool_result(tool_name, args, result)
    if not proposed:
        return result, [], None

    harness_msgs = []
    rejections = []

    for p in proposed:
        known_rows = get_fact(p['fact_key'])
        # Filter to recently-verified high-confidence rows from non-agent sources
        recent = [
            r for r in known_rows
            if r['source'] != 'agent_observation'
            and r['confidence'] >= min_conf
            and _age_minutes(r['last_verified']) <= max_age_min
        ]
        if not recent:
            continue
        # Take the highest-confidence recent row as the authoritative one
        best = max(recent, key=lambda r: r['confidence'])
        if best['fact_value'] == p['value']:
            # Agreement. No rejection.
            continue

        # DISAGREEMENT: the tool says X, known_facts says Y (fresh + high conf)
        rejections.append({
            'fact_key':          p['fact_key'],
            'tool_value':        p['value'],
            'known_value':       best['fact_value'],
            'known_source':      best['source'],
            'known_confidence':  best['confidence'],
            'known_age_min':     _age_minutes(best['last_verified']),
        })

    if not rejections:
        return result, [], None

    # Apply mode
    if mode == 'soft':
        harness_msgs.append(_format_advisory(tool_name, rejections))
        return result, harness_msgs, None

    if mode == 'hard':
        return None, [_format_failure(tool_name, rejections)], 'fact_age_rejection'

    # Medium (default): strip conflicting values, add _rejected_by_fact_age,
    # inject harness advisory
    modified = _deep_copy(result)
    _strip_conflicting_values(modified, rejections)
    modified.setdefault('_rejected_by_fact_age', []).extend(rejections)
    harness_msgs.append(_format_medium_advisory(tool_name, rejections))
    return modified, harness_msgs, None


def _strip_conflicting_values(result: dict, rejections: list):
    """
    Best-effort walk of result.data looking for values that match the
    tool-reported values in the rejection list. Replace with a sentinel
    string '[REJECTED_BY_FACT_AGE]'.

    For structured results (service_placement etc.), we know the path:
      result.data.containers[*].node for placement
      result.data.brokers[*].host for broker status
      etc.

    Use tool_name-specific stripping functions. For unknown shapes,
    leave result unchanged and rely on the harness message alone.
    """


def _format_medium_advisory(tool_name: str, rejections: list) -> str:
    lines = [
        f"[harness] Fact-age rejection fired on `{tool_name}` results. "
        f"The tool reported values that contradict high-confidence facts "
        f"verified within the last few minutes. The conflicting values have "
        f"been stripped from the tool output you see."
    ]
    for r in rejections[:5]:
        lines.append(
            f"  - {r['fact_key']}: tool said {_short(r['tool_value'])}, "
            f"known_facts says {_short(r['known_value'])} "
            f"(source {r['known_source']}, conf {r['known_confidence']:.2f}, "
            f"age {r['known_age_min']}min)"
        )
    lines.append(
        "If you believe the known fact is stale (e.g. something just changed), "
        "call the verification tool specifically for that entity. Do NOT cite "
        "the rejected value in your final answer."
    )
    return "\n".join(lines)


def _format_advisory(tool_name: str, rejections: list) -> str:
    """Soft mode: advisory only, no stripping."""
    lines = [
        f"[harness] Advisory: `{tool_name}` reported values that conflict "
        f"with high-confidence recent facts. The tool output is unchanged, "
        f"but verify before citing:"
    ]
    for r in rejections[:5]:
        lines.append(
            f"  - {r['fact_key']}: tool says {_short(r['tool_value'])}, "
            f"known says {_short(r['known_value'])}"
        )
    return "\n".join(lines)


def _format_failure(tool_name: str, rejections: list) -> str:
    """Hard mode: tool call marked failed."""
    return (
        f"[harness] Hard fact-age rejection on `{tool_name}`. "
        f"{len(rejections)} fact(s) contradicted by high-confidence recent data. "
        f"Tool result not returned. Either accept the known_facts values or "
        f"call a different verification path."
    )


def _age_minutes(last_verified) -> float:
    from datetime import datetime, timezone
    if isinstance(last_verified, str):
        last_verified = datetime.fromisoformat(last_verified.replace('Z', '+00:00'))
    return (datetime.now(timezone.utc) - last_verified).total_seconds() / 60


def _short(v, n=60):
    import json
    s = json.dumps(v) if not isinstance(v, str) else v
    return s[:n] + ('…' if len(s) > n else '')
```

## Change 2 — wire into tool-result handler

In `api/routers/agent.py`, after each tool executes and before the
result is added to the conversation, apply the rejection check:

```python
from api.agents.fact_age_rejection import check_and_apply_rejection

# After tool call completes:
modified_result, rejection_harness_msgs, failure_reason = check_and_apply_rejection(
    tool_name=tc.function.name,
    args=parsed_args,
    result=tool_result,
    settings=_get_facts_settings(),
)

if failure_reason == 'fact_age_rejection':
    # Hard mode: mark the tool call as failed
    tool_result = {
        'status': 'error',
        'error_type': 'fact_age_rejection',
        'message': rejection_harness_msgs[0],
    }
else:
    tool_result = modified_result  # None if mode=off, or modified/unchanged otherwise
    # (check_and_apply_rejection returns the original if no rejection fired)

# Inject harness messages
for msg in rejection_harness_msgs:
    state.queued_harness_messages.append(msg)
    FACT_AGE_REJECTIONS_COUNTER.labels(
        mode=settings.get('factAgeRejectionMode'),
        source_rejected='agent_tool',
    ).inc()
```

Also proceed with existing `on_tool_result(state, ...)` so in-run
contradiction detection (v2.35.2) still runs on whatever the agent sees.
The rejected facts are in `_rejected_by_fact_age` so they don't corrupt
`state.run_facts`.

## Change 3 — gate-detection expansion

Extend `api/agents/gate_detection.py` + `gui/src/utils/gateDetection.js`:

```python
gates["fact_age_rejection"] = {"count": 0, "details": []}
for s in steps:
    for m in s.get("messages_delta", []):
        c = m.get("content", "")
        if "[harness] Fact-age rejection" in c or "[harness] Hard fact-age" in c:
            gates["fact_age_rejection"]["count"] += 1
            gates["fact_age_rejection"]["details"].append(
                {"step": s["step_index"], "snippet": c[:180]}
            )
```

## Change 4 — Prometheus

```python
FACT_AGE_REJECTIONS_COUNTER = Counter(
    "deathstar_fact_age_rejections_total",
    "Tool results modified or blocked due to disagreement with recent facts",
    ["mode", "source_rejected"],  # mode: soft|medium|hard, source: agent_tool
)
```

## Change 5 — settings

Already declared in v2.35.0 (shipped with defaults off). v2.35.3 just
starts enforcing them:

- `factAgeRejectionMode` = `medium`
- `factAgeRejectionMaxAgeMin` = 5
- `factAgeRejectionMinConfidence` = 0.85

## Change 6 — tests

`tests/test_fact_age_rejection.py`:

- mode=off: tool result pass-through regardless of contradictions
- mode=soft: result unchanged, harness message emitted
- mode=medium: conflicting values stripped, `_rejected_by_fact_age` field
  populated, harness message emitted
- mode=hard: tool result replaced with error sentinel
- No-recent-fact scenario: tool result pass-through (no rejection)
- Agreement scenario: no rejection
- Low-confidence existing fact: no rejection (threshold not met)
- Stale existing fact (>max_age_min): no rejection (age not met)

## Change 7 — trace visibility

Rejection events appear in Logs → Trace as harness system messages.
Gates Fired sidebar shows `✓ fact_age_rejection xN`.

Add a "Why was this value stripped?" inspectable view on the tool-result
pane: if a result has `_rejected_by_fact_age`, render a small banner
with the details.

## Commit

```
git add -A
git commit -m "feat(agents): v2.35.3 fact-age rejection (Medium mode default)"
git push origin main
```

## Test after deploy

1. Seed a synthetic scenario: manually `UPDATE known_facts_current SET fact_value='"192.168.199.33"', last_verified=NOW() WHERE fact_key='prod.kafka.broker.3.host' AND source='proxmox_collector'` to set a fresh high-conf fact.
2. Force a tool result that disagrees: craft a test task that exercises `kafka_broker_status`, stub the result to return `host: "10.0.4.17"` for broker 3. (Or just run against a dev instance and inject via monkey-patch.)
3. Observe: trace shows the tool result with `_rejected_by_fact_age` and a harness message. Agent's final_answer does NOT cite `10.0.4.17`.
4. Settings → Facts & Knowledge → flip mode to `soft`. Re-run. Now the tool result is unchanged but the advisory harness message still appears.
5. Flip to `hard`. Re-run. Tool call returns `status=error, error_type=fact_age_rejection`.
6. `/metrics | grep fact_age_rejections_total` shows counter incrementing.

## Non-goals

- Automatic re-verification when rejection fires (agent must decide to re-verify).
- Cross-source fact-age rejection (only known_facts.source != agent_observation is considered authoritative).

## Risk register

- Overly-aggressive stripping may hide genuine changes. Medium mode is a compromise — the original value is preserved in `_rejected_by_fact_age` so operators can review.
- If the collector itself is buggy (bad fact) and the tool is right, medium mode will hide the truth. Mitigation: Settings gives the operator the kill-switch (off or soft).
- Hard mode failure reason may trip retry logic. Flag `error_type=fact_age_rejection` is distinct so retry policies can skip rather than loop.
