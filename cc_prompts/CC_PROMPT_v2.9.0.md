# CC PROMPT — v2.9.0 — Entity State DB Layer: Change Tracking + Event Log + Image Digest

## What this does

Adds permanent historical state tracking to the database. Collectors that previously
overwrote state now also write to two new tables:

- `entity_changes` — field-level audit trail: what changed, from what, to what, when
- `entity_events` — discrete named events: restarts, version changes, digest changes, thresholds

Also adds Docker image digest tracking to catch "same tag, different image" re-deploys.

This is the DB foundation phase. Agent tools and GUI integration follow in v2.9.1.

Version bump: 2.8.1 → 2.9.0 (new persistent data layer, minor x.1.x bump)

---

## Change 1 — api/db/entity_history.py (NEW FILE)

```python
"""Entity change and event tracking — append-only historical audit trail.

entity_changes: permanent record of field-level value changes.
  Written when a collector detects a field changed vs the prior snapshot.
  Never overwritten — full diff history preserved indefinitely.

entity_events: permanent discrete named events.
  Restarts, version changes, digest changes, threshold crossings.
  Severity-tagged for alert filtering.

Both tables are indexed for fast entity + time range queries.
Agent tools and GUI use these for "what changed" and "what happened" queries.
"""
import json
import logging
import os
import uuid
from datetime import datetime, timezone

log = logging.getLogger(__name__)

_DDL_PG = """
CREATE TABLE IF NOT EXISTS entity_changes (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id           TEXT NOT NULL,
    entity_type         TEXT NOT NULL,
    connection_id       TEXT,
    field_name          TEXT NOT NULL,
    old_value           TEXT,
    new_value           TEXT NOT NULL,
    detected_at         TIMESTAMPTZ DEFAULT NOW(),
    source_collector    TEXT,
    metadata            JSONB DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_entity_changes_entity  ON entity_changes(entity_id, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_entity_changes_field   ON entity_changes(field_name, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_entity_changes_time    ON entity_changes(detected_at DESC);

CREATE TABLE IF NOT EXISTS entity_events (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id           TEXT NOT NULL,
    entity_type         TEXT NOT NULL,
    connection_id       TEXT,
    event_type          TEXT NOT NULL,
    severity            TEXT NOT NULL DEFAULT 'info',
    description         TEXT NOT NULL,
    metadata            JSONB DEFAULT '{}',
    occurred_at         TIMESTAMPTZ DEFAULT NOW(),
    source_collector    TEXT
);
CREATE INDEX IF NOT EXISTS idx_entity_events_entity   ON entity_events(entity_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_entity_events_type     ON entity_events(event_type, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_entity_events_severity ON entity_events(severity, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_entity_events_time     ON entity_events(occurred_at DESC);
"""

_initialized = False


def _ts(): return datetime.now(timezone.utc).isoformat()
def _is_pg(): return "postgres" in os.environ.get("DATABASE_URL", "")


def init_entity_history() -> bool:
    """Create entity_changes and entity_events tables. Called from api/main.py."""
    global _initialized
    if _initialized: return True
    if not _is_pg():
        _initialized = True
        return True   # SQLite: skip, collectors will no-op gracefully
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        conn.autocommit = True
        cur = conn.cursor()
        for stmt in _DDL_PG.strip().split(";"):
            stmt = stmt.strip()
            if stmt: cur.execute(stmt)
        cur.close(); conn.close()
        _initialized = True
        log.info("entity_changes + entity_events tables ready")
        return True
    except Exception as e:
        log.warning("entity_history init failed: %s", e)
        return False


def write_change(
    *,
    entity_id: str,
    entity_type: str,
    field_name: str,
    old_value: str | None,
    new_value: str,
    connection_id: str = "",
    source_collector: str = "",
    metadata: dict | None = None,
) -> None:
    """Record a field-level change. Never raises."""
    if not _is_pg() or not entity_id or not field_name:
        return
    if old_value == new_value:
        return   # no-op if values are identical
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO entity_changes
                (id, entity_id, entity_type, connection_id, field_name,
                 old_value, new_value, detected_at, source_collector, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            str(uuid.uuid4()), entity_id, entity_type,
            connection_id or None, field_name,
            str(old_value) if old_value is not None else None,
            str(new_value),
            _ts(), source_collector or None,
            json.dumps(metadata or {}),
        ))
        conn.commit(); cur.close(); conn.close()
    except Exception as e:
        log.debug("write_change failed (non-fatal): %s", e)


def write_event(
    *,
    entity_id: str,
    entity_type: str,
    event_type: str,
    description: str,
    severity: str = "info",
    connection_id: str = "",
    source_collector: str = "",
    metadata: dict | None = None,
) -> None:
    """Record a discrete named event. Never raises.

    event_type examples:
      version_change, image_digest_change, container_restart,
      service_degraded, service_recovered, disk_threshold_crossed,
      new_ssh_host, config_change
    severity: info | warning | error | critical
    """
    if not _is_pg() or not entity_id or not event_type:
        return
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO entity_events
                (id, entity_id, entity_type, connection_id, event_type,
                 severity, description, metadata, occurred_at, source_collector)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            str(uuid.uuid4()), entity_id, entity_type,
            connection_id or None, event_type,
            severity, description[:500],
            json.dumps(metadata or {}),
            _ts(), source_collector or None,
        ))
        conn.commit(); cur.close(); conn.close()
    except Exception as e:
        log.debug("write_event failed (non-fatal): %s", e)


def get_changes(
    entity_id: str,
    hours: int = 24,
    field_name: str = "",
    limit: int = 50,
) -> list[dict]:
    """Query entity_changes for an entity within the last N hours."""
    if not _is_pg(): return []
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        sql = """
            SELECT field_name, old_value, new_value, detected_at, source_collector, metadata
            FROM entity_changes
            WHERE entity_id = %s
              AND detected_at >= NOW() - INTERVAL '%s hours'
        """
        params = [entity_id, hours]
        if field_name:
            sql += " AND field_name = %s"
            params.append(field_name)
        sql += " ORDER BY detected_at DESC LIMIT %s"
        params.append(limit)
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.close(); conn.close()
        for r in rows:
            if hasattr(r.get("detected_at"), "isoformat"):
                r["detected_at"] = r["detected_at"].isoformat()
            if isinstance(r.get("metadata"), str):
                try: r["metadata"] = json.loads(r["metadata"])
                except: pass
        return rows
    except Exception as e:
        log.debug("get_changes failed: %s", e)
        return []


def get_events(
    entity_id: str,
    hours: int = 24,
    event_type: str = "",
    severity: str = "",
    limit: int = 50,
) -> list[dict]:
    """Query entity_events for an entity within the last N hours."""
    if not _is_pg(): return []
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        sql = """
            SELECT event_type, severity, description, occurred_at,
                   source_collector, metadata
            FROM entity_events
            WHERE entity_id = %s
              AND occurred_at >= NOW() - INTERVAL '%s hours'
        """
        params = [entity_id, hours]
        if event_type:
            sql += " AND event_type = %s"; params.append(event_type)
        if severity:
            sql += " AND severity = %s"; params.append(severity)
        sql += " ORDER BY occurred_at DESC LIMIT %s"
        params.append(limit)
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.close(); conn.close()
        for r in rows:
            if hasattr(r.get("occurred_at"), "isoformat"):
                r["occurred_at"] = r["occurred_at"].isoformat()
            if isinstance(r.get("metadata"), str):
                try: r["metadata"] = json.loads(r["metadata"])
                except: pass
        return rows
    except Exception as e:
        log.debug("get_events failed: %s", e)
        return []


def get_recent_changes_summary(entity_id: str, hours: int = 24) -> str | None:
    """Return a compact one-line summary of recent changes for prompt injection.

    Example: "3 changes in 24h: os (12.6→12.7), docker_version (28.0→29.3.1)"
    Returns None if no changes found.
    """
    changes = get_changes(entity_id, hours=hours, limit=10)
    if not changes:
        return None
    parts = []
    for c in changes[:3]:
        old = c.get("old_value", "?")
        new = c.get("new_value", "?")
        field = c.get("field_name", "?")
        parts.append(f"{field} ({old}→{new})")
    n = len(changes)
    return f"{n} change{'s' if n > 1 else ''} in {hours}h: {', '.join(parts)}"
```

