# CC PROMPT — v2.9.1 — Entity History Agent Tools + Context Injection

## What this does

Builds on the v2.9.0 DB layer by exposing entity history to the agent and GUI:

1. **Two new agent tools** — `entity_history` and `entity_events` let the agent
   answer "what changed on agent-01 today?" or "how many times did this container
   restart?" with one tool call and real data.

2. **Automatic context injection** — when the agent task mentions a known entity,
   recent changes and events are injected into the system prompt so the agent
   already knows about them before calling any tools.

3. **GUI entity drawer badge** — entity cards show a "3 changes" or "5 events"
   badge when recent activity is present, clickable to expand the history.

Version bump: 2.9.0 → 2.9.1 (tooling + GUI on top of the DB layer)

---

## Change 1 — mcp_server/tools/entity_history_tools.py (NEW FILE)

```python
"""Agent tools for querying entity change history and event log.

Built on entity_changes and entity_events tables from api/db/entity_history.py.
Use these tools to answer questions about what changed, when, and how often.
"""
from datetime import datetime, timezone

def _ts(): return datetime.now(timezone.utc).isoformat()
def _ok(data, msg=""): return {"status":"ok","data":data,"message":msg,"timestamp":_ts()}
def _err(msg): return {"status":"error","data":None,"message":msg,"timestamp":_ts()}


def entity_history(entity_id: str, hours: int = 24, field: str = "") -> dict:
    """Get field-level change history for an infrastructure entity.

    Returns what changed (old → new values) for the entity within the time window.
    Use to answer: "what changed on agent-01 today?", "did the OS version change?",
    "when did Docker get updated on this host?"

    Args:
        entity_id: Entity identifier. For VM hosts: use the label (e.g. "hp1-ai-agent-lab").
                   For swarm services: "swarm:service:kafka_broker-1".
        hours:     Look-back window in hours (default 24, max 720 = 30 days).
        field:     Optional: filter to a specific field name (e.g. "os", "docker_version",
                   "image_digest"). Leave blank to return all changed fields.
    """
    try:
        from api.db.entity_history import get_changes
        changes = get_changes(entity_id, hours=int(hours),
                              field_name=field, limit=50)
        if not changes:
            return _ok({"changes": [], "count": 0},
                       f"No changes recorded for {entity_id!r} in last {hours}h")

        # Build readable diff list
        diffs = []
        for c in changes:
            diffs.append({
                "field":     c["field_name"],
                "old":       c.get("old_value"),
                "new":       c["new_value"],
                "when":      str(c.get("detected_at", ""))[:19],
                "collector": c.get("source_collector", ""),
            })

        return _ok({
            "entity_id": entity_id,
            "hours":     hours,
            "count":     len(changes),
            "changes":   diffs,
        }, f"{len(changes)} change(s) on {entity_id!r} in last {hours}h")
    except Exception as e:
        return _err(f"entity_history error: {e}")


def entity_events(
    entity_id: str,
    hours: int = 24,
    event_type: str = "",
    severity: str = "",
) -> dict:
    """Get named event log for an infrastructure entity.

    Returns discrete events like restarts, version changes, digest changes,
    threshold crossings. Use to answer: "how many times did this container restart?",
    "was there a disk threshold warning on agent-01?", "did any image silently update?"

    Args:
        entity_id:  Entity identifier (same format as entity_history).
        hours:      Look-back window in hours (default 24).
        event_type: Filter by event type, e.g. "image_digest_change",
                    "version_change", "disk_threshold_crossed", "container_restart".
                    Leave blank for all event types.
        severity:   Filter by severity: info | warning | error | critical.
    """
    try:
        from api.db.entity_history import get_events
        events = get_events(entity_id, hours=int(hours),
                            event_type=event_type, severity=severity, limit=50)
        if not events:
            return _ok({"events": [], "count": 0},
                       f"No events for {entity_id!r} in last {hours}h"
                       + (f" (type={event_type})" if event_type else ""))

        items = []
        for ev in events:
            items.append({
                "type":        ev["event_type"],
                "severity":    ev["severity"],
                "description": ev["description"],
                "when":        str(ev.get("occurred_at", ""))[:19],
                "collector":   ev.get("source_collector", ""),
            })

        # Count by severity for quick summary
        by_severity = {}
        for ev in items:
            s = ev["severity"]
            by_severity[s] = by_severity.get(s, 0) + 1

        return _ok({
            "entity_id":   entity_id,
            "hours":       hours,
            "count":       len(events),
            "by_severity": by_severity,
            "events":      items,
        }, f"{len(events)} event(s) on {entity_id!r} in last {hours}h")
    except Exception as e:
        return _err(f"entity_events error: {e}")
```

---

## Change 2 — api/agents/router.py — add to allowlists

Add `"entity_history"` and `"entity_events"` to:
- `OBSERVE_AGENT_TOOLS`
- `INVESTIGATE_AGENT_TOOLS`
- `EXECUTE_GENERAL_TOOLS`
- `EXECUTE_SWARM_TOOLS`

