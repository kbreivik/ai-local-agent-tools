# CC PROMPT — v2.47.19 — fix(tests): rewrite gate_macros to match codebase sync DB pattern

## What this does

Fixes v2.47.18's broken macro endpoints (both 500 today). Root cause:

1. **`gate_macros.py:ensure_schema()`** uses async SQLAlchemy + a
   multi-statement `text(_DDL)` block. asyncpg rejects multi-statement
   queries by default — the DDL fails, `ensure_schema()` swallows the
   exception in its own try/except, the `gate_macros` table never gets
   created.
2. **`GET /api/tests/macros`** then queries the missing table and 500s
   because `list_macros()` has no try/except wrapper.

The codebase has a battle-tested sync pattern for this exact use case:
`api/db/known_facts.py`, `api/db/test_runs.py`, and ~15 other modules
all use `from api.connections import _get_conn` (psycopg2 sync), split
multi-statement DDL on `;` and execute each statement individually. v2.47.18
should have followed that pattern.

This prompt rewrites `api/db/gate_macros.py` to match. The endpoints in
`tests_api.py` are mostly fine — they just need to drop `await` on the
sync DB calls and add try/except returning 500 with a useful message.

The migration: existing v2.47.18 module is replaced wholesale. No data
to migrate (table never existed). After this lands, `GET
/api/tests/macros` returns `{"macros": []}` and `POST
/api/tests/macros/from-run` works against any completed run.

Version bump: 2.47.18 → 2.47.19

---

## Change 1 — `api/db/gate_macros.py` — full rewrite to sync pattern

CC: open `api/db/gate_macros.py`. **Replace the ENTIRE file** with the
following content. Do not preserve any of the existing v2.47.18 code.