---

## Change 2 — api/db/entity_history.py — add get_last_known_values() helper

Add to the same file:

```python
def get_last_known_values(entity_id: str, fields: list[str]) -> dict[str, str | None]:
    """Return the most recent known value for each requested field.

    Used by collectors to check if a field changed since last poll.
    Queries entity_changes for the most recent new_value per field.
    Returns {field_name: last_value_or_None}.
    """
    if not _is_pg() or not entity_id or not fields:
        return {f: None for f in fields}
    try:
        from api.connections import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        # Use DISTINCT ON for efficient latest-per-field query
        cur.execute("""
            SELECT DISTINCT ON (field_name) field_name, new_value
            FROM entity_changes
            WHERE entity_id = %s AND field_name = ANY(%s)
            ORDER BY field_name, detected_at DESC
        """, (entity_id, fields))
        result = {f: None for f in fields}
        for row in cur.fetchall():
            result[row[0]] = row[1]
        cur.close(); conn.close()
        return result
    except Exception as e:
        log.debug("get_last_known_values failed: %s", e)
        return {f: None for f in fields}
```

---

## Change 3 — api/collectors/vm_hosts.py — instrument _poll_one_vm

After `upsert_entity(...)` succeeds in `_poll_one_vm`, add change detection:

```python
        # ── Change detection ──────────────────────────────────────────────────
        try:
            from api.db.entity_history import write_change, write_event, get_last_known_values

            _TRACKED_FIELDS = ["os", "kernel", "docker_version", "hostname"]
            last = get_last_known_values(label, _TRACKED_FIELDS)

            for field in _TRACKED_FIELDS:
                new_val = result.get(field, "")
                if not new_val:
                    continue
                old_val = last.get(field)
                if old_val and old_val != new_val:
                    write_change(
                        entity_id=label,
                        entity_type="vm_host",
                        field_name=field,
                        old_value=old_val,
                        new_value=new_val,
                        connection_id=str(conn.get("id", "")),
                        source_collector="vm_hosts",
                    )
                    # Version changes fire an event
                    if field in ("os", "kernel", "docker_version"):
                        write_event(
                            entity_id=label,
                            entity_type="vm_host",
                            event_type="version_change",
                            severity="warning",
                            description=f"{field} changed: {old_val} → {new_val}",
                            connection_id=str(conn.get("id", "")),
                            source_collector="vm_hosts",
                            metadata={"field": field, "old": old_val, "new": new_val},
                        )

            # Disk threshold events
            max_disk = max((d.get("usage_pct", 0) for d in result.get("disks", [])), default=0)
            if max_disk >= 90:
                write_event(
                    entity_id=label, entity_type="vm_host",
                    event_type="disk_threshold_crossed", severity="critical",
                    description=f"Disk usage at {max_disk}% on {label}",
                    connection_id=str(conn.get("id", "")),
                    source_collector="vm_hosts",
                    metadata={"usage_pct": max_disk},
                )
            elif max_disk >= 80:
                write_event(
                    entity_id=label, entity_type="vm_host",
                    event_type="disk_threshold_crossed", severity="warning",
                    description=f"Disk usage at {max_disk}% on {label}",
                    connection_id=str(conn.get("id", "")),
                    source_collector="vm_hosts",
                    metadata={"usage_pct": max_disk},
                )
        except Exception as _he:
            log.debug("entity_history write failed (non-fatal): %s", _he)
```

