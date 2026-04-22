# CC PROMPT — v2.38.7 — fix(agents): enrich force-external prerun context from known_facts

## What this does

v2.38.6 shipped the force-external toggle but the first real test revealed that
external AI output was immediately rejected by the harness gate. Root cause:
`synthesize_replace` at prerun time receives only `[system_prompt, user_task]` as
the message history. `_flatten_openai_messages_to_text` skips the system role, so
`context_text` is just the task string — Claude Sonnet gets zero infrastructure
evidence and correctly responds "I don't have access to your infrastructure", which
the `preamble_only_completion` or `too_short_completion` gate discards.

Fix: when `force_external=True`, build a prerun context digest from the
infrastructure knowledge already available in `known_facts` and preflight facts,
and pass it to `synthesize_replace` as the `digest` parameter so Claude Sonnet
has real evidence to synthesise from.

Two-part change:
1. Add `_build_prerun_external_context()` helper in `api/routers/agent.py` that
   pulls top confident facts from `known_facts` + preflight facts block
2. Thread it through `_maybe_route_to_external_ai` → `synthesize_replace`

Version bump: 2.38.6 → 2.38.7.

---

## Change 1 — `api/routers/agent.py` — add _build_prerun_external_context helper

Add the following function immediately before `_maybe_route_to_external_ai`
(i.e. just before the `async def _maybe_route_to_external_ai(` line at ~801):

```python
def _build_prerun_external_context(
    task: str,
    preflight_facts_block: str = "",
    max_facts: int = 60,
) -> str:
    """Build a context digest for force-external prerun calls.

    synthesize_replace at prerun has no tool-call history to flatten —
    the message list is just [system_prompt, user_task]. This helper
    pulls real infrastructure state from known_facts so that external AI
    has evidence to synthesise from rather than responding 'I don't know'.

    Returns a formatted string injected as the `digest` param of
    synthesize_replace. Empty string on any failure (safe fallback).
    """
    parts: list[str] = []

    # 1. Preflight facts (entity-specific, highest signal)
    if preflight_facts_block and preflight_facts_block.strip():
        parts.append(preflight_facts_block.strip())

    # 2. Broad infra facts from known_facts — top confident rows
    try:
        from api.db.known_facts import get_confident_facts
        rows = get_confident_facts(min_confidence=0.7, max_rows=max_facts)
        if rows:
            lines = ["INFRASTRUCTURE STATE (from knowledge store):"]
            for r in rows:
                key = r.get("fact_key", "")
                val = r.get("fact_value", "")
                conf = r.get("confidence", 0.0)
                if isinstance(val, (list, dict)):
                    import json as _json
                    val = _json.dumps(val)
                lines.append(f"  {key} = {val}  (confidence={conf:.2f})")
            parts.append("\n".join(lines))
    except Exception as _e:
        log.debug("_build_prerun_external_context: known_facts query failed: %s", _e)

    if not parts:
        return ""

    header = (
        "NOTE: The following facts were gathered by infrastructure collectors "
        "and represent current known state. Use this as your primary evidence. "
        "Do NOT invent values not present here.\n\n"
    )
    return header + "\n\n".join(parts)
```

---

## Change 2 — `api/routers/agent.py` — _maybe_route_to_external_ai accepts prerun_digest

Locate the `_maybe_route_to_external_ai` signature:

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
    force: bool = False,
) -> str | None:
    """Run the v2.36.1 router. If it fires, gate on v2.36.2 confirmation and
    call the v2.36.3 external AI. Return the synthesis text on success,
    None on no-op, or raise a sentinel-failure string via ExternalAIError.

    Caller treats a non-None return as the final_answer (REPLACE mode).

    force=True (v2.38.6): skip router decision and confirmation modal entirely.
    Operator explicitly chose external AI — treat as pre-approved.
    """
```

Replace with:

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
```

Now locate the `synthesize_replace` call inside `_maybe_route_to_external_ai`.
It will look like:

```python
        result = await synthesize_replace(
            task=task,
            agent_type=agent_type,
            messages=messages,
```

Replace with:

```python
        result = await synthesize_replace(
            task=task,
            agent_type=agent_type,
            messages=messages,
            digest=prerun_digest or None,
```

---

## Change 3 — `api/routers/agent.py` — _stream_agent builds and passes prerun_digest

Locate the prerun `_maybe_route_to_external_ai` call (line ~4320):

```python
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
        )
```

Replace with:

```python
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
```

---

## Version bump

Update `VERSION` file: `2.38.6` → `2.38.7`

---

## Commit

```
git add -A
git commit -m "fix(agents): v2.38.7 enrich force-external prerun context from known_facts"
git push origin main
```

Then deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