```python
"""gate_macros — store recorded gate sequences from real test runs.

A macro is a named replayable sequence of gate answers (clarifications
+ plan_action approvals/cancels) captured from one specific test_run.
Macros are addressable by name and can later be applied to a fresh
test run instead of using the TestCase's hardcoded fields.

v2.47.18 — Phase 1: record-only. Replay is wired in Phase 2.
v2.47.19 — sync rewrite using psycopg2; v2.47.18 async version failed
because asyncpg rejects multi-statement DDL.

This module is sync-only (matches known_facts.py / test_runs.py
conventions), never raises into callers, and no-ops on SQLite.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

log = logging.getLogger(__name__)


_DDL_PG = """
CREATE TABLE IF NOT EXISTS gate_macros (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name          TEXT NOT NULL,
    description   TEXT NOT NULL DEFAULT '',
    source_run_id UUID,
    test_id       TEXT NOT NULL,
    gates         JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by    TEXT NOT NULL DEFAULT 'system',
    UNIQUE (name, test_id)
);

CREATE INDEX IF NOT EXISTS ix_gate_macros_name ON gate_macros (name);
CREATE INDEX IF NOT EXISTS ix_gate_macros_test ON gate_macros (test_id);
"""


_initialized = False


def _is_pg() -> bool:
    return "postgres" in os.environ.get("DATABASE_URL", "")


def _conn():
    """Sync psycopg2 connection — same pattern as test_runs.py."""
    from api.connections import _get_conn
    return _get_conn()


def init_gate_macros() -> bool:
    """Create gate_macros table + indexes. Idempotent. Sync. Best-effort."""
    global _initialized
    if _initialized:
        return True
    if not _is_pg():
        _initialized = True
        return True
    try:
        conn = _conn()
        if conn is None:
            return False
        conn.autocommit = True
        cur = conn.cursor()
        # Split DDL on ; — psycopg2 doesn't run multi-statement strings cleanly
        # without a server-side context. Same pattern as known_facts.py.
        for stmt in _DDL_PG.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                cur.execute(stmt)
        cur.close()
        conn.close()
        _initialized = True
        log.info("gate_macros table ready")
        return True
    except Exception as e:
        log.warning("gate_macros init failed: %s", e)
        return False


# ── Read API ──────────────────────────────────────────────────────────────────

def _rows_to_dicts(cur) -> list[dict]:
    """Convert a cursor's results to dicts with ISO timestamps."""
    cols = [d[0] for d in cur.description]
    out = []
    for r in cur.fetchall():
        d = dict(zip(cols, r))
        for k, v in list(d.items()):
            if hasattr(v, "isoformat"):
                d[k] = v.isoformat()
            elif k == "id" and v is not None:
                d[k] = str(v)
            elif k == "source_run_id" and v is not None:
                d[k] = str(v)
        out.append(d)
    return out


def list_macros(name_filter: str | None = None) -> list[dict]:
    """Return all macros, optionally filtered by name prefix."""
    if not _is_pg():
        return []
    try:
        conn = _conn()
        if conn is None:
            return []
        cur = conn.cursor()
        if name_filter:
            cur.execute(
                "SELECT id, name, description, source_run_id, test_id, "
                "gates, created_at, created_by "
                "FROM gate_macros WHERE name LIKE %s "
                "ORDER BY name, test_id",
                (f"{name_filter}%",),
            )
        else:
            cur.execute(
                "SELECT id, name, description, source_run_id, test_id, "
                "gates, created_at, created_by "
                "FROM gate_macros ORDER BY name, test_id"
            )
        rows = _rows_to_dicts(cur)
        cur.close()
        conn.close()
        return rows
    except Exception as e:
        log.warning("list_macros failed: %s", e)
        return []


def get_macro(name: str, test_id: str) -> dict | None:
    """Return one macro by (name, test_id) or None."""
    if not _is_pg() or not name or not test_id:
        return None
    try:
        conn = _conn()
        if conn is None:
            return None
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, description, source_run_id, test_id, "
            "gates, created_at, created_by "
            "FROM gate_macros WHERE name = %s AND test_id = %s",
            (name, test_id),
        )
        rows = _rows_to_dicts(cur)
        cur.close()
        conn.close()
        return rows[0] if rows else None
    except Exception as e:
        log.warning("get_macro failed: %s", e)
        return None


# ── Write API ─────────────────────────────────────────────────────────────────

def record_macro(
    *,
    name: str,
    description: str,
    source_run_id: str,
    test_id: str,
    gates: list[dict],
    created_by: str = "system",
) -> dict:
    """Insert or replace a macro for (name, test_id).

    `gates` is a list of dicts. Recognised shapes:
      {"kind": "clarification", "question": str, "answer": str}
      {"kind": "plan", "summary": str, "steps_count": int, "approved": bool}
    """
    if not _is_pg() or not name or not test_id:
        return {"name": name, "test_id": test_id, "gates_count": 0,
                "error": "noop"}
    try:
        conn = _conn()
        if conn is None:
            return {"name": name, "test_id": test_id, "gates_count": 0,
                    "error": "no_connection"}
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO gate_macros "
            "(name, description, source_run_id, test_id, gates, created_by) "
            "VALUES (%s, %s, %s, %s, %s::jsonb, %s) "
            "ON CONFLICT (name, test_id) DO UPDATE SET "
            "description = EXCLUDED.description, "
            "source_run_id = EXCLUDED.source_run_id, "
            "gates = EXCLUDED.gates, "
            "created_by = EXCLUDED.created_by, "
            "created_at = NOW()",
            (name, description, source_run_id, test_id,
             json.dumps(gates), created_by),
        )
        conn.commit()
        cur.close()
        conn.close()
        return {"name": name, "test_id": test_id,
                "gates_count": len(gates)}
    except Exception as e:
        log.warning("record_macro failed: %s", e)
        return {"name": name, "test_id": test_id, "gates_count": 0,
                "error": str(e)}


def delete_macro(name: str, test_id: str | None = None) -> int:
    """Delete one macro (if test_id given) or all macros named `name`."""
    if not _is_pg() or not name:
        return 0
    try:
        conn = _conn()
        if conn is None:
            return 0
        cur = conn.cursor()
        if test_id:
            cur.execute(
                "DELETE FROM gate_macros WHERE name = %s AND test_id = %s",
                (name, test_id),
            )
        else:
            cur.execute(
                "DELETE FROM gate_macros WHERE name = %s",
                (name,),
            )
        rows = cur.rowcount or 0
        conn.commit()
        cur.close()
        conn.close()
        return rows
    except Exception as e:
        log.warning("delete_macro failed: %s", e)
        return 0


# ── Run-to-macro extraction ───────────────────────────────────────────────────

def extract_gates_from_test_result(test_result: dict) -> list[dict]:
    """Pull gate events from a single test_run_result row.

    Returns a list with at most 2 entries (one clarification, one plan)
    matching the test_run_results schema:
      - clarification_question + clarification_answer_used
      - plan_summary + plan_steps_count + plan_approved
    """
    gates: list[dict] = []
    if test_result.get("clarification_question"):
        gates.append({
            "kind": "clarification",
            "question": test_result.get("clarification_question") or "",
            "answer":   test_result.get("clarification_answer_used") or "",
        })
    if test_result.get("plan_summary"):
        gates.append({
            "kind":        "plan",
            "summary":     test_result.get("plan_summary") or "",
            "steps_count": int(test_result.get("plan_steps_count") or 0),
            "approved":    bool(test_result.get("plan_approved")),
        })
    return gates
```