---

## Change 4 — api/collectors/swarm.py — image digest tracking

In `_collect_sync()`, when building `svc_data` for each service, extract and store
image digest alongside the tag:

```python
                # Separate tag from digest for change tracking
                image_full = container_spec.get("Image", "unknown")
                image_tag = image_full.split("@")[0]    # strip digest
                image_digest = ""
                if "@sha256:" in image_full:
                    image_digest = "sha256:" + image_full.split("@sha256:")[1][:16]  # short digest

                svc_data.append({
                    ...existing fields...,
                    "image_digest": image_digest,
                })
```

After writing svc_data, add change detection for image digests:

```python
        # ── Image digest change detection ─────────────────────────────────────
        try:
            from api.db.entity_history import write_change, write_event, get_last_known_values
            for svc in svc_data:
                name = svc.get("name", "")
                digest = svc.get("image_digest", "")
                if not digest or not name:
                    continue
                entity_id = f"swarm:service:{name}"
                last = get_last_known_values(entity_id, ["image_digest", "image_tag"])
                old_digest = last.get("image_digest")
                old_tag = last.get("image_tag")
                new_tag = svc.get("image", "")

                if old_digest and old_digest != digest:
                    write_change(
                        entity_id=entity_id, entity_type="swarm_service",
                        field_name="image_digest",
                        old_value=old_digest, new_value=digest,
                        source_collector="swarm",
                    )
                    severity = "info" if old_tag == new_tag else "warning"
                    description = (
                        f"Service {name}: image digest changed"
                        + (f" (tag unchanged: {new_tag})" if old_tag == new_tag else f" ({old_tag} → {new_tag})")
                    )
                    write_event(
                        entity_id=entity_id, entity_type="swarm_service",
                        event_type="image_digest_change",
                        severity=severity,
                        description=description,
                        source_collector="swarm",
                        metadata={"old_digest": old_digest, "new_digest": digest,
                                  "tag": new_tag, "silent": old_tag == new_tag},
                    )

                # Always write current state for next comparison
                write_change(
                    entity_id=entity_id, entity_type="swarm_service",
                    field_name="image_digest",
                    old_value=old_digest,  # None on first write
                    new_value=digest,
                    source_collector="swarm",
                ) if not old_digest else None

                if old_tag != new_tag and old_tag:
                    write_change(
                        entity_id=entity_id, entity_type="swarm_service",
                        field_name="image_tag",
                        old_value=old_tag, new_value=new_tag,
                        source_collector="swarm",
                    )
        except Exception as _de:
            log.debug("image digest tracking failed (non-fatal): %s", _de)
```

