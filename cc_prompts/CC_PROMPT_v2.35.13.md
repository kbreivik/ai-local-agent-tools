# CC PROMPT — v2.35.13 — Fix fallback enrichment: DB-sourced tool_calls + per-host dedup + fix template gaps

## What this does

v2.35.12 wired up `_programmatic_fallback` with a rich path BUT the
wiring was too fragile — the real `tool_calls` in the DB have keys
`tool_name` / `status` / `result` (a dict, not a string), and the
value CC passed from `state["tool_history"]` ended up with
`status=None` and a ~12-char `result` snippet. Also, dedup collapsed
8 `vm_exec` calls across 8 hosts into 1 snippet row.

Three targeted fixes make the enriched fallback actually useful:

1. **Query the DB directly** in `_programmatic_fallback` for the real
   `tool_calls` records. Removes dependence on whatever caller-side
   variable shape was used. DB is the single source of truth and has
   a stable schema.

2. **Dedup by `(tool_name, first_arg_value)`** instead of just
   `tool_name`. `vm_exec(host='worker-01')` and
   `vm_exec(host='worker-02')` become separate rows.

3. **Extract a better snippet from the result dict** — result records
   are always dicts like `{"status": "ok", "message": "...", "data": {...}}`.
   Prefer `message` → first bullet of `data.summary` → top-level keys
   → json dump fallback. No more 12-char mystery snippets.

Two template-coverage fixes as bonus:

4. **Add `pbs_datastore_health()` MCP tool** — closes the PBS
   datastore health template gap (previously `hallucination_guard_exhausted`).

5. **Add `agent_performance_summary(hours_back)` MCP tool** — closes
   the Agent success rate audit template gap (previously completed
   with empty `final_answer` because agent had no HTTP-fetch tool).

Version bump: 2.35.12 → 2.35.13.

---

## Evidence gathered before this prompt was written

Two v2.35.12 verification runs (2026-04-19 against commit `bcb9568`):

| op | template | snippet_count | observed issue |
|---|---|---|---|
| e5df1b7c | VM host overview | 1 | 8 vm_exec calls collapsed to 1 row, status=None, 12-char content |
| 606bd235 | DNS resolver | 5 | 5 distinct tools each got a row — better, but still status=None |

Raw tool_call record shape confirmed from
`/api/logs/operations/{id}`:
```
record_keys: duration_ms, error_detail, id, model_used, operation_id,
             params (dict), result (dict), status ("ok"/"error"),
             timestamp, tool_name
result_lengths: 972–1989 bytes (stringified)
result_types: ["object"]
```

No cumulative regressions on v2.35.11 wins:
- `fabricated_total = 0` across all runs
- `placeholder_echo` drift = 0 (v2.35.12 removed the attractor)
- Fallback output contains real tool names (just sparse snippets)

---

## Change 1 — `api/agents/forced_synthesis.py` — DB-sourced fallback

Accept an `operation_id` parameter on `_programmatic_fallback` (and on
`run_forced_synthesis`). When provided, the fallback queries the DB for
canonical `tool_calls` rows and uses them in preference to any
caller-provided `actual_tool_calls` list. Backward-compat paths are
preserved for tests that construct calls directly.

Replace `_programmatic_fallback` with:

```python
def _programmatic_fallback(
    *,
    reason: str,
    tool_count: int,
    budget: int,
    operation_id: str | None = None,       # NEW v2.35.13 preferred
    actual_tool_calls: list[dict] | None = None,
    actual_tool_names: list[str] | None = None,  # backward compat
) -> str:
    """Build a final_answer from tool history alone.

    Source preference:
      1. If `operation_id` is provided, query the DB directly for
         the run's tool_calls rows (canonical shape). This is the
         preferred v2.35.13 path — removes caller-wiring fragility.
      2. Else, use `actual_tool_calls` (v2.35.12 path, any shape
         with name/tool_name + status + result keys).
      3. Else, use `actual_tool_names` (v2.35.10 names-only path).

    Dedup v2.35.13: groups by (tool_name, first_arg_value) so
    vm_exec calls across different hosts each get their own row.
    """
    label = _REASON_LABELS.get(reason, reason)

    calls: list[dict] = []
    source = "names_only"

    # --- Source 1: DB query (preferred) -------------------------
    if operation_id:
        try:
            calls = _load_tool_calls_for_op(operation_id)
            source = "db"
        except Exception as e:
            log.debug("fallback DB load failed op=%s: %s", operation_id, e)
            calls = []

    # --- Source 2: caller-provided dicts ------------------------
    if not calls and actual_tool_calls:
        calls = list(actual_tool_calls)
        source = "caller_calls"

    # --- Source 3: names-only (legacy) --------------------------
    if not calls and actual_tool_names:
        calls = [{"tool_name": n} for n in actual_tool_names]
        source = "names_only"

    log.info(
        "forced_synthesis fallback source=%s calls=%d reason=%s",
        source, len(calls), reason,
    )

    # --- Dedup by (tool_name, first_arg_value) -------------------
    unique_rows: list[dict] = []
    seen_keys: set[tuple[str, str]] = set()
    for call in calls:
        name = (call.get("tool_name") or call.get("name") or "").strip()
        if not name:
            continue
        first_arg = _first_arg_value(call.get("params") or {})
        key = (name, first_arg)
        if key in seen_keys:
            # Already have this (tool, first_arg). Prefer success over
            # error: if incoming is ok and existing is error, swap.
            existing_idx = next(
                (i for i, r in enumerate(unique_rows)
                 if (r.get("tool_name") or r.get("name")) == name
                 and _first_arg_value(r.get("params") or {}) == first_arg),
                None,
            )
            if existing_idx is not None:
                existing = unique_rows[existing_idx]
                if (call.get("status") == "ok"
                        and existing.get("status") != "ok"):
                    unique_rows[existing_idx] = call
            continue
        seen_keys.add(key)
        unique_rows.append(call)

    lines = [
        f"[HARNESS FALLBACK] Agent reached {label} "
        f"({tool_count}/{budget} tool calls). The model failed to produce "
        "a clean synthesis; this summary was built from tool history alone.",
        "",
        "EVIDENCE:",
    ]

    if unique_rows:
        for row in unique_rows:
            name = row.get("tool_name") or row.get("name") or "?"
            first_arg = _first_arg_value(row.get("params") or {})
            status = row.get("status") or "?"
            snippet = _best_snippet(row.get("result"))
            arg_label = f"({first_arg})" if first_arg else "()"
            if snippet:
                lines.append(f"- {name}{arg_label} status={status}: {snippet}")
            else:
                lines.append(f"- {name}{arg_label} status={status}")
        lines.append("- See the Trace viewer (Logs \u2192 Trace) "
                     "for full tool results.")
    else:
        lines.append("- No tool calls were recorded for this run.")

    lines += [
        "",
        "UNRESOLVED: The agent did not converge on a conclusion within "
        "the budget. The evidence above may still be useful.",
        "",
        "NEXT STEPS:",
        "1. Open the Trace viewer for this operation to inspect the "
        "full tool results.",
        "2. Consider re-running with a narrower task (scope to a single "
        "entity or a single question), or ask a follow-up that "
        "references a specific tool result to continue from that "
        "evidence.",
    ]
    return "\n".join(lines)


# --- Helpers (new in v2.35.13) -------------------------------------

_FIRST_ARG_KEYS_PRIORITY = (
    "host", "service_name", "entity_id", "container_id",
    "vm_name", "node", "broker_id", "pool", "datastore",
    "topic", "group", "key", "name", "label",
)


def _first_arg_value(params: dict) -> str:
    """Return a short stable representation of the call's primary arg.

    Used for dedup keying: calls to the same tool with different primary
    args should NOT be collapsed into a single fallback row. For example,
    `vm_exec(host='worker-01', command='df -h')` and
    `vm_exec(host='worker-02', command='df -h')` must produce two rows.

    Looks for common "primary arg" keys in priority order. Falls back
    to an empty string (= no distinction) when none present.
    """
    if not isinstance(params, dict) or not params:
        return ""
    for k in _FIRST_ARG_KEYS_PRIORITY:
        v = params.get(k)
        if v is not None:
            s = str(v).strip()
            if s:
                return s[:40]
    # Last-ditch: use first non-empty string/number value
    for k, v in params.items():
        if isinstance(v, (str, int, float)) and str(v).strip():
            return str(v).strip()[:40]
    return ""


def _best_snippet(result, max_chars: int = 120) -> str:
    """Extract a useful short snippet from a tool's result.

    Tool results have a canonical shape:
      {"status": "ok"|"error", "message": "<short>", "data": {...}}

    Preference order:
      1. `message` field (already short, author-written)
      2. First bullet/line of `data.summary`
      3. Top-level keys of `data` (for structured tool returns)
      4. JSON dump of `data` (truncated)
      5. str(result) truncated

    Replaces internal newlines with space; truncates at max_chars.
    """
    if result is None:
        return ""
    if not isinstance(result, dict):
        s = str(result).strip().replace("\n", " ")
        return s[:max_chars - 3] + "..." if len(s) > max_chars else s

    # 1. message field
    msg = result.get("message")
    if isinstance(msg, str) and msg.strip():
        s = msg.strip().replace("\n", " ")
        return s[:max_chars - 3] + "..." if len(s) > max_chars else s

    data = result.get("data")

    # 2. data.summary first line
    if isinstance(data, dict):
        summ = data.get("summary")
        if isinstance(summ, str) and summ.strip():
            s = summ.strip().split("\n", 1)[0].strip()
            return s[:max_chars - 3] + "..." if len(s) > max_chars else s

    # 3. top-level data keys
    if isinstance(data, dict) and data:
        pairs = []
        for k, v in list(data.items())[:6]:
            if isinstance(v, (str, int, float, bool)):
                pairs.append(f"{k}={v}")
            elif isinstance(v, list):
                pairs.append(f"{k}=[{len(v)} items]")
            elif isinstance(v, dict):
                pairs.append(f"{k}={{{len(v)} keys}}")
        if pairs:
            s = ", ".join(pairs)
            return s[:max_chars - 3] + "..." if len(s) > max_chars else s
    elif isinstance(data, list) and data:
        s = f"[{len(data)} items]"
        return s

    # 4. json dump fallback
    try:
        import json as _json
        s = _json.dumps(result, default=str)
        s = s.replace("\n", " ")
        return s[:max_chars - 3] + "..." if len(s) > max_chars else s
    except Exception:
        s = str(result).strip().replace("\n", " ")
        return s[:max_chars - 3] + "..." if len(s) > max_chars else s


def _load_tool_calls_for_op(operation_id: str) -> list[dict]:
    """Load canonical tool_calls rows from the DB for a given operation.

    Returns [] on any DB error (logged at debug). Never raises — the
    fallback must work even if the DB is flaky.

    Rows have the canonical shape:
      {tool_name, status, params (dict), result (dict),
       duration_ms, timestamp}
    """
    try:
        from sqlalchemy import create_engine, text
        import os as _os
        # Use the same URL construction as api.db.base, but sync engine
        # since _programmatic_fallback is not async.
        db_url = _os.environ.get("DATABASE_URL", "").replace(
            "postgresql+asyncpg://", "postgresql://"
        ).replace("postgresql+psycopg://", "postgresql://")
        if not db_url:
            return []
        eng = create_engine(db_url, pool_pre_ping=True, pool_size=1)
        with eng.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT tool_name, status, params, result, "
                    "duration_ms, timestamp "
                    "FROM tool_calls WHERE operation_id = :op "
                    "ORDER BY timestamp ASC"
                ),
                {"op": operation_id},
            ).mappings().all()
        eng.dispose()
        return [dict(r) for r in rows]
    except Exception as e:
        log.debug("fallback DB load error op=%s: %s", operation_id, e)
        return []
```

