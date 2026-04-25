# CC PROMPT — v2.45.33 — fix(sensors): clear all 5 sensor violations from commit f346017

## What this does
Clears the 5 sensor violations the local check_sensors.py + GitHub Actions
sensor stack reported on commit f346017. Three are real defects (one
runtime-crashing tuple/scalar mismatch in `correlator.py`, two `NameError`
bugs in `agent.py` cleanup) hidden by surrounding `try/except` swallows.
Two are mechanical (long line, complex function).

The sensor stack itself is correct and not modified — it surfaced these
violations, and its HINT messages are accurate. The thresholds (C901=80,
E501=250) are also correct for this codebase — five violations on ~70K
LOC is the right signal-to-noise ratio.

Version bump: 2.45.32 → 2.45.33

---

## Change 1 — `api/correlator.py` — fix F821 + the tuple/scalar bug it hides

`_query_logs` calls `_es_post(f"/{_index()}/_search", body)` — but
the lambda is defined as `_INDEX = lambda: ...` (uppercase). The lowercase
reference is a typo from a v2 rename. Worse: the function returns
`_extract_hits(resp), resp.get(...)` (a tuple) but is annotated
`-> list[dict]`, and callers later treat the return as a list. The
F821 crash hides a second bug — fix both at once.

### Edit 1a — fix the index name reference

Find:

```python
    resp = _es_post(f"/{_index()}/_search", body)
    return _extract_hits(resp), resp.get("hits", {}).get("total", {}).get("value", 0)
```

Replace with:

```python
    resp = _es_post(f"/{_INDEX()}/_search", body)
    hits = _extract_hits(resp)
    total = resp.get("hits", {}).get("total", {}).get("value", 0)
    return hits, total
```

### Edit 1b — fix the function signature so callers and lints agree

Find the `_query_logs` definition:

```python
def _query_logs(since: str, until: str, size: int = 500) -> list[dict]:
    """Query Elasticsearch for logs in time window."""
```

Replace with:

```python
def _query_logs(since: str, until: str, size: int = 500) -> tuple[list[dict], int]:
    """Query Elasticsearch for logs in time window. Returns (hits, total_count)."""
```

The single caller in `correlate()` already does
`all_logs, total = _query_logs(since, until)` — that line was always
expecting a tuple; the signature was lying.

---

## Change 2 — `api/db/runbooks.py` — wrap the 314-char line (E501)

The audit named line 203 specifically. The offender is a `BASE_RUNBOOKS`
entry where the `"command":` value is a single oversized string. Apply
implicit-concat wrapping — Python concatenates adjacent string literals
at compile time, no runtime cost.

CC: open `api/db/runbooks.py` and look at lines 198-210 in BASE_RUNBOOKS.
Find the `plan_action(summary='Reboot worker-03 via Proxmox to recover kafka_broker-3'...)`
command line — it is the longest in that block. Apply this transformation:

Find (whole `command:` value, single line):

```python
             "command": "plan_action(summary='Reboot worker-03 via Proxmox to recover kafka_broker-3', steps=['proxmox_vm_power reboot'], risk_level='medium', reversible=True)"},
```

Replace with:

```python
             "command": (
                 "plan_action("
                 "summary='Reboot worker-03 via Proxmox to recover kafka_broker-3', "
                 "steps=['proxmox_vm_power reboot'], "
                 "risk_level='medium', reversible=True)"
             )},
```

CC: also scan the rest of `BASE_RUNBOOKS` for other lines that may now
trip E501 after a careful look. Apply the same pattern (parenthesised
implicit-concat) to any line over 250 chars. Do NOT touch lines under 250.
Re-running `ruff check api/db/runbooks.py --select E501` after the edit
should report zero violations in this file.

---

## Change 3 — `api/main.py` — split `lifespan` (C901 95 → ~25)

Two extractions. Both preserve startup ordering exactly; they're pure
moves, no logic change.

### Edit 3a — extract DB init blocks to a single helper

Find this block (the long sequence of `try: from api.db.X import init_X; init_X(); except Exception as e: _log.debug("X init skipped: %s", e)`):

Look between these two anchor lines (they bracket the sequence):

- Start anchor: `# Initialize entity maintenance table` (about line 175 in lifespan)
- End anchor: `# Initialize VM action audit log table` is INSIDE the block,
  keep going until `init_subagent_runs() ... runbooks ... card_templates ... display_aliases`
