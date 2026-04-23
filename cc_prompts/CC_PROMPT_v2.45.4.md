# CC PROMPT — v2.45.4 — fix(tests): record accurate run timestamps — started_at before tests, finished_at after

## Root cause

`create_run()` is called AFTER `run_all_tests()` completes. Both `started_at`
and `finished_at` default to `NOW()` within seconds of each other, so all runs
show 1–6s duration regardless of actual test time.

Fix: record wall-clock timestamps around the actual test execution and pass them
explicitly to `create_run()` and `finish_run()`.

Two-file change:
- `api/db/test_runs.py` — add `started_at` param to `create_run()`, add
  `finished_at` param to `finish_run()`
- `api/routers/tests_api.py` — stamp `_t_start` before `run_all_tests()`,
  stamp `_t_end` after, pass both to DB helpers

Version bump: 2.45.3 → 2.45.4.

---

## Change 1 — `api/db/test_runs.py`

### `create_run` — add optional `started_at` param

Find:
```python
def create_run(suite_id: str = None, suite_name: str = '', config: dict = None,
               triggered_by: str = 'manual') -> str:
```
Replace with:
```python
def create_run(suite_id: str = None, suite_name: str = '', config: dict = None,
               triggered_by: str = 'manual', started_at=None) -> str:
```

Find the INSERT statement inside `create_run`:
```python
        cur.execute("""
            INSERT INTO test_runs (id, suite_id, suite_name, config, triggered_by)
            VALUES (%s, %s, %s, %s, %s)
        """, (run_id, suite_id, suite_name, json.dumps(config or {}), triggered_by))
```
Replace with:
```python
        if started_at is not None:
            cur.execute("""
                INSERT INTO test_runs (id, suite_id, suite_name, config, triggered_by, started_at)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (run_id, suite_id, suite_name, json.dumps(config or {}), triggered_by, started_at))
        else:
            cur.execute("""
                INSERT INTO test_runs (id, suite_id, suite_name, config, triggered_by)
                VALUES (%s, %s, %s, %s, %s)
            """, (run_id, suite_id, suite_name, json.dumps(config or {}), triggered_by))
```

### `finish_run` — add optional `finished_at` param

Find:
```python
def finish_run(run_id: str, total: int, passed: int, score_pct: float,
               weighted_pct: float = 0.0, error: str = '') -> None:
```
Replace with:
```python
def finish_run(run_id: str, total: int, passed: int, score_pct: float,
               weighted_pct: float = 0.0, error: str = '', finished_at=None) -> None:
```

Find the UPDATE statement inside `finish_run`:
```python
        cur.execute("""
            UPDATE test_runs SET
                finished_at=NOW(), status=%s, total=%s, passed=%s,
                failed=%s, score_pct=%s, weighted_pct=%s, error=%s
            WHERE id=%s
        """, (status, total, passed, total-passed, score_pct, weighted_pct, error, run_id))
```
Replace with:
```python
        _fin = finished_at if finished_at is not None else 'NOW()'
        if finished_at is not None:
            cur.execute("""
                UPDATE test_runs SET
                    finished_at=%s, status=%s, total=%s, passed=%s,
                    failed=%s, score_pct=%s, weighted_pct=%s, error=%s
                WHERE id=%s
            """, (finished_at, status, total, passed, total-passed, score_pct, weighted_pct, error, run_id))
        else:
            cur.execute("""
                UPDATE test_runs SET
                    finished_at=NOW(), status=%s, total=%s, passed=%s,
                    failed=%s, score_pct=%s, weighted_pct=%s, error=%s
                WHERE id=%s
            """, (status, total, passed, total-passed, score_pct, weighted_pct, error, run_id))
```

---

## Change 2 — `api/routers/tests_api.py`

In `_run_tests_bg`, surround the `run_all_tests()` call with timestamps and
pass them to the DB helpers.

Find the comment `# ── 3. Run tests` block:
```python
        # ── 3. Run tests ──────────────────────────────────────────────────
        from api.db.test_definitions import TEST_CASES
        from tests.integration.test_agent import run_all_tests, save_results
        import httpx
```
Add timestamp import and start stamp immediately after:
```python
        # ── 3. Run tests ──────────────────────────────────────────────────
        from api.db.test_definitions import TEST_CASES
        from tests.integration.test_agent import run_all_tests, save_results
        from datetime import datetime, timezone
        import httpx

        _t_start = datetime.now(timezone.utc)
```

Then find the line after `save_results(results)`:
```python
        save_results(results)

        # ── 4. Persist to DB ──────────────────────────────────────────────
```
Add end timestamp:
```python
        save_results(results)
        _t_end = datetime.now(timezone.utc)

        # ── 4. Persist to DB ──────────────────────────────────────────────
```

Then find the `create_run(...)` call in the DB persist block:
```python
            run_id = tr_db_inner.create_run(
                suite_id=suite_id,
                suite_name=suite_name or ((",".join(categories)) if categories else "all"),
                config={
                    "categories": categories or [],
                    "test_ids": test_ids or [],
                    "suite_id": suite_id,
                    "memoryEnabled": memory_enabled,
                    "memoryBackend": memory_backend,
                },
                triggered_by="api",
            )
```
Replace with:
```python
            run_id = tr_db_inner.create_run(
                suite_id=suite_id,
                suite_name=suite_name or ((",".join(categories)) if categories else "all"),
                config={
                    "categories": categories or [],
                    "test_ids": test_ids or [],
                    "suite_id": suite_id,
                    "memoryEnabled": memory_enabled,
                    "memoryBackend": memory_backend,
                },
                triggered_by="api",
                started_at=_t_start,
            )
```

Then find the `finish_run(...)` call:
```python
            tr_db_inner.finish_run(
                run_id=run_id,
                total=results_data.get("total", 0),
                passed=results_data.get("passed", 0),
                score_pct=results_data.get("score_pct", 0),
                weighted_pct=results_data.get("weighted_pct", 0),
            )
```
Replace with:
```python
            tr_db_inner.finish_run(
                run_id=run_id,
                total=results_data.get("total", 0),
                passed=results_data.get("passed", 0),
                score_pct=results_data.get("score_pct", 0),
                weighted_pct=results_data.get("weighted_pct", 0),
                finished_at=_t_end,
            )
```

---

## Version bump

Update `VERSION`: `2.45.3` → `2.45.4`

---

## Commit

```
git add -A
git commit -m "fix(tests): v2.45.4 record accurate run timestamps — stamp before/after run_all_tests"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