**CC note:** the exact table name (`tool_calls`) and column names above
match current DB schema as verified through `/api/logs/operations/{id}`.
If the actual schema in `api/db/queries.py` or `api/db/schema.py` uses
different names, use those instead — the goal is to read the same rows
the operations endpoint serves.

## Change 2 — `api/agents/forced_synthesis.py` — thread `operation_id` through `run_forced_synthesis`

```python
def run_forced_synthesis(
    *,
    client,
    model: str,
    messages: list,
    agent_type: str,
    reason: str,
    tool_count: int,
    budget: int,
    actual_tool_names: Iterable[str],
    operation_id: str | None = None,         # NEW v2.35.13
    actual_tool_calls: list[dict] | None = None,
    max_tokens: int = 1500,
) -> tuple[str, str, dict | None]:
```

At the fallback trigger site, pass `operation_id`:

```python
if not synthesis_text:
    if FORCED_SYNTHESIS_FALLBACK_COUNTER is not None:
        try:
            FORCED_SYNTHESIS_FALLBACK_COUNTER.labels(reason=reason).inc()
        except Exception:
            pass
    synthesis_text = _programmatic_fallback(
        reason=reason,
        tool_count=tool_count,
        budget=budget,
        operation_id=operation_id,           # NEW v2.35.13
        actual_tool_calls=actual_tool_calls,
        actual_tool_names=actual_list,
    )
```