- True end anchor: the line `# Migrate operations table: add parent_session_id if not present`

CC: that's roughly 25 init blocks. Extract them into a new module-level
function in `api/main.py` (above `lifespan`):

```python
async def _init_db_tables(_log) -> None:
    """v2.45.33 — extracted from lifespan to reduce cyclomatic complexity.
    Each table init is best-effort: a failure logs at debug level and the
    next init proceeds. Order matters for some pairs (e.g. connections
    before credential_profiles); preserve the order from the original
    inline sequence."""
    # entity_maintenance
    try:
        init_maintenance()
    except Exception as e:
        _log.debug("entity_maintenance init skipped: %s", e)
    # infra_inventory
    try:
        from api.db.infra_inventory import init_inventory
        init_inventory()
    except Exception as e:
        _log.debug("Infra inventory init skipped: %s", e)
    # ssh_log
    try:
        from api.db.ssh_log import init_ssh_log
        init_ssh_log()
    except Exception as e:
        _log.debug("SSH log init skipped: %s", e)
    # ssh_capabilities
    try:
        from api.db.ssh_capabilities import init_capabilities
        init_capabilities()
    except Exception as e:
        _log.debug("SSH capabilities init skipped: %s", e)
    # result_store
    try:
        from api.db.result_store import init_result_store
        init_result_store()
    except Exception as e:
        _log.debug("Result store init skipped: %s", e)
    # entity_history
    try:
        from api.db.entity_history import init_entity_history
        init_entity_history()
    except Exception as e:
        _log.debug("Entity history init skipped: %s", e)
    # known_facts
    try:
        from api.db.known_facts import init_known_facts
        init_known_facts()
    except Exception as e:
        _log.debug("known_facts init skipped: %s", e)
    # drift_events view
    try:
        from api.db.drift_events import init_drift_view
        init_drift_view()
    except Exception as e:
        _log.debug("Drift view init skipped: %s", e)
    # notifications
    try:
        from api.db.notifications import init_notifications
        init_notifications()
    except Exception as e:
        _log.debug("Notifications init skipped: %s", e)
    # credential_profiles
    try:
        from api.db.credential_profiles import init_credential_profiles
        init_credential_profiles()
    except Exception as e:
        _log.debug("Credential profiles init skipped: %s", e)
    # escalations
    try:
        init_escalations()
    except Exception as e:
        _log.debug("Escalations table init skipped: %s", e)
    # agent_actions
    try:
        from api.db.agent_actions import init_agent_actions
        init_agent_actions()
    except Exception as e:
        _log.debug("agent_actions init skipped: %s", e)
    # agent_attempts
    try:
        from api.db.agent_attempts import init_agent_attempts
        init_agent_attempts()
    except Exception as e:
        _log.debug("agent_attempts init skipped: %s", e)
    # agent_blackouts
    try:
        from api.db.agent_blackouts import init_agent_blackouts
        init_agent_blackouts()
    except Exception as e:
        _log.debug("agent_blackouts init skipped: %s", e)
    # vm_action_log
    try:
        from api.db.vm_action_log import init_vm_action_log
        init_vm_action_log()
    except Exception as e:
        _log.debug("VM action log init skipped: %s", e)
    # vm_exec_allowlist
    try:
        from api.db.vm_exec_allowlist import init_allowlist
        init_allowlist()
    except Exception as e:
        _log.debug("vm_exec_allowlist init skipped: %s", e)
    # subtask_proposals
    try:
        from api.db.subtask_proposals import init_subtask_proposals
        init_subtask_proposals()
    except Exception as e:
        _log.debug("subtask_proposals init skipped: %s", e)
    # subagent_runs
    try:
        from api.db.subagent_runs import init_subagent_runs
        init_subagent_runs()
    except Exception as e:
        _log.debug("subagent_runs init skipped: %s", e)
    # runbooks
    try:
        from api.db.runbooks import init_runbooks
        init_runbooks()
    except Exception as e:
        _log.debug("runbooks init skipped: %s", e)
    # card_templates
    try:
        from api.db.card_templates import init_card_templates
        init_card_templates()
    except Exception as e:
        _log.debug("card_templates init skipped: %s", e)
    # display_aliases
    try:
        from api.db.display_aliases import init_display_aliases
        init_display_aliases()
    except Exception as e:
        _log.debug("display_aliases init skipped: %s", e)
```