---

## Change 5 — api/main.py — init on startup

After `init_capabilities()` call, add:

```python
    from api.db.entity_history import init_entity_history
    init_entity_history()
```

---

## Change 6 — api/routers/logs.py — expose history endpoints

Add two endpoints:

```python
@router.get("/entity/{entity_id}/changes")
async def get_entity_changes(
    entity_id: str,
    hours: int = Query(24, ge=1, le=720),
    field_name: str = Query(""),
    limit: int = Query(50, ge=1, le=200),
    _: str = Depends(get_current_user),
):
    """Field-level change history for an entity."""
    from api.db.entity_history import get_changes
    return {"changes": get_changes(entity_id, hours=hours, field_name=field_name, limit=limit),
            "entity_id": entity_id, "hours": hours}

@router.get("/entity/{entity_id}/events")
async def get_entity_events(
    entity_id: str,
    hours: int = Query(24, ge=1, le=720),
    event_type: str = Query(""),
    severity: str = Query(""),
    limit: int = Query(50, ge=1, le=200),
    _: str = Depends(get_current_user),
):
    """Named event log for an entity."""
    from api.db.entity_history import get_events
    return {"events": get_events(entity_id, hours=hours, event_type=event_type,
                                  severity=severity, limit=limit),
            "entity_id": entity_id, "hours": hours}
```

---

## Version bump

Update VERSION: `2.8.1` → `2.9.0`

---

## Commit

```bash
git add -A
git commit -m "feat(db): v2.9.0 entity change tracking and event log

- New: entity_changes table — field-level audit trail (permanent)
- New: entity_events table — discrete named events with severity (permanent)
- vm_hosts collector: tracks os, kernel, docker_version, hostname changes
- vm_hosts collector: disk threshold crossed events (80%=warning, 90%=critical)
- swarm collector: image digest change detection (catches silent re-deploys)
- GET /api/logs/entity/{id}/changes and /events endpoints
- api/db/entity_history.py: write_change, write_event, get_changes, get_events"
git push origin main
```
