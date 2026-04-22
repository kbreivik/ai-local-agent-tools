# CC PROMPT — v2.39.4 — feat(agents): skill preflight prompt snapshots + Prometheus counter

## What this does

Follow-up to v2.39.3. Two hardening items:

1. Snapshot CI guard: update `tests/snapshots/prompts/` to include the
   new DYNAMIC SKILLS text so `test_prompt_snapshots.py` doesn't break CI.
   The v2.39.3 DYNAMIC SKILLS change is a string replacement — snapshots
   must reflect it.

2. Prometheus counter: `deathstar_preflight_skills_total{outcome}` with
   labels `matched` (N>0 skills returned) / `empty` (no matches) / `error`
   (exception in list_skills). Surfaces adoption and failure rate in metrics.

3. Emit a preflight WebSocket event for skill count — extends the existing
   `preflight` WS broadcast to include `skills_matched: N` so the Preflight
   Panel in the UI can show how many skills were pre-matched.

Version bump: 2.39.3 → 2.39.4.

---

## Change 1 — `api/agents/preflight.py` — add counter to preflight_skills()

Locate the `preflight_skills` function added in v2.39.3. Find the `return ""`
statements and the final `return "\n".join(lines)`. Wrap them with counter calls.

After the `from mcp_server.tools.skills.registry import list_skills` try/except,
add a helper at the top of the function body:

```python
    def _bump(outcome: str) -> None:
        try:
            from api.metrics import PREFLIGHT_SKILLS_COUNTER
            PREFLIGHT_SKILLS_COUNTER.labels(outcome=outcome).inc()
        except Exception:
            pass
```

Replace each bare `return ""` in the function with:

```python
        _bump("error")   # or "empty" — see below
        return ""
```

Specifically:
- The `except Exception` path → `_bump("error"); return ""`
- The `if not skills: return ""` → `_bump("empty"); return ""`
- The `if not top: return ""` → `_bump("empty"); return ""`
- The final `return "\n".join(lines)` → `_bump("matched"); return "\n".join(lines)`

---

## Change 2 — `api/metrics.py` — register new counter

Locate the file and add after the existing PREFLIGHT counters:

```python
PREFLIGHT_SKILLS_COUNTER = Counter(
    "deathstar_preflight_skills_total",
    "Skill preflight outcomes",
    ["outcome"],   # matched | empty | error
)
```

---

## Change 3 — `api/routers/agent.py` — extend preflight WS broadcast with skills_matched

Locate the existing preflight WebSocket broadcast inside `_stream_agent`:

```python
            await manager.broadcast({
                "type": "preflight",
                "session_id": session_id,
                "operation_id": operation_id,
                "preflight": _preflight_result.as_dict(),
```

Add `skills_matched` to the broadcast payload:

```python
            await manager.broadcast({
                "type": "preflight",
                "session_id": session_id,
                "operation_id": operation_id,
                "preflight": _preflight_result.as_dict(),
                "skills_matched": len([
                    ln for ln in _preflight_skills_block.splitlines()
                    if ln.startswith("- ")
                ]) if _preflight_skills_block else 0,
```

---

## Change 4 — Update prompt snapshots

CC must regenerate the prompt snapshots. Run:

```bash
cd /d/claude_code/ai-local-agent-tools
python -m pytest tests/test_prompt_snapshots.py --snapshot-update -x
```

If that command is not available, manually update
`tests/snapshots/prompts/observe_prompt.txt`,
`tests/snapshots/prompts/investigate_prompt.txt`,
`tests/snapshots/prompts/execute_prompt.txt`, and
`tests/snapshots/prompts/build_prompt.txt`
to replace the old DYNAMIC SKILLS text with the new version from v2.39.3.

---

## Version bump

Update `VERSION` file: `2.39.3` → `2.39.4`

---

## Commit

```
git add -A
git commit -m "feat(agents): v2.39.4 skill preflight Prometheus counter + WS event + snapshot update"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