In `lifespan`, replace the original ~25-block sequence with a single call:

```python
    await _init_db_tables(_log)
```

(Keep the items BEFORE the start anchor — `init_db()`, `check_secrets()`,
warnings, `_start_logger`, `_seed_settings`, `_sync_env`,
`migrate_plaintext_secrets`, `ensure_crypto_canary`, `init_doc_chunks`,
`init_connections` — in `lifespan` itself, since they involve cross-module
ordering and shared `_BUILD_INFO`/`_log` interactions that are clearer
inline. Only the homogeneous `try: import; init(); except: log` blocks
get extracted.)

### Edit 3b — extract background-loop tasks to a new module

Create new file `api/maintenance.py`:

```python
"""api/maintenance.py — periodic background tasks for the FastAPI lifespan.

v2.45.33 — extracted from api/main.py:lifespan to reduce cyclomatic
complexity. Each public coroutine here is created via asyncio.create_task
once at startup. They run until cancellation (or process exit). All swallow
exceptions per-iteration so a single failure cannot kill the loop.
"""
from __future__ import annotations

import asyncio
import logging

log = logging.getLogger(__name__)


async def result_store_cleanup_loop() -> None:
    """Purge expired result_store rows every 30 minutes."""
    while True:
        await asyncio.sleep(1800)
        try:
            from api.db.result_store import cleanup_expired
            n = cleanup_expired()
            if n:
                log.info("result_store: purged %d expired rows", n)
        except Exception:
            pass


async def status_snapshot_cleanup_loop() -> None:
    """Daily 30-day retention purge of status_snapshots."""
    while True:
        await asyncio.sleep(86400)
        try:
            from api.db.base import get_engine
            from sqlalchemy import text as _t
            async with get_engine().begin() as conn:
                result = await conn.execute(_t(
                    "DELETE FROM status_snapshots "
                    "WHERE timestamp < NOW() - INTERVAL '30 days'"
                ))
                deleted = result.rowcount
                if deleted:
                    log.info(
                        "status_snapshots cleanup: deleted %d rows older than 30 days",
                        deleted,
                    )
        except Exception as e:
            log.debug("status_snapshots cleanup error: %s", e)


async def metric_samples_cleanup_loop() -> None:
    """Daily 30-day retention purge of metric_samples."""
    while True:
        await asyncio.sleep(86400)
        try:
            from api.db.metric_samples import cleanup_old_samples
            n = cleanup_old_samples(days=30)
            if n:
                log.info(
                    "metric_samples cleanup: deleted %d rows older than 30d", n,
                )
        except Exception as e:
            log.debug("metric_samples cleanup failed: %s", e)


async def operation_log_cleanup_loop() -> None:
    """Hourly retention + per-session trim of operation_log."""
    while True:
        await asyncio.sleep(3600)
        try:
            from mcp_server.tools.skills.storage import get_backend
            retention_days = int(get_backend().get_setting("opLogRetentionDays") or 30)
            from api.session_store import cleanup_old_logs
            n = await cleanup_old_logs(retention_days)
            if n:
                log.info(
                    "operation_log: purged %d rows older than %d days",
                    n, retention_days,
                )
        except Exception as e:
            log.debug("operation_log cleanup failed: %s", e)


async def llm_trace_cleanup_loop() -> None:
    """Daily retention purge of agent_llm_traces."""
    while True:
        await asyncio.sleep(86400)
        try:
            from api.db.llm_trace_retention import purge_old_traces
            r = purge_old_traces()
            if r.get("steps_purged") or r.get("prompts_purged"):
                log.info(
                    "llm_traces cleanup: purged %d steps, %d prompts",
                    r["steps_purged"], r["prompts_purged"],
                )
        except Exception as e:
            log.debug("llm_traces cleanup failed: %s", e)


async def refresh_facts_gauges_loop() -> None:
    """v2.35.0 — periodic Prometheus gauge refresh from known_facts."""
    while True:
        await asyncio.sleep(60)
        try:
            from api.db.known_facts import get_gauge_snapshot
            from api.metrics import (
                KNOWN_FACTS_TOTAL, KNOWN_FACTS_CONFIDENT_TOTAL,
                KNOWN_FACTS_CONFLICTS_TOTAL, FACTS_REFRESH_STALE_GAUGE,
            )
            snap = get_gauge_snapshot()
            KNOWN_FACTS_TOTAL.set(snap.get("total", 0))
            KNOWN_FACTS_CONFIDENT_TOTAL.set(snap.get("confident", 0))
            KNOWN_FACTS_CONFLICTS_TOTAL.set(snap.get("pending_conflicts", 0))
            for platform, count in (snap.get("stale_by_platform") or {}).items():
                FACTS_REFRESH_STALE_GAUGE.labels(platform=platform).set(count)
        except Exception:
            pass


async def preflight_timeout_sweeper_loop() -> None:
    """v2.35.1 — auto-cancel preflight-awaiting operations past timeout."""
    while True:
        await asyncio.sleep(60)
        try:
            from api.db.base import get_engine
            from sqlalchemy import text as _t
            timeout_sec = 300
            try:
                async with get_engine().connect() as conn:
                    r = await conn.execute(_t(
                        "SELECT value FROM settings "
                        "WHERE key='preflightDisambiguationTimeout'"
                    ))
                    row = r.fetchone()
                    if row and row[0]:
                        timeout_sec = int(row[0])
            except Exception:
                pass
            async with get_engine().begin() as conn:
                res = await conn.execute(_t(
                    "UPDATE operations SET status='cancelled', "
                    "final_answer='preflight clarification timeout' "
                    "WHERE status='awaiting_clarification' "
                    "  AND created_at < NOW() - (:sec || ' seconds')::interval "
                    "RETURNING id"
                ), {"sec": timeout_sec})
                cancelled = res.fetchall() or []
            for _row in cancelled:
                try:
                    from api.agents.preflight import record_disambiguation_outcome
                    record_disambiguation_outcome("timeout")
                except Exception:
                    pass
        except Exception as e:
            log.debug("preflight timeout sweeper failed: %s", e)
```

