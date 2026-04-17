"""log_timeline — unified chronological view of everything that happened to an entity.

Merges events from operation_log, agent_actions, entity_changes + entity_events,
and Elasticsearch logs into a single time-sorted list with a normalised schema.

Sync by project convention — see .claude/rules/python.md and CLAUDE.md.
"""
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Any

log = logging.getLogger(__name__)

EVENT_SCHEMA = (
    "ts: ISO8601 UTC timestamp | "
    "source: operation_log|agent_action|entity_history|elastic | "
    "kind: tool_call|plan_executed|state_change|drift|log_line|error | "
    "actor: who/what caused it | "
    "summary: one-line description | "
    "detail: structured source-specific fields"
)


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ok(data: Any, message: str = "OK") -> dict:
    return {"status": "ok", "data": data, "timestamp": _ts(), "message": message}


def _err(message: str, data: Any = None) -> dict:
    return {"status": "error", "data": data, "timestamp": _ts(), "message": message}


def _is_pg() -> bool:
    return "postgres" in os.environ.get("DATABASE_URL", "")


def _to_iso(v) -> str:
    if v is None:
        return ""
    if hasattr(v, "isoformat"):
        try:
            return v.isoformat()
        except Exception:
            return str(v)
    return str(v)


def _resolve_entity_hints(entity_id: str) -> dict:
    """Best-effort extraction of (name, host, service) from entity_id + resolver.

    entity_id is free-form — the prompt suggests `platform:name:id` but existing
    infra uses mixed formats. We take the most informative token as `name`, then
    try resolve_entity() for a canonical label, hostname, and IP.
    """
    hints = {"name": "", "host": "", "service": ""}
    if not entity_id:
        return hints

    parts = [p for p in entity_id.split(":") if p]
    if parts:
        hints["name"] = parts[1] if len(parts) >= 2 else parts[0]

    try:
        from api.db.infra_inventory import resolve_entity as _re
        resolved = _re(hints["name"] or entity_id) or {}
        if resolved.get("found"):
            hints["name"] = resolved.get("canonical_label") or hints["name"]
            hints["host"] = (resolved.get("hostname") or "").strip()
            ips = resolved.get("ips") or []
            if not hints["host"] and ips:
                hints["host"] = ips[0]
    except Exception as e:
        log.debug("resolve_entity_hints: %s", e)

    return hints


def _from_operation_log(entity_id: str, name: str, since_iso: str, limit: int) -> list[dict]:
    """Query operation_log rows referencing this entity.

    The table is SQLite-style TEXT timestamps + TEXT metadata JSON, so we match
    by substring against session_id / content / metadata.
    """
    rows: list[dict] = []
    try:
        from api.db.base import get_sync_engine
        from sqlalchemy import text as _t
        needle = (name or entity_id).lower()
        if not needle:
            return []
        like = f"%{needle}%"
        eng = get_sync_engine()
        with eng.connect() as c:
            rs = c.execute(_t("""
                SELECT id, session_id, type, content, metadata, timestamp
                FROM operation_log
                WHERE timestamp >= :since
                  AND (lower(COALESCE(content, '')) LIKE :like
                       OR lower(COALESCE(metadata, '')) LIKE :like
                       OR lower(session_id) LIKE :like)
                ORDER BY timestamp DESC
                LIMIT :limit
            """), {"since": since_iso, "like": like, "limit": limit})
            rows = [dict(r._mapping) for r in rs.fetchall()]
    except Exception as e:
        log.debug("log_timeline._from_operation_log failed: %s", e)
        return []

    out = []
    for r in rows:
        md = r.get("metadata")
        if isinstance(md, str):
            try:
                md = json.loads(md) if md else {}
            except Exception:
                md = {"raw": md[:200]}
        out.append({
            "ts":      _to_iso(r.get("timestamp")),
            "source":  "operation_log",
            "kind":    r.get("type") or "tool_call",
            "actor":   f"session:{r.get('session_id', '')[:12]}",
            "summary": (r.get("content") or "")[:160],
            "detail":  {"type": r.get("type"), "metadata": md},
        })
    return out


