# CC PROMPT — v2.49.11 — fix(perf+bugs): status_snapshots index + retention + kafka/memory bugs

## What this does

Four bundled fixes surfaced during full-mem-on test:

1. **Composite index on status_snapshots(component, timestamp DESC).** Current
   indexes are pk(id) and idx_snap_comp(component) only. Queries that fetch
   the latest snapshot per component fall back to seq scan within the
   component group (650k rows / ~14 components = ~45k rows scanned per
   lookup). PG saw `wait_event_type=IO, wait_event=DataFileRead`,
   `xact_time` averaging 1.4s per query under test load, with
   container OOM-bound at 256MB.

2. **Retention task — prune status_snapshots older than 30 days.** Runs
   nightly at 03:00 via APScheduler. Table currently 1.1GB / 653k rows;
   most components write every 60s, so 30d = ~43k rows per component =
   trim to ~15% of current size. Massive reduction in working set.

3. **Kafka fact extractor crash:**
   `int() argument must be ... not 'list'`. Two sites:
   - `snapshot["under_replicated_partitions"]` — collector returns a
     list of partition descriptors, not a count.
   - per-topic `t["under_replicated_partitions"]` — same shape issue.
   Fix: branch on type. If list, use `len()`. If already int, pass through.

4. **PgMemoryClient missing `_base` attr** (causes 500 on
   `/api/memory/health`). Endpoint reads `client._base` for the
   reachability URL. MuninnClient has it; PgMemoryClient doesn't.
   Add `_base` as a class-level constant identifying the PG backend.

Version bump: 2.49.10 → 2.49.11

---

## Change 1 — `api/db/migrations.py`

Append migration 14 to MIGRATIONS list. Find the closing of migration 13:

````python
    (13, "v2.45.32 — audit columns on test_run_results", [
        "ALTER TABLE test_run_results ADD COLUMN IF NOT EXISTS clarification_question TEXT DEFAULT ''",
        "ALTER TABLE test_run_results ADD COLUMN IF NOT EXISTS clarification_answer_used TEXT DEFAULT ''",
        "ALTER TABLE test_run_results ADD COLUMN IF NOT EXISTS plan_summary TEXT DEFAULT ''",
        "ALTER TABLE test_run_results ADD COLUMN IF NOT EXISTS plan_steps_count INTEGER DEFAULT 0",
        "ALTER TABLE test_run_results ADD COLUMN IF NOT EXISTS plan_approved BOOLEAN DEFAULT FALSE",
        "ALTER TABLE test_run_results ADD COLUMN IF NOT EXISTS operation_id TEXT DEFAULT ''",
    ]),
]
````

Replace with (add migration 14, keep the closing `]`):

````python
    (13, "v2.45.32 — audit columns on test_run_results", [
        "ALTER TABLE test_run_results ADD COLUMN IF NOT EXISTS clarification_question TEXT DEFAULT ''",
        "ALTER TABLE test_run_results ADD COLUMN IF NOT EXISTS clarification_answer_used TEXT DEFAULT ''",
        "ALTER TABLE test_run_results ADD COLUMN IF NOT EXISTS plan_summary TEXT DEFAULT ''",
        "ALTER TABLE test_run_results ADD COLUMN IF NOT EXISTS plan_steps_count INTEGER DEFAULT 0",
        "ALTER TABLE test_run_results ADD COLUMN IF NOT EXISTS plan_approved BOOLEAN DEFAULT FALSE",
        "ALTER TABLE test_run_results ADD COLUMN IF NOT EXISTS operation_id TEXT DEFAULT ''",
    ]),
    (14, "v2.49.11 — composite index on status_snapshots(component, timestamp DESC)", [
        # Hot query pattern: 'latest snapshot per component'. Existing
        # idx_snap_comp(component) alone forces a within-group scan. The
        # composite index lets PG return the newest row per component via
        # a single index lookup. Massive reduction in DataFileRead waits
        # under sustained load (650k+ rows, ~14 components).
        "CREATE INDEX IF NOT EXISTS idx_snap_comp_ts "
        "ON status_snapshots (component, timestamp DESC)",
    ]),
]
````

## Change 2 — `api/facts/extractors.py`

Find the kafka extractor's cluster-level under_replicated block:

````python
    # Under-replicated summary from snapshot top-level if present
    ur = snapshot.get("under_replicated_partitions")
    if ur is not None:
        _add(facts, "prod.kafka.cluster.under_replicated_partitions",
             "kafka_collector", int(ur))
````

Replace with:

````python
    # Under-replicated summary from snapshot top-level if present.
    # v2.49.11: collector may return either a list of partition descriptors
    # or an int count. Handle both shapes safely.
    ur = snapshot.get("under_replicated_partitions")
    if ur is not None:
        ur_count = len(ur) if isinstance(ur, (list, tuple)) else int(ur)
        _add(facts, "prod.kafka.cluster.under_replicated_partitions",
             "kafka_collector", ur_count)
````

In the same function, find the per-topic under_replicated block:

````python
        # v2.39.2: per-topic under-replicated count
        t_ur = t.get("under_replicated_partitions", t.get("under_replicated"))
        if t_ur is not None:
            _add(facts, f"prod.kafka.topic.{name}.under_replicated_partitions",
                 "kafka_collector", int(t_ur))
````

Replace with:

````python
        # v2.39.2: per-topic under-replicated count
        # v2.49.11: handle list-or-int shape (same fix as cluster level above)
        t_ur = t.get("under_replicated_partitions", t.get("under_replicated"))
        if t_ur is not None:
            t_ur_count = len(t_ur) if isinstance(t_ur, (list, tuple)) else int(t_ur)
            _add(facts, f"prod.kafka.topic.{name}.under_replicated_partitions",
                 "kafka_collector", t_ur_count)
````

## Change 3 — `api/memory/pg_client.py`

Find the `PgMemoryClient` class definition:

````python
class PgMemoryClient:
    """PG-native engram store with tsvector keyword activation."""

    async def store(self, concept: str, content: str,
                    tags: list[str] | None = None) -> str | None:
````

Replace with (add the `_base` class attr immediately after the docstring,
before the first method):

````python
class PgMemoryClient:
    """PG-native engram store with tsvector keyword activation."""

    # v2.49.11: API surface compat with MuninnClient — /api/memory/health
    # reads client._base for a reachability URL/label. PG backend has no
    # remote URL, so use a stable identifier the GUI can display.
    _base = "pg://hp1_agent.pg_engrams"

    async def store(self, concept: str, content: str,
                    tags: list[str] | None = None) -> str | None:
````

## Change 4 — `api/scheduler.py` (retention task)

Append a new scheduled job for daily status_snapshots pruning. Find the
existing scheduler setup. Look for `BackgroundScheduler` or
`AsyncIOScheduler` or similar startup section. Add this job registration
alongside existing ones (at the end of whatever function does the job
adds — typically `start_scheduler()` or `register_jobs()`):

````python
    # v2.49.11 — nightly status_snapshots retention. Default 30d; settable
    # via STATUS_SNAPSHOT_RETENTION_DAYS env var. Runs at 03:00 server time
    # to avoid collector polling overlap.
    from api.db.base import DB_BACKEND, get_engine
    from sqlalchemy import text

    async def _prune_status_snapshots():
        if DB_BACKEND != "postgres":
            return
        days = int(os.environ.get("STATUS_SNAPSHOT_RETENTION_DAYS", "30"))
        try:
            async with get_engine().begin() as conn:
                result = await conn.execute(
                    text(f"DELETE FROM status_snapshots "
                         f"WHERE timestamp < NOW() - INTERVAL '{days} days'")
                )
                log.info(f"status_snapshots retention: deleted {result.rowcount} "
                         f"rows older than {days}d")
        except Exception as e:
            log.warning(f"status_snapshots retention failed: {e}")

    scheduler.add_job(
        _prune_status_snapshots,
        trigger="cron", hour=3, minute=0,
        id="status_snapshots_retention",
        replace_existing=True,
    )
````

If `api/scheduler.py` doesn't have a `start_scheduler()` or
`register_jobs()` function, place this in `api/main.py` startup hook
instead (the `@app.on_event("startup")` block). Adapt to whatever
scheduler instance exists. If no scheduler at all exists, fall back to
appending this as a one-shot cleanup at startup (less ideal but
acceptable for v2.49.11).

The first run of CC may need to investigate the actual structure — if
unsure, prefer the startup-only one-shot approach over breaking an
existing scheduler.

## Change 5 — `docker/.env.example`

Append below the existing PostgreSQL credentials block:

````bash

