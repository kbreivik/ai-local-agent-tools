# CC PROMPT — v2.44.7 — fix(tests): wire suite_id + test_ids through to run_all_tests + fix http client

## What this does

Two bugs in `_run_tests_bg` preventing suite-based and test_id-filtered runs:

1. `run_all_tests(categories=categories)` — missing required `http` arg and
   ignores `test_ids`, so suites defined by test IDs always run all tests.

2. `run_all_tests` signature is `(categories, http, args=None)` — the API must
   create its own httpx client to call it.

3. Suite config (`memoryEnabled`, `memoryBackend`) is read from the suite record
   in the DB but never applied before the run.

Fix all three in `api/routers/tests_api.py`.

Version bump: 2.44.6 → 2.44.7.

---

## Change — `api/routers/tests_api.py`

Replace the entire `_run_tests_bg` function body (keep the signature):

```python
async def _run_tests_bg(
    categories: list[str] | None,
    test_ids: list[str] | None = None,
    suite_id: str | None = None,
    memory_enabled: bool | None = None,
    memory_backend: str | None = None,
    suite_name: str = "",
) -> None:
    global _running
    _running = True
    try:
        # ── 1. Load suite config if suite_id provided ─────────────────────
        if suite_id:
            try:
                from api.db import test_runs as _tr
                suites = _tr.list_suites()
                suite = next((s for s in suites if s["id"] == suite_id), None)
                if suite:
                    suite_name = suite_name or suite.get("name", "")
                    cfg = suite.get("config") or {}
                    if not categories:
                        categories = suite.get("categories") or []
                    if not test_ids:
                        test_ids = suite.get("test_ids") or []
                    if memory_enabled is None:
                        memory_enabled = cfg.get("memoryEnabled", True)
                    if memory_backend is None:
                        memory_backend = cfg.get("memoryBackend", "muninndb")
            except Exception as _se:
                import logging; logging.getLogger(__name__).debug("suite load: %s", _se)

        # ── 2. Apply memory settings ──────────────────────────────────────
        if memory_enabled is not None:
            try:
                from api.settings_manager import set_setting
                set_setting("memoryEnabled", memory_enabled)
            except Exception: pass
        if memory_backend is not None:
            try:
                from api.settings_manager import set_setting
                set_setting("memoryBackend", memory_backend)
            except Exception: pass

        # ── 3. Run tests ──────────────────────────────────────────────────
        from api.db.test_definitions import TEST_CASES
        from tests.integration.test_agent import run_all_tests, save_results
        import httpx

        # Filter cases
        cases_to_run = TEST_CASES
        if categories:
            cases_to_run = [tc for tc in cases_to_run if tc.category in categories]
        if test_ids:
            cases_to_run = [tc for tc in cases_to_run if tc.id in test_ids]

        async with httpx.AsyncClient(timeout=30.0) as http:
            results = await run_all_tests(
                categories=categories or None,
                http=http,
                args=None,
            )

        save_results(results)

        # ── 4. Persist to DB ──────────────────────────────────────────────
        try:
            from api.db import test_runs as tr_db_inner
            results_data = {}
            try:
                results_data = json.loads(RESULTS_PATH.read_text())
            except Exception:
                results_data = {}

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
            for r in results_data.get("results", []):
                tr_db_inner.insert_result(run_id, r)
            tr_db_inner.finish_run(
                run_id=run_id,
                total=results_data.get("total", 0),
                passed=results_data.get("passed", 0),
                score_pct=results_data.get("score_pct", 0),
                weighted_pct=results_data.get("weighted_pct", 0),
            )
        except Exception as _dbe:
            import logging
            logging.getLogger(__name__).debug("DB persist failed: %s", _dbe)

    except Exception as e:
        import json as _json
        from datetime import datetime, timezone
        RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        RESULTS_PATH.write_text(_json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": str(e),
            "total": 0, "passed": 0, "failed": 0, "score_pct": 0, "results": [],
        }, indent=2))
    finally:
        _running = False
```

Also update the `run_tests` endpoint to pass the new params:

```python
@router.post("/run")
async def run_tests(
    body: RunTestsRequest,
    background_tasks: BackgroundTasks,
    _: str = Depends(get_current_user),
):
    global _running
    if _running:
        return {"status": "already_running",
                "message": "A test run is already in progress."}
    background_tasks.add_task(
        _run_tests_bg,
        categories=body.categories,
        test_ids=body.test_ids,
        suite_id=body.suite_id,
        memory_enabled=body.memory_enabled,
        suite_name="",
    )
    return {"status": "started",
            "message": f"Test run started (suite={body.suite_id}, categories={body.categories}, ids={len(body.test_ids or [])} tests)"}
```

---

## Verification

After deploy, trigger smoke suite run:
```bash
curl -X POST http://192.168.199.10:8000/api/tests/run \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"suite_id": "07db3255-bf03-40fd-a8f8-8b5ddcfca4bd"}'
```
Expected: `{"status": "started", ...}`

---

## Version bump

Update `VERSION`: `2.44.6` → `2.44.7`

---

## Commit

```
git add -A
git commit -m "fix(tests): v2.44.7 wire suite_id+test_ids through run — apply suite config + fix http client"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