def _from_agent_actions(entity_id: str, name: str, since_iso: str, limit: int) -> list[dict]:
    """Query agent_actions audit rows (destructive tool calls).

    Schema: tool_name, args_redacted (JSONB), result_status, result_summary,
    blast_radius, owner_user, session_id, timestamp.
    """
    try:
        from api.db.agent_actions import list_actions
    except Exception as e:
        log.debug("log_timeline: agent_actions module not importable: %s", e)
        return []

    needle = (name or entity_id or "").lower()
    try:
        rows = list_actions(since_iso=since_iso, limit=limit) or []
    except Exception as e:
        log.debug("log_timeline: list_actions failed: %s", e)
        return []

    out = []
    for r in rows:
        args = r.get("args_redacted") or {}
        args_text = json.dumps(args, default=str).lower() if not isinstance(args, str) else args.lower()
        if needle and needle not in args_text and needle not in (r.get("tool_name", "") or "").lower():
            continue
        tool = r.get("tool_name", "?")
        radius = r.get("blast_radius", "unknown")
        status = r.get("result_status", "?")
        out.append({
            "ts":      _to_iso(r.get("timestamp")),
            "source":  "agent_action",
            "kind":    "plan_executed",
            "actor":   f"user:{r.get('owner_user', '?')} session:{(r.get('session_id') or '')[:12]}",
            "summary": f"{tool} [radius={radius}] -> {status}",
            "detail":  {
                "tool": tool,
                "args": args,
                "blast_radius": radius,
                "status": status,
                "summary": r.get("result_summary", ""),
            },
        })
    return out


def _from_entity_history(entity_id: str, hours: int, limit: int) -> list[dict]:
    """Pull entity_changes and entity_events for the entity within the window."""
    out: list[dict] = []
    try:
        from api.db.entity_history import get_changes, get_events
    except Exception as e:
        log.debug("log_timeline: entity_history module not importable: %s", e)
        return []

    try:
        changes = get_changes(entity_id, hours=hours, limit=limit) or []
    except Exception as e:
        log.debug("log_timeline: get_changes failed: %s", e)
        changes = []
    for c in changes:
        field = c.get("field_name", "?")
        out.append({
            "ts":      _to_iso(c.get("detected_at")),
            "source":  "entity_history",
            "kind":    "state_change",
            "actor":   c.get("source_collector") or "collector",
            "summary": f"{field}: {c.get('old_value')} -> {c.get('new_value')}",
            "detail":  c,
        })

    try:
        events = get_events(entity_id, hours=hours, limit=limit) or []
    except Exception as e:
        log.debug("log_timeline: get_events failed: %s", e)
        events = []
    for e in events:
        etype = e.get("event_type") or ""
        kind = "drift" if "drift" in etype or "config" in etype or "digest" in etype else "state_change"
        out.append({
            "ts":      _to_iso(e.get("occurred_at")),
            "source":  "entity_history",
            "kind":    kind,
            "actor":   e.get("source_collector") or "collector",
            "summary": f"[{e.get('severity', 'info')}] {etype}: {e.get('description', '')}"[:160],
            "detail":  e,
        })

    return out


