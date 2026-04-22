# CC PROMPT — v2.40.0 — fix(db): remove orphaned escalations table + dead SQLAlchemy helpers

## What this does

Two parallel escalation tables have existed since v2.37.1. The fix was
band-aided: `api/routers/logs.py` was rewired to query `agent_escalations`
directly, but the dead SQLAlchemy `escalations` table and its helpers in
`api/db/queries.py` were left in place "to avoid migration surprise".

It is now safe to remove them. Three callers remain in queries.py itself
(`get_stats` calls `count_unresolved_escalations`) — these must be updated to
query `agent_escalations` via psycopg like the v2.37.1 fix did.

Three-part change:
1. Remove dead `escalations` table references from `api/db/queries.py`
2. Fix `get_stats()` to count from `agent_escalations` instead
3. Remove `escalations` from `api/db/models.py` table definitions

Version bump: 2.39.4 → 2.40.0.

---

## Change 1 — `api/db/queries.py` — remove dead escalation helpers

Locate and DELETE the following four functions entirely:
- `create_escalation()`
- `get_escalations()`
- `resolve_escalation()`
- `count_unresolved_escalations()`

Also remove `escalations` from the import at the top of the file:

```python
from api.db.models import (
    escalations, audit_log,
```

Replace with:

```python
from api.db.models import (
    audit_log,
```

---

## Change 2 — `api/db/queries.py` — fix get_stats() unresolved escalation count

Locate in `get_stats()`:

```python
    # Unresolved escalations
    unresolved = await count_unresolved_escalations(conn)
```

Replace with:

```python
    # Unresolved escalations — read from agent_escalations (canonical table)
    try:
        from api.connections import _get_conn as _pg
        _ec = _pg()
        if _ec:
            _cur = _ec.cursor()
            _cur.execute(
                "SELECT COUNT(*) FROM agent_escalations WHERE acknowledged = FALSE"
            )
            unresolved = (_cur.fetchone() or [0])[0]
            _cur.close()
            _ec.close()
        else:
            unresolved = 0
    except Exception:
        unresolved = 0
```

---

## Change 3 — `api/db/models.py` — remove escalations Table definition

Locate the `escalations` Table definition. It will look something like:

```python
escalations = Table(
    "escalations", metadata,
    Column("id", ...),
    Column("session_id", ...),
    Column("reason", ...),
    Column("context", ...),
    Column("resolved", ...),
    Column("resolved_at", ...),
    Column("timestamp", ...),
)
```

Delete this Table definition entirely.

Do NOT drop the actual DB table — leave it in the database for now. If the
table has no rows (verify with `SELECT COUNT(*) FROM escalations`), it can
be dropped in a future migration prompt. This prompt only removes the dead
Python code.

---

## Version bump

Update `VERSION` file: `2.39.4` → `2.40.0`

---

## Commit

```
git add -A
git commit -m "fix(db): v2.40.0 remove orphaned escalations SQLAlchemy table + dead helpers"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