CC: this is a wholesale file replacement. After the edit, the file has:
- One `init_gate_macros()` sync function (renamed from `ensure_schema`)
- Sync `list_macros`, `get_macro`, `record_macro`, `delete_macro`
- Same `extract_gates_from_test_result` helper as before

---

## Change 2 — `api/main.py` — replace async ensure_schema call with sync init

CC: open `api/main.py`. Find the v2.47.18 block in `_init_db_tables`:

```python
    # gate_macros (v2.47.18)
    try:
        from api.db.gate_macros import ensure_schema as gm_schema
        await gm_schema()
    except Exception as e:
        _log.warning("gate_macros schema init failed: %s", e)
```

Replace with:

```python
    # gate_macros (v2.47.18, sync rewrite v2.47.19)
    try:
        from api.db.gate_macros import init_gate_macros
        init_gate_macros()
    except Exception as e:
        _log.warning("gate_macros init failed: %s", e)
```

CC: keep the surrounding indentation. Only the import name and the call
change (no more `await`).

---

## Change 3 — `api/routers/tests_api.py` — drop `await` from sync DB calls

CC: open `api/routers/tests_api.py`. Find the three v2.47.18 macro endpoints
near the bottom (search for `# ── v2.47.18 — Gate macros (Phase 1: record-only) ──`).

### 3a. `list_macros_endpoint`

Current:
```python
@router.get("/macros")
async def list_macros_endpoint(
    name: str | None = None,
    _: str = Depends(get_current_user),
):
    """List all gate macros, optionally filtered by name prefix."""
    from api.db.gate_macros import list_macros
    return {"macros": await list_macros(name)}
```

Replace with:
```python
@router.get("/macros")
async def list_macros_endpoint(
    name: str | None = None,
    _: str = Depends(get_current_user),
):
    """List all gate macros, optionally filtered by name prefix."""
    from api.db.gate_macros import list_macros
    return {"macros": list_macros(name)}
```

(One change: remove `await` on `list_macros`.)

### 3b. `macro_from_run`

Current:
```python
    for tr in (run.get("results") or []):
        tid = tr.get("test_id")
        if test_ids_filter and tid not in test_ids_filter:
            continue
        gates = extract_gates_from_test_result(tr)
        if not gates:
            skipped.append({"test_id": tid, "reason": "no gates fired"})
            continue
        await record_macro(
            name=name, description=description,
            source_run_id=source_run_id, test_id=tid,
            gates=gates, created_by=user,
        )
        recorded.append({"test_id": tid, "gates_count": len(gates)})
```

Replace the `await record_macro(...)` call with the sync version (drop
`await`):

```python
    for tr in (run.get("results") or []):
        tid = tr.get("test_id")
        if test_ids_filter and tid not in test_ids_filter:
            continue
        gates = extract_gates_from_test_result(tr)
        if not gates:
            skipped.append({"test_id": tid, "reason": "no gates fired"})
            continue
        result = record_macro(
            name=name, description=description,
            source_run_id=source_run_id, test_id=tid,
            gates=gates, created_by=user,
        )
        if result.get("error"):
            skipped.append({"test_id": tid, "reason": result["error"]})
        else:
            recorded.append({"test_id": tid, "gates_count": len(gates)})
```

### 3c. `delete_macro_endpoint`