def _from_elastic(host: str, service: str, name: str, minutes: int, limit: int) -> list[dict]:
    """Elasticsearch log slice for the entity's host/service."""
    try:
        from mcp_server.tools import elastic as _el
    except Exception as e:
        log.debug("log_timeline: elastic module not importable: %s", e)
        return []

    if not _el._es_url():
        return []

    since = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    must: list[dict] = [{"range": {"@timestamp": {"gte": since}}}]

    host_filter = host or name
    if host_filter:
        must.append({"bool": {"should": [
            {"wildcard": {"host.name": f"*{host_filter}*"}},
            {"wildcard": {"container.name": f"*{host_filter}*"}},
        ], "minimum_should_match": 1}})
    if service:
        must.append({"wildcard": {
            "docker.container.labels.com.docker.swarm.service.name": f"*{service}*"
        }})

    body = {
        "query": {"bool": {"must": must}},
        "sort":  [{"@timestamp": {"order": "desc"}}],
        "size":  min(int(limit), 500),
        "_source": [
            "@timestamp", "message", "log.level", "level",
            "host.name", "container.name",
            "docker.container.labels.com.docker.swarm.service.name",
        ],
    }

    try:
        resp = _el._post(f"/{_el._index()}/_search", body)
    except Exception as e:
        return [{
            "ts":      _ts(),
            "source":  "elastic",
            "kind":    "error",
            "actor":   "log_timeline",
            "summary": f"elastic query failed: {e}",
            "detail":  {},
        }]

    out = []
    for hit in (resp.get("hits", {}).get("hits", []) or []):
        src = hit.get("_source", {}) or {}
        out.append({
            "ts":      src.get("@timestamp") or "",
            "source":  "elastic",
            "kind":    "log_line",
            "actor":   (src.get("host", {}) or {}).get("name")
                       or (src.get("container", {}) or {}).get("name")
                       or "?",
            "summary": (src.get("message") or "")[:160],
            "detail":  {
                "level": (src.get("log", {}) or {}).get("level") or src.get("level"),
                "index": hit.get("_index"),
            },
        })
    return out


def log_timeline(
    entity_id: str,
    window_minutes: int = 60,
    sources: list | None = None,
    limit: int = 200,
) -> dict:
    """Return a unified event timeline for an entity.

    entity_id:       Free-form entity identifier (e.g. "proxmox:worker-03:9203",
                     "swarm:service:kafka_broker-1", or a vm_host label).
    window_minutes:  Look-back window. Default 60. Capped to [1, 1440].
    sources:         Subset of {operation_log, agent_action, entity_history, elastic}.
                     None = all.
    limit:           Max events per source. Default 200.
    """
    try:
        window_minutes = int(window_minutes)
    except Exception:
        window_minutes = 60
    window_minutes = max(1, min(window_minutes, 1440))

    try:
        limit = int(limit)
    except Exception:
        limit = 200
    limit = max(1, min(limit, 500))

    since_dt = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
    since_iso = since_dt.isoformat()
    hours = max(1, (window_minutes + 59) // 60)

    valid = {"operation_log", "agent_action", "entity_history", "elastic"}
    if sources:
        sources = [s for s in sources if s in valid]
    if not sources:
        sources = sorted(valid)
    sources_set = set(sources)

    hints = _resolve_entity_hints(entity_id)
    name = hints["name"]
    host = hints["host"]
    service = hints["service"]

    events: list[dict] = []

    if "operation_log" in sources_set:
        try:
            events.extend(_from_operation_log(entity_id, name, since_iso, limit))
        except Exception as e:
            log.debug("log_timeline: operation_log branch failed: %s", e)

    if "agent_action" in sources_set:
        try:
            events.extend(_from_agent_actions(entity_id, name, since_iso, limit))
        except Exception as e:
            log.debug("log_timeline: agent_action branch failed: %s", e)

    if "entity_history" in sources_set:
        try:
            events.extend(_from_entity_history(entity_id, hours, limit))
        except Exception as e:
            log.debug("log_timeline: entity_history branch failed: %s", e)

    if "elastic" in sources_set and (host or service or name):
        try:
            events.extend(_from_elastic(host, service, name, window_minutes, limit))
        except Exception as e:
            log.debug("log_timeline: elastic branch failed: %s", e)

    events.sort(key=lambda e: e.get("ts") or "", reverse=True)
    events = events[: limit * 2]

    data = {
        "entity_id":       entity_id,
        "window_minutes":  window_minutes,
        "sources_queried": sorted(sources_set),
        "hints":           hints,
        "total":           len(events),
        "events":          events,
        "schema_note":     EVENT_SCHEMA,
    }
    msg = f"{len(events)} event(s) on {entity_id!r} in last {window_minutes}min"
    return _ok(data, msg)