Add to `STATUS_PROMPT` in the VM HOST COMMANDS section:

```
ENTITY HISTORY TOOLS:
Use entity_history(entity_id=..., hours=24) to see what fields changed recently.
Use entity_events(entity_id=..., hours=24) to see discrete events (restarts, version
changes, image digest changes, disk threshold crossings).
entity_id format: VM hosts use their label (e.g. "hp1-ai-agent-lab"),
  Swarm services use "swarm:service:<name>".
These tools answer "what changed?" questions without additional SSH commands.
```

---

## Change 3 — api/routers/agent.py — context injection for known entities

In `_stream_agent()`, after the domain capability injection block (the vm_host block),
add entity history injection:

```python
    # ── Entity history context injection ──────────────────────────────────────
    # If task mentions a known entity, inject recent changes/events as context
    try:
        from api.db.entity_history import get_recent_changes_summary, get_events
        from api.db.infra_inventory import resolve_host

        # Try to identify the entity from the task text
        _entity_hints = []
        task_words = task.split()
        for word in task_words:
            if len(word) < 4:
                continue
            entry = resolve_host(word)
            if entry:
                entity_id = entry.get("label", word)
                summary = get_recent_changes_summary(entity_id, hours=48)
                if summary:
                    _entity_hints.append(f"  {entity_id}: {summary}")
                # Also check for critical/warning events
                recent_events = get_events(entity_id, hours=48, severity="warning", limit=3)
                critical_events = get_events(entity_id, hours=48, severity="critical", limit=3)
                all_events = critical_events + recent_events
                if all_events:
                    ev_str = "; ".join(e["description"][:80] for e in all_events[:3])
                    _entity_hints.append(f"  {entity_id} events: {ev_str}")
                break   # one entity per task is enough

        if _entity_hints:
            history_hint = "RECENT ENTITY ACTIVITY (last 48h):\n" + "\n".join(_entity_hints) + "\n\n"
            system_prompt = history_hint + system_prompt
    except Exception:
        pass
```

---

## Change 4 — api/routers/dashboard.py (or equivalent) — entity history endpoint

Add an endpoint that the GUI can call to get a combined history+events summary for
an entity drawer:

```python
@router.get("/entity-history/{entity_id}")
async def entity_history_summary(
    entity_id: str,
    hours: int = Query(24, ge=1, le=720),
    _: str = Depends(get_current_user),
):
    """Combined change + event summary for entity drawer / card badge."""
    from api.db.entity_history import get_changes, get_events
    changes = get_changes(entity_id, hours=hours, limit=20)
    events  = get_events(entity_id, hours=hours, limit=20)
    return {
        "entity_id": entity_id,
        "hours": hours,
        "change_count": len(changes),
        "event_count": len(events),
        "changes": changes[:10],
        "events":  events[:10],
        "has_critical": any(e["severity"] == "critical" for e in events),
        "has_warning":  any(e["severity"] == "warning"  for e in events),
    }
```

Mount this router in `api/main.py` if it's a new file, or add to `api/routers/dashboard.py`.

---

## Change 5 — GUI: entity card activity badge (gui/src/components/ServiceCards.jsx or VMHostsSection.jsx)

On each entity card, fetch `/api/dashboard/entity-history/{entity_id}?hours=24` once
on mount (or when the entity changes). If `change_count > 0` or `event_count > 0`,
show a small badge:

```jsx
// In the card header, alongside existing status badges:
{(historyData?.change_count > 0 || historyData?.event_count > 0) && (
  <span
    style={{
      fontSize: 8,
      fontFamily: 'var(--font-mono)',
      padding: '1px 5px',
      borderRadius: 2,
      background: historyData?.has_critical ? 'rgba(204,40,40,0.2)' :
                  historyData?.has_warning  ? 'rgba(204,136,0,0.15)' :
                  'var(--bg-3)',
      color: historyData?.has_critical ? 'var(--red)' :
             historyData?.has_warning  ? 'var(--amber)' : 'var(--text-3)',
      cursor: 'pointer',
    }}
    title={`${historyData.change_count} changes, ${historyData.event_count} events (24h)`}
    onClick={() => setShowHistory(true)}
  >
    {historyData.change_count + historyData.event_count} changes
  </span>
)}
```

The `showHistory` state can open a small inline panel below the card showing the
changes and events lists — same pattern as the EntityDrawer. Keep it simple for now:
a collapsible list of changes, then events.

---

## Version bump

Update VERSION: `2.9.0` → `2.9.1`

---

## Commit

```bash
git add -A
git commit -m "feat(agent+gui): v2.9.1 entity history tools and context injection

- New tools: entity_history() and entity_events() for agent direct querying
- Context injection: recent changes/events for mentioned entities prepended to prompt
- GET /api/dashboard/entity-history/{entity_id} for GUI badge data
- Entity card activity badge: shows change+event count with severity colour
- STATUS_PROMPT: ENTITY HISTORY TOOLS section added
- entity_history + entity_events added to all relevant agent allowlists"
git push origin main
```