Current:
```python
@router.delete("/macros/{name}")
async def delete_macro_endpoint(
    name: str,
    test_id: str | None = None,
    _: str = Depends(get_current_user),
):
    """Delete a macro (all test_ids if test_id is omitted)."""
    from api.db.gate_macros import delete_macro
    rows = await delete_macro(name, test_id)
    return {"name": name, "test_id": test_id, "deleted": rows}
```

Replace with:
```python
@router.delete("/macros/{name}")
async def delete_macro_endpoint(
    name: str,
    test_id: str | None = None,
    _: str = Depends(get_current_user),
):
    """Delete a macro (all test_ids if test_id is omitted)."""
    from api.db.gate_macros import delete_macro
    rows = delete_macro(name, test_id)
    return {"name": name, "test_id": test_id, "deleted": rows}
```

---

## Verify

```bash
python -m py_compile \
    api/db/gate_macros.py \
    api/main.py \
    api/routers/tests_api.py

# Confirm sync init function exists
grep -n "def init_gate_macros\|def list_macros\|def record_macro" api/db/gate_macros.py
# Expected: 3 def lines (no `async`)

# Confirm main.py calls sync init
grep -n "init_gate_macros\|gm_schema" api/main.py
# Expected: 1 import line + 1 call line, no `await`

# Confirm endpoints have no await on DB calls
grep -n "await list_macros\|await record_macro\|await delete_macro" api/routers/tests_api.py
# Expected: NO matches
```

After deploy:

```bash
TOKEN=...  # operator-supplied bearer

# 1. List should return empty array (table now exists, no rows yet)
curl -s -H "Authorization: Bearer $TOKEN" \
  http://192.168.199.10:8000/api/tests/macros | jq
# Expected: {"macros": []}

# 2. Record from latest baseline run
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  http://192.168.199.10:8000/api/tests/macros/from-run \
  -d '{
    "name": "baseline-2026-04-27",
    "description": "Captured from v2.47.16 baseline",
    "source_run_id": "04504024-c89d-44cb-976a-837b37fa263a"
  }' | jq

# Expected: { recorded: [~13 entries], skipped: [~25 entries with "no gates fired"] }

# 3. Verify
curl -s -H "Authorization: Bearer $TOKEN" \
  http://192.168.199.10:8000/api/tests/macros | jq '.macros | length'
# Expected: 13
```

Confirm the table got created (via Postgres, optional):

```bash
docker exec deathstar-postgres psql -U postgres -d deathstar -c \
  "\d gate_macros"
# Expected: full column listing
```

---

## Why sync pattern over async

This is purely a "match the codebase" decision, not a perf or correctness
one. The reasons sync wins here:

- **Multi-statement DDL works.** psycopg2 + split-on-`;` runs each
  statement individually, no asyncpg restriction.
- **Shared connection pool.** `_get_conn()` is the same helper every
  other DB module uses. Async would have pulled in a parallel pool that
  doesn't share state with the sync workload.
- **Same exception handling style.** Every other DB module returns
  empty lists / sentinel dicts on failure, not raises. Endpoints stay
  simple — no try/except needed in the FastAPI route.
- **Reads are fast.** Gate macro reads are small (~40 rows max even
  after years of operation). No measurable benefit from async.

Phase 2 (replay wiring) will continue to use the same sync pattern.

---

## What this does NOT do

- **Does not validate v2.47.17's loop guard.** No fresh test run since
  v2.47.17 deployed. Run a smoke or full baseline after this lands to
  confirm `research-elastic-pattern-01` passes with the tightened guard
  (threshold=2 for `elastic_search_logs`).
- **Does not implement Phase 2 (macro replay).** Macros are still
  record-only. Phase 2 wiring lands in v2.47.20+ once the user has
  recorded one or two baseline macros they want to replay.

---

## Version bump

Update `VERSION`: `2.47.18` → `2.47.19`

---

## Commit

```bash
git add -A
git commit -m "fix(tests): v2.47.19 rewrite gate_macros to match codebase sync DB pattern"
git push origin main
```

Deploy:

```bash
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```

After deploy:
- `gate_macros` table actually exists this time
- 3 macro endpoints work (GET / POST from-run / DELETE)
- Phase 2 (replay) becomes feasible to add