In `lifespan`, find the inline `async def _result_store_cleanup_loop(): ...`,
the inline `async def _snapshot_cleanup_loop(): ...`, the inline
`async def _daily_metric_cleanup(): ...`, the inline
`async def _operation_log_cleanup_loop(): ...`, the inline
`async def _llm_trace_cleanup_loop(): ...`, the inline
`async def _refresh_facts_gauges_loop(): ...`, and the inline
`async def _preflight_timeout_sweeper(): ...` — and the seven matching
`_aio.create_task(...)` lines.

Replace the entire seven `async def + create_task` blocks with:

```python
    # v2.45.33 — periodic background tasks (extracted to api/maintenance.py)
    from api import maintenance as _mx
    _aio.create_task(_mx.result_store_cleanup_loop())
    _aio.create_task(_mx.status_snapshot_cleanup_loop())
    _aio.create_task(_mx.metric_samples_cleanup_loop())
    _aio.create_task(_mx.operation_log_cleanup_loop())
    _aio.create_task(_mx.llm_trace_cleanup_loop())
    _aio.create_task(_mx.refresh_facts_gauges_loop())
    _aio.create_task(_mx.preflight_timeout_sweeper_loop())
```

Keep the one-shot startup `DELETE FROM status_snapshots ...` block before
the loop creation (it must run once, synchronously at startup, even if
the daily loop fails). Keep the `_recover_blocked_final_answers()` call
inline — it's a one-shot recovery, not a loop.

CC: After both edits, `lifespan` cyclomatic complexity should drop from
95 to roughly 20-30. Verify with:

```bash
ruff check api/main.py --select C901
```

Expected: zero C901 reports for `lifespan`. If it still flags (still > 80),
also extract the prompt-tool-mention smoke-test block at the top of
lifespan (the OBSERVE/INVESTIGATE/ACTION_PROMPT loop) into
`_emit_prompt_smoke_metrics()` — that's another ~5 complexity points.

---

## Change 4 — `api/routers/agent.py` — fix F821 `last_reasoning` ordering bug

The `record_attempt` block at lines ~2342-2343 references `last_reasoning`
before it is defined further down (line ~2364). The result is a `NameError`
that the surrounding `except Exception as _ae` swallows — every agent run
silently fails to write its `record_attempt` row with a populated summary.
This was a regression from a v2.45 refactor that moved the
`last_reasoning = ""` assignment downward.