## Change 3 — `api/routers/agent.py` — pass `operation_id` at the call site

CC: grep `run_forced_synthesis(` in `api/routers/agent.py` and add
`operation_id=operation_id` (the loop's local variable) to the kwargs.
The local is already in scope wherever `run_forced_synthesis` is called —
it's passed down from the parent `_stream_agent` / `drive_agent` call.

## Change 4 — Add `pbs_datastore_health()` MCP tool

Create `mcp_server/tools/pbs_health.py` with:

```python
"""PBS datastore health tool — read-only, collector-sourced."""
from typing import Optional

from api.tool_registry import tool
from api.db.base import get_engine
from sqlalchemy import text


@tool(
    blast_radius="none",
    description=(
        "Return health snapshot of every Proxmox Backup Server datastore: "
        "free/used/total bytes, usage pct, last GC status, last backup "
        "success timestamp per datastore, and a DEGRADED/HEALTHY flag for "
        "each. Data sourced from the PBS collector snapshot (collector "
        "runs every 5 min); no live PBS API call is made."
    ),
)
def pbs_datastore_health() -> dict:
    """Return {status, message, data: {datastores: [...], summary: str}}."""
    import asyncio

    async def _q():
        async with get_engine().connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT entity_id, label, metadata, status_text, "
                    "updated_at "
                    "FROM infra_inventory "
                    "WHERE platform = 'pbs' "
                    "AND entity_type = 'datastore' "
                    "ORDER BY label"
                )
            )
            return [dict(r._mapping) for r in rows]

    try:
        datastores = asyncio.get_event_loop().run_until_complete(_q())
    except RuntimeError:
        # already inside an event loop — create fresh
        new_loop = asyncio.new_event_loop()
        try:
            datastores = new_loop.run_until_complete(_q())
        finally:
            new_loop.close()
    except Exception as e:
        return {"status": "error", "message": f"PBS query failed: {e}",
                "data": {}}

    if not datastores:
        return {"status": "ok",
                "message": "No PBS datastores found in inventory. "
                           "Check if a PBS connection is configured and "
                           "polled.",
                "data": {"datastores": [], "summary": "no datastores"}}

    enriched = []
    degraded = 0
    for r in datastores:
        meta = r.get("metadata") or {}
        used = meta.get("used_bytes") or 0
        total = meta.get("total_bytes") or 0
        pct = (used / total * 100.0) if total else 0.0
        flag = "HEALTHY"
        if pct >= 95:
            flag = "CRITICAL"; degraded += 1
        elif pct >= 85:
            flag = "DEGRADED"; degraded += 1
        enriched.append({
            "label": r["label"],
            "entity_id": r["entity_id"],
            "used_gb": round(used / 1e9, 1) if used else None,
            "total_gb": round(total / 1e9, 1) if total else None,
            "usage_pct": round(pct, 1),
            "last_gc_status": meta.get("last_gc_status"),
            "last_backup_ts": meta.get("last_backup_ts"),
            "flag": flag,
        })

    summary = (
        f"{len(enriched)} datastores, {degraded} flagged "
        f"({'all healthy' if degraded == 0 else 'attention needed'})"
    )
    return {
        "status": "ok",
        "message": summary,
        "data": {"datastores": enriched, "summary": summary},
    }
```

Register the tool by importing it in `mcp_server/tools/__init__.py`
(or wherever other tools are imported). Also add `pbs_datastore_health`
to the `observe` and `investigate` allowlists in `api/agents/router.py`.

## Change 5 — Add `agent_performance_summary()` MCP tool

Create `mcp_server/tools/agent_perf.py`:

```python
"""Agent self-monitoring tool — read-only query of operations table."""
from api.tool_registry import tool
from api.db.base import get_engine
from sqlalchemy import text
import asyncio


@tool(
    blast_radius="none",
    description=(
        "Return aggregated agent performance over the past N hours: total "
        "run count, per-(agent_type, status) breakdown, success rate, "
        "median wall-clock per agent_type, and top-10 task labels that "
        "ended status in ('error', 'capped', 'escalated'). Scans the "
        "operations table directly \u2014 no HTTP fetch required. "
        "Supersedes the 'Agent success rate audit' template's implicit "
        "HTTP call."
    ),
)
def agent_performance_summary(hours_back: int = 24) -> dict:
    """Return {status, message, data: {...aggregates...}}."""
    hours_back = max(1, min(168, int(hours_back)))

    async def _q():
        async with get_engine().connect() as conn:
            cutoff = await conn.execute(
                text(
                    "SELECT COUNT(*) as n FROM operations "
                    "WHERE started_at > NOW() - INTERVAL ':h hours'"
                ).bindparams(h=hours_back)
            )
            total = cutoff.scalar() or 0
            if not total:
                return {"total": 0}

            by_status = await conn.execute(
                text(
                    "SELECT agent_type, status, COUNT(*) AS n, "
                    "percentile_cont(0.5) WITHIN GROUP ("
                    "  ORDER BY EXTRACT(EPOCH FROM (COALESCE("
                    "    finished_at, NOW()) - started_at))"
                    ") AS median_wall_s "
                    "FROM operations "
                    "WHERE started_at > NOW() - INTERVAL ':h hours' "
                    "GROUP BY agent_type, status"
                ).bindparams(h=hours_back)
            )
            buckets = [dict(r._mapping) for r in by_status]

            failing = await conn.execute(
                text(
                    "SELECT task_label, status, COUNT(*) AS n "
                    "FROM operations "
                    "WHERE started_at > NOW() - INTERVAL ':h hours' "
                    "AND status IN ('error', 'capped', 'escalated', 'failed') "
                    "GROUP BY task_label, status "
                    "ORDER BY n DESC LIMIT 10"
                ).bindparams(h=hours_back)
            )
            top_failing = [dict(r._mapping) for r in failing]

            return {"total": total, "buckets": buckets,
                    "top_failing": top_failing}

    try:
        data = asyncio.get_event_loop().run_until_complete(_q())
    except RuntimeError:
        new_loop = asyncio.new_event_loop()
        try:
            data = new_loop.run_until_complete(_q())
        finally:
            new_loop.close()
    except Exception as e:
        return {"status": "error",
                "message": f"operations query failed: {e}",
                "data": {}}

    total = data.get("total", 0)
    if total == 0:
        return {"status": "ok",
                "message": f"No runs in past {hours_back}h",
                "data": {"total": 0, "summary": "no runs"}}

    completed = sum(b["n"] for b in data["buckets"]
                    if b["status"] == "completed")
    success_rate = round(completed / total * 100.0, 1) if total else 0.0

    data["success_rate_pct"] = success_rate
    data["summary"] = (
        f"{total} runs in past {hours_back}h, {completed} completed "
        f"({success_rate}%). Top-failing tasks: "
        + (", ".join(f"{r['task_label']} ({r['n']}x {r['status']})"
                     for r in data["top_failing"][:3]) or "none")
    )

    return {
        "status": "ok",
        "message": data["summary"],
        "data": data,
    }
```

Register + add to `observe` allowlist only (not `investigate` — this
tool is meta, not diagnostic).

**CC note:** if the actual `operations` table columns differ
(`agent_type` might be `task_type`, `started_at` might be `created_at`,
etc.), use the actual names — check `api/db/queries.py`. The tool
must return the canonical `{status, message, data}` envelope regardless
of underlying column names.

## Change 6 — Update templates to use new tools

In `gui/src/components/TaskTemplates.jsx`:

- **PBS datastore health** template: change `task` to
  `"Use pbs_datastore_health() to check every Proxmox Backup Server
  datastore. Report any at >85% usage, any with failed GC, and any
  where the last backup is more than 24 hours old."`

- **Agent success rate audit** template: change `task` to
  `"Use agent_performance_summary(hours_back=24) to audit recent agent
  runs. Report overall success rate, per-agent_type breakdown, and
  top-3 failing tasks. If success rate is below 70%, flag as DEGRADED."`

## Change 7 — Tests

Extend `tests/test_forced_synthesis_drift.py` with:

```python
def test_fallback_db_source_when_operation_id_given(monkeypatch):
    """v2.35.13: with operation_id, fallback loads from DB and renders
    per-host rows for vm_exec."""
    from api.agents import forced_synthesis as fs

    def _fake_load(op_id):
        # 3 vm_exec calls to different hosts + 1 swarm_node_status
        return [
            {"tool_name": "vm_exec", "status": "ok",
             "params": {"host": "worker-01", "command": "df -h"},
             "result": {"status": "ok", "message": "/dev/sda1 42G/120G"}},
            {"tool_name": "vm_exec", "status": "ok",
             "params": {"host": "worker-02", "command": "df -h"},
             "result": {"status": "ok", "message": "/dev/sda1 50G/120G"}},
            {"tool_name": "vm_exec", "status": "ok",
             "params": {"host": "worker-03", "command": "df -h"},
             "result": {"status": "ok", "message": "/dev/sda1 90G/120G"}},
            {"tool_name": "swarm_node_status", "status": "ok",
             "params": {},
             "result": {"status": "ok", "message": "6 nodes Ready"}},
        ]
    monkeypatch.setattr(fs, "_load_tool_calls_for_op", _fake_load)

    out = fs._programmatic_fallback(
        reason="budget_cap", tool_count=4, budget=8,
        operation_id="op-xyz",
    )
    # All 3 vm_exec rows present, keyed by host
    assert out.count("vm_exec(worker-01)") == 1
    assert out.count("vm_exec(worker-02)") == 1
    assert out.count("vm_exec(worker-03)") == 1
    assert "swarm_node_status" in out
    # Snippets from message field are present (no status=None)
    assert "status=ok" in out
    assert "42G/120G" in out or "50G/120G" in out or "90G/120G" in out


def test_fallback_dedup_same_host_calls():
    """Two calls to same tool with same first-arg collapse to one row,
    preferring the success over the error."""
    from api.agents.forced_synthesis import _programmatic_fallback
    calls = [
        {"tool_name": "vm_exec", "status": "error",
         "params": {"host": "worker-01"},
         "result": {"status": "error", "message": "ssh timeout"}},
        {"tool_name": "vm_exec", "status": "ok",
         "params": {"host": "worker-01"},
         "result": {"status": "ok", "message": "42G used"}},
    ]
    out = _programmatic_fallback(
        reason="budget_cap", tool_count=2, budget=8,
        actual_tool_calls=calls,
    )
    # Only one vm_exec(worker-01) row, and it's the success
    assert out.count("vm_exec(worker-01)") == 1
    assert "42G used" in out
    assert "ssh timeout" not in out


def test_best_snippet_prefers_message_field():
    from api.agents.forced_synthesis import _best_snippet
    result = {"status": "ok", "message": "6 nodes Ready, 0 Down",
              "data": {"nodes": [{"n": 1}, {"n": 2}]}}
    assert _best_snippet(result) == "6 nodes Ready, 0 Down"


def test_best_snippet_falls_back_to_data_summary():
    from api.agents.forced_synthesis import _best_snippet
    result = {"status": "ok",
              "data": {"summary": "3 datastores healthy\nSecond line"}}
    # First line only
    assert _best_snippet(result) == "3 datastores healthy"


def test_best_snippet_falls_back_to_data_keys():
    from api.agents.forced_synthesis import _best_snippet
    result = {"status": "ok",
              "data": {"broker_count": 3, "isr_ok": True,
                       "topics": [{"t": 1}, {"t": 2}]}}
    snip = _best_snippet(result)
    assert "broker_count=3" in snip
    assert "isr_ok=True" in snip
    assert "topics=[2 items]" in snip


def test_first_arg_value_priority():
    from api.agents.forced_synthesis import _first_arg_value
    # host wins
    assert _first_arg_value({"host": "h1", "command": "x"}) == "h1"
    # service_name is next
    assert _first_arg_value({"service_name": "kafka_broker-1"}) == "kafka_broker-1"
    # Empty on missing
    assert _first_arg_value({}) == ""
    # Long value truncated
    long = "x" * 100
    assert len(_first_arg_value({"host": long})) <= 40
```

## Change 8 — `VERSION`

Replace with:

```
2.35.13
```

## Verify

```bash
pytest tests/test_forced_synthesis_drift.py -v
pytest tests/test_fabrication_detector_regex.py -v
pytest tests/ -v -k "forced_synthesis or fabrication or fallback"
```

## Commit

```bash
git add -A
git commit -m "fix(agents): v2.35.13 DB-sourced fallback + per-host dedup + best_snippet + PBS + agent_perf tools

v2.35.12 wired up _programmatic_fallback's rich path but snippets
came out as 'status=None, 12 chars' because the caller-side dict
shape was fragile. Fix: _programmatic_fallback now optionally takes
an operation_id and queries the DB directly for canonical tool_calls
rows (tool_name/status/params/result). Bypasses all wiring ambiguity.

Three fallback improvements:
1. DB source path via _load_tool_calls_for_op(operation_id).
2. Dedup keyed by (tool_name, first_arg_value) so vm_exec across
   8 hosts produces 8 rows, not 1.
3. _best_snippet helper: prefers result['message'] -> data.summary
   first line -> top-level data keys -> JSON dump. Never returns
   the 12-char mystery string.

Two template-gap tools:
- pbs_datastore_health() reads infra_inventory for PBS datastore
  rows written by the PBS collector. Closes the hallucination_guard
  failure on 'PBS datastore health' template.
- agent_performance_summary(hours_back=24) queries the operations
  table directly for per-agent-type success rates and top failing
  tasks. Closes the empty-final_answer failure on 'Agent success
  rate audit' template (which previously referenced an HTTP endpoint
  the agent had no tool for).

Both new tools registered with blast_radius=none and added to the
observe allowlist (pbs_datastore_health also in investigate).
Templates updated to reference the new tools explicitly."
git push origin main
```

## Deploy + smoke test

```bash
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```

Post-deploy verification:

1. **VM host overview** — expected: fallback shows 6-8 rows like
   `- vm_exec(ds-docker-worker-01) status=ok: /dev/sda1 42G used 120G avail`.
   One row per host instead of a single collapsed row.

2. **PBS datastore health** — expected: status=completed (not
   hallucination_guard_exhausted). Agent calls `pbs_datastore_health()`
   once, gets structured datastore list.

3. **Agent success rate audit** — expected: status=completed with
   non-empty `final_answer`. Agent calls
   `agent_performance_summary(hours_back=24)` once, synthesises from
   the returned aggregates.

4. `/metrics` — `deathstar_forced_synthesis_fallback_total` may
   continue incrementing (fallback rate still high), but the fallback
   content is now genuinely informative.