# ── status_snapshots retention (v2.49.11) ──────────────────────────────
# Days of status_snapshots history to keep. Pruned nightly at 03:00.
# Default 30. Set lower if disk pressure, higher for longer audit trails.
STATUS_SNAPSHOT_RETENTION_DAYS=30
````

## Change 6 — VERSION

Update `VERSION`: 2.49.10 → 2.49.11

## Verify

````bash
# 1. New migration registered
grep -q "v2.49.11 — composite index on status_snapshots" api/db/migrations.py
grep -q "idx_snap_comp_ts" api/db/migrations.py

# 2. Kafka extractor fix applied (no bare int() on possibly-list)
grep -q "isinstance(ur, (list, tuple))" api/facts/extractors.py
grep -q "isinstance(t_ur, (list, tuple))" api/facts/extractors.py
! grep -E '_add\(facts.*int\(ur\)\)$' api/facts/extractors.py
! grep -E '_add\(facts.*int\(t_ur\)\)$' api/facts/extractors.py

# 3. PgMemoryClient._base present
grep -q '_base = "pg://hp1_agent.pg_engrams"' api/memory/pg_client.py

# 4. Retention job registered (in scheduler.py or main.py somewhere)
grep -rE '(status_snapshots_retention|_prune_status_snapshots)' api/

# 5. Env var documented
grep -q 'STATUS_SNAPSHOT_RETENTION_DAYS' docker/.env.example
````

## Commit

````bash
git add -A
git commit -m "fix(perf+bugs): status_snapshots index + retention + kafka/memory bugs (v2.49.11)

Four fixes surfaced during full-mem test under transaction-mode pgbouncer:

1. Composite index on status_snapshots(component, timestamp DESC).
   Existing single-column idx_snap_comp(component) caused seq scans
   within component groups for 'latest snapshot per component' queries.
   With ~650k rows / 14 components, each lookup scanned ~45k rows.
   New composite index returns latest row per component via single
   index lookup. Should drop DataFileRead waits substantially.

2. Nightly retention task (default 30d). Table at 1.1GB; pruning to
   30d expected to cut working set ~85%. Settable via env var
   STATUS_SNAPSHOT_RETENTION_DAYS.

3. Kafka fact extractor crash on 'under_replicated_partitions' field.
   Collector returns a list of partition descriptors; extractor
   called int() on it. Fix: detect list shape, use len() instead.
   Same fix applied per-topic. Extractor is wrapped in try/except in
   the caller — error was logged but no facts written for kafka.

4. PgMemoryClient missing _base attribute. /api/memory/health endpoint
   reads client._base; MuninnClient has it, PgMemoryClient didn't.
   Endpoint returned 500. Added as class-level identifier.

PG memory bump (256MB → 2GB) tracked separately in Ansible (postgres
role); this prompt is the app-side complement."
git push origin main
````

## Deploy

After CC commits and CI image rebuild — **and** after the Ansible PG
memory bump is applied:

````bash
# On agent-01
cd /opt/hp1-agent
git pull origin main

# Image change — wait for CI and pull
docker pull ghcr.io/kbreivik/hp1-ai-agent:latest

# Recreate hp1_agent. Migration 14 runs on startup.
cd docker
docker compose --env-file .env up -d --force-recreate hp1_agent

# Verify migration applied
sleep 10
docker exec hp1-postgres psql -U hp1 -d hp1_agent -c \
  "SELECT version, description FROM schema_versions WHERE version = 14;"

# Verify new index present
docker exec hp1-postgres psql -U hp1 -d hp1_agent -c \
  "SELECT indexname, indexdef FROM pg_indexes WHERE tablename='status_snapshots';"

# Verify kafka facts now writing (no more 'Fact extraction failed for kafka')
docker logs hp1_agent --since 5m 2>&1 | grep -i 'fact extraction failed for kafka'
# Expect: no output

# Verify memory health endpoint returns 200
curl -sf http://localhost:8000/api/memory/health
# Expect: JSON with status:"ok" or "unconfigured", no 500

# Optional — manually run retention once to free disk now (not waiting for 03:00)
docker exec hp1-postgres psql -U hp1 -d hp1_agent -c \
  "DELETE FROM status_snapshots WHERE timestamp < NOW() - INTERVAL '30 days'; VACUUM ANALYZE status_snapshots;"
````

After deploy, retry the full-mem test. Should complete without
grinding the GUI to a halt.
