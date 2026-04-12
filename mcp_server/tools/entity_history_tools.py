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