### Fix: define `last_reasoning` BEFORE the `record_attempt` block

CC: open `api/routers/agent.py` at the cleanup section. Search for the
line:

```python
        # Use the full step output for final_answer, not the 300-char verdict summary
        last_reasoning = ""
        if prior_verdict:
```

This block currently sits AFTER the `record_attempt` block. Move it BEFORE
the `record_attempt` block.

Concretely: find the `record_attempt` block (it starts with the comment
`# v2.32.3: Record attempt history for the detected entity`) and the
`last_reasoning` initialisation block that follows it. Reorder so that
`last_reasoning = ""` and the `if prior_verdict: last_reasoning = ...`
lines come BEFORE `record_attempt`'s `try:` clause.

The result should look like:

```python
        # Use the full step output for final_answer, not the 300-char verdict
        # summary. v2.45.33 — moved ABOVE record_attempt so the F821 NameError
        # in record_attempt's `if isinstance(last_reasoning, str): _summary =
        # last_reasoning[:500]` line stops being silently swallowed.
        last_reasoning = ""
        if prior_verdict:
            last_reasoning = prior_verdict.get("full_output") or prior_verdict.get("summary", "")

        # v2.32.3: Record attempt history for the detected entity
        try:
            from api.db.agent_attempts import record_attempt
            from api.db.infra_inventory import resolve_host
            from api.agents.router import detect_domain

            _rec_entity = None
            for word in task.split():
                if len(word) < 4:
                    continue
                entry = resolve_host(word)
                if entry:
                    _rec_entity = entry.get("label", word)
                    break
            if not _rec_entity:
                domain = detect_domain(task)
                if domain == "kafka":
                    _rec_entity = "kafka_cluster"
                elif domain == "swarm":
                    _rec_entity = "swarm_cluster"

            if _rec_entity:
                _seen = set()
                _dedup_tools = []
                for t in all_tools_used:
                    if t not in _seen:
                        _seen.add(t)
                        _dedup_tools.append(t)

                _summary = ""
                if isinstance(last_reasoning, str):
                    _summary = last_reasoning[:500]

                record_attempt(
                    entity_id=_rec_entity,
                    task_type=first_intent,
                    task_text=task[:500],
                    tools_used=_dedup_tools[:10],
                    outcome=final_status,
                    summary=_summary,
                    session_id=session_id,
                    operation_id=operation_id or "",
                )
        except Exception as _ae:
            log.debug("record_attempt failed: %s", _ae)
```

After moving, **delete** the now-duplicate `last_reasoning = ""` /
`if prior_verdict: ...` block that previously came after `record_attempt`.
There should be exactly ONE definition of `last_reasoning` in this
cleanup section.

CC: do NOT change the rest of the cleanup logic (truncation rescue,
contradiction detection, final_answer write, agent_observation writer).
Those all run AFTER the moved block in the new ordering — preserve
their order verbatim.

---

## Verify

```bash
# Static checks — should all pass
ruff check api/correlator.py api/db/runbooks.py api/main.py api/routers/agent.py \
    --select F821,E501,C901
# Expected: All checks passed.

# Compile / import
python -m py_compile api/correlator.py api/db/runbooks.py \
                    api/main.py api/maintenance.py api/routers/agent.py

# Smoke import
python -c "from api import maintenance; from api import main; print('ok')"

# Full sensor stack
make check-agent
# Expected output:
#   (clean — exit code 0)
```

Manual checks:

- Hit Logs view → click an old operation → click "Correlate logs". Should
  return non-empty results (was crashing on `_index()` before).
- Run any agent task. After it finishes, query
  `SELECT entity_id, summary FROM agent_attempts ORDER BY created_at DESC LIMIT 5;`.
  `summary` should be populated (was always empty before due to the swallowed
  NameError).
- Container logs at startup should show all the same `init_X` debug lines
  as before, in the same order. Background loops should still tick (e.g.
  the hourly `result_store: purged N expired rows` log).

---

## Version bump

Update `VERSION`: `2.45.32` → `2.45.33`

---

## Commit

```
git add -A
git commit -m "fix(sensors): v2.45.33 clear all 5 violations from f346017 — F821 (correlator + agent), E501, C901"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```

After this lands, the next sensor CI run on main should be green.
