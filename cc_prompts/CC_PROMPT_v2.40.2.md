# CC PROMPT — v2.40.2 — feat(agents): enrich external AI prerun context with entity history

## What this does

`_build_prerun_external_context()` currently gives external AI only
known_facts + preflight facts. For entities with recent activity (restarts,
status changes, errors in the last 24h), the entity_history table has high-
signal evidence that is more actionable than stale facts.

The agent loop already injects entity history into the local system prompt
(line ~4181 in agent.py). This prompt reuses the same logic inside
`_build_prerun_external_context` so external AI gets it too.

Version bump: 2.40.1 → 2.40.2.

---

## Change 1 — `api/routers/agent.py` — enrich _build_prerun_external_context

Locate `_build_prerun_external_context`. Add a third section after the
existing known_facts block. The function currently ends with:

```python
    if not parts:
        return ""

    header = (
        "NOTE: The following facts were gathered by infrastructure collectors "
        "and represent current known state. Use this as your primary evidence. "
        "Do NOT invent values not present here.\n\n"
    )
    return header + "\n\n".join(parts)
```

Replace with:

```python
    # 3. Entity history — recent changes and events for preflight candidates
    try:
        from api.db.entity_history import get_recent_changes_summary, get_events
        from api.agents.preflight import tier1_regex_extract

        candidates = tier1_regex_extract(task)
        entity_ids = [c.entity_id for c in candidates[:5]]  # cap to avoid bloat

        history_lines: list[str] = []
        for eid in entity_ids:
            summary = get_recent_changes_summary(eid, hours=24)
            if summary:
                history_lines.append(f"  {eid}: {summary}")
            warn_events = get_events(eid, hours=24, severity="warning", limit=2)
            crit_events = get_events(eid, hours=24, severity="critical", limit=2)
            for ev in (crit_events + warn_events):
                ev_str = ev.get("description") or ev.get("event_type", "")
                if ev_str:
                    history_lines.append(f"  {eid} [{ev.get('severity','?')}]: {ev_str}")

        if history_lines:
            parts.append(
                "RECENT ENTITY ACTIVITY (last 24h):\n" + "\n".join(history_lines)
            )
    except Exception as _eh:
        log.debug("_build_prerun_external_context: entity history failed: %s", _eh)

    if not parts:
        return ""

    header = (
        "NOTE: The following facts and recent activity were gathered by "
        "infrastructure collectors and represent current known state. "
        "Use this as your primary evidence. "
        "Do NOT invent values not present here.\n\n"
    )
    return header + "\n\n".join(parts)
```

---

## Version bump

Update `VERSION` file: `2.40.1` → `2.40.2`

---

## Commit

```
git add -A
git commit -m "feat(agents): v2.40.2 enrich external AI prerun context with entity history"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
